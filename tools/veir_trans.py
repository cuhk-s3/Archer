import json
import shlex
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from lms.tool import FuncToolBase, FuncToolCallException, FuncToolSpec
from veir.helper import strip_mlir_fence


def run_opt(source: str, args: str, build_dir: str):
  executable = Path(build_dir) / "bin" / "veir-opt"
  if not executable.is_file():
    raise FuncToolCallException(f"veir-opt not found at {executable}")
  with TemporaryDirectory() as tmp:
    input_path = Path(tmp) / "input.mlir"
    input_path.write_text(strip_mlir_fence(source), encoding="utf-8")
    proc = subprocess.run(
      [str(executable), str(input_path), "--print-op-generic", *shlex.split(args)],
      capture_output=True, text=True, timeout=60,
    )
  log = proc.stdout + proc.stderr
  crashed = proc.returncode < 0 or any(
    marker in log.lower()
    for marker in ("panic", "internal error", "segmentation fault", "backtrace")
  )
  # Older veir-opt revisions print ordinary diagnostics but still exit 0.
  # Never feed those diagnostic strings to veir-interpret as transformed IR.
  ordinary_error = any(
    marker in log.lower()
    for marker in (
      "error: unknown pass", "error parsing operation", "error parsing pass",
      "unrecognized pass", "unknown pass:",
    )
  ) or log.lstrip().startswith("Error:")
  if proc.returncode or ordinary_error:
    return None, log, crashed
  return proc.stdout.strip(), proc.stderr, False


class TransTool(FuncToolBase):
  def __init__(self, build_dir):
    self.build_dir = str(Path(build_dir).resolve())

  def spec(self):
    return FuncToolSpec("trans", "Transform MLIR with the PR build of veir-opt.", [
      FuncToolSpec.Param("orig_ir", "string", True, "Self-contained MLIR wrapped in ```mlir fences."),
      FuncToolSpec.Param("args", "string", True, "veir-opt arguments, for example -p=instcombine."),
      FuncToolSpec.Param("thoughts", "string", True, "What this transformation is testing."),
    ])

  def _call(self, *, orig_ir, args, thoughts, **kwargs):
    transformed, log, crashed = run_opt(orig_ir, args, self.build_dir)
    if transformed is None:
      return json.dumps({"found": crashed, "is_crash": crashed, "tool": "trans", "args": args,
        "original_ir": strip_mlir_fence(orig_ir), "transformed_ir": "<veir-opt failed>",
        "log": log, "thoughts": thoughts})
    return f"```mlir\n{transformed}\n```"
