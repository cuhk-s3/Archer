#!/usr/bin/env python3
"""
PR Review Script for Open Pull Requests

This script handles code review for open PRs in LLVM, similar to main.py but with the following differences:
1. Input is a PR ID instead of an issue ID
2. Extracts patch from PR information
3. Applies the patch and builds LLVM (in build_dir/open/)
"""

import json
import os
import re
import shutil
import subprocess
import time
from argparse import ArgumentParser
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import json_repair
import requests
from unidiff import PatchSet

import prompts
from base.console import get_boxed_console
from llvm.debugger import DebuggerBase
from llvm.llvm import LLVM
from llvm.llvm_helper import (
  apply as apply_patch,
)
from llvm.llvm_helper import (
  dataset_dir,
  get_langref_desc,
  get_llvm_build_dir,
  infer_related_components,
  llvm_dir,
  reset,
  set_llvm_build_dir,
)
from lms.agent import AgentBase
from main import (
  Bug,
  RunStats,
  TestStrategy,
  check_duplicate_tool_call,
  ensure_tools_available,
  get_component_knowledge,
)
from tools.difftest import DiffTestTool
from tools.findn import FindNTool
from tools.grepn import GrepNTool
from tools.langref import LangRefTool
from tools.listn import ListNTool
from tools.readn import ReadNTool
from tools.report import ReportTool
from tools.stop import StopTool
from tools.tests import Test, TestsTool
from tools.trans import TransTool
from tools.verify import VerifyTool

# - ===============================================
# - Agent configurations
# - ===============================================

MAX_CHAT_ROUNDS = 500
MAX_CONSUMED_TOKENS = 10_000_000
MAX_TCS_GET_CONTEXT = 250
MAX_ROLS_PER_TC = 250

# - ================================================
# - LLVM settings
# - ================================================
COMPILATION_FLAGS = "-O0"
ADDITIONAL_CMAKE_FLAGS = [
  f"-DCMAKE_C_FLAGS_RELWITHDEBINFO={COMPILATION_FLAGS}",
  f"-DCMAKE_CXX_FLAGS_RELWITHDEBINFO={COMPILATION_FLAGS}",
]
ALIVE_TV_PATH = os.environ.get("LAB_LLVM_ALIVE_TV", None)
LLUBI_PATH = os.environ.get("LAB_LLVM_LLUBI", None)

console = get_boxed_console(debug_mode=True)


def panic(msg: str):
  console.print(f"Error: {msg}", color="red")
  exit(1)


if not ALIVE_TV_PATH:
  panic("LAB_LLVM_ALIVE_TV is not set")

if not LLUBI_PATH:
  panic("LAB_LLVM_LLUBI is not set")


@dataclass
class PRInfo:
  """Information extracted from a GitHub PR"""

  pr_id: int
  title: str
  author: str
  base_commit: str
  fix_commit: str  # Latest commit in the PR
  patch: str
  components: List[str]
  description: str = ""
  tests: List[dict] = field(default_factory=list)  # Filled after applying patch


class PREnvironment:
  """Simplified environment class for PR review"""

  def __init__(self, pr_info: PRInfo):
    self.pr_info = pr_info
    self.base_commit = pr_info.base_commit

  def get_langref_desc(self, keywords):
    """Get language reference descriptions for given keywords"""
    return get_langref_desc(keywords, self.base_commit)

  def get_tests(self):
    """Get the tests extracted from PR patch"""
    return self.pr_info.tests


