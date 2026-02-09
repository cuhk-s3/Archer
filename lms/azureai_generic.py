import os
from typing import Dict, List, Tuple

from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import AssistantMessage, SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential

from lms.generic import GenericAgent


class GenericAzureAIAgent(GenericAgent):
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
    endpoint = os.environ.get("LLVM_AUTOFIX_LM_API_ENDPOINT")
    token = os.environ.get("LLVM_AUTOFIX_LM_API_KEY")
    self.client = ChatCompletionsClient(
      endpoint=endpoint,
      credential=AzureKeyCredential(token),
    )

  def _complete_chat(self, messages: List[Dict]) -> Tuple[str, str]:
    azure_messages = []
    for message in messages:
      role, content = message["role"], message["content"]
      if role == "system":
        azure_messages.append(SystemMessage(content))
      elif role == "user":
        azure_messages.append(UserMessage(content))
      elif role == "assistant":
        azure_messages.append(AssistantMessage(content))
      else:
        raise RuntimeError(f"Unknown message role: {role}".format())

    completion = self.client.complete(
      model=self.model,
      messages=azure_messages,
      temperature=self.temperature,
      top_p=self.top_p,
      max_tokens=self.max_tokens,
      stream=True,
    )

    reasoning_content = ""
    answer_content = ""

    for chunk in completion:
      # Update tokens that we have consumed
      if chunk.usage:
        self.chat_stats["input_tokens"] += chunk.usage.prompt_tokens
        if hasattr(chunk.usage, "prompt_tokens_details"):
          self.chat_stats["cached_tokens"] += (
            chunk.usage.prompt_tokens_details.cached_tokens
          )
        self.chat_stats["output_tokens"] += chunk.usage.completion_tokens
        self.chat_stats["total_tokens"] += chunk.usage.total_tokens

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
