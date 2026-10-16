import os
import re
import shutil
import subprocess
import fcntl
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
veir_dir = os.environ.get("LAB_VEIR_DIR", str(PROJECT_ROOT / "deps" / "veir"))
ELAN_HOME = PROJECT_ROOT / "deps" / "elan"
TOOLCHAIN_PATTERN = re.compile(
  r"^leanprover/lean4(?:-nightly)?:[A-Za-z0-9][A-Za-z0-9._-]*$"
)


def read_toolchain(repo_dir=None) -> str:
  toolchain_file = Path(repo_dir or veir_dir) / "lean-toolchain"
  toolchain = toolchain_file.read_text(encoding="utf-8").strip()
  if not TOOLCHAIN_PATTERN.fullmatch(toolchain):
    raise ValueError(f"Unsupported Lean toolchain name: {toolchain!r}")
  return toolchain


def _toolchain_lakes(toolchain: str):
  directory = toolchain.replace("/", "--").replace(":", "---")
  candidates = [directory]
  if toolchain.startswith("leanprover/lean4:nightly-"):
    candidates.insert(0, directory.replace("lean4---nightly-", "lean4-nightly---nightly-"))
  return [ELAN_HOME / "toolchains" / name / "bin" / "lake" for name in candidates]


def ensure_toolchain(repo_dir=None) -> Path:
  """Install the checkout's official Lean toolchain into the project cache."""
  toolchain = read_toolchain(repo_dir)
  lakes = _toolchain_lakes(toolchain)
  installed = next((path for path in lakes if path.is_file()), None)
  if installed is not None:
    return installed

  elan = os.environ.get("ARCHER_ELAN_BIN") or shutil.which("elan")
  if not elan:
    fallback = Path("/root/.elan/bin/elan")
    elan = str(fallback) if fallback.is_file() else None
  if not elan:
    raise FileNotFoundError(
      "elan is required for automatic Lean toolchain installation; "
      "set ARCHER_ELAN_BIN"
    )

  ELAN_HOME.mkdir(parents=True, exist_ok=True)
  lock_path = ELAN_HOME / ".archer-toolchain.lock"
  with lock_path.open("a+") as lock:
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
    installed = next((path for path in lakes if path.is_file()), None)
    if installed is None:
      env = os.environ.copy()
      env["ELAN_HOME"] = str(ELAN_HOME)
      timeout = int(env.get("ARCHER_TOOLCHAIN_TIMEOUT_SEC", "1800"))
      proc = subprocess.run(
        [elan, "toolchain", "install", toolchain], env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout,
      )
      if proc.returncode:
        raise RuntimeError(
          f"Failed to install Lean toolchain {toolchain}:\n{proc.stdout}"
        )
      installed = next((path for path in lakes if path.is_file()), None)
  if installed is None:
    raise FileNotFoundError(f"elan installed {toolchain}, but lake was not found")
  return installed


def lake_executable(repo_dir=None) -> str:
  override = os.environ.get("LAB_VEIR_LAKE")
  if override:
    return override
  return str(ensure_toolchain(repo_dir))


def git_execute(args):
  return subprocess.check_output(
    ["git", "-C", veir_dir, *args], stderr=subprocess.DEVNULL
  ).decode("utf-8")


def reset(commit):
  subprocess.check_call(["git", "-C", veir_dir, "restore", "--staged", "."])
  subprocess.check_call(["git", "-C", veir_dir, "clean", "-fd"])
  subprocess.check_call(["git", "-C", veir_dir, "restore", "."])
  subprocess.check_call(["git", "-C", veir_dir, "checkout", commit])


def apply(patch: str, repo_dir=None):
  proc = subprocess.run(
    ["git", "-C", str(repo_dir or veir_dir), "apply"], input=patch, text=True,
    capture_output=True,
  )
  return proc.returncode == 0, proc.stdout + proc.stderr


def build(max_build_jobs=None, repo_dir=None):
  repo_dir = str(repo_dir or veir_dir)
  env = os.environ.copy()
  if max_build_jobs:
    env["LAKE_JOBS"] = str(max_build_jobs)
  targets = ["veir-opt", "veir-interpret"]
  config_text = "\n".join(
    path.read_text(encoding="utf-8", errors="replace")
    for path in (Path(repo_dir) / "lakefile.toml", Path(repo_dir) / "lakefile.lean")
    if path.is_file()
  )
  if re.search(r'(?:name\s*=\s*"llrwt"|lean_exe\s+llrwt\b)', config_text):
    targets.append("llrwt")
  try:
    proc = subprocess.run(
      [lake_executable(repo_dir), "build", *targets], cwd=repo_dir,
      env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
      timeout=int(env.get("ARCHER_BUILD_TIMEOUT_SEC", "3600")),
    )
  except subprocess.TimeoutExpired as exc:
    output = exc.stdout or ""
    if isinstance(output, bytes):
      output = output.decode("utf-8", errors="replace")
    return False, output + "\nArcher: VeIR build timed out."
  return proc.returncode == 0, proc.stdout


def infer_related_components(files):
  components = set()
  for filename in files:
    path = Path(filename)
    if path.parts and path.parts[0] in {"Veir", "Exe", "Test", "UnitTest"}:
      parts = path.parts[1:]
      component = parts[0] if len(parts) > 1 else path.stem
      if component in {"Passes", "Dialects", "Analysis", "Interpreter", "IR", "Rewriter"} and len(parts) > 1:
        component = parts[1].removesuffix(".lean")
      components.add(component)
  return sorted(components) or ["unknown"]


def executable(name: str) -> Path:
  return Path(veir_dir) / ".lake" / "build" / "bin" / name


def strip_mlir_fence(source: str) -> str:
  source = source.strip()
  if not source.startswith("```"):
    return source
  lines = source.splitlines()[1:]
  if lines and lines[-1].strip() == "```":
    lines.pop()
  return "\n".join(lines).strip()


def remove_path_from_output(output: str) -> str:
  return output.replace(str(Path(veir_dir).resolve()) + "/", "")
