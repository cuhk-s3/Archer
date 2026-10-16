import os
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import List, Optional

from dataset import get_store
from veir import helper

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class PREnvironmentError(Exception):
  pass


@dataclass
class PRInfo:
  pr_id: int
  pr_url: str = ""
  title: str = ""
  author: str = ""
  base_commit: str = ""
  fix_commit: str = ""
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
  def __init__(self, pr_info, console, version_id=None):
    self.pr_info = pr_info
    self.base_commit = pr_info.base_commit
    self.console = console
    self.version_id = version_id
    self.build_dir = None
    self.baseline_dir = None

  @staticmethod
  def _pr_info_from_dict(data):
    allowed = {f.name for f in fields(PRInfo)}
    values = {k: v for k, v in data.items() if k in allowed}
    for name in ("components", "tests", "labels", "comments"):
      values[name] = values.get(name) or []
    for name in ("patch_location_lineno", "patch_location_funcname"):
      values[name] = values.get(name) or {}
    return PRInfo(**values)

  @classmethod
  def load_from_db(cls, pr_id, fix_commit=None, console=None):
    try:
      store = get_store()
      version = store.get_version_by_commit(pr_id, fix_commit) if fix_commit else store.get_latest_version(pr_id)
      if version is None:
        return None, None
      version_id = int(version["id"])
      return cls._pr_info_from_dict(store.to_pr_info(pr_id, version_id)), version_id
    except Exception as exc:
      if console:
        console.print(f"Warning: Failed to load PR info: {exc}", color="yellow")
      return None, None

  @classmethod
  def load(cls, pr_id, console, fix_commit=None):
    info, version_id = cls.load_from_db(pr_id, fix_commit, console)
    if info is None:
      script = PROJECT_ROOT / "dataset" / "scripts" / "pr_extract.py"
      proc = subprocess.run(["python3", str(script), str(pr_id), "--skip-closed-check"], text=True, capture_output=True)
      if proc.returncode:
        raise PREnvironmentError(proc.stderr or proc.stdout)
      info, version_id = cls.load_from_db(pr_id, fix_commit, console)
    if info is None:
      raise PREnvironmentError("Failed to load PR information after extraction")
    return cls(info, console, version_id)

  def _checkout_base(self):
    try:
      helper.reset(self.base_commit)
    except Exception as exc:
      raise PREnvironmentError(f"Failed to checkout VeIR base commit: {exc}") from exc

  def _build_source_dir(self, role):
    version = (self.pr_info.fix_commit or self.base_commit)[:12]
    return PROJECT_ROOT / "builds" / "veir" / f"pr-{self.pr_info.pr_id}" / version / role

  def _prepare_worktree(self, role):
    source_dir = self._build_source_dir(role)
    if not source_dir.exists():
      source_dir.parent.mkdir(parents=True, exist_ok=True)
      proc = subprocess.run(
        ["git", "-C", helper.veir_dir, "worktree", "add", "--detach",
         str(source_dir), self.base_commit],
        text=True, capture_output=True,
      )
      if proc.returncode:
        raise PREnvironmentError(
          f"Failed to create {role} VeIR worktree: {proc.stdout}{proc.stderr}"
        )
    return source_dir

  def _write_build_manifest(self, source_dir, role):
    build_dir = source_dir / ".lake" / "build"
    binaries = {}
    for name in ("veir-opt", "veir-interpret", "llrwt"):
      path = build_dir / "bin" / name
      if name != "llrwt" and not path.is_file():
        raise PREnvironmentError(f"Build succeeded but {path} is missing")
      if not path.is_file():
        continue
      binaries[name] = {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
      }
    manifest = {
      "schema": 1,
      "pr_id": self.pr_info.pr_id,
      "role": role,
      "base_commit": self.base_commit,
      "fix_commit": self.pr_info.fix_commit,
      "source_dir": str(source_dir.resolve()),
      "toolchain": helper.read_toolchain(source_dir),
      "built_at": datetime.now(timezone.utc).isoformat(),
      "binaries": binaries,
    }
    path = source_dir.parent / f"{role}-build.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

  def prepare(self, additional_cmake_args=None, max_build_jobs=None):
    source_dir = self._prepare_worktree("patched")
    ok, log = helper.apply(self.pr_info.patch, source_dir)
    if not ok:
      # A persistent worktree may already contain this exact patch.
      reverse = subprocess.run(
        ["git", "-C", str(source_dir), "apply", "--reverse", "--check"],
        input=self.pr_info.patch, text=True, capture_output=True,
      )
      if reverse.returncode:
        raise PREnvironmentError(f"Failed to apply PR patch: {log}")
    ok, log = helper.build(max_build_jobs, source_dir)
    if not ok:
      raise PREnvironmentError(f"Failed to build VeIR:\n{log}")
    self._write_build_manifest(source_dir, "patched")
    self.build_dir = str(source_dir / ".lake" / "build")
    return self.build_dir

  def prepare_baseline(self, additional_cmake_args=None, max_build_jobs=None):
    source_dir = self._prepare_worktree("baseline")
    ok, log = helper.build(max_build_jobs, source_dir)
    if not ok:
      raise PREnvironmentError(f"Failed to build baseline VeIR:\n{log}")
    self._write_build_manifest(source_dir, "baseline")
    self.baseline_dir = str(source_dir / ".lake" / "build")
    return self.baseline_dir

  def get_tests(self):
    return self.pr_info.tests
