import json
import os
import re
import shlex
import subprocess
import time
from argparse import ArgumentParser
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.verify import VerifyTool

os.environ["MSWEA_SILENT_STARTUP"] = "1"  # Silent startup
os.environ["MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT"] = "3"  # Retry 3 times
import yaml
from minisweagent import Model
from minisweagent.agents.default import DefaultAgent
from minisweagent.environments.local import LocalEnvironment
from minisweagent.exceptions import Submitted
from minisweagent.models.litellm_model import LitellmModel

from base.console import get_boxed_console
from llvm.lab_env import Environment as FixEnvironment
from llvm.llvm_helper import (
  get_llvm_build_dir,
  git_execute,
  llvm_dir,
  set_llvm_build_dir,
)
from llvm.llvm_helper import (
  reset as reset_llvm,
)
from lms.agent import ReachRoundLimit, ReachTokenLimit
from main import (
  ADDITIONAL_CMAKE_FLAGS,
  ALIVE_TV_PATH,
  MAX_CHAT_ROUNDS,
  MAX_CONSUMED_TOKENS,
  NoAvailableBugFound,
  RunStats,
)

# TODO: remove duplicates with main.py
console = get_boxed_console(debug_mode=False)


def panic(msg: str):
  console.print(f"Error: {msg}", color="red")
  exit(1)


# TODO: add other tools that do not require permission
FORBIDDEN_TOOLS = [
  "which",
  "sudo",
  "rm",
  "curl",
  "wget",
  "git",
  "ssh",
  "scp",
  "ftp",
  "telnet",
  "ping",
  "traceroute",
  "nslookup",
  "dig",
  "nmap",
  "apt",
  "apt-get",
  "dpkg",
]


# TODO: Python etc can also edit files ...
EDITING_TOOLS = [
  "sed",
  "awk",
]


@dataclass
class Patch:
  type: str
  patch: str

  def as_dict(self) -> dict:
    return {
      "bug_type": self.type,
      "patch": self.patch,
    }


class MyModel(LitellmModel):
  def __init__(self, model: str, *, token_limit=-1, round_limit=-1):
    super().__init__(
      model_name=model,
      model_kwargs={
        "custom_llm_provider": "openai",
        "api_base": os.environ.get("LLVM_AUTOREVIEW_LM_API_ENDPOINT"),
        "api_key": os.environ.get("LLVM_AUTOREVIEW_LM_API_KEY"),
        "temperature": 0,
        "top_p": 0.95,
        "max_tokens": 4096,
        "drop_params": True,
      },
      cost_tracking="ignore_errors",  # Ignore cost tracking errors, we have our own
    )
    self.token_limit = token_limit
    self.round_limit = round_limit
    self.chat_stats = {
      "chat_rounds": 0,
      "input_tokens": 0,
      "cached_tokens": 0,
      "output_tokens": 0,
      "total_tokens": 0,
    }

  def _query(self, messages, **kwargs):
    if self.round_limit > 0 and self.chat_stats["chat_rounds"] >= self.round_limit:
      raise ReachRoundLimit()
    if self.token_limit > 0 and self.chat_stats["total_tokens"] >= self.token_limit:
      raise ReachTokenLimit()

    response = super()._query(messages, **kwargs)

    console.print(
      f"Executing round #{self.chat_stats['chat_rounds']}, chat statistics so far: {self.chat_stats}"
    )
    self.chat_stats["chat_rounds"] += 1
    usage = getattr(response, "usage", None)
    if usage:
      self.chat_stats["input_tokens"] += usage.prompt_tokens
      if usage.prompt_tokens_details:
        self.chat_stats["cached_tokens"] += usage.prompt_tokens_details.cached_tokens
      self.chat_stats["output_tokens"] += usage.completion_tokens
      self.chat_stats["total_tokens"] += usage.total_tokens

    return response

  def query(self, messages, **kwargs):
    console.printb(message=messages[-1]["content"], title=messages[-1]["role"])
    response = super().query(messages, **kwargs)
    console.printb(message=response["content"], title="assistant")
    return response


class MyEnvironment(LocalEnvironment):
  def __init__(self, *, cwd: str, stats: RunStats):
    super().__init__(cwd=cwd)
    self.shim_path = os.path.join("/", "tmp", "mswe_myenv_shim.sh")
    self._create_shim()
    self.stats = stats

  def _create_shim(self):
    # TODO: How to defend the models from accessing /usr/bin/xxx directly?
    # Shim script to set up the execution environment for mini-swe-agent
    shim_content = "#!/bin/bash\n"
    for cmd in FORBIDDEN_TOOLS:
      shim_content += f"""
{cmd}() {{
  echo "Error: You do not have perssion to access the command '{cmd}'."
  return 1
}}
"""
    with open(self.shim_path, "w") as f:
      f.write(shim_content)
    os.chmod(self.shim_path, 0o755)

  def execute(
    self, action: dict, cwd: str = "", *, timeout: int | None = None
  ) -> dict[str, Any]:
    cmd = action.get("command", "")
    cwd = cwd or self.config.cwd or os.getcwd()
    if cmd == "report":
      raise Submitted(
        {
          "role": "exit",
          "content": "Review finished.",
        }
      )
    command = shlex.join(["bash", "-c", f". {self.shim_path} && {cmd}"])
    if "alive-tv" in cmd:
      try:
        result = subprocess.run(
          command,
          shell=True,
          text=True,
          cwd=cwd,
          env=os.environ | self.config.env,
          timeout=timeout or self.config.timeout,
          encoding="utf-8",
          errors="replace",
          stdout=subprocess.PIPE,
          stderr=subprocess.STDOUT,
        )
        if result.returncode == 0:  # Check return code or output for errors
          m = re.search(r"(\d+)\s+incorrect transformations", result.stdout)
          if m and int(m.group(1)) > 0:
            self.stats.bugs.append(result.stdout)
        self.stats.test_traj.append(
          {
            "command": cmd,
            "output": result.stdout,
            "returncode": result.returncode,
          }
        )
      except Exception as e:
        self.stats.test_traj.append(
          {
            "command": cmd,
            "output": str(e),
            "returncode": -1,
          }
        )
        console.print(f"Error executing command '{cmd}': {e}", color="red")
        pass
    action["command"] = command
    return super().execute(action, cwd, timeout=timeout)


