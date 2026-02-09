import json
import re
from abc import abstractmethod
from typing import Dict, List, Optional, Tuple

import json_repair

from lms.agent import (
  AgentBase,
  ChatMessageFunctionCall,
  ChatMessageFunctionCallOutput,
  ChatMessageMessage,
  ReachRoundLimit,
  ReachTokenLimit,
  ResponseHandler,
  ToolUseHandler,
)
from lms.tool import FuncToolBase

TOOL_CALL_BEGIN_TAG = "<tool_call>"
TOOL_CALL_END_TAG = "</tool_call>"
TOOL_CALL_PATTERN = re.compile(
  f"{TOOL_CALL_BEGIN_TAG}\n.*?{TOOL_CALL_END_TAG}",
  re.DOTALL,
)

TOOL_CALL_INSTRUCTION = f"""\
## Available Tools ##

You have access to the following {{num_tools}} tools to help you complete your task:

{{tool_specs}}

### Tool Call Format ###

When using a tool, return a JSON object strictly following below format:

{TOOL_CALL_BEGIN_TAG}
{{{{
  "name": <tool_name>,
  "args": <tool_args>
}}}}
{TOOL_CALL_END_TAG}

For example:

{TOOL_CALL_BEGIN_TAG}
{{{{
  "name": "get_weather",
  "args": {{{{
    "location": "New York",
    "date": "2023-10-01",
    "celsius": true
  }}}}
}}}}
{TOOL_CALL_END_TAG}

### Key Requirements ###

1. ALWAYS wrap your response with "{TOOL_CALL_BEGIN_TAG}" and "{TOOL_CALL_END_TAG}" as shown above so that I know you are calling a tool.
2. Content inside "{TOOL_CALL_BEGIN_TAG}" and "{TOOL_CALL_END_TAG}" MUST be a valid JSON object. Put all other content outside of these tags.
3. The "args" field MUST also be a valid JSON object. It is NOT a string that represents a JSON object.
4. Only call ONE tool in each of your response. Do NOT call multiple tools at the same time.
"""


