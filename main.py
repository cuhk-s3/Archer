#!/usr/bin/env python3
import json
import os
import re
import time
from argparse import ArgumentParser
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import json_repair

import prompts
from base.console import get_boxed_console
from dataset import get_store
from llvm.lab_env import PREnvironment, PREnvironmentError, PRInfo
from llvm.llvm import LLVM
from llvm.llvm_helper import (
  llvm_dir,
)
from lms.agent import AgentBase, RepeatedToolCallLimitExceeded
from repro import Reproducer, reproduce
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
from utils.log import Bug, RunStats, collect_agent_stats, print_results, save_outputs

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


class NoAvailableBugFound(Exception):
  pass


class ReachToolBudget(Exception):
  pass


@dataclass
class TestStrategy:
  name: str
  target: str
  rationale: str
  expected_issue: str

  def as_dict(self) -> dict:
    return {
      "name": self.name,
      "target": self.target,
      "rationale": self.rationale,
      "expected_issue": self.expected_issue,
    }

  def __str__(self) -> str:
    return json.dumps(self.as_dict(), indent=2)


def ensure_tools_available(agent: AgentBase, tools: List[str]):
  available_tools = agent.tools.list(ignore_budget=False)
  unavailable_tools = []
  for tool in tools:
    if tool not in available_tools:
      unavailable_tools.append(tool)
  if len(unavailable_tools) > 0:
    raise ReachToolBudget(f"Tools [{', '.join(unavailable_tools)}] are out of budget.")


def get_component_knowledge(component: List[str]) -> str:
  console.print(f"Retrieving knowledge for component: {component} ...")

  knowledge_dir = Path(__file__).parent / "subsystem" / "summary"

  knowledge_file = []
  for comp_name in component:
    candidate = knowledge_dir / f"{comp_name}.md"
    if candidate.exists():
      knowledge_file.append(candidate)

  if not knowledge_file:
    return "No specific knowledge provided for this component."

  knowledge = [f.read_text(encoding="utf-8") for f in knowledge_file]
  return "\n".join(knowledge)


def check_duplicate_tool_call(
  name: str, args: object, executed_tool_calls: set, consecutive_duplicates: List[int]
) -> Optional[str]:
  try:
    if isinstance(args, str):
      obj = json_repair.loads(args)
    else:
      obj = args
    normalized_args = json.dumps(obj, sort_keys=True)
  except Exception:
    normalized_args = "".join(str(args).split())

  if not any(name.startswith(prefix) for prefix in ["find", "grep", "read", "list"]):
    return None

  call_signature = (name, normalized_args)
  if call_signature in executed_tool_calls:
    consecutive_duplicates[0] += 1
    if consecutive_duplicates[0] >= 5:
      raise RepeatedToolCallLimitExceeded()
    return (
      f"Error: You have already executed the tool '{name}' with these exact arguments. "
      "Please change your arguments or thoughts to try a different approach. "
      "Repeating the same action will not yield new results. DO NOT repeat the same tool call!"
    )

  executed_tool_calls.add(call_signature)
  consecutive_duplicates[0] = 0
  return None


