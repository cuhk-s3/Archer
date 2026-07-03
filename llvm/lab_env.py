import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import List, Optional

from llvm import llvm_helper
from llvm.llvm_helper import (
  apply as apply_patch,
)
from llvm.llvm_helper import (
  dataset_dir,
  get_langref_desc,
  get_llvm_build_dir,
  git_execute,
  reset,
  set_llvm_build_dir,
)

# Project root (parent of the `llvm` package directory).
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class PREnvironmentError(Exception):
  """Raised when the PR environment cannot be set up."""


@dataclass
class PRInfo:
  """Information extracted from a GitHub PR"""

  pr_id: int
  pr_url: str = ""
  title: str = ""
  author: str = ""
  base_commit: str = ""
  fix_commit: str = ""  # Latest commit in the PR
  patch: str = ""
  components: List[str] = field(default_factory=list)
  state: str = ""
  knowledge_cutoff: str = ""
  description: str = ""
  tests: List[dict] = field(default_factory=list)
  labels: List[str] = field(default_factory=list)
  comments: List[dict] = field(default_factory=list)
  patch_location_lineno: dict = field(default_factory=dict)
  patch_location_funcname: dict = field(default_factory=dict)


class PREnvironment:
  """Encapsulates all PR-related environment concerns.

  Responsibilities:
    - Locating / loading / extracting PR info from the dataset.
    - Checking out the base commit and applying the PR patch.
    - Managing the per-PR build directory and building LLVM.
    - Exposing helpers used by the agent tools (langref / tests).
  """

  def __init__(self, pr_info: PRInfo, console):
    self.pr_info = pr_info
    self.base_commit = pr_info.base_commit
    self.console = console
    self.build_dir: Optional[str] = None

  # ---------------------------------------------------------------------------
  # Discovery / loading
  # ---------------------------------------------------------------------------
  @staticmethod
  def get_pr_info_path(pr_id: int) -> Optional[Path]:
    """Get the path to PR info, checking both closed/ and open/ directories"""
    # Check closed directory first (most PRs should be closed)
    closed_path = Path(dataset_dir) / "closed" / f"{pr_id}.json"
    if closed_path.exists():
      return closed_path

    # Check open directory
    open_path = Path(dataset_dir) / "open" / f"{pr_id}.json"
    if open_path.exists():
      return open_path

    return None

  @classmethod
  def load_saved_pr_info(cls, pr_id: int, console=None) -> Optional[PRInfo]:
    """Load previously saved PR info"""
    info_path = cls.get_pr_info_path(pr_id)
    if info_path is None:
      return None
    try:
      with open(info_path, "r") as f:
        data = json.load(f)
      allowed_keys = {f.name for f in fields(PRInfo)}
      filtered = {k: v for k, v in data.items() if k in allowed_keys}
      return PRInfo(**filtered)
    except Exception as e:
      if console is not None:
        console.print(f"Warning: Failed to load saved PR info: {e}", color="yellow")
      return None

  @staticmethod
  def extract_pr_info(pr_id: int, console) -> bool:
    """Extract PR info using pr_extract.py script"""
    pr_extract_script = PROJECT_ROOT / "dataset" / "scripts" / "pr_extract.py"

    try:
      console.print(f"Extracting PR #{pr_id} information...")
      result = subprocess.run(
        ["python3", str(pr_extract_script), str(pr_id), "--skip-closed-check"],
        capture_output=True,
        text=True,
        timeout=300,
      )

      if result.returncode != 0:
        console.print(f"Failed to extract PR info: {result.stderr}", color="red")
        return False

      console.print(result.stdout)
      return True
    except subprocess.TimeoutExpired:
      console.print("PR extraction timed out", color="red")
      return False
    except Exception as e:
      console.print(f"Error extracting PR info: {e}", color="red")
      return False

  @classmethod
  def load(cls, pr_id: int, console) -> "PREnvironment":
    """Load PR info (extracting it first if necessary) and build the env."""
    pr_info = cls.load_saved_pr_info(pr_id, console)

    if pr_info is None:
      # PR info not found, extract it using pr_extract.py
      console.print(f"PR #{pr_id} data not found, extracting...")
      if not cls.extract_pr_info(pr_id, console):
        raise PREnvironmentError("Failed to extract PR information")

      # Try loading again
      pr_info = cls.load_saved_pr_info(pr_id, console)
      if pr_info is None:
        raise PREnvironmentError("Failed to load PR information after extraction")

    return cls(pr_info, console)

  @staticmethod
  def pr_info_changed(
    old_pr_info: Optional[PRInfo], new_pr_info: PRInfo, console=None
  ) -> bool:
    """Check if PR info has changed by comparing fix_commit.

    If the latest commit in the PR has changed, we need to rebuild.
    """
    if old_pr_info is None:
      return True  # No saved info, always need to rebuild

    # Compare fix_commit (latest commit in PR)
    if old_pr_info.fix_commit != new_pr_info.fix_commit:
      if console is not None:
        console.print(
          f"PR commit has changed: {old_pr_info.fix_commit[:7]} -> {new_pr_info.fix_commit[:7]}",
          color="yellow",
        )
      return True

    return False

  # ---------------------------------------------------------------------------
  # Build directory + LLVM setup
  # ---------------------------------------------------------------------------
  def prepare_build_dir(self) -> str:
    """Set up the per-PR build directory, wiping it if the PR changed."""
    base_build_dir = get_llvm_build_dir()
    build_dir = os.path.join(base_build_dir, "pr", str(self.pr_info.pr_id))

    # Check if PR info has changed
    saved_pr_info = self.load_saved_pr_info(self.pr_info.pr_id, self.console)
    pr_changed = self.pr_info_changed(saved_pr_info, self.pr_info, self.console)

    if pr_changed and Path(build_dir).exists():
      self.console.print(
        "PR has changed. Removing old build directory...",
        color="yellow",
      )
      self.console.print(f"Removing old build directory: {build_dir}", color="yellow")
      shutil.rmtree(build_dir)

    # Ensure build directory exists
    os.makedirs(build_dir, exist_ok=True)
    set_llvm_build_dir(build_dir)
    self.build_dir = build_dir
    return build_dir

  def setup_llvm(self):
    """Setup LLVM environment by checking out base commit and applying patch"""
    # Checkout base commit
    self.console.print("Checking out the base commit ...")
    try:
      reset(self.pr_info.base_commit)
    except Exception as e:
      self.console.print(
        f"Warning: Failed to reset HEAD to {self.pr_info.base_commit}: {e}",
        color="yellow",
      )
      self.console.print("Sync the repository and try again.", color="yellow")
      reset("main")
      git_execute(["pull", "origin", "main"])
      try:
        reset(self.pr_info.base_commit)
      except Exception as e:
        raise PREnvironmentError(
          f"Failed to reset HEAD to {self.pr_info.base_commit}: {e}"
        )

    # Apply the patch
    success, log = apply_patch(self.pr_info.patch)
    if not success:
      raise PREnvironmentError(f"Failed to apply patch: {log}")

  def build(self, additional_cmake_args=None, max_build_jobs: Optional[int] = None):
    """Build LLVM into the prepared build directory if `opt` is missing."""
    if self.build_dir is None:
      raise PREnvironmentError("Build directory is not prepared yet.")

    opt_path = Path(self.build_dir) / "bin" / "opt"
    if opt_path.exists():
      self.console.print(f"LLVM already built at {self.build_dir}", color="green")
      return

    self.console.print("Building LLVM with the PR patch...")
    if max_build_jobs is None:
      max_build_jobs = int(
        os.environ.get("LLVM_AUTOREVIEW_MAX_BUILD_JOBS", os.cpu_count())
      )

    success, log = llvm_helper.build(
      max_build_jobs=max_build_jobs,
      additional_cmake_args=additional_cmake_args or [],
    )

    if not success:
      self.console.print("Build failed:", color="red")
      self.console.print(log)
      raise PREnvironmentError("Failed to build LLVM")

    self.console.print("LLVM built successfully!", color="green")

  def prepare(
    self, additional_cmake_args=None, max_build_jobs: Optional[int] = None
  ) -> str:
    """Full environment setup: build dir -> checkout+patch -> build.

    Returns the per-PR build directory path.
    """
    self.prepare_build_dir()
    self.setup_llvm()
    self.build(
      additional_cmake_args=additional_cmake_args, max_build_jobs=max_build_jobs
    )
    return self.build_dir

  # ---------------------------------------------------------------------------
  # Helpers used by the agent tools
  # ---------------------------------------------------------------------------
  def get_langref_desc(self, keywords):
    """Get language reference descriptions for given keywords"""
    return get_langref_desc(keywords, self.base_commit)

  def get_tests(self):
    """Get the tests extracted from PR patch"""
    return self.pr_info.tests
