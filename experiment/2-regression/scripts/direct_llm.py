import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict
from pathlib import Path
from subprocess import STDOUT, CalledProcessError, check_output
from tempfile import TemporaryDirectory

# Add the root directory to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent.parent))

from llvm.llvm_helper import (
  get_llvm_build_dir,
  reset,
  set_llvm_build_dir,
  strip_llvm_fence,
)
from lms.anthropic import ClaudeAgent
from lms.openai import OpenAIAgent
from main import Bug, RunStats

MAX_CONSUMED_TOKENS = 10_000_000
ADDITIONAL_CMAKE_FLAGS = [
  "-DCMAKE_C_FLAGS_RELWITHDEBINFO=-O0",
  "-DCMAKE_CXX_FLAGS_RELWITHDEBINFO=-O0",
]
ALIVE_TV_PATH = os.environ.get("LAB_LLVM_ALIVE_TV")


class NoAvailableBugFound(Exception):
  pass


def panic(msg):
  print(f"Error: {msg}")
  sys.exit(1)


# Copied from regression.py to avoid executing top-level code on import
class HistoryEnvironment:
  def __init__(self, issue_id, additional_cmake_args=[]):
    self.issue_id = issue_id
    self.additional_cmake_args = additional_cmake_args

    # Adjusted path to dataset relative to this file
    dataset_dir = str(Path(__file__).resolve().parent.parent / "dataset")
    try:
      with open(os.path.join(dataset_dir, f"{issue_id}.json")) as f:
        self.data = json.load(f)
    except FileNotFoundError:
      panic(f"Dataset file for issue {issue_id} not found at {dataset_dir}")

    self.history = self.data.get("history", {})
    if not self.history:
      panic(f"No history found in {issue_id}.json")

    self.bug_type = self.data.get("bug_type")
    self.test_commit = self.history.get("commit_sha")
    self.base_commit = self.data.get("bisect", self.test_commit)

  def get_bug_type(self):
    return self.bug_type

  def get_base_commit(self):
    return self.base_commit

  def get_reference_patch(self):
    return self.history.get("patch", "")

  def get_hint_fix_commit(self):
    return self.test_commit

  def apply(self):
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
  parser = argparse.ArgumentParser(
    description="Simple LLM process for LLVM patch analysis and verification."
  )
  parser.add_argument("--issue", type=str, required=True, help="The issue ID.")
  parser.add_argument("--model", type=str, required=True, help="The LLM model name.")
  parser.add_argument(
    "--driver",
    type=str,
    default="openai",
    choices=["openai", "anthropic"],
    help="LLM driver.",
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


def get_agent(driver, model, debug_mode=False):
  if driver == "openai":
    return OpenAIAgent(model, token_limit=MAX_CONSUMED_TOKENS, debug_mode=debug_mode)
  elif driver == "anthropic":
    return ClaudeAgent(model, token_limit=MAX_CONSUMED_TOKENS, debug_mode=debug_mode)
  raise ValueError(f"Unknown driver: {driver}")


def extract_llvm_ir(text):
  match = re.search(r"```llvm\n(.*?)\n```", text, re.DOTALL)
  if match:
    return match.group(1)

  # Fallback: search for first line starting with ; or define or @
  if "; RUN:" in text or "define " in text:
    # Heuristic: return the whole text if it looks like IR and no fences
    return text
  return None


def extract_opt_args(ir_code):
  # Try regex first
  match = re.search(r"RUN:\s*opt\s+(.*?)(?:\s*[|<]|$)", ir_code, re.MULTILINE)
  if match:
    args_str = match.group(1)
    # Remove -S, %s, and -o <file> (including -o -)
    args = []
    skip_next = False
    for arg in args_str.split():
      if skip_next:
        skip_next = False
        continue
      if arg == "-o":
        skip_next = True
        continue
      if arg not in ["-S", "%s"]:
        args.append(arg)
    if args:
      return " ".join(args)

  # Fallback linear scan
  for line in ir_code.splitlines():
    if "opt" in line and "RUN:" in line:
      # Simple heuristic: take everything after 'opt' until '|' or '<'
      try:
        after_opt = line.split("opt", 1)[1]
        args_part = re.split(r"[|<]", after_opt)[0]
        args = []
        skip_next = False
        for arg in args_part.split():
          if skip_next:
            skip_next = False
            continue
          if arg == "-o":
            skip_next = True
            continue
          if arg not in ["-S", "%s"]:
            args.append(arg)
        if args:
          return " ".join(args)
      except IndexError:
        continue

  return "-O3"


def verify_transformation(build_dir, alive_tv_path, ir_code, opt_args, debug=False):
  traj_data = {
    "found": False,
    "tool": "verify",
    "original_ir": ir_code,
    "transformed_ir": "",
    "log": "",
    "thoughts": f"Verifying with opt args: {opt_args}",
  }

  if debug:
    print(f"Verifying with opt args: {opt_args}")

  opt_path = Path(build_dir) / "bin" / "opt"

  if not opt_path.exists():
    if debug:
      print(f"opt not found at {opt_path}")
    traj_data["log"] = "opt not found"
    return False, "opt not found", [json.dumps(traj_data)]

  with TemporaryDirectory() as tmpdir:
    tmp_path = Path(tmpdir)
    orig_path = tmp_path / "orig.ll"
    trans_path = tmp_path / "trans.ll"

    ir_code = strip_llvm_fence(ir_code)
    traj_data["original_ir"] = ir_code  # Update with stripped version
    with open(orig_path, "w") as f:
      f.write(ir_code)

    cmd_opt = f"{opt_path} -S {opt_args} {orig_path} -o {trans_path}"
    try:
      check_output(cmd_opt, shell=True, stderr=STDOUT)
      if trans_path.exists():
        with open(trans_path) as f:
          traj_data["transformed_ir"] = f.read()
    except CalledProcessError as e:
      msg = e.output.decode("utf-8") if e.output else str(e)
      if debug:
        print(f"Opt failed: {msg}")
      traj_data["log"] = f"Opt failed: {msg}"
      # Opt failure is NOT a bug in the transformation (it's a tool failure or invalid IR)
      return True, f"Opt failed: {msg}", [json.dumps(traj_data)]

    cmd_alive = (
      f"{alive_tv_path} {opt_args} --disable-undef-input {orig_path} {trans_path}"
    )
    if debug:
      print(f"Running alive-tv: {cmd_alive}")
    try:
      # We check output even if return code is non-zero
      output = check_output(cmd_alive, shell=True, stderr=STDOUT).decode("utf-8")
    except CalledProcessError as e:
      output = e.output.decode("utf-8") if e.output else str(e)
      if debug:
        print(f"Alive-TV execution failed or returned non-zero: {output}")

    traj_data["log"] = output
    if debug:
      print("Alive-TV Output:")
      print(output)

    # Check for "incorrect transformations"
    m = re.search(r"(\d+)\s+incorrect transformations", output)
    if m and int(m.group(1)) > 0:
      traj_data["found"] = True
      return False, output, [json.dumps(traj_data)]

    return True, output, [json.dumps(traj_data)]


def main():
  if not ALIVE_TV_PATH:
    print("Error: LAB_LLVM_ALIVE_TV environment variable not set.")
    sys.exit(1)

  args = parse_args()

  build_dir = os.path.join(get_llvm_build_dir(), "regression", args.issue)
  set_llvm_build_dir(build_dir)

  env = HistoryEnvironment(args.issue, additional_cmake_args=ADDITIONAL_CMAKE_FLAGS)
  print(f"Loaded environment for issue {args.issue}")

  if args.stats:
    stats_path = Path(args.stats)
    if stats_path.exists():
      print(f"Stats file {stats_path} already exists. Skipping...")
      return

  if args.history:
    history_path = Path(args.history)
    if history_path.exists():
      print(f"History file {history_path} already exists. Skipping...")
      return

  # Check if we have the binary
  opt_bin = Path(build_dir) / "bin" / "opt"
  if not opt_bin.exists():
    print(f"Build directory {build_dir} missing 'opt'. Attempting build...")
    # Reset environment to the test commit only if we need to build
    env.apply()
    env.build()
  else:
    print(f"Using existing build at {build_dir}")

  agent = get_agent(args.driver, args.model, debug_mode=args.debug)

  stats = RunStats(command=vars(args))
  stats.total_time_sec = time.time()
  stats.chat_rounds = 1

  # Analyze Patch and Generate Test in one go
  patch = env.get_reference_patch()
  bug_type = env.get_bug_type()

  prompt_combined = f"""
You are an expert LLVM developer. Please review this LLVM patch:

Type: {bug_type}

Patch:

{patch}

1. Analyze the patch for potential issues.
2. Generate test cases to expose the issues in the patch based on your analysis.
   - Wrap the LLVM IR code in ```llvm ... ``` blocks.
   - This test case should be suitable for alive-tv verification (input for opt).
   - Important: Include a RUN line comment inside the IR that specifies the 'opt' arguments needed to trigger the pass (e.g., ; RUN: opt -passes=instcombine -S).
"""
  try:
    # Use execute() approach compatible with OpenAIAgent / AgentBase
    agent.clear_history()
    agent.append_user_message(prompt_combined)

    # We need a response handler that stops immediately and returns the content
    def response_handler(content: str):
      return False, content  # Stop and return content

    # We need a dummy tool handler, though we aren't using tools properly here
    # (unless the agent tries to call one, which it shouldn't given no tools registered)
    def tool_call_handler(name, args, res):
      return True, res

    # AgentBase.run(activated_tools, response_handler, tool_call_handler, round_limit)
    response = agent.run([], response_handler, tool_call_handler, round_limit=1)

    if args.debug:
      print(response)

    # Extract & Transform & Verify
    ir_code = extract_llvm_ir(response)
    if not ir_code:
      print("Failed to extract LLVM IR from response.")
      raise ValueError("Failed to extract LLVM IR")

    # Store thought process/report
    stats.report = response

    opt_args = extract_opt_args(ir_code)
    success, log, traj = verify_transformation(
      build_dir, ALIVE_TV_PATH, ir_code, opt_args, debug=args.debug
    )
    stats.test_traj.extend(traj)

    bug_record = Bug(
      original_ir=ir_code,
      transformed_ir=log,
      log=log,
      thoughts="Generated test case verification result.",
    )

    if success:
      print(
        "Verification Result: No bug found (or transformation correct/failed-to-prove)."
      )
      raise NoAvailableBugFound("All efforts tried yet no available patches found.")
    else:
      # Success is False only if "incorrect transformations" was found
      stats.bugs.append(bug_record)
      print("Verification Result: Transformation is incorrect (Bug Reproduced).")

  except Exception as e:
    import traceback

    stats.error = type(e).__name__
    stats.errmsg = str(e)
    stats.traceback = traceback.format_exc()
    if isinstance(e, NoAvailableBugFound):
      print(f"Result: {e}")
    else:
      print(f"Error: {e}")

  finally:
    # Populate stats
    if agent and hasattr(agent, "chat_stats"):
      stats.input_tokens = agent.chat_stats.get("input_tokens", 0)
      stats.output_tokens = agent.chat_stats.get("output_tokens", 0)
      stats.total_tokens = agent.chat_stats.get("total_tokens", 0)
      stats.chat_cost = agent.chat_stats.get("total_cost", 0.0)
    stats.total_time_sec = time.time() - stats.total_time_sec
    # Save stats
    if args.stats:
      stats_path = Path(args.stats)
      with stats_path.open("w") as fout:
        json.dump(stats.as_dict(), fout, indent=2)
      print(f"Generation statistics saved to {stats_path}.")
    # Save history
    if args.history:
      history_path = Path(args.history)
      with history_path.open("w") as fout:
        json.dump([asdict(m) for m in agent.get_history()], fout, indent=2)
      print(f"Chat history saved to {history_path}.")


if __name__ == "__main__":
  main()