def get_tool_list(
  pr_env: PREnvironment,
  llvm: LLVM,
  build_dir: str,
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
              repro_kind="verify",
              args=bug.get("args"),
            )
          )

        log = bug.get("log", "")
        if "failed-to-prove transformations" in log:
          match = re.search(r"(\d+)\s+failed-to-prove transformations", log)
          if match and int(match.group(1)) > 0:
            res += "\n\nHint: There are failed-to-prove transformations. You should consider using the `difftest` tool to verify the correctness of this case."
      except Exception:
        return (True, res)

    if name == "trans":
      try:
        trans_result = json.loads(res)
        # Check if trans returned a crash (bug found)
        if trans_result.get("is_crash") and trans_result.get("found"):
          stats.test_traj.append(res)
          stats.bugs.append(
            Bug(
              original_ir=trans_result["original_ir"],
              transformed_ir=trans_result.get("transformed_ir", "<crash>"),
              log=trans_result["log"],
              thoughts=trans_result.get("thoughts"),
              repro_kind="trans",
              args=trans_result.get("args"),
            )
          )
          return (True, res)
      except Exception:
        pass

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
          difftest_args = None
          difftest_call_instr = None
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
                difftest_args = prev_res.get("args")
                difftest_call_instr = prev_res.get("call_instr")
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
                repro_kind="difftest",
                args=difftest_args,
                call_instr=difftest_call_instr,
              )
            )
        elif diff_result.get("action") == "test":
          return (True, res)
      except Exception:
        return (True, res)

    if name == "report":
      report_data = json.loads(res)

      force_stop = report_data.get("force", False)
      all_tested = all(t.tested for t in test_objects)

      console.print(
        f"Report called. force={force_stop}, all_tested={all_tested}, bugs_found={len(stats.bugs)}"
      )

      # If force=True, allow immediate stop without any checks
      if force_stop:
        console.print("Force stopping the process as requested.")
        stats.report = report_data.get("thoughts", None)
        return False, res

      # If all tests have been completed, allow the report regardless of bugs found
      if all_tested:
        stats.report = report_data.get("thoughts", None)
        return False, res

      # If not all tests are done and no force stop, require continuing
      return True, (
        "Error: You cannot call `report` yet "
        "because not all tests have been marked as tested (which requires covering all strategies per test). "
        "Please use `tests_manager` to check untested tests, "
        "test them, and mark them as tested. "
        "If you want to stop immediately without further testing, set `force=True` in `report`."
      )

    return True, res  # Continue the process for other tools

  try:
    return agent.run(
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
  finally:
    # Ensure phase 2 rounds are recorded even if agent.run exits via exception
    # (e.g. ReachTokenLimit / ReachRoundLimit).
    stats.phase2_round = max(0, agent.chat_stats["chat_rounds"] - stats.phase1_round)


def run_pr_agent(
  agent: AgentBase,
  pr_info: PRInfo,
  pr_env: PREnvironment,
  llvm: LLVM,
  stats: RunStats,
  build_dir: str,
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

  tools_phase2 = get_tool_list(pr_env, llvm, build_dir, phase=2)
  try:
    if hasattr(agent.tools, "remove_tool"):
      agent.tools.remove_tool("stop")
  except Exception:
    pass

  existing_tools = set(agent.tools.list(ignore_budget=True))
  for to, th in tools_phase2:
    tool_name = to.name()
    if tool_name in existing_tools:
      continue
    agent.register_tool(to, th)
    existing_tools.add(tool_name)

  return generate_test_for_pr(
    agent=agent,
    pr_env=pr_env,
    llvm=llvm,
    stats=stats,
  )


# - ===============================================
# - DB-backed review orchestration helpers
# - ===============================================
def _repro_from_row(row) -> Reproducer:
  """Build a Reproducer from a ``bugs`` DB row."""
  return Reproducer(
    kind=row["repro_kind"] or "verify",
    original_ir=row["original_ir"] or "",
    args=row["args"] or "",
    call_instr=row["call_instr"],
  )


def _repro_from_bug(bug: Bug) -> Reproducer:
  """Build a Reproducer from an in-memory ``Bug``."""
  return Reproducer(
    kind=bug.repro_kind or "verify",
    original_ir=bug.original_ir or "",
    args=bug.args or "",
    call_instr=bug.call_instr,
  )


def ensure_version(store, pr_info: PRInfo, existing_version_id: Optional[int]) -> int:
  """Return the DB version_id for this PR commit, creating it if necessary."""
  if existing_version_id is not None:
    return existing_version_id
  version_id, _ = store.upsert_pr_version(asdict(pr_info))
  return version_id


def run_regression_gate(
  store, prev_version, build_dir: str
) -> List[Tuple[object, str]]:
  """Regression gate for multi-version PRs.

  Re-run every still-active bug of the *previous* version against the *current*
  patched build. Returns the list of ``(bug_row, log)`` that STILL trigger. An
  empty list means the current version is clear to open a review.
  """
  still_triggering: List[Tuple[object, str]] = []
  active = store.list_active_bugs(int(prev_version["id"]))
  if not active:
    return still_triggering

  console.print(
    f"Regression gate: re-running {len(active)} previous-version bug(s) "
    f"on the current build..."
  )
  for bug_row in active:
    repro = _repro_from_row(bug_row)
    if not repro.is_runnable():
      console.print(
        f"  bug #{bug_row['id']} ({repro.kind}) not runnable; skipping.",
        color="yellow",
      )
      continue
    triggered, log = reproduce(
      build_dir, repro, alive_path=ALIVE_TV_PATH, llubi_path=LLUBI_PATH
    )
    console.print(f"  bug #{bug_row['id']} ({repro.kind}) triggered={triggered}")
    if triggered:
      still_triggering.append((bug_row, log))
  return still_triggering


def run_baseline_check(pr_env: PREnvironment, bugs: List[Bug]) -> None:
  """Check patch-specificity: re-run each found bug on the baseline build.

  Builds the base commit WITHOUT the patch and re-runs every bug. A bug that
  also triggers on the baseline is flagged ``non_patch_specific`` (the patch is
  not what introduced it).
  """
  if not bugs:
    return

  try:
    baseline_dir = pr_env.prepare_baseline(additional_cmake_args=ADDITIONAL_CMAKE_FLAGS)
  except PREnvironmentError as e:
    console.print(
      f"Baseline build failed; skipping baseline check: {e}", color="yellow"
    )
    return

  console.print(f"Baseline check: re-running {len(bugs)} bug(s) on the baseline...")
  for bug in bugs:
    repro = _repro_from_bug(bug)
    bug.baseline_checked = True
    if not repro.is_runnable():
      bug.baseline_triggered = None
      continue
    triggered, _ = reproduce(
      baseline_dir, repro, alive_path=ALIVE_TV_PATH, llubi_path=LLUBI_PATH
    )
    bug.baseline_triggered = triggered
    bug.non_patch_specific = triggered
    console.print(
      f"  bug ({repro.kind}) triggered_on_baseline={triggered} "
      f"-> non_patch_specific={triggered}"
    )


def persist_review(store, pr_id: int, version_id: int, review_id: int, stats, agent):
  """Persist final review stats and its bugs (with baseline flags) to the DB."""
  status = "failed" if stats.error else "succeeded"
  payload = stats.as_dict()
  payload["status"] = status
  try:
    payload["history"] = [asdict(m) for m in agent.get_history()]
  except Exception:
    payload["history"] = None
  store.finish_review(review_id, payload)

  for bug in stats.bugs:
    bug_id = store.add_bug(
      pr_id,
      version_id,
      review_id,
      {
        "repro_kind": bug.repro_kind,
        "original_ir": bug.original_ir,
        "transformed_ir": bug.transformed_ir,
        "args": bug.args,
        "call_instr": bug.call_instr,
        "log": bug.log,
        "thoughts": bug.thoughts,
      },
    )
    if bug.baseline_checked and bug.baseline_triggered is not None:
      store.set_bug_baseline(bug_id, bool(bug.baseline_triggered))


def pr_review(
  agent: AgentBase,
  pr_info: PRInfo,
  pr_env: PREnvironment,
  llvm: LLVM,
  stats: RunStats,
  build_dir: str,
):
  """Main PR review function"""
  # Register Phase 1 tools
  tools_phase1 = get_tool_list(pr_env, llvm, build_dir, phase=1)
  for to, th in tools_phase1:
    agent.register_tool(to, th)

  return run_pr_agent(
    agent=agent,
    pr_info=pr_info,
    pr_env=pr_env,
    llvm=llvm,
    stats=stats,
    build_dir=build_dir,
  )


def parse_args():
  parser = ArgumentParser(description="PR Review Tool for LLVM Pull Requests")
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
    panic("Error: The llvm-autoreview environment has not been brought up.")

  args = parse_args()

  # Set up console
  if args.debug:
    console.debug = True

  # Set up the PR environment: load/extract PR info, prepare the per-PR build
  # directory, checkout the base commit, apply the patch and build LLVM.
  try:
    pr_env = PREnvironment.load(args.pr, console)
    build_dir = pr_env.prepare(additional_cmake_args=ADDITIONAL_CMAKE_FLAGS)
  except PREnvironmentError as e:
    panic(str(e))

  pr_info = pr_env.pr_info

  # Resolve this commit's DB version and apply the multi-version regression gate:
  # only open a review if the previous version's bugs no longer trigger here.
  store = get_store()
  version_id = ensure_version(store, pr_info, pr_env.version_id)
  pr_env.version_id = version_id

  prev_version = store.get_previous_version(version_id)
  if prev_version is not None:
    still = run_regression_gate(store, prev_version, build_dir)
    if still:
      review_id = store.create_review(pr_info.pr_id, version_id, pr_info.fix_commit)
      reason = (
        f"{len(still)} previous-version bug(s) still trigger on commit "
        f"{pr_info.fix_commit[:10]}; review not opened."
      )
      store.skip_review(review_id, reason)
      console.print(reason, color="yellow")
      return
    # Previous version's bugs no longer trigger -> considered fixed by this version.
    for bug_row in store.list_active_bugs(int(prev_version["id"])):
      store.mark_bug_fixed(int(bug_row["id"]), version_id)

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

  # Open the review run in the DB now that the gate has passed.
  review_id = store.create_review(pr_info.pr_id, version_id, pr_info.fix_commit)

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
    collect_agent_stats(stats, agent)
    # Patch-specificity: re-run found bugs on the baseline (base commit, no patch).
    run_baseline_check(pr_env, stats.bugs)
    # Persist review + bugs (with baseline flags) to the DB.
    persist_review(store, pr_info.pr_id, version_id, review_id, stats, agent)
    cur_version = store.get_version(version_id)
    version_meta = {
      "seq": int(cur_version["seq"]) if cur_version is not None else None,
      "version_id": version_id,
    }
    if prev_version is not None:
      version_meta["prev_fix_commit"] = prev_version["fix_commit"]
      version_meta["gate_conclusion"] = (
        "passed — previous version's bug(s) no longer trigger "
        "(treated as fixed by this version)"
      )
    save_outputs(
      stats,
      pr_info,
      agent,
      console,
      stats_path,
      history_path,
      review_path,
      version_meta,
    )

  print_results(stats, console)


if __name__ == "__main__":
  main()
