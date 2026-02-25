import json
import os
import time
from argparse import ArgumentParser
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import json_repair

import prompts
from base.console import get_boxed_console
from llvm.debugger import DebuggerBase
from llvm.lab_env import Environment
from llvm.llvm import LLVM
from llvm.llvm_helper import (
  get_llvm_build_dir,
  git_execute,
  llvm_dir,
  reset,
  set_llvm_build_dir,
)
from lms.agent import AgentBase
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

# We restrict the agent to chat at most 500 rounds for each run
# and consume at most 10 million tokens among all runs.
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
# TODO: integrate llubi to env scripts
LLUBI_PATH = os.environ.get("LAB_LLVM_LLUBI", None)

# - ================================================
# - Statistis and output
# - ================================================


def panic(msg: str):
  console.print(f"Error: {msg}", color="red")
  exit(1)


if not ALIVE_TV_PATH:
  panic("LAB_LLVM_ALIVE_TV is not set")

if not LLUBI_PATH:
  panic("LAB_LLVM_LLUBI is not set")


@dataclass
class Bug:
  original_ir: str
  transformed_ir: str
  log: str
  thoughts: Optional[str] = None


@dataclass
class RunStats:
  # Command to run autoreview
  command: dict
  # The error message for failed runs
  error: Optional[str] = None
  errmsg: Optional[str] = None
  traceback: Optional[str] = None
  # Agent interaction stats
  input_tokens: int = 0
  output_tokens: int = 0
  cached_tokens: int = 0
  total_tokens: int = 0
  chat_cost: float = 0.0
  chat_rounds: int = 0
  phase1_round: int = 0
  phase2_round: int = 0
  total_time_sec: float = 0.0
  # The tool usage
  tool_usage: List[dict] = field(default_factory=list)
  # Review stats
  strategies: List[dict] = field(
    default_factory=lambda *_, **__: [
      {
        "name": "<not-provided>",
        "target": "<not-provided>",
        "rationale": "<not-provided>",
        "expected_issue": "<not-provided>",
      }
    ]
  )
  reason_thou: str = "<not-provided>"
  # The generated bugs for successful runs
  bugs: List[Bug] = field(default_factory=list)
  test_traj: List[str] = field(
    default_factory=list
  )  # Trajectories of patches ever tried during testing
  report: Optional[str] = None

  def as_dict(self) -> dict:
    return asdict(self)


# - ===============================================
# - Agent's main code
# - ==============================================


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


def get_tool_list(
  fixenv: Environment,
  llvm: LLVM,
  build_dir: str,
  debugger: DebuggerBase = None,
  phase: int = 0,
):
  common_tools = [
    # General tools
    (FindNTool(llvm_dir, n=MAX_ROLS_PER_TC), MAX_TCS_GET_CONTEXT),
    (GrepNTool(llvm_dir, n=MAX_ROLS_PER_TC), MAX_TCS_GET_CONTEXT),
    (ListNTool(llvm_dir, n=MAX_ROLS_PER_TC), MAX_TCS_GET_CONTEXT),
    (ReadNTool(llvm_dir, n=MAX_ROLS_PER_TC), MAX_TCS_GET_CONTEXT),
    # LLVM-specific tools
    (LangRefTool(fixenv), MAX_TCS_GET_CONTEXT),
  ]

  if phase == 1:
    return common_tools + [
      # Stop the analysis (Phase 1)
      (StopTool(), MAX_TCS_GET_CONTEXT),
    ]
  elif phase == 2:
    return common_tools + [
      # LLVM-specific tools for Phase 2
      (TransTool(build_dir), MAX_TCS_GET_CONTEXT),
      (VerifyTool(build_dir, alive_path=ALIVE_TV_PATH), MAX_TCS_GET_CONTEXT),
      (DiffTestTool(build_dir, llubi_path=LLUBI_PATH), MAX_TCS_GET_CONTEXT * 2),
      # Report the bug (Phase 2)
      (ReportTool(), MAX_TCS_GET_CONTEXT),
    ]
  else:
    # Default behavior: return all tools (maybe for retro-compatibility or fallback)
    return common_tools + [
      (TransTool(build_dir), MAX_TCS_GET_CONTEXT),
      (VerifyTool(build_dir, alive_path=ALIVE_TV_PATH), MAX_TCS_GET_CONTEXT),
      (DiffTestTool(build_dir, llubi_path=LLUBI_PATH), MAX_TCS_GET_CONTEXT * 2),
      (StopTool(), MAX_TCS_GET_CONTEXT),
      (ReportTool(), MAX_TCS_GET_CONTEXT),
    ]


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
  name: str, args: str, executed_tool_calls: set
) -> Optional[str]:
  try:
    # Use json_repair to handle partially malformed JSON
    obj = json_repair.loads(args)
    # Ensure consistent string representation
    normalized_args = json.dumps(obj, sort_keys=True)
  except Exception:
    # Fallback to simple string normalization if JSON parsing fails entirely
    # Remove whitespace to be safer against formatting changes
    normalized_args = "".join(args.split())

  call_signature = (name, normalized_args)
  if call_signature in executed_tool_calls:
    return (
      f"Error: You have already executed the tool '{name}' with these exact arguments. "
      "Please change your arguments or thoughts to try a different approach. "
      "Repeating the same action will not yield new results."
    )
  executed_tool_calls.add(call_signature)
  return None


