import json
import os
import sys
import time
from argparse import ArgumentParser
from dataclasses import asdict
from pathlib import Path

# Add the root directory to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

import main as main_module
from base.console import get_boxed_console
from llvm.llvm import LLVM
from llvm.llvm_helper import get_llvm_build_dir, git_execute, reset, set_llvm_build_dir
from main import (
  ADDITIONAL_CMAKE_FLAGS,
  MAX_CONSUMED_TOKENS,
  NoAvailableBugFound,
  RunStats,
  autoreview,
  panic,
)

console = get_boxed_console(debug_mode=True)
main_module.console = console


class ReproEnvironment:
  def __init__(self, issue_id, additional_cmake_args=[]):
    self.issue_id = issue_id
    self.additional_cmake_args = additional_cmake_args

    dataset_dir = str(Path(__file__).parent / "dataset")
    with open(os.path.join(dataset_dir, f"{issue_id}.json")) as f:
      self.data = json.load(f)

    self.bug_type = self.data.get("bug_type")
    self.base_commit = self.data.get("base_commit")
    self.test_commit = self.data.get("hints", {}).get("fix_commit")

  def get_bug_type(self):
    return self.bug_type

  def get_base_commit(self):
    return self.base_commit

  def get_tests(self):
    return self.data.get("tests", [])

  def get_reference_patch(self):
    return self.data.get("patch", "")

  def get_hint_fix_commit(self):
    return self.test_commit

  def get_hint_components(self):
    return self.data.get("hints", {}).get("components", [])

  def get_hint_issue(self):
    issue_data = self.data.get("issue", {})
    return {
      "title": issue_data.get("title", ""),
      "labels": issue_data.get("labels", []),
    }

  def get_langref_desc(self, keywords):
    from llvm.llvm_helper import get_langref_desc as helper_get_langref_desc

    return helper_get_langref_desc(keywords, self.base_commit)

  def apply(self):
    # Checkout the fix commit
    reset(self.test_commit)

  def build(self):
    from llvm.llvm_helper import build as llvm_build

    max_build_jobs = os.environ.get("LLVM_AUTOREVIEW_MAX_BUILD_JOBS")
    if max_build_jobs is None:
      max_build_jobs = os.cpu_count()
    else:
      max_build_jobs = int(max_build_jobs)
    res, log = llvm_build(max_build_jobs, self.additional_cmake_args)
    return res, log


def parse_args():
  parser = ArgumentParser(description="llvm-autoreview (repro)")
  parser.add_argument(
    "--issue",
    type=str,
    required=True,
    help="The issue ID to review.",
  )
  parser.add_argument(
    "--model",
    type=str,
    required=True,
    help="The LLM model to use for the agent.",
  )
  parser.add_argument(
    "--driver",
    type=str,
    default="openai",
    help="The LLM api to use (default: openai).",
    choices=["openai", "anthropic", "openai-generic"],
  )
  parser.add_argument(
    "--stats",
    type=str,
    default=None,
    help="Path to save the generation statistics as a JSON file (default: None).",
  )
  parser.add_argument(
    "--history",
    type=str,
    default=None,
    help="Path to a JSON file containing the chat history of the agent (default: None).",
  )
  parser.add_argument(
    "--debug",
    action="store_true",
    default=False,
    help="Enable debug mode for more verbose output (default: False).",
  )
  return parser.parse_args()