def fetch_pr_info(pr_id: int, session: requests.Session) -> PRInfo:
  """Fetch PR information from GitHub API"""
  pr_url = f"https://api.github.com/repos/llvm/llvm-project/pulls/{pr_id}"
  pr = session.get(pr_url).json()

  if "message" in pr and pr["message"] == "Not Found":
    panic(f"PR #{pr_id} not found")

  if pr["state"] == "closed":
    panic(f"PR #{pr_id} is already closed. This script is for open PRs only.")

  # Fetch the patch
  patch_response = session.get(
    f"https://api.github.com/repos/llvm/llvm-project/pulls/{pr_id}",
    headers={"Accept": "application/vnd.github.v3.diff"},
  )
  patch = patch_response.text

  # Get files changed
  files_url = pr["url"] + "/files"
  files = session.get(files_url).json()
  changed_files = [f["filename"] for f in files]

  # Check for invalid file changes (same as postfix_extract.py)
  changed_files_str = "\n".join(changed_files)
  if "/AsmParser/" in changed_files_str or "/Bitcode/" in changed_files_str:
    panic("PR contains changes to AsmParser or Bitcode which are not supported")

  # Filter for LLVM lib/include files and infer components
  llvm_files = [
    f for f in changed_files if f.startswith(("llvm/lib/", "llvm/include/"))
  ]
  components = infer_related_components(llvm_files)

  # Get the latest commit (head) of the PR
  fix_commit = pr["head"]["sha"]

  # Note: tests will be extracted AFTER applying the patch
  return PRInfo(
    pr_id=pr_id,
    title=pr["title"],
    author=pr["user"]["login"],
    base_commit=pr["base"]["sha"],
    fix_commit=fix_commit,
    patch=patch,
    components=sorted(components),
    description=pr.get("body", "") or "",
  )


def extract_tests_from_patch(full_patch: str) -> List[dict]:
  """Extract tests from patch after it has been applied, similar to postfix_extract.py

  This should be called AFTER the patch has been applied to the repo (i.e., after setup_llvm_environment).
  At that point, HEAD contains the patch and we can read the test files.
  """
  tests = []

  # Parse only test files from the patch
  try:
    patchset = PatchSet(full_patch)
  except Exception as e:
    console.print(f"Warning: Failed to parse patch: {e}", color="yellow")
    return tests

  runline_pattern = re.compile(r"; RUN: (.+)\| FileCheck")
  testname_pattern = re.compile(r"define .+ @([.\w]+)\(")

  llvm_dir = os.environ["LAB_LLVM_DIR"]

  for file in patchset:
    # Only process test files
    if not file.path.startswith("llvm/test/"):
      continue

    # Read file from working directory (patch has been applied)
    # For new files: they're not in git history yet, must read from filesystem
    # For modified files: working directory has the latest version after patch
    test_file_path = os.path.join(llvm_dir, file.path)
    try:
      with open(test_file_path, "r") as f:
        test_file = f.read()
    except Exception as e:
      console.print(f"Warning: Could not read {file.path}: {e}", color="yellow")
      continue

    # Extract RUN commands
    commands = []
    for match in re.findall(runline_pattern, test_file):
      commands.append(match.strip())

    # Determine which test functions to extract
    test_names = set()

    if file.is_added_file:
      # For newly added files, extract all function definitions
      for match in re.findall(testname_pattern, test_file):
        test_names.add(match.strip())
    else:
      # For modified files, extract only the test functions that were modified
      for hunk in file:
        matched = re.search(testname_pattern, hunk.section_header)
        if matched:
          test_names.add(matched.group(1))
        for line in hunk.target:
          for match in re.findall(testname_pattern, line):
            test_names.add(match.strip())

    # Extract each test function using llvm-extract
    subtests = []
    if test_names:
      for test_name in test_names:
        try:
          test_body = subprocess.check_output(
            ["llvm-extract", f"--func={test_name}", "-S", "-"],
            input=test_file.encode(),
          ).decode()
          test_body = test_body.removeprefix(
            "; ModuleID = '<stdin>'\nsource_filename = \"<stdin>\"\n"
          ).removeprefix("\n")
          subtests.append(
            {
              "test_name": test_name,
              "test_body": test_body,
            }
          )
        except Exception:
          # llvm-extract may fail for some functions, skip them
          pass

    # If no functions were found or extracted, use the whole file as one test (fallback)
    if not subtests:

      def is_valid_test_line(line: str):
        line = line.strip()
        if (
          line.startswith("; NOTE")
          or line.startswith("; RUN")
          or line.startswith("; CHECK")
        ):
          return False
        return True

      normalized_body = "\n".join(filter(is_valid_test_line, test_file.splitlines()))
      if normalized_body.strip():  # Only add if there's actual content
        tests.append(
          {
            "file": file.path,
            "commands": commands,
            "tests": [{"test_name": "<module>", "test_body": normalized_body}],
          }
        )
    else:
      tests.append({"file": file.path, "commands": commands, "tests": subtests})

  return tests


