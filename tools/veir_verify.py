import json
import re
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from lms.tool import FuncToolBase, FuncToolCallException, FuncToolSpec
from tools.veir_trans import run_opt
from veir.helper import strip_mlir_fence


def interpret(executable: Path, source: str):
  with TemporaryDirectory() as tmp:
    path = Path(tmp) / "program.mlir"
    path.write_text(source, encoding="utf-8")
    proc = subprocess.run([str(executable), str(path)], capture_output=True, text=True, timeout=30)
  def normalize(text: str):
    return re.sub(r"/tmp/tmp[^/]+/program\.mlir", "<input>", text.strip())

  return {
    "return_code": proc.returncode,
    "stdout": normalize(proc.stdout),
    "stderr": normalize(proc.stderr),
  }


def observable(result: dict):
  stdout = result["stdout"]
  if stdout.startswith("Undefined behavior"):
    return "ub"
  return (result["return_code"], stdout, result["stderr"])


class VerifyTool(FuncToolBase):
  def __init__(self, build_dir):
    self.build_dir = str(Path(build_dir).resolve())

  def spec(self):
    return FuncToolSpec("verify", "Transform MLIR with veir-opt and compare veir-interpret behavior before and after.", [
      FuncToolSpec.Param("orig_ir", "string", True, "A self-contained zero-argument @main MLIR program in ```mlir fences."),
      FuncToolSpec.Param("args", "string", True, "veir-opt pass arguments, for example -p=instcombine."),
      FuncToolSpec.Param("thoughts", "string", False, "Expected behavior and review rationale."),
      FuncToolSpec.Param("test_index", "integer", False, "Related tests_manager index."),
      FuncToolSpec.Param("covered_strategy", "string", False, "Related Phase 1 strategy name."),
    ])

  def _call(self, *, orig_ir, args, thoughts="", test_index=None, covered_strategy=None, **kwargs):
    original = strip_mlir_fence(orig_ir)
    transformed, opt_log, crashed = run_opt(orig_ir, args, self.build_dir)
    result = {"tool": "verify", "args": args, "original_ir": original,
      "transformed_ir": transformed or "<veir-opt failed>", "thoughts": thoughts,
      "test_index": test_index, "covered_strategy": covered_strategy}
    if transformed is None:
      result.update(found=crashed, log=opt_log)
      return json.dumps(result)
    interpreter = Path(self.build_dir) / "bin" / "veir-interpret"
    if not interpreter.is_file():
      raise FuncToolCallException(f"veir-interpret not found at {interpreter}")
    before = interpret(interpreter, original)
    after = interpret(interpreter, transformed)
    result.update(
      found=observable(before) != "ub" and observable(before) != observable(after),
      log={"original_test_output": before, "transformed_test_output": after},
    )
    return json.dumps(result)


class DiffTestTool(VerifyTool):
  def spec(self):
    return FuncToolSpec("difftest", "Compare veir-interpret behavior before and after a veir-opt pass.", [
      FuncToolSpec.Param("action", "string", True, "Use 'test' to run or 'confirm' to classify a difference."),
      FuncToolSpec.Param("orig_ir", "string", False, "Self-contained zero-argument @main MLIR program."),
      FuncToolSpec.Param("args", "string", False, "veir-opt pass arguments."),
      FuncToolSpec.Param("is_bug", "boolean", False, "For confirm: whether the observed difference is a bug."),
      FuncToolSpec.Param("thoughts", "string", True, "Review rationale."),
      FuncToolSpec.Param("test_index", "integer", False, "Related test index."),
      FuncToolSpec.Param("covered_strategy", "string", False, "Related strategy name."),
    ])

  def _call(self, *, action="test", is_bug=None, **kwargs):
    if action == "confirm":
      return json.dumps({"found": bool(is_bug), "tool": "difftest", "action": "confirm",
        "thoughts": kwargs.get("thoughts", "")})
    result = json.loads(super()._call(**kwargs))
    result["tool"] = "difftest"
    result["action"] = "test"
    return json.dumps(result)