def generate_test(
  agent: AgentBase,
  fixenv: Environment,
  llvm: LLVM,
  stats: RunStats,
) -> Optional[str]:
  initial_tests = fixenv.get_tests()
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
        # Check if the action is verify or difftest and is associated with the current test index
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

  tests_tool = TestsTool(test_objects, strategies=stats.strategies, validator=validator)
  agent.register_tool(tests_tool, MAX_TCS_GET_CONTEXT * 2)

  console.print("Phase 2: Generating and verifying test cases ...")
  agent.append_user_message(
    prompts.PROMPT_GENERATE.format(
      strategies=str(stats.strategies),
    )
  )

  executed_tool_calls = set()

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
    # Check for duplicate tool calls
    nonlocal executed_tool_calls
    if dup_msg := check_duplicate_tool_call(name, args, executed_tool_calls):
      return True, dup_msg

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
      except Exception:
        return (True, res)  # Continue the process with an error message
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
          # Find the last unconfirmed test in test_traj
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
            # We only add to bugs if the agent confirms it's a real bug
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
        return (True, res)  # Continue the process with an error message
    if name != "report":
      return True, res  # Continue the process
    all_tested = all(t.tested for t in test_objects)
    if not all_tested:
      return True, (
        "Error: You cannot call `report` yet "
        "because not all tests have been marked as tested (which requires covering all strategies per test). "
        "Please use `tests_manager` to check untested tests, "
        "test them, and mark them as tested."
      )

    try:
      # The report tool returns a parseable JSON string
      json.loads(res)
    except Exception:
      return (True, res)  # Continue the process with an error message
    stats.report = json.loads(res).get("thoughts", None)
    return False, res  # Stop the process with the result

  ret = agent.run(
    [
      # Explore codebase tools
      f"list{MAX_ROLS_PER_TC}",
      f"read{MAX_ROLS_PER_TC}",
      f"find{MAX_ROLS_PER_TC}",
      f"grep{MAX_ROLS_PER_TC}",
      # Documentation tools
      "langref",
      # Verification and transformation tools
      "trans",
      "verify",
      "difftest",
      "tests_manager",
      # Stop tool to finish the analysis
      "report",
    ],
    response_handler=response_handler,
    tool_call_handler=tool_call_handler,
    round_limit=MAX_CHAT_ROUNDS,
  )
  stats.phase2_round = agent.chat_stats["chat_rounds"] - stats.phase1_round
  return ret


def run_mini_agent(
  agent: AgentBase,
  fixenv: Environment,
  llvm: LLVM,
  stats: RunStats,
  build_dir: str,
  debugger: DebuggerBase = None,
) -> Optional[str]:
  agent.clear_history()
  agent.append_system_message(prompts.PROMPT_SYSTEM)

  #####################################################
  # The agent runs by:
  # 1. Analyze the fix first to reason about the possible issues and propose potential bug-trigger strategies.
  # 2. Generate test cases and verify the proposed strategies to confirm the real bug.
  #####################################################

  console.print("Phase 1: Analyzing the fix ...")
  agent.append_user_message(
    prompts.PROMPT_ANALYZE.format(
      bug_type=fixenv.get_bug_type(),
      component=", ".join(fixenv.get_hint_components()),
      patch=fixenv.get_reference_patch(),
      knowledge=get_component_knowledge(fixenv.get_hint_components()),
    )
  )

  executed_tool_calls = set()

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
    if name != "stop":
      # Check for duplicate tool calls
      nonlocal executed_tool_calls
      if dup_msg := check_duplicate_tool_call(name, args, executed_tool_calls):
        return True, dup_msg

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
    # TODO: Remove the hardcoded tool names
    [
      # Explore codebase tools
      f"list{MAX_ROLS_PER_TC}",
      f"read{MAX_ROLS_PER_TC}",
      f"find{MAX_ROLS_PER_TC}",
      f"grep{MAX_ROLS_PER_TC}",
      # Documentation tools
      "langref",
      # Stop tool to finish the analysis
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

  tools_phase2 = get_tool_list(fixenv, llvm, build_dir, debugger, phase=2)
  try:
    if hasattr(agent.tools, "remove_tool"):
      agent.tools.remove_tool("stop")
  except Exception:
    pass

  for to, th in tools_phase2:
    agent.register_tool(to, th)

  return generate_test(
    agent=agent,
    fixenv=fixenv,
    llvm=llvm,
    stats=stats,
  )


def autoreview(
  agent: AgentBase,
  fixenv: Environment,
  llvm: LLVM,
  stats: RunStats,
  build_dir: str,
):
  debugger = None

  # Register Phase 1 tools
  tools_phase1 = get_tool_list(fixenv, llvm, build_dir, debugger, phase=1)
  for to, th in tools_phase1:
    agent.register_tool(to, th)

  return run_mini_agent(
    debugger=debugger,
    agent=agent,
    fixenv=fixenv,
    llvm=llvm,
    stats=stats,
    build_dir=build_dir,
  )


def parse_args():
  parser = ArgumentParser(description="llvm-autoreview (mini)")
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

  # Set up the console for output
  if args.debug:
    global console
    console = get_boxed_console(debug_mode=True)

  # Set up used LLMs and agents
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

  # Set up the LLVM environment
  build_dir = os.path.join(get_llvm_build_dir(), args.issue)
  set_llvm_build_dir(build_dir)
  env = Environment(
    args.issue,
    base_model_knowledge_cutoff="2000-12-31Z",  # FIXME: workaround for evaluation
    additional_cmake_args=ADDITIONAL_CMAKE_FLAGS,
    max_build_jobs=os.environ.get("LLVM_AUTOREVIEW_MAX_BUILD_JOBS"),
  )

  bug_type = env.get_bug_type()
  if bug_type not in [
    "miscompilation",
  ]:  # We only support miscompilation for now
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

  # Start analyzing and repairing the issue
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
