# Implementation of OpenAI-compatible agents (Chat Completions API).

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


class OpenAIAgent(AgentBase):
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

  def render_message_list(self) -> List[dict]:
    messages = []
    for message in self.history:
      if isinstance(message, ChatMessageMessage):
        messages.append(
          {
            "role": message.role,
            "content": message.content,
          }
        )
      elif isinstance(message, ChatMessageFunctionCall):
        messages.append(
          {
            "role": "assistant",
            "content": "",
            "tool_calls": [
              {
                "id": message.call_id,
                "function": {
                  "arguments": message.arguments,
                  "name": message.name,
                },
                "type": "function",
                "index": 0,
              }
            ],
          }
        )
      elif isinstance(message, ChatMessageFunctionCallOutput):
        messages.append(
          {
            "role": "tool",
            "tool_call_id": message.call_id,
            "content": message.output,
          }
        )

    return messages

  @retry(wait=wait_random_exponential(min=1, max=60), stop=stop_after_attempt(3))
  def _completion_with_backoff(self, **kwargs):
    return self.client.chat.completions.create(**kwargs)

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
      completion = self._completion_with_backoff(
        model=self.model,
        messages=self.render_message_list(),
        temperature=self.temperature,
        top_p=self.top_p,
        max_tokens=self.max_tokens,
        tools=(
          [tool.spec().render_in_openai_format() for tool in remaining_tools]
          or NOT_GIVEN
        ),
      )

      if completion.usage:
        self.chat_stats["input_tokens"] += completion.usage.prompt_tokens
        if completion.usage.prompt_tokens_details:
          self.chat_stats["cached_tokens"] += (
            completion.usage.prompt_tokens_details.cached_tokens
          )
        self.chat_stats["output_tokens"] += completion.usage.completion_tokens
        self.chat_stats["total_tokens"] += completion.usage.total_tokens
        cost = getattr(completion.usage, "cost", None)
        if cost is not None:
          self.chat_stats["total_cost"] += cost

      response = completion.choices[0].message

      if not response.tool_calls:
        # Handle normal response
        self.append_assistant_message(response.content)
        flag, content = response_handler(response.content)
        if flag:
          self.append_user_message(content)
          continue
        else:
          return content

      # Handle tool calls
      for tool_call in response.tool_calls:
        name = tool_call.function.name
        args = tool_call.function.arguments
        self.append_function_tool_call(
          call_id=tool_call.id,
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
        self.append_function_tool_call_output(call_id=tool_call.id, result=result)
        flag, result = tool_call_handler(name, args, result)
        if not flag:
          return result

    if curr_round == round_limit - 1:
      raise ReachRoundLimit()