def setup_github_session() -> requests.Session:
  """Setup GitHub API session with authentication"""
  github_token = os.environ.get("LAB_GITHUB_TOKEN")
  if not github_token:
    panic("LAB_GITHUB_TOKEN environment variable is not set")

  session = requests.Session()
  session.headers.update(
    {
      "X-GitHub-Api-Version": "2022-11-28",
      "Authorization": f"Bearer {github_token}",
      "Accept": "application/vnd.github+json",
    }
  )
  return session


def setup_llvm_environment(pr_info: PRInfo) -> bool:
  """Setup LLVM environment by checking out base commit and applying patch

  After this function, pr_info.tests will be populated with extracted tests.
  """
  # Checkout base commit
  try:
    reset(pr_info.base_commit)
  except Exception as e:
    console.print(f"Failed to checkout base commit: {e}", color="red")
    return False

  # Apply the patch
  success, log = apply_patch(pr_info.patch)
  if not success:
    console.print(f"Failed to apply patch: {log}", color="red")
    return False

  # Extract tests from the applied patch
  pr_info.tests = extract_tests_from_patch(pr_info.patch)

  return True


def get_pr_info_path(pr_id: int) -> Path:
  """Get the path to store PR info for a specific PR in dataset_dir/open/"""
  open_dir = Path(dataset_dir) / "open"
  open_dir.mkdir(parents=True, exist_ok=True)
  return open_dir / f"{pr_id}.json"


def save_pr_info(pr_info: PRInfo):
  """Save PR info to a JSON file"""
  info_path = get_pr_info_path(pr_info.pr_id)
  with open(info_path, "w") as f:
    json.dump(asdict(pr_info), f, indent=2)


def load_saved_pr_info(pr_id: int) -> Optional[PRInfo]:
  """Load previously saved PR info"""
  info_path = get_pr_info_path(pr_id)
  if not info_path.exists():
    return None
  try:
    with open(info_path, "r") as f:
      data = json.load(f)
    return PRInfo(**data)
  except Exception as e:
    console.print(f"Warning: Failed to load saved PR info: {e}", color="yellow")
    return None


def pr_info_changed(old_pr_info: Optional[PRInfo], new_pr_info: PRInfo) -> bool:
  """Check if PR info has changed by comparing fix_commit

  If the latest commit in the PR has changed, we need to rebuild.
  """
  if old_pr_info is None:
    return True  # No saved info, always need to rebuild

  # Compare fix_commit (latest commit in PR)
  if old_pr_info.fix_commit != new_pr_info.fix_commit:
    console.print(
      f"PR commit has changed: {old_pr_info.fix_commit[:7]} -> {new_pr_info.fix_commit[:7]}",
      color="yellow",
    )
    return True

  return False


def get_tool_list(
  pr_env: PREnvironment,
  llvm: LLVM,
  build_dir: str,
  debugger: DebuggerBase = None,
  phase: int = 0,
):
  """Get tool list for different phases"""
  common_tools = [
    (FindNTool(llvm_dir, n=MAX_ROLS_PER_TC), MAX_TCS_GET_CONTEXT),
    (GrepNTool(llvm_dir, n=MAX_ROLS_PER_TC), MAX_TCS_GET_CONTEXT),
    (ListNTool(llvm_dir, n=MAX_ROLS_PER_TC), MAX_TCS_GET_CONTEXT),
    (ReadNTool(llvm_dir, n=MAX_ROLS_PER_TC), MAX_TCS_GET_CONTEXT),
    (LangRefTool(pr_env), MAX_TCS_GET_CONTEXT),
  ]

  if phase == 1:
    return common_tools + [
      (StopTool(), MAX_TCS_GET_CONTEXT),
    ]
  elif phase == 2:
    return common_tools + [
      (TransTool(build_dir), MAX_TCS_GET_CONTEXT),
      (VerifyTool(build_dir, alive_path=ALIVE_TV_PATH), MAX_TCS_GET_CONTEXT),
      (DiffTestTool(build_dir, llubi_path=LLUBI_PATH), MAX_TCS_GET_CONTEXT * 2),
      (ReportTool(), MAX_TCS_GET_CONTEXT),
    ]
  else:
    return common_tools + [
      (TransTool(build_dir), MAX_TCS_GET_CONTEXT),
      (VerifyTool(build_dir, alive_path=ALIVE_TV_PATH), MAX_TCS_GET_CONTEXT),
      (DiffTestTool(build_dir, llubi_path=LLUBI_PATH), MAX_TCS_GET_CONTEXT * 2),
      (StopTool(), MAX_TCS_GET_CONTEXT),
      (ReportTool(), MAX_TCS_GET_CONTEXT),
    ]


