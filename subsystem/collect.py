import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

# Add the project root to sys.path to allow imports from lms and collect
sys.path.append(str(Path(__file__).parent.parent))

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_random_exponential

from subsystem.prompts import (
  PROMPT_ANALYZE,
  PROMPT_SYSTEM_ANALYZE,
  PROMPT_SYSTEM_VERIFY,
  PROMPT_VERIFY,
)

# Setup logging
logging.basicConfig(
  level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@dataclass
class Bug:
  original_ir: str
  transformed_ir: str
  log: str


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
  strategies: List[dict] = field(default_factory=list)
  reason_thou: str = "<not-provided>"
  # The generated bugs for successful runs
  bugs: List[Bug] = field(default_factory=list)
  test_traj: List[str] = field(default_factory=list)

  def as_dict(self) -> dict:
    return asdict(self)


class SimpleOpenAIClient:
  def __init__(self, model: str, debug: bool = False):
    self.model = model
    self.debug = debug
    end_point = os.environ.get("LLVM_AUTOREVIEW_LM_API_ENDPOINT")
    token = os.environ.get("LLVM_AUTOREVIEW_LM_API_KEY")
    if not end_point or not token:
      logger.warning(
        "LLVM_AUTOREVIEW_LM_API_ENDPOINT or LLVM_AUTOREVIEW_LM_API_KEY not set."
      )
    self.client = OpenAI(api_key=token, base_url=end_point)
    # Using a simple list of dicts for history
    self.history = []
    # Initialize chat stats
    self.chat_stats = {
      "chat_rounds": 0,
      "input_tokens": 0,
      "cached_tokens": 0,
      "output_tokens": 0,
      "total_tokens": 0,
      "total_cost": 0.0,
    }

  def clear_history(self):
    # We don't clear chat_stats, as it's for the whole session or needs to be accumulated
    # But if we treat each phase as separate, we might need to handle that carefully.
    # SimpleOpenAIClient is reused? In main it's instantiated twice.
    # If instantiated twice, we need to sum up their stats.
    self.history = []

  def append_system_message(self, content: str):
    self.history.append({"role": "system", "content": content})

  def append_user_message(self, content: str):
    self.history.append({"role": "user", "content": content})

  @retry(wait=wait_random_exponential(min=1, max=60), stop=stop_after_attempt(6))
  def chat(self, temperature=0):
    try:
      if self.debug:
        for msg in self.history:
          print(f"[{msg['role'].upper()}]:\n{msg['content']}\n")

      response = self.client.chat.completions.create(
        model=self.model,
        messages=self.history,
        temperature=temperature,
      )

      # Update usage stats
      if response.usage:
        self.chat_stats["input_tokens"] += response.usage.prompt_tokens
        if response.usage.prompt_tokens_details:
          self.chat_stats["cached_tokens"] += (
            response.usage.prompt_tokens_details.cached_tokens
          )
        self.chat_stats["output_tokens"] += response.usage.completion_tokens
        self.chat_stats["total_tokens"] += response.usage.total_tokens
        cost = getattr(response.usage, "cost", None)
        if cost is not None:
          self.chat_stats["total_cost"] += cost

      self.chat_stats["chat_rounds"] += 1

      content = response.choices[0].message.content

      if self.debug:
        print(f"[ASSISTANT]:\n{content}")

      # Append assistant response to history
      self.history.append({"role": "assistant", "content": content})
      return content
    except Exception as e:
      logger.error(f"Error during OpenAI API call: {e}")
      raise


def load_issue_data(dataset_dir: str, issue_id: str):
  # Construct path assuming the dataset structure provided
  dataset_path = Path(dataset_dir)
  json_path = dataset_path / f"{issue_id}.json"

  if not json_path.exists():
    # Fallback: check if the dataset dir contains the json files flatly
    # or if the user provided the full path to json
    if Path(issue_id).exists() and str(issue_id).endswith(".json"):
      json_path = Path(issue_id)
    else:
      raise FileNotFoundError(f"Issue file not found: {json_path}")

  with open(json_path, "r") as f:
    data = json.load(f)
  return data


def analyze_bug(agent: SimpleOpenAIClient, data: dict, issue_id: str, passes_dir: str):
  # Extract required fields
  bug_type = data.get("bug_type", "unknown")

  # Try to find component/pass name
  components = data.get("hints", {}).get("components", [])
  component_str = ", ".join(components) if components else "unknown"

  # Using issue body and patch
  issue_body = data.get("issue", {}).get("body", "")
  patch = data.get("patch", "")

  # Fill prompt
  prompt = PROMPT_ANALYZE.format(
    bug_type=bug_type, component=component_str, issue=issue_body, patch=patch
  )

  logger.info(f"Analyzing bug {issue_id}...")

  # Reset agent history for new task
  agent.clear_history()
  agent.append_system_message(PROMPT_SYSTEM_ANALYZE)
  agent.append_user_message(prompt)

  response_content = agent.chat()

  analysis_result = response_content

  # Prepare paths but do not write yet
  md_paths = []
  if not components:
    components = ["unknown"]

  for comp in components:
    # Sanitize it
    safe_pass_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", comp)
    output_path = Path(passes_dir) / f"{safe_pass_name}.md"
    md_paths.append(output_path)

  return md_paths, analysis_result


def generate_and_verify(
  agent: SimpleOpenAIClient, strategy: str, issue_id: str, output_dir: str
):
  logger.info(f"Generating LLVM IR for bug {issue_id} based on strategy...")

  # Reset agent history
  agent.clear_history()
  agent.append_system_message(PROMPT_SYSTEM_VERIFY)
  prompt = PROMPT_VERIFY.format(strategy=strategy)
  agent.append_user_message(prompt)

  response_content = agent.chat()

  generation_result = response_content

  # Extract JSON
  original_ir = None
  optimized_ir = None

  try:
    # Find JSON block
    match = re.search(r"```json\s*(.*?)\s*```", generation_result, re.DOTALL)
    if match:
      json_str = match.group(1)
    elif generation_result.strip().startswith(
      "{"
    ) and generation_result.strip().endswith("}"):
      json_str = generation_result
    else:
      logger.error("Could not find JSON in LLM output")
      return

    test_case = json.loads(json_str)
    original_ir = test_case.get("original_ir", "")
    optimized_ir = test_case.get("optimized_ir", "")

    if not original_ir or not optimized_ir:
      logger.error("Generated JSON missing original_ir or optimized_ir")
      return

  except json.JSONDecodeError as e:
    logger.error(f"Failed to parse JSON: {e}")
    return

  # Verify with alive-tv
  alive_tv_path = os.environ.get("LAB_LLVM_ALIVE_TV")
  if not alive_tv_path:
    logger.error(
      "LAB_LLVM_ALIVE_TV environment variable not set. Skipping verification."
    )
    return

  print(f"Original IR:\n{original_ir}\n")
  print(f"Optimized IR:\n{optimized_ir}\n")

  import tempfile

  with tempfile.NamedTemporaryFile(mode="w", suffix=".ll", delete=False) as src_file:
    src_file.write(original_ir)
    src_path = src_file.name

  with tempfile.NamedTemporaryFile(mode="w", suffix=".ll", delete=False) as tgt_file:
    tgt_file.write(optimized_ir)
    tgt_path = tgt_file.name

  logger.info(f"Running alive-tv on {src_path} and {tgt_path}...")

  verification_success = False
  try:
    # alive-tv usage: alive-tv source.ll target.ll
    cmd = [alive_tv_path, "--disable-undef-input", src_path, tgt_path]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

    if "Transformation seems to be correct" in result.stdout:
      logger.info("Verification Result: EQUIVALENT")
      verification_success = False
    elif "Transformation doesn't verify" in result.stdout:
      logger.info("Verification Result: NOT EQUIVALENT (Bug Reproduced!)")
      verification_success = True
    else:
      logger.info("Verification Result: UNKNOWN")

  except Exception as e:
    logger.error(f"Error running alive-tv: {e}")
  finally:
    # Clean up temp files
    if os.path.exists(src_path):
      os.remove(src_path)
    if os.path.exists(tgt_path):
      os.remove(tgt_path)

  if verification_success:
    return original_ir, optimized_ir
  return None, None


def save_success_issue_json(
  issue_id: str,
  strategy: str,
  src_ir: str,
  tgt_ir: str,
  output_dir: str,
  model: str,
):
  out_dir = Path(output_dir)
  out_dir.mkdir(parents=True, exist_ok=True)

  out_path = out_dir / f"{issue_id}.json"
  payload = {
    "issue": issue_id,
    "analysis": strategy,
    "examples": [
      {
        "original_ir": src_ir,
        "optimized_ir": tgt_ir,
        "status": "Reproduced",
      }
    ],
    "meta": {
      "model": model,
    },
  }

  with open(out_path, "w") as f:
    json.dump(payload, f, indent=2)

  logger.info(f"Per-issue success JSON saved to {out_path}")


def parse_args():
  parser = argparse.ArgumentParser(
    description="LLVM Bug Analysis and Test Case Generation"
  )
  parser.add_argument(
    "--issue", type=str, required=True, help="Issue ID (e.g., 100298)"
  )
  parser.add_argument("--model", type=str, default="gpt-4o", help="Model name for LLMs")
  parser.add_argument(
    "--dataset-dir",
    type=str,
    default="../dataset",
    help="Path to dataset directory",
  )
  parser.add_argument(
    "--passes-dir",
    type=str,
    default="passes",
    help="Directory to save strategy MDs",
  )
  parser.add_argument(
    "--output-dir",
    type=str,
    default="output",
    help="Directory to save generated IRs and verification results",
  )
  parser.add_argument(
    "--log-dir",
    type=str,
    default="log",
    help="Directory to save full execution logs",
  )
  parser.add_argument(
    "--success-dir",
    type=str,
    default="success-issues",
    help="Directory to save one JSON per successfully reproduced issue",
  )
  parser.add_argument(
    "--debug",
    action="store_true",
    help="Enable debug mode for more verbose output",
  )
  return parser.parse_args()


# removed save_execution_log as it is superseded by RunStats logic in main


def main():
  args = parse_args()

  # Check if log already exists
  log_path = Path(args.log_dir) / f"{args.issue}.json"
  if log_path.exists():
    logger.info(f"Log file {log_path} already exists. Skipping.")
    return

  stats = RunStats(command=vars(args))
  stats.total_time_sec = time.time()

  agent1 = None
  agent2 = None

  try:
    data = load_issue_data(args.dataset_dir, args.issue)

    # 1. Analyze
    agent1 = SimpleOpenAIClient(args.model, debug=args.debug)
    try:
      md_paths, strategy = analyze_bug(agent1, data, args.issue, args.passes_dir)
      stats.strategies.append({"content": strategy})
      stats.phase1_round = agent1.chat_stats["chat_rounds"]
    except Exception as e:
      logger.error(f"Analysis failed: {e}")
      raise e

    # 2. Generate and Verify
    agent2 = SimpleOpenAIClient(args.model, debug=args.debug)
    verification_success = False
    try:
      src_ir, tgt_ir = generate_and_verify(
        agent2, strategy, args.issue, args.output_dir
      )
      stats.phase2_round = agent2.chat_stats["chat_rounds"]

      verification_success = src_ir is not None and tgt_ir is not None

      if verification_success:
        stats.bugs.append(
          Bug(original_ir=src_ir, transformed_ir=tgt_ir, log="Reproduced")
        )

        save_success_issue_json(
          issue_id=args.issue,
          strategy=strategy,
          src_ir=src_ir,
          tgt_ir=tgt_ir,
          output_dir=args.success_dir,
          model=args.model,
        )

        if md_paths:
          for md_path in md_paths:
            # Ensure directory exists
            md_path.parent.mkdir(parents=True, exist_ok=True)

            file_exists = md_path.exists()

            with open(md_path, "a") as f:
              if file_exists:
                f.write("\n\n---\n\n")
              f.write(f"# Issue {args.issue}\n\n")
              f.write(strategy)
              f.write("\n\n## Example\n\n")
              f.write("### Original IR\n")
              f.write("```llvm\n")
              f.write(src_ir)
              f.write("\n```\n")
              f.write("### Optimized IR\n")
              f.write("```llvm\n")
              f.write(tgt_ir)
              f.write("\n```\n")
            logger.info(f"Verified example appended to {md_path}")

    except Exception as e:
      logger.error(f"Generation/Verification failed: {e}")
      raise e

  except Exception as e:
    import traceback

    stats.error = type(e).__name__
    stats.errmsg = str(e)
    stats.traceback = traceback.format_exc()
    logger.error(f"Execution failed: {e}")

  finally:
    stats.total_time_sec = time.time() - stats.total_time_sec

    # Accumulate stats from agents
    for agent in [a for a in [agent1, agent2] if a]:
      stats.input_tokens += agent.chat_stats["input_tokens"]
      stats.output_tokens += agent.chat_stats["output_tokens"]
      stats.cached_tokens += agent.chat_stats["cached_tokens"]
      stats.total_tokens += agent.chat_stats["total_tokens"]
      stats.chat_cost += agent.chat_stats["total_cost"]
      stats.chat_rounds += agent.chat_stats["chat_rounds"]

    # Collect history
    full_history = []
    if agent1:
      full_history.extend(agent1.history)
    if agent2:
      full_history.extend(agent2.history)

    # Save stats and history
    log_path = Path(args.log_dir) / f"{args.issue}.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    output_data = stats.as_dict()
    output_data["history"] = full_history  # Add history to the output

    with open(log_path, "w") as f:
      json.dump(output_data, f, indent=2)

    logger.info(f"Full execution log saved to {log_path}")
    logger.info(f"Total Cost: ${stats.chat_cost:.4f}")


if __name__ == "__main__":
  main()
