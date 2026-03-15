import json
import os
import sys
import time
from argparse import ArgumentParser
from dataclasses import asdict
from pathlib import Path

# Add the root directory to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent.parent))

import main as main_module
from base.console import get_boxed_console
from llvm.llvm import LLVM
from llvm.llvm_helper import get_llvm_build_dir, git_execute, reset, set_llvm_build_dir
from main import (
  ADDITIONAL_CMAKE_FLAGS,
  MAX_CONSUMED_TOKENS,
  PRInfo,
  RunStats,
  generate_review,
  panic,
  pr_review,
)

console = get_boxed_console(debug_mode=True)
main_module.console = console


class HistoryEnvironment:
  def __init__(self, issue_id, additional_cmake_args=[]):
    self.issue_id = issue_id
    self.additional_cmake_args = additional_cmake_args

    dataset_dir = str(Path(__file__).parent / "dataset")
    with open(os.path.join(dataset_dir, f"{issue_id}.json")) as f:
      self.data = json.load(f)

    self.history = self.data.get("history", {})
    if not self.history:
      panic(f"No history found in {issue_id}.json")

    self.bug_type = self.data.get("bug_type")
    self.test_commit = self.history.get("commit_sha")
    self.base_commit = self.data.get(
      "bisect", self.test_commit
    )  # Or parent of test_commit

  def get_bug_type(self):
    return self.bug_type

  def get_base_commit(self):
    return self.base_commit

  def get_tests(self):
    return self.history.get("tests", [])

  def get_reference_patch(self):
    return self.history.get("patch", "")

  def get_hint_fix_commit(self):
    return self.test_commit

  def get_hint_components(self):
    return self.history.get("components", [])

  def get_hint_issue(self):
    # Fake issue data
    issue = self.data.get("issue", {})
    return {
      "url": self.data.get("issue_url", ""),
      "title": self.history.get("commit_subject", ""),
      "author": self.history.get("commit_author", ""),
      "description": self.history.get("commit_message", ""),
      "knowledge_cutoff": self.data.get("knowledge_cutoff", ""),
      "labels": issue.get(
        "labels", [self.bug_type] + self.history.get("components", [])
      ),
      "comments": issue.get("comments", []),
      "patch_location_lineno": self.data.get("hints", {}).get(
        "bug_location_lineno", {}
      ),
      "patch_location_funcname": self.data.get("hints", {}).get(
        "bug_location_funcname", {}
      ),
    }

  def get_langref_desc(self, keywords):
    from llvm.llvm_helper import get_langref_desc as helper_get_langref_desc

    return helper_get_langref_desc(keywords, self.base_commit)

  def to_pr_info(self) -> PRInfo:
    """Convert HistoryEnvironment data into a PRInfo for use with main.py functions."""
    try:
      issue_id_int = int(self.issue_id)
    except (ValueError, TypeError):
      issue_id_int = 0
    hint = self.get_hint_issue()
    return PRInfo(
      pr_id=issue_id_int,
      pr_url=hint["url"],
      title=hint["title"],
      author=hint["author"],
      knowledge_cutoff=hint["knowledge_cutoff"],
      description=hint["description"],
      base_commit=self.base_commit,
      fix_commit=self.test_commit,
      patch=self.get_reference_patch(),
      components=self.get_hint_components(),
      state="closed",
      tests=self.get_tests(),
      labels=hint["labels"],
      comments=hint["comments"],
      patch_location_lineno=hint["patch_location_lineno"],
      patch_location_funcname=hint["patch_location_funcname"],
    )

  def apply(self):
    # Checkout the history commit
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
  parser = ArgumentParser(description="llvm-autoreview (regression)")
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
    "--review",
    type=str,
    default=None,
    help="Path to save the generated review as a Markdown file (default: None).",
  )
  parser.add_argument(
    "--debug",
    action="store_true",
    default=False,
    help="Enable debug mode for more verbose output (default: False).",
  )
  parser.add_argument(
    "--force",
    action="store_true",
    default=False,
    help="Force overwrite existing stats/history/review files (default: False).",
  )
  return parser.parse_args()