def generate_test_for_pr(
  agent: AgentBase,
  pr_env: PREnvironment,
  llvm: LLVM,
  stats: RunStats,
) -> Optional[str]:
  """Generate tests for PR (Phase 2) - following main.py's generate_test logic"""
  console.print("Phase 2: Generating and verifying test cases for PR...")

  # Extract test objects from PR environment (like main.py does from fixenv)
  initial_tests = pr_env.get_tests()
  test_objects = []
  for _, test_file in enumerate(initial_tests):
    commands = test_file.get("commands", [])
    tests = test_file.get("tests", [])
    for test_idx, test in enumerate(tests):
      test_name = test.get("test_name", f"test_{test_idx}")
      test_body = test.get("test_body", "")
      test_objects.append(
        Test(test_name=test_name, test_body=test_body, commands=commands)
      )

  test_get_timestamps = {}

  def validator(index: int) -> Tuple[bool, str]:
    if index not in test_get_timestamps:
      return (
        False,
        f"You must call `tests_manager` with action='get' and index={index} before marking it as tested.",
      )

    start_time = test_get_timestamps[index]
    relevant_actions = stats.test_traj[start_time:]

    has_verification = False
    for action_str in relevant_actions:
      try:
        action = json_repair.loads(action_str)
        if action.get("test_index") == index and action.get("tool") in [
          "verify",
          "difftest",
        ]:
          has_verification = True
          break
      except Exception:
        pass

    if not has_verification:
      return False, (
        f"You have not performed any `verify` or `difftest` actions for test {index} since you retrieved it. "
        "You must verify the test case before marking it as tested. Ensure you pass `test_index` and `covered_strategy` to verification tools."
      )

    return True, ""

  # Register TestsTool (like main.py does)
  tests_tool = TestsTool(test_objects, strategies=stats.strategies, validator=validator)
  agent.register_tool(tests_tool, MAX_TCS_GET_CONTEXT * 2)

  agent.append_user_message(
    prompts.PROMPT_GENERATE.format(
      strategies=str(stats.strategies),
    )
  )

  executed_tool_calls = set()
  consecutive_duplicates = [0]

  def tool_pre_check(name: str, args: dict) -> Optional[str]:
    return check_duplicate_tool_call(
      name, args, executed_tool_calls, consecutive_duplicates
    )

  agent.set_tool_pre_check_handler(tool_pre_check)

  def response_handler(_: str) -> Tuple[bool, str]:
    ensure_tools_available(agent, ["report"])
    return True, (
      "Error: You are not calling any tool or your tool call format is incorrect. "
      "You should always continue with tool calling and correct tool call format. "
      "You must use function tool call instead of using message to respond. "
      "Please continue."
      " If you are done, call the `report` tool with the result."
      " If you already called the `report` tool, please check the format and try again."
    )

  def tool_call_handler(name: str, args: str, res: str) -> Tuple[bool, str]:
    ensure_tools_available(agent, ["report", "verify", "difftest", "tests_manager"])

    if name == "tests_manager":
      try:
        args_obj = json.loads(args)
        if args_obj.get("action") == "get":
          idx = args_obj.get("index")
          if idx is not None:
            test_get_timestamps[int(idx)] = len(stats.test_traj)
      except Exception:
        pass

    if name == "verify":
      try:
        bug = json_repair.loads(res)
        stats.test_traj.append(res)
        idx = bug.get("test_index")
        cov = bug.get("covered_strategy")
        if idx is not None and cov:
          if cov not in tests_tool.all_strategies:
            return (
              True,
              f"Error: The strategy '{cov}' is not a valid Phase 1 strategy. "
              f"Please provide a valid strategy name from: {list(tests_tool.all_strategies)}.",
            )
          tests_tool.add_covered_strategy(idx, cov)
        if bug.get("found", False):
          stats.bugs.append(
            Bug(
              original_ir=bug["original_ir"],
              transformed_ir=bug["transformed_ir"],
              log=bug["log"],
              thoughts=bug.get("thoughts"),
            )
          )

        log = bug.get("log", "")
        if "failed-to-prove transformations" in log:
          match = re.search(r"(\d+)\s+failed-to-prove transformations", log)
          if match and int(match.group(1)) > 0:
            res += "\n\nHint: There are failed-to-prove transformations. You should consider using the `difftest` tool to verify the correctness of this case."
      except Exception:
        return (True, res)

    if name == "difftest":
      try:
        diff_result = json.loads(res)
        stats.test_traj.append(res)

        idx = diff_result.get("test_index")
        cov = diff_result.get("covered_strategy")
        if idx is not None and cov:
          if cov not in tests_tool.all_strategies:
            return (
              True,
              f"Error: The strategy '{cov}' is not a valid Phase 1 strategy. "
              f"Please provide a valid strategy name from: {list(tests_tool.all_strategies)}.",
            )
          tests_tool.add_covered_strategy(idx, cov)

        if diff_result.get("action") == "confirm":
          original_ir = "<missing>"
          transformed_ir = "<missing>"
          original_out = "<missing>"
          transformed_out = "<missing>"
          for i in range(len(stats.test_traj) - 1, -1, -1):
            try:
              prev_res = json.loads(stats.test_traj[i])
              if (
                prev_res.get("tool") == "difftest"
                and prev_res.get("action") == "test"
                and not prev_res.get("confirmed", False)
              ):
                original_ir = prev_res.get("original_ir", "<missing>")
                transformed_ir = prev_res.get("transformed_ir", "<missing>")
                original_out = prev_res.get("log", {}).get("original_test_output", "")
                transformed_out = prev_res.get("log", {}).get(
                  "transformed_test_output", ""
                )
                prev_res["confirmed"] = True
                stats.test_traj[i] = json.dumps(prev_res)
                break
            except Exception:
              pass

          if diff_result.get("found", False) and original_out != transformed_out:
            log_msg = f"Confirmed as bug by agent.\nOriginal Output: {original_out}\nTransformed Output: {transformed_out}"
            stats.bugs.append(
              Bug(
                original_ir=original_ir,
                transformed_ir=transformed_ir,
                log=log_msg,
                thoughts=diff_result.get("thoughts"),
              )
            )
        elif diff_result.get("action") == "test":
          return (True, res)
      except Exception:
        return (True, res)

    if name != "report":
      return True, res

    try:
      report_data = json.loads(res)
    except Exception:
      return (True, res)

    force_stop = report_data.get("force", False)
    all_tested = all(t.tested for t in test_objects)

    if not all_tested and not force_stop:
      return True, (
        "Error: You cannot call `report` yet "
        "because not all tests have been marked as tested (which requires covering all strategies per test). "
        "Please use `tests_manager` to check untested tests, "
        "test them, and mark them as tested. "
        "If you have already found at least one bug and want to stop immediately, set `force=True` in `report`."
      )

    if force_stop and not stats.bugs:
      return True, (
        "Error: You cannot use `force=True` in `report` because no bugs have been found yet. "
        "Please verify the bug using `verify` or `difftest` tools first."
      )

    stats.report = report_data.get("thoughts", None)
    return False, res

  ret = agent.run(
    [
      f"list{MAX_ROLS_PER_TC}",
      f"read{MAX_ROLS_PER_TC}",
      f"find{MAX_ROLS_PER_TC}",
      f"grep{MAX_ROLS_PER_TC}",
      "langref",
      "trans",
      "verify",
      "difftest",
      "tests_manager",
      "report",
    ],
    response_handler=response_handler,
    tool_call_handler=tool_call_handler,
    round_limit=MAX_CHAT_ROUNDS,
  )
  stats.phase2_round = agent.chat_stats["chat_rounds"] - stats.phase1_round
  return ret