class MyAgent(DefaultAgent):
  def __init__(self, model: Model, stats: RunStats, workdir: str) -> None:
    super().__init__(
      model=MyModel(
        model=model, token_limit=MAX_CONSUMED_TOKENS, round_limit=MAX_CHAT_ROUNDS * 2
      ),
      env=MyEnvironment(cwd=workdir, stats=stats),
      **yaml.safe_load(
        Path(
          os.path.join(os.environ.get("LLVM_AUTOREVIEW_HOME_DIR"), "mswe.yaml")
        ).read_text()
      )["agent"],
    )
    self.stats = stats
    self.issue = None
    self.fixenv = None

  def setup_llvm(self, issue: str):
    console.print("Setting up the buggy LLVM environment ...")
    self.issue = issue
    build_dir = os.path.join(get_llvm_build_dir(), issue)
    set_llvm_build_dir(build_dir)
    self.fixenv = FixEnvironment(
      issue,
      base_model_knowledge_cutoff="2000-12-31Z",  # FIXME: workaround for evaluation
      additional_cmake_args=ADDITIONAL_CMAKE_FLAGS,
      max_build_jobs=os.environ.get("LLVM_AUTOREVIEW_MAX_BUILD_JOBS"),
    )
    bug_type = self.fixenv.get_bug_type()
    if bug_type not in [
      "miscompilation",
    ]:  # We only support miscompilation for now
      panic(f"Unsupported bug type: {bug_type}")
    try:
      self.fixenv.apply()
    except Exception as e:
      console.print(
        f"Warning: Failed to reset HEAD to {self.fixenv.get_base_commit()}: {e}",
        color="yellow",
      )
      console.print("Sync the repository and try again.", color="yellow")
      reset_llvm("main")
      git_execute(["pull", "origin", "main"])
      try:
        self.fixenv.apply()
      except Exception as e:
        panic(f"Failed to reset HEAD to {self.fixenv.get_hint_fix_commit()}: {e}")
    if not (Path(build_dir) / "bin" / "opt").exists():
      self.fixenv.build()
    self.verifytool = VerifyTool(build_dir, alive_path=ALIVE_TV_PATH)

  def setup_patch(self) -> Patch:
    return Patch(
      type=self.fixenv.get_bug_type(), patch=self.fixenv.get_reference_patch()
    )

  def step(self):
    console.print("Remaining tools: [verify, report]")
    return super().step()


def parse_args():
  parser = ArgumentParser(description="mini-swe-agent (llvm-autoreview)")
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
  parser.add_argument(
    "--history",
    type=str,
    default=None,
    help="Path to save the agent execution history (trajectory).",
  )
  return parser.parse_args()


def main():
  if os.environ.get("LLVM_AUTOREVIEW_HOME_DIR") is None:
    panic("The llvm-autoreview environment has not been brought up.")

  args = parse_args()

  if args.debug:
    global console
    console = get_boxed_console(debug_mode=True)

  if args.stats:
    if Path(args.stats).exists():
      panic(f"Stats file {args.stats} already exists.")

  history_path = None
  if args.history:
    history_path = Path(args.history)
    if history_path.exists():
      panic(f"History file {history_path} already exists.")

  stats = RunStats(command=vars(args))
  agent = MyAgent(args.model, stats, workdir=llvm_dir)
  try:
    agent.setup_llvm(args.issue)
    patch = agent.setup_patch()
    stats.total_time_sec = time.time()
    console.print("Starting to review the patch ...")
    agent.run(
      "",
      **patch.as_dict(),
      forbidden_tools=", ".join(FORBIDDEN_TOOLS),
      workdir=llvm_dir,
    )
    if not stats.bugs:
      raise NoAvailableBugFound("All efforts tried yet no bugs found.")
  except Exception as e:
    import traceback

    stats.error = type(e).__name__
    stats.errmsg = str(e)
    stats.traceback = traceback.format_exc()

    raise e
  finally:
    stats.chat_rounds = agent.model.chat_stats["chat_rounds"]
    stats.input_tokens = agent.model.chat_stats["input_tokens"]
    stats.output_tokens = agent.model.chat_stats["output_tokens"]
    stats.cached_tokens = agent.model.chat_stats["cached_tokens"]
    stats.total_tokens = agent.model.chat_stats["total_tokens"]
    stats.total_time_sec = time.time() - stats.total_time_sec
    if args.stats:
      with open(args.stats, "w") as fou:
        json.dump(stats.as_dict(), fou, indent=2)
      console.print(f"Generation statistics saved to {args.stats}.")
      agent.model.config.model_kwargs["api_base"] = "hidden"
      agent.model.config.model_kwargs["api_key"] = "hidden"

    if args.history:
      agent.save(Path(args.history))
      console.print(f"Agent trajectory saved to {args.history}.")

    stats.test_traj = agent.save(path=None)

  console.print("Bugs Found")
  console.print("----------")
  for idx, bug in enumerate(stats.bugs):
    console.print(f"Bug #{idx + 1}:")
    console.print(bug)
    console.print("----------")
  console.print("Statistics")
  console.print("----------")
  console.print(json.dumps(stats.as_dict(), indent=2))


if __name__ == "__main__":
  main()