def main():
  if os.environ.get("LLVM_AUTOREVIEW_HOME_DIR") is None:
    panic("The llvm-autoreview environment has not been brought up.")

  args = parse_args()

  # Set up console
  if args.debug:
    console.debug = True

  env = HistoryEnvironment(
    args.issue,
    additional_cmake_args=ADDITIONAL_CMAKE_FLAGS,
  )

  bug_type = env.get_bug_type()
  if bug_type not in ["miscompilation"]:
    panic(f"Unsupported bug type: {bug_type}")

  pr_info = env.to_pr_info()

  console.print(f"Issue ID: {args.issue}")
  console.print(f"Issue Type: {bug_type}")
  console.print(f"Issue Commit: {env.get_base_commit()}")
  console.print(f"Issue Fix Commit: {env.get_hint_fix_commit()}")
  console.print(f"Issue Title: {env.get_hint_issue()['title']}")
  console.print(f"Issue Labels: {env.get_hint_issue()['labels']}")

  build_dir = os.path.join(get_llvm_build_dir(), "regression", args.issue)
  os.makedirs(build_dir, exist_ok=True)
  set_llvm_build_dir(build_dir)

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

  opt_path = Path(build_dir) / "bin" / "opt"
  if not opt_path.exists():
    console.print("Building LLVM for the regression test...")
    res, log = env.build()
    if not res:
      console.print("Build failed:", color="red")
      console.print(log)
      panic("Failed to build LLVM")
    console.print("LLVM built successfully!", color="green")
  else:
    console.print(f"LLVM already built at {build_dir}", color="green")

  # Set up LLM and agent
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
    panic(f"Unknown driver: {args.driver}")

  # Set up saved statistics and output
  stats_path = None
  if args.stats:
    stats_path = Path(args.stats)
    if stats_path.exists() and not args.force:
      panic(f"Stats file {stats_path} already exists.")

  history_path = None
  if args.history:
    history_path = Path(args.history)
    if history_path.exists() and not args.force:
      panic(f"History file {history_path} already exists.")

  review_path = None
  if args.review:
    review_path = Path(args.review)
    if review_path.exists() and not args.force:
      panic(f"Review file {review_path} already exists.")

  llvm = LLVM()

  stats = RunStats(command=vars(args))
  stats.total_time_sec = time.time()

  try:
    report = pr_review(
      agent=agent,
      pr_info=pr_info,
      pr_env=env,
      llvm=llvm,
      stats=stats,
      build_dir=build_dir,
    )
    stats.report = report
  except Exception as e:
    import traceback

    stats.error = type(e).__name__
    stats.errmsg = str(e)
    stats.traceback = traceback.format_exc()
    console.print(f"Error during regression review: {e}", color="red")
    console.print(stats.traceback)
  finally:
    stats.total_time_sec = time.time() - stats.total_time_sec
    stats.chat_rounds = agent.chat_stats["chat_rounds"]
    stats.input_tokens = agent.chat_stats["input_tokens"]
    stats.output_tokens = agent.chat_stats["output_tokens"]
    stats.cached_tokens = agent.chat_stats["cached_tokens"]
    stats.total_tokens = agent.chat_stats["total_tokens"]
    stats.chat_cost = agent.chat_stats["total_cost"]
    # Source of truth: full chat history (covers both phases and removed tools such as `stop`).
    history_usage = {}
    for message in agent.get_history():
      if getattr(message, "type", None) != "function_call":
        continue
      tool_name = getattr(message, "name", None)
      if not tool_name:
        continue
      history_usage[tool_name] = history_usage.get(tool_name, 0) + 1

    # Keep currently registered tools in output even if their usage is zero.
    all_tool_names = set(agent.tools.list(ignore_budget=True)) | set(
      history_usage.keys()
    )
    stats.tool_usage = [
      {"name": name, "usage": history_usage.get(name, 0)}
      for name in sorted(all_tool_names)
    ]

    if stats_path:
      with stats_path.open("w") as fout:
        json.dump(stats.as_dict(), fout, indent=2)
      console.print(f"Generation statistics saved to {stats_path}.")

    if history_path:
      with history_path.open("w") as fout:
        json.dump([asdict(m) for m in agent.get_history()], fout, indent=2)
      console.print(f"Chat history saved to {history_path}.")

    if review_path:
      review_content = generate_review(pr_info, stats)
      with review_path.open("w", encoding="utf-8") as fout:
        fout.write(review_content)
      console.print(f"Review saved to {review_path}.")

  console.print("Bugs Found")
  console.print("----------")
  for idx, bug in enumerate(stats.bugs):
    console.print(f"Bug #{idx + 1}:")
    if bug.thoughts:
      console.print("Thoughts:")
      console.print(bug.thoughts)
    console.print("Original LLVM IR:")
    console.print(bug.original_ir)
    console.print("Transformed LLVM IR:")
    console.print(bug.transformed_ir)
    console.print("Verification Log:")
    console.print(bug.log)
    console.print("----------")
  console.print("Report")
  console.print("----------")
  console.print(stats.report)
  console.print("Statistics")
  console.print("----------")
  console.print(json.dumps(stats.as_dict(), indent=2))


if __name__ == "__main__":
  main()