def run_pr_agent(
  agent: AgentBase,
  pr_info: PRInfo,
  pr_env: PREnvironment,
  llvm: LLVM,
  stats: RunStats,
  build_dir: str,
  debugger: DebuggerBase = None,
) -> Optional[str]:
  """Main PR review agent"""
  agent.clear_history()
  agent.append_system_message(prompts.PROMPT_SYSTEM)

  #####################################################
  # Phase 1: Analyze the PR
  #####################################################
  console.print("Phase 1: Analyzing the PR...")
  # Combine title, description, and patch for the prompt
  full_patch = f"{pr_info.title}\n{pr_info.description}\n{pr_info.patch}"
  agent.append_user_message(
    prompts.PROMPT_ANALYZE.format(
      component=", ".join(pr_info.components),
      patch=full_patch,
      knowledge=get_component_knowledge(pr_info.components),
    )
  )

  executed_tool_calls = set()
  consecutive_duplicates = [0]

  def tool_pre_check(name: str, args: dict) -> Optional[str]:
    return check_duplicate_tool_call(
      name, args, executed_tool_calls, consecutive_duplicates
    )

  agent.set_tool_pre_check_handler(tool_pre_check)

  def response_handler(_: str) -> Tuple[bool, str]:
    ensure_tools_available(agent, ["stop"])
    return True, (
      "Error: You are not calling any tool or your tool call format is incorrect. "
      "You should always continue with tool calling and correct tool call format. "
      "You must use function tool call instead of using message to respond. "
      "Please continue."
      " If you are done, call the `stop` tool with the test strategies."
      " If you already called the `stop` tool, please check the format and try again."
    )

  def tool_call_handler(name: str, args: str, res: str) -> Tuple[bool, str]:
    # Note: Duplicate checking is now handled by tool_pre_check_handler in AgentBase

    ensure_tools_available(agent, ["stop"])
    if name != "stop":
      return True, res  # Continue the process
    try:
      # The stop tool returns a parseable JSON string
      json.loads(res)
    except Exception:
      return (True, res)  # Continue the process with an error message
    return False, res  # Stop the process with the result

  response = agent.run(
    [
      f"list{MAX_ROLS_PER_TC}",
      f"read{MAX_ROLS_PER_TC}",
      f"find{MAX_ROLS_PER_TC}",
      f"grep{MAX_ROLS_PER_TC}",
      "langref",
      "stop",
    ],
    response_handler=response_handler,
    tool_call_handler=tool_call_handler,
    round_limit=MAX_CHAT_ROUNDS,
  )
  stats.phase1_round = agent.chat_stats["chat_rounds"]

  # Parse the response to get potential test strategies
  response = json.loads(response)
  strategies = response.get("strategies", [])
  reasoning_thoughts = response.get("thoughts", "")
  test_strategies = []

  for strat in strategies:
    try:
      name, target, rationale, expected_issue = strat
      test_strategies.append(
        TestStrategy(
          name=name,
          target=target,
          rationale=rationale,
          expected_issue=expected_issue,
        )
      )
    except Exception as e:
      console.print(f"Warning: Invalid strategy format: {strat}: {e}", color="yellow")

  stats.reason_thou = reasoning_thoughts
  stats.strategies = [s.as_dict() for s in test_strategies]

  tools_phase2 = get_tool_list(pr_env, llvm, build_dir, debugger, phase=2)
  try:
    if hasattr(agent.tools, "remove_tool"):
      agent.tools.remove_tool("stop")
  except Exception:
    pass

  for to, th in tools_phase2:
    agent.register_tool(to, th)

  return generate_test_for_pr(
    agent=agent,
    pr_env=pr_env,
    llvm=llvm,
    stats=stats,
  )


