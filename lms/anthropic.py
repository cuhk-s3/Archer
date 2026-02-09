# Implementation of Claude-based agents.

import json
import os
from typing import List

from anthropic import NOT_GIVEN, Anthropic

from lms.agent import (
  AgentBase,
  ChatMessageMessage,
  ReachRoundLimit,
  ReachTokenLimit,
  ResponseHandler,
  ToolUseHandler,
)


class ClaudeAgent(AgentBase):
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
    token = os.environ.get("LLVM_AUTOFIX_LM_API_KEY")
    self.client = Anthropic(api_key=token)

  def run(
    self,
    activated_tools: List[str],
    response_handler: ResponseHandler,
    tool_call_handler: ToolUseHandler,
    round_limit: int = -1,
  ) -> str:
    messages = []
    for message in self.history:
      if isinstance(message, ChatMessageMessage):
        messages.append(
          {
            "role": message.role,
            "content": message.content,
          }
        )
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
      response = self.client.messages.create(
        model=self.model,
        messages=messages,
        temperature=self.temperature,
        top_p=self.top_p,
        max_tokens=self.max_tokens,
        tools=(
          [tool.spec().render_in_claude_format() for tool in remaining_tools]
          or NOT_GIVEN
        ),
      )
      self.chat_stats["input_tokens"] += response.usage.input_tokens
      self.chat_stats["cached_tokens"] += response.usage.cache_read_input_tokens
      self.chat_stats["output_tokens"] += response.usage.output_tokens
      self.chat_stats["total_tokens"] += (
        response.usage.input_tokens + response.usage.output_tokens
      )
      messages.append({"role": "assistant", "content": response.content})
      if response.stop_reason == "tool_use":
        for content in response.content:
          if content.type == "text":
            self.append_assistant_message(content.text)
          elif content.type == "tool_use":
            name = content.name
            call_id = content.id
            args = content.input
            args_text = json.dumps(args)
            self.append_function_tool_call(
              call_id=call_id,
              name=name,
              arguments=args_text,
            )
            result = self.perform_tool_call(name, args)
            flag, result = tool_call_handler(name, args_text, result)
            if not flag:
              return result
            self.append_function_tool_call_output(call_id=call_id, result=result)
            messages.append(
              {
                "role": "user",
                "content": [
                  {
                    "type": "tool_result",
                    "tool_use_id": call_id,
                    "content": result,
                  }
                ],
              }
            )
      elif response.stop_reason == "stop_sequence":
        self.append_assistant_message(response.content[0].text)
        flag, content = response_handler(response.content[0].text)
        if flag:
          self.append_user_message(content)
          messages.append(
            {
              "role": "user",
              "content": content,
            }
          )
        else:
          return content
    if curr_round == round_limit - 1:
      raise ReachRoundLimit()
