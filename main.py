from argparse import ArgumentParser
from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
from time import time
from typing import List, Optional, Tuple

from base.console import get_boxed_console
from llvm.debugger import DebuggerBase
from llvm.gdb_support import GDB
from lms.agent import AgentBase
from llvm.lab_env import Environment
from llvm.llvm import LLVM
from llvm.llvm_helper import get_llvm_build_dir, git_execute, llvm_dir, reset, set_llvm_build_dir
from tools.code import CodeTool
from tools.debugger import DebuggerTool
from tools.docs import DocsTool
from tools.eval import EvalTool
from tools.findn import FindNTool
from tools.grepn import GrepNTool
from tools.langref import LangRefTool
from tools.list import ListTool
from tools.readn import ReadNTool
from tools.stop import StopTool

# - ===============================================
# - Agent configurations
# - ===============================================

# We restrict the agent to chat at most 500 rounds for each run
# and consume at most 5 million tokens among all runs.
MAX_CHAT_ROUNDS = 500
MAX_CONSUMED_TOKENS = 5_000_000
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

# - ================================================
# - Statistis and output
# - ================================================

console = get_boxed_console(debug_mode=False)


def panic(msg: str):
  console.print(f"Error: {msg}", color="red")
  exit(1)

@dataclass
class RunStats:
  # Command to run autoreview
  command: dict
  # The generated path for successful runs
  bug: Optional[str] = None
  # The error message for failed runs
  error: Optional[str] = None
  errmsg: Optional[str] = None
  traceback: Optional[str] = None
  # Agent interaction stats
  input_tokens: int = 0
  output_tokens: int = 0
  cached_tokens: int = 0
  total_tokens: int = 0
  chat_rounds: int = 0
  total_time_sec: float = 0.0
  # Fix stats
  trans_point: Tuple[str, str] = ("<not-provided>", "<not-provided>")
  edit_points: List[Tuple[str, int, int]] = field(
    default_factory=lambda *_, **__: [("<not-provided>", -1, -1)]
  )
  reason_thou: str = "<not-provided>"
  test_traj: List[str] = field(
    default_factory=list
  )  # Trajectories of patches ever tried during testing

  def as_dict(self) -> dict:
    return asdict(self)


# - ===============================================
# - Agent's main code
# - ==============================================


class NoAvailableBugFound(Exception):
  pass


class ReachToolBudget(Exception):
  pass


def get_tool_list(fixenv: Environment, llvm: LLVM, debugger: DebuggerBase):
  return [
    # General tools
    (FindNTool(llvm_dir, n=MAX_ROLS_PER_TC), MAX_TCS_GET_CONTEXT),
    (GrepNTool(llvm_dir, n=MAX_ROLS_PER_TC), MAX_TCS_GET_CONTEXT),
    (ListTool(llvm_dir, n=MAX_ROLS_PER_TC), MAX_TCS_GET_CONTEXT),
    (ReadNTool(llvm_dir, n=MAX_ROLS_PER_TC), MAX_TCS_GET_CONTEXT),
    # LLVM-specific tools
    (CodeTool(llvm, debugger), MAX_TCS_GET_CONTEXT),
    (DocsTool(llvm, debugger), MAX_TCS_GET_CONTEXT),
    (LangRefTool(fixenv), MAX_TCS_GET_CONTEXT),
    # Debugging tools
    (DebuggerTool(debugger), MAX_TCS_GET_CONTEXT),
    (EvalTool(debugger), MAX_TCS_GET_CONTEXT),
    # Stop the agent process
    (StopTool(llvm_dir), MAX_TCS_GET_CONTEXT),
  ]


def run_mini_agent(
  debugger: DebuggerBase,
  agent: AgentBase,
  fixenv: Environment,
  llvm: LLVM,
  stats: RunStats,
) -> Optional[str]:
  agent.clear_history()
  
  #####################################################
  # The agent runs by:
  # 1. Analyze the issue first to reason about the root cause and propose potential edit points.
  # 2. Leverage the provided information to guide the patch generation.
  #####################################################
  
  pass


def autoreview(
  agent: AgentBase,
  fixenv: Environment,
  llvm: LLVM,
  stats: RunStats,
):
  debugger = GDB(["/bin/true"])
  
  tools = get_tool_list(fixenv, llvm)
  for to, th in tools:
    agent.register_tool(to, th)

  return run_mini_agent(
    debugger=debugger,
    agent=agent,
    fixenv=fixenv,
    stats=stats,
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

  # Set up the LLVM environment
  set_llvm_build_dir(os.path.join(get_llvm_build_dir(), args.issue))
  env = Environment(
    args.issue,
    base_model_knowledge_cutoff="2023-12-31Z",
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
      f"Warning: Failed to reset HEAD to {env.get_hint_fix_commit()}: {e}", color="yellow"
    )
    console.print("Sync the repository and try again.", color="yellow")
    reset("main")
    git_execute(["pull", "origin", "main"])
    try:
      env.apply()
    except Exception as e:
      panic(f"Failed to reset HEAD to {env.get_hint_fix_commit()}: {e}")
  
  env.build()
  
  llvm = LLVM()
  
  # Start analyzing and repairing the issue
  stats = RunStats(command=vars(args))
  stats.total_time_sec = time()
  try:
    stats.bug = autoreview(agent, env, llvm, stats)
    if not stats.bug:
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
    stats.total_time_sec = time.time() - stats.total_time_sec
    if stats_path:
      with stats_path.open("w") as fout:
        json.dump(stats.as_dict(), fout, indent=2)
      console.print(f"Generation statistics saved to {stats_path}.")

  console.print("Statistics")
  console.print("----------")
  console.print(json.dumps(stats.as_dict(), indent=2))

if __name__ == "__main__":
  main()