def pr_review(
  agent: AgentBase,
  pr_info: PRInfo,
  pr_env: PREnvironment,
  llvm: LLVM,
  stats: RunStats,
  build_dir: str,
):
  """Main PR review function"""
  debugger = None

  # Register Phase 1 tools
  tools_phase1 = get_tool_list(pr_env, llvm, build_dir, debugger, phase=1)
  for to, th in tools_phase1:
    agent.register_tool(to, th)

  return run_pr_agent(
    debugger=debugger,
    agent=agent,
    pr_info=pr_info,
    pr_env=pr_env,
    llvm=llvm,
    stats=stats,
    build_dir=build_dir,
  )


def parse_args():
  parser = ArgumentParser(description="PR Review Tool for Open LLVM Pull Requests")
  parser.add_argument(
    "--pr",
    type=int,
    required=True,
    help="The PR ID to review.",
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
    help="The LLM API to use (default: openai).",
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
    panic("Error: The llvm-autoreview environment has not been brought up.")

  args = parse_args()

  # Set up console
  if args.debug:
    console.debug = True

  # Setup GitHub session
  session = setup_github_session()

  # Fetch PR information
  try:
    pr_info = fetch_pr_info(args.pr, session)
  except Exception as e:
    panic(f"Failed to fetch PR information: {e}")

  # Setup build directory under open/
  base_build_dir = get_llvm_build_dir()
  build_dir = os.path.join(base_build_dir, "open", str(args.pr))
  os.makedirs(build_dir, exist_ok=True)
  set_llvm_build_dir(build_dir)

  # Check if PR info has changed
  saved_pr_info = load_saved_pr_info(args.pr)
  pr_changed = pr_info_changed(saved_pr_info, pr_info)

  if pr_changed:
    console.print(
      "PR has changed or no previous build found. Preparing to rebuild...",
      color="yellow",
    )
    # Remove old build directory if it exists
    if Path(build_dir).exists():
      console.print(f"Removing old build directory: {build_dir}", color="yellow")
      shutil.rmtree(build_dir)
    os.makedirs(build_dir, exist_ok=True)

  # Setup LLVM environment
  if not setup_llvm_environment(pr_info):
    panic("Failed to setup LLVM environment")

  # Save PR info after successful setup
  save_pr_info(pr_info)

  # Build LLVM if not already built
  opt_path = Path(build_dir) / "bin" / "opt"
  if not opt_path.exists():
    console.print("Building LLVM with the PR patch...")
    from llvm import llvm_helper

    success, log = llvm_helper.build(
      max_build_jobs=int(
        os.environ.get("LLVM_AUTOREVIEW_MAX_BUILD_JOBS", os.cpu_count())
      ),
      additional_cmake_args=ADDITIONAL_CMAKE_FLAGS,
    )

    if not success:
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
    if stats_path.exists():
      panic(f"Stats file {stats_path} already exists.")

  history_path = None
  if args.history:
    history_path = Path(args.history)
    if history_path.exists():
      panic(f"History file {history_path} already exists.")

  llvm = LLVM()

  # Create PR environment
  pr_env = PREnvironment(pr_info)

  # Run PR review
  stats = RunStats(command=vars(args))
  stats.total_time_sec = time.time()

  try:
    report = pr_review(
      agent=agent,
      pr_info=pr_info,
      pr_env=pr_env,
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
    console.print(f"Error during PR review: {e}", color="red")
    console.print(stats.traceback)
  finally:
    stats.total_time_sec = time.time() - stats.total_time_sec
    stats.chat_rounds = agent.chat_stats["chat_rounds"]
    stats.input_tokens = agent.chat_stats["input_tokens"]
    stats.output_tokens = agent.chat_stats["output_tokens"]
    stats.cached_tokens = agent.chat_stats["cached_tokens"]
    stats.total_tokens = agent.chat_stats["total_tokens"]
    stats.chat_cost = agent.chat_stats["total_cost"]
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
