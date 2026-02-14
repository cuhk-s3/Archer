# Implementation of OpenAI-compatible agents (Chat Completions API).
# Unlike the OpenAIAgent, this agent does not use the native OpenAI API for tool calling.
# Instead, it uses system prompts to describe the tools.

import os
from typing import Dict, List, Tuple

from openai import OpenAI
from tenacity import (
  retry,
  stop_after_attempt,
  wait_random_exponential,
)  # for exponential backoff

from lms.generic import GenericAgent


class GenericOpenAIAgent(GenericAgent):
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

  @retry(wait=wait_random_exponential(min=1, max=60), stop=stop_after_attempt(3))
  def _completion_with_backoff(self, **kwargs):
    return self.client.chat.completions.create(**kwargs)

  def _complete_chat(self, messages: List[Dict]) -> Tuple[str, str]:
    completion = self._completion_with_backoff(
      model=self.model,
      messages=messages,
      temperature=self.temperature,
      top_p=self.top_p,
      max_tokens=self.max_tokens,
      stream=True,
      stream_options={"include_usage": True},
    )

    reasoning_content = ""
    answer_content = ""

    for chunk in completion:
      # Update tokens that we have consumed
      if chunk.usage:
        if chunk.usage.prompt_tokens:
          self.chat_stats["input_tokens"] += chunk.usage.prompt_tokens
        if (
          chunk.usage.prompt_tokens_details
          and chunk.usage.prompt_tokens_details.cached_tokens
        ):
          self.chat_stats["cached_tokens"] += (
            chunk.usage.prompt_tokens_details.cached_tokens
          )
        if chunk.usage.completion_tokens:
          self.chat_stats["output_tokens"] += chunk.usage.completion_tokens
        if chunk.usage.total_tokens:
          self.chat_stats["total_tokens"] += chunk.usage.total_tokens
        cost = getattr(completion.usage, "cost", None)
        if cost is not None:
          self.chat_stats["total_cost"] += cost

      if not chunk.choices:
        continue

      delta = chunk.choices[0].delta

      if hasattr(delta, "reasoning_content") and delta.reasoning_content is not None:
        reasoning_content += delta.reasoning_content

      if hasattr(delta, "content") and delta.content:
        answer_content += delta.content

    if (
      not reasoning_content
      and "<think>" in answer_content
      and "</think>" in answer_content
    ):
      think_begin = answer_content.index("<think>") + len("<think>")
      think_end = answer_content.rindex("</think>")
      reasoning_content = answer_content[think_begin:think_end]
      answer_content = (
        answer_content[: think_begin - len("<think>")]
        + "\n"
        + answer_content[think_end + len("</think>") :]
      )

    return reasoning_content, answer_content
