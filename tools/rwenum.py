import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from lms.tool import FuncToolBase, FuncToolCallException, FuncToolSpec


class RwenumTool(FuncToolBase):
  """Bounded wrapper around connglli/veir Tools/rwenum."""

  def __init__(self, build_dir):
    self.build_dir = Path(build_dir).resolve()
    self.engine = Path(os.environ.get(
      "ARCHER_RWENUM_ENGINE", Path(__file__).parent / "vendor" / "rwenum.py"
    )).resolve()

  def spec(self):
    return FuncToolSpec("rwenum", (
      "Enumerate integer widths, constants, and LLVM flags for a rewrite DSL, "
      "run the PR build's llrwt, and stop on the first validator counterexample."
    ), [
      FuncToolSpec.Param("rewrite", "string", True,
        "Rewrite shape such as 'x * 2 => x + x'. The RHS is a descriptive label."),
      FuncToolSpec.Param("max_width", "integer", False,
        "Enumerate widths 1..N; bounded to 16 (default 4)."),
      FuncToolSpec.Param("additional_widths", "string", False,
        "Comma-separated extra widths (default '32,64')."),
      FuncToolSpec.Param("constants", "string", False,
        "Optional constant subset, for example '0,1,-1,2'."),
      FuncToolSpec.Param("limit", "integer", False,
        "Maximum cases; bounded to 1000 (default 100)."),
      FuncToolSpec.Param("thoughts", "string", True,
        "Why this enumeration targets the reviewed rewrite."),
      FuncToolSpec.Param("test_index", "integer", False, "Related test index."),
      FuncToolSpec.Param("covered_strategy", "string", False,
        "Related Phase 1 strategy name."),
    ])

  @staticmethod
  def _tool(explicit_env, build_candidate, fallback):
    explicit = os.environ.get(explicit_env)
    if explicit:
      return str(Path(explicit).resolve())
    if build_candidate.is_file():
      return str(build_candidate)
    return shutil.which(fallback)

  def _call(self, *, rewrite, thoughts, max_width=4,
      additional_widths="32,64", constants=None, limit=100,
      test_index=None, covered_strategy=None, **kwargs):
    max_width = int(max_width)
    limit = int(limit)
    if not 1 <= max_width <= 16:
      raise FuncToolCallException("max_width must be between 1 and 16")
    if not 1 <= limit <= 1000:
      raise FuncToolCallException("limit must be between 1 and 1000")

    llrwt = self._tool(
      "ARCHER_LLRWT", self.build_dir / "bin" / "llrwt", "llrwt"
    )
    validator = self._tool(
      "ARCHER_RWT_VALIDATOR", Path("/__missing__"), "alive-tv"
    )
    base = {
      "tool": "rwenum", "rewrite": rewrite, "thoughts": thoughts,
      "test_index": test_index, "covered_strategy": covered_strategy,
    }
    missing = [name for name, path in (("llrwt", llrwt), ("validator", validator)) if not path]
    if missing:
      return json.dumps({**base, "found": False, "status": "unavailable",
        "missing_capabilities": missing})

    timeout = int(os.environ.get("ARCHER_RWENUM_TIMEOUT_SEC", "300"))
    per_case = min(60, max(1, int(os.environ.get("ARCHER_RWENUM_CASE_TIMEOUT_SEC", "30"))))
    with TemporaryDirectory(prefix="archer-rwenum-") as tmp:
      outdir = Path(tmp) / "run"
      command = [
        sys.executable, str(self.engine), rewrite,
        "--max-width", str(max_width),
        "--additional-widths", str(additional_widths),
        "--limit", str(limit), "--outdir", str(outdir),
        "--llrwt", llrwt, "--alive2", validator,
        "--timeout", str(per_case),
      ]
      if constants is not None:
        command += ["--constants", str(constants)]
      try:
        proc = subprocess.run(
          command, text=True, capture_output=True, timeout=timeout,
        )
      except subprocess.TimeoutExpired:
        return json.dumps({**base, "found": False, "status": "timeout",
          "log": f"rwenum exceeded {timeout}s total timeout"})

      run_info = {}
      run_file = outdir / "run.json"
      if run_file.is_file():
        run_info = json.loads(run_file.read_text(encoding="utf-8"))
      status = run_info.get("status", "complete" if proc.returncode == 0 else "tool_error")
      result = {**base, "found": status == "counterexample", "status": status,
        "completed_cases": run_info.get("completed_cases", 0),
        "total_cases": run_info.get("total_cases"),
        "log": (proc.stdout + proc.stderr)[-12000:]}
      failing = run_info.get("failing_case")
      if failing:
        case_dir = Path(failing)
        for key, filename in (
          ("case", "case.json"), ("original_ir", "before.ll"),
          ("transformed_ir", "after.ll"), ("validator_log", "alive2.log"),
        ):
          path = case_dir / filename
          if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            result[key] = json.loads(text) if key == "case" else text[-20000:]
      return json.dumps(result)
