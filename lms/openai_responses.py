import json
import os
from typing import List

import json_repair
from openai import NOT_GIVEN, OpenAI
from tenacity import (
  retry,
  stop_after_attempt,
  wait_random_exponential,
)  # for exponential backoff

from lms.agent import (
  AgentBase,
  ChatMessageFunctionCall,
  ChatMessageFunctionCallOutput,
  ChatMessageMessage,
  ReachRoundLimit,
  ReachTokenLimit,
  RepeatedToolCallLimitExceeded,
  ResponseHandler,
  ToolUseHandler,
)


class OpenAIResponsesAgent(AgentBase):
  def __init__(
    self,
    model: str,
    *,
    temperature=0,
    top_k=50,
    top_p=0.95,
    max_tokens=4096,
    token_limit=-1,
    debug_mode=False,
  ):
    super().__init__(
      model,
      temperature=temperature,
      top_k=top_k,
      top_p=top_p,
      max_tokens=max_tokens,
      token_limit=token_limit,
      debug_mode=debug_mode,
    )
    end_point = os.environ.get("LLVM_AUTOREVIEW_LM_API_ENDPOINT")
    token = os.environ.get("LLVM_AUTOREVIEW_LM_API_KEY")
    self.client = OpenAI(api_key=token, base_url=end_point)

  def _render_instructions(self) -> str:
    """Concatenate all system messages; the Responses API takes system prompts
    via the top-level ``instructions`` field rather than inline items."""
    parts = [
      m.content
      for m in self.history
      if isinstance(m, ChatMessageMessage) and m.role == "system"
    ]
    return "\n\n".join(p for p in parts if p)

  def render_input_list(self) -> List[dict]:
    """Render non-system history as Responses API input items."""
    items: List[dict] = []
    for message in self.history:
      if isinstance(message, ChatMessageMessage):
        if message.role == "system":
          continue  # carried via `instructions`
        items.append(
          {
            "role": message.role,
            "content": message.content,
          }
        )
      elif isinstance(message, ChatMessageFunctionCall):
        items.append(
          {
            "type": "function_call",
            "call_id": message.call_id,
            "name": message.name,
            "arguments": message.arguments,
          }
        )
      elif isinstance(message, ChatMessageFunctionCallOutput):
        items.append(
          {
            "type": "function_call_output",
            "call_id": message.call_id,
            "output": message.output,
          }
        )
    return items

  @retry(wait=wait_random_exponential(min=1, max=60), stop=stop_after_attempt(3))
  def _responses_with_backoff(self, **kwargs):
    return self.client.responses.create(**kwargs)

  @staticmethod
  def _extract_text(response) -> str:
    """Pull the assistant's text out of a Responses API result."""
    text = getattr(response, "output_text", None)
    if text:
      return text
    # Fallback: walk output items for message content.
    parts: List[str] = []
    for item in getattr(response, "output", None) or []:
      if getattr(item, "type", None) != "message":
        continue
      for chunk in getattr(item, "content", None) or []:
        chunk_text = getattr(chunk, "text", None)
        if chunk_text:
          parts.append(chunk_text)
    return "".join(parts)

  @staticmethod
  def _extract_function_calls(response) -> List[dict]:
    """Return the function-call items from a Responses API result."""
    calls: List[dict] = []
    for item in getattr(response, "output", None) or []:
      if getattr(item, "type", None) != "function_call":
        continue
      calls.append(
        {
          # `call_id` is the id used to correlate the tool output; `id` is the
          # item id. We key off call_id when returning the output.
          "call_id": getattr(item, "call_id", None) or getattr(item, "id", ""),
          "name": getattr(item, "name", ""),
          "arguments": getattr(item, "arguments", "") or "",
        }
      )
    return calls

  def run(
    self,
    activated_tools: List[str],
    response_handler: ResponseHandler,
    tool_call_handler: ToolUseHandler,
    round_limit: int = -1,
  ) -> str:
    curr_round = -1

    while round_limit <= 0 or curr_round < round_limit - 1:
      curr_round += 1
      self.chat_stats["chat_rounds"] += 1
      self.console.print(
        f"Executing round #{curr_round}, chat statistics so far: {self.chat_stats}"
      )
      if self.token_limit > 0 and self.chat_stats["total_tokens"] >= self.token_limit:
        raise ReachTokenLimit()
      remaining_tools = self._get_remaining_tools_from(activated_tools)
      response = self._responses_with_backoff(
        model=self.model,
        instructions=self._render_instructions() or NOT_GIVEN,
        input=self.render_input_list(),
        temperature=self.temperature,
        top_p=self.top_p,
        max_output_tokens=self.max_tokens,
        tools=(
          [tool.spec().render_in_openai_responses_format() for tool in remaining_tools]
          or NOT_GIVEN
        ),
      )

      usage = getattr(response, "usage", None)
      if usage:
        self.chat_stats["input_tokens"] += getattr(usage, "input_tokens", 0) or 0
        input_details = getattr(usage, "input_tokens_details", None)
        if input_details:
          self.chat_stats["cached_tokens"] += (
            getattr(input_details, "cached_tokens", 0) or 0
          )
        self.chat_stats["output_tokens"] += getattr(usage, "output_tokens", 0) or 0
        self.chat_stats["total_tokens"] += getattr(usage, "total_tokens", 0) or 0
        cost = getattr(usage, "cost", None)
        if cost is not None:
          self.chat_stats["total_cost"] += cost

      function_calls = self._extract_function_calls(response)

      if not function_calls:
        # Handle normal response
        content = self._extract_text(response)
        self.append_assistant_message(content)
        flag, content = response_handler(content)
        if flag:
          self.append_user_message(content)
          continue
        else:
          return content

      # Handle tool calls
      for call in function_calls:
        name = call["name"]
        args = call["arguments"]
        call_id = call["call_id"]
        self.append_function_tool_call(
          call_id=call_id,
          name=name,
          arguments=args,
        )
        try:
          arguments = json_repair.loads(args)
          if isinstance(arguments, str):
            arguments = json.loads(arguments)
          result = self.perform_tool_call(name, arguments)
        except RepeatedToolCallLimitExceeded:
          raise
        except Exception as e:
          result = f"Error: Failed to parse tool arguments as JSON: {e}. Please check your tool call format and try again."
        self.append_function_tool_call_output(call_id=call_id, result=result)
        flag, result = tool_call_handler(name, args, result)
        if not flag:
          return result

    if curr_round == round_limit - 1:
      raise ReachRoundLimit()