def main():
  if os.environ.get("LLVM_AUTOREVIEW_HOME_DIR") is None:
    panic("The llvm-autoreview environment has not been brought up.")

  args = parse_args()

  if args.debug:
    global console
    console = get_boxed_console(debug_mode=True)
    main_module.console = console

  if args.driver == "openai":
    from lms.openai import OpenAIAgent

    agent = OpenAIAgent(
      args.model, token_limit=MAX_CONSUMED_TOKENS, debug_mode=args.debug
    )
  elif args.driver == "anthropic":
    from lms.anthropic import ClaudeAgent

    agent = ClaudeAgent(
      args.model, token_limit=MAX_CONSUMED_TOKENS, debug_mode=args.debug
    )
  elif args.driver == "openai-generic":
    from lms.openai_generic import GenericOpenAIAgent

    agent = GenericOpenAIAgent(
      args.model, token_limit=MAX_CONSUMED_TOKENS, debug_mode=args.debug
    )
  else:
    panic(f"Unsupported LLM driver: {args.driver}")

  stats_path = None
  if args.stats:
    stats_path = Path(args.stats)
    if stats_path.exists():
      panic(f"Stats file {stats_path} already exists.")

  history_path = None
  if args.history:
    history_path = Path(args.history)
    if history_path.exists():
      panic(f"History file {history_path} already exists.")

  build_dir = os.path.join(get_llvm_build_dir(), args.issue)
  set_llvm_build_dir(build_dir)

  env = ReproEnvironment(
    args.issue,
    additional_cmake_args=ADDITIONAL_CMAKE_FLAGS,
  )

  bug_type = env.get_bug_type()
  if bug_type not in ["miscompilation"]:
    panic(f"Unsupported bug type: {bug_type}")

  console.print(f"Issue ID: {args.issue}")
  console.print(f"Issue Type: {bug_type}")
  console.print(f"Issue Commit: {env.get_base_commit()}")
  console.print(f"Issue Fix Commit: {env.get_hint_fix_commit()}")
  console.print(f"Issue Title: {env.get_hint_issue()['title']}")
  console.print(f"Issue Labels: {env.get_hint_issue()['labels']}")

  console.print("Checking out the issue's environment ...")
  try:
    env.apply()
  except Exception as e:
    console.print(
      f"Warning: Failed to reset HEAD to {env.get_hint_fix_commit()}: {e}",
      color="yellow",
    )
    console.print("Sync the repository and try again.", color="yellow")
    reset("main")
    git_execute(["pull", "origin", "main"])
    try:
      env.apply()
    except Exception as e:
      panic(f"Failed to reset HEAD to {env.get_hint_fix_commit()}: {e}")

  if not (Path(build_dir) / "bin" / "opt").exists():
    env.build()

  llvm = LLVM()

  stats = RunStats(command=vars(args))
  stats.total_time_sec = time.time()
  try:
    autoreview(agent, env, llvm, stats, build_dir)
    if not stats.bugs:
      raise NoAvailableBugFound("All efforts tried yet no available patches found.")
  except Exception as e:
    import traceback

    stats.error = type(e).__name__
    stats.errmsg = str(e)
    stats.traceback = traceback.format_exc()
  finally:
    stats.chat_rounds = agent.chat_stats["chat_rounds"]
    stats.input_tokens = agent.chat_stats["input_tokens"]
    stats.output_tokens = agent.chat_stats["output_tokens"]
    stats.cached_tokens = agent.chat_stats["cached_tokens"]
    stats.total_tokens = agent.chat_stats["total_tokens"]
    stats.chat_cost = agent.chat_stats["total_cost"]
    stats.total_time_sec = time.time() - stats.total_time_sec
    usage = []
    for name in agent.tools.list(ignore_budget=False):
      total = agent.tools.get_total_budget(name)
      remaining = agent.tools.get_remaining_budget(name)
      usage.append({"name": name, "usage": total - remaining})
    stats.tool_usage = usage
    if stats_path:
      with stats_path.open("w") as fout:
        json.dump(stats.as_dict(), fout, indent=2)
      console.print(f"Generation statistics saved to {stats_path}.")
    if history_path:
      with history_path.open("w") as fout:
        json.dump([asdict(m) for m in agent.get_history()], fout, indent=2)
      console.print(f"Chat history saved to {history_path}.")

  console.print("Bugs Found")
  console.print("----------")
  for idx, bug in enumerate(stats.bugs):
    console.print(f"Bug #{idx + 1}:")
    console.print("Original LLVM IR:")
    console.print(bug.original_ir)
    console.print("Transformed LLVM IR:")
    console.print(bug.transformed_ir)
    console.print("Verification Log:")
    console.print(bug.log)
    console.print("----------")
  console.print("Statistics")
  console.print("----------")
  console.print(json.dumps(stats.as_dict(), indent=2))


if __name__ == "__main__":
  main()