class GenericAgent(AgentBase):
  """
  Implementation of a generic agent without relying on model's native
  tool-call capability to support a wider range of models.
  """

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

  def render_tool_call_inst(self, tools: List[FuncToolBase]) -> Optional[str]:
    tool_specs = [tool.spec().render_in_simple_format() for tool in tools]
    return (
      TOOL_CALL_INSTRUCTION.format(
        num_tools=len(tool_specs),
        tool_specs=json.dumps(tool_specs, indent=2, ensure_ascii=False),
        tool_call_begin_tag=TOOL_CALL_BEGIN_TAG,
        tool_call_end_tag=TOOL_CALL_END_TAG,
      )
      if len(tool_specs) != 0
      else None
    )

  def run(
    self,
    activated_tools: List[str],
    response_handler: ResponseHandler,
    tool_call_handler: ToolUseHandler,
    round_limit: int = -1,
  ) -> str:
    # TODO: Avoid changing tool instructions for better prompt caching performance.
    remaining_tools = self._get_remaining_tools_from(activated_tools)

    # Decide where to insert the tool call instruction
    if len(remaining_tools) > 0:
      inst = self.render_tool_call_inst(remaining_tools)
      assert inst is not None, "Tool call instruction should not be None"
      self.append_user_message(inst)
      tool_call_inst_index = len(self.history) - 1
    else:
      tool_call_inst_index = -1

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
      if tool_call_inst_index != -1:
        inst = self.render_tool_call_inst(remaining_tools)
        if inst:
          self.history[tool_call_inst_index] = ChatMessageMessage(
            role="user", content=inst
          )
        else:
          self.append_user_message(
            "NOTICE: From now on, no available tools. Please continue the conversation without tool calls."
          )
      messages = [self._chat_message_to_dict(m) for m in self.history]

      reasoning_content, answer_content = self._complete_chat(messages)
      if reasoning_content:
        # We never append reasoning content to the history to reduce the token usage.
        self.console.printb(
          title="Assistant",
          message=f"<thinking>{reasoning_content}</thinking>",
        )

      # Handle tool call
      if TOOL_CALL_BEGIN_TAG in answer_content:
        result = self._handle_tool_call(answer_content, tool_call_handler)
        if result:
          return result
        continue

      # Handle normal response
      self.append_assistant_message(answer_content)
      cont_exec, result = response_handler(answer_content)
      self.append_user_message(
        result
      )  # Append the message in case the user may continue to run the agent
      if not cont_exec:
        return result

    if curr_round == round_limit - 1:
      raise ReachRoundLimit()

  @abstractmethod
  def _complete_chat(self, messages: List[Dict]) -> Tuple[str, str]:
    """Complete the chat with the given messages and return reasoning and answer content."""
    ...

  def _handle_tool_call(self, content, tool_call_handler) -> Optional[str]:
    content = content.strip()

    matches = TOOL_CALL_PATTERN.findall(content)
    if len(matches) == 0:
      # Try fixing some simple errors
      fix_succeeded = False
      if TOOL_CALL_END_TAG not in content:
        last_rbrace = content.rfind("}")
        fixed_content = (
          content[: last_rbrace + 1]
          + "\n"
          + TOOL_CALL_END_TAG
          + content[last_rbrace + 1 :]
        )
        fixed_matches = TOOL_CALL_PATTERN.findall(fixed_content)
        if len(fixed_matches) == 1:
          content = fixed_content
          matches = fixed_matches
          fix_succeeded = True
      if not fix_succeeded:
        self.append_assistant_message(content)
        self.append_user_message(
          f"Error: tool call format is incorrect. "
          f'Wrap your JSON object within "{TOOL_CALL_BEGIN_TAG}" and "{TOOL_CALL_END_TAG}"'
        )
        return None  # None to continue agent execution
    elif len(matches) > 1:
      self.append_assistant_message(content)
      self.append_user_message(
        f"Error: {len(matches)} tool calls detected. "
        "Ensure only ONE tool call in each of your response."
      )
      return None  # None to continue agent execution

    content = matches[0]

    json_beg = content.index(TOOL_CALL_BEGIN_TAG) + len(TOOL_CALL_BEGIN_TAG)
    json_end = content.rindex(TOOL_CALL_END_TAG)
    json_str = content[json_beg:json_end].strip()

    try:
      tool_call = json_repair.loads(json_str)
    except Exception as e:
      self.append_assistant_message(content)
      self.append_user_message(f"Error: Failed to parse tool call JSON: {e}")
      return None  # None to continue agent execution

    # Once json_repair.loads() returned successfully, there's a chance that the
    # model-returned json_str is invalid but repaired by json_repair.loads().
    # To avoid such cases and maintain a good history and also guide the model
    # to fix it correctly if there're still bugs in the repaired json, we alter
    # content to use the repaired json_str.
    repaired_json_str = json.dumps(tool_call, ensure_ascii=False)
    repaired_content = (
      content[:json_beg] + "\n" + repaired_json_str + "\n" + content[json_end:]
    )

    try:
      if "name" not in tool_call:
        raise KeyError("Tool call JSON must contain 'name' field")
      tool_name = tool_call["name"]
      if "args" not in tool_call:
        raise KeyError("Tool call JSON must contain 'args' field")
      tool_args = tool_call["args"] or {}
      if not isinstance(tool_args, dict):
        raise Exception(
          f"Tool call arguments must be a JSON object, but got: {type(tool_args)}"
        )
    except Exception as e:
      self.append_assistant_message(repaired_content)
      self.append_user_message(f"Error: {e}")
      return None  # None to continue agent execution

    tool_args_text = json.dumps(tool_args, ensure_ascii=False)
    self.append_function_tool_call(
      call_id="<no-id>", name=tool_name, arguments=tool_args_text
    )

    result = self.perform_tool_call(tool_name, tool_args)
    cont_exec, result = tool_call_handler(tool_name, tool_args_text, result)
    if not cont_exec:
      self.append_user_message(result)
      return result  # Stop the agent execution and return the result

    self.append_function_tool_call_output(call_id="<no-id>", result=result)

    return None  # None to continue agent execution

  @staticmethod
  def _chat_message_to_dict(message):
    if isinstance(message, ChatMessageMessage):
      return {"role": message.role, "content": message.content}
    elif isinstance(message, ChatMessageFunctionCall):
      tool_call_formatted = json.dumps(
        {"name": message.name, "args": json.loads(message.arguments)}
      )
      return {
        "role": "assistant",
        "content": f"{TOOL_CALL_BEGIN_TAG}\n{tool_call_formatted}\n{TOOL_CALL_END_TAG}",
      }
    elif isinstance(message, ChatMessageFunctionCallOutput):
      return {"role": "user", "content": message.output}
    else:
      raise ValueError(f"Unsupported message type: {type(message)}")
