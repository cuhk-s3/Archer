import json
import re
from pathlib import Path
from subprocess import CalledProcessError
from tempfile import TemporaryDirectory

from llvm.llvm_helper import strip_llvm_fence
from lms.tool import FuncToolBase, FuncToolCallException, FuncToolSpec
from utils import cmdline


def is_opt_crash(error_message: str) -> bool:
  """Detect if the error is an opt crash (which indicates a bug)."""
  crash_indicators = [
    "LLVM ERROR",
    "compilation aborted",
    "Stack dump:",
    "Broken module found",
    "does not dominate all uses",
    "PLEASE submit a bug report",
  ]
  return any(indicator in error_message for indicator in crash_indicators)


class VerifyTool(FuncToolBase):
  def __init__(self, build_dir: str, alive_path: str):
    self.build_dir = Path(build_dir).resolve().absolute()
    self.alive_path = Path(alive_path).resolve().absolute()
    print(self.build_dir, self.alive_path)

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "verify",
      "Verify if the transformation from original LLVM IR code to optimized LLVM IR code is correct using alive-tv with provided arguments.",
      [
        FuncToolSpec.Param(
          "orig_ir",
          "string",
          True,
          "The original LLVM IR code to be verified. The code should be wrapped with ```llvm and ```. "
          "For example, '```llvm\n; LLVM IR code\n```\n'.",
        ),
        FuncToolSpec.Param(
          "args",
          "string",
          True,
          "The arguments for alive-tv to specify the verification options. For example, '-passes=instcombine'.",
        ),
      ],
    )

  def _call(self, *, orig_ir: str, args: str, **kwargs) -> str:
    if not (
      isinstance(orig_ir, str)
      and orig_ir.startswith("```llvm")
      and orig_ir.endswith("```")
    ):
      raise FuncToolCallException(
        f"orig_ir must be a self-contained LLVM IR code wrapped with ```llvm and ```: {orig_ir}"
      )
    opt_path = self.build_dir / "bin" / "opt"
    if not opt_path.is_file():
      raise FuncToolCallException(f"opt tool not found at {opt_path}")
    alive_tv_path = self.alive_path
    if not alive_tv_path.is_file():
      raise FuncToolCallException(f"alive-tv tool not found at {alive_tv_path}")

    with TemporaryDirectory() as tmpdir:
      orig_ir_path = Path(tmpdir) / "orig.ll"
      transformed_ir_path = Path(tmpdir) / "transformed.ll"
      orig_ir_code = strip_llvm_fence(orig_ir)
      with open(orig_ir_path, "w") as f:
        f.write(orig_ir_code)

      cmd = f"{opt_path} -S {args} {orig_ir_path} -o {transformed_ir_path}"
      try:
        cmdline.check_output(cmd)
      except CalledProcessError as e:
        err_msg = (
          e.stderr.decode("utf-8", errors="replace").strip() if e.stderr else str(e)
        )

        # Check if this is an opt crash (bug found)
        if is_opt_crash(err_msg):
          return json.dumps(
            {
              "found": True,
              "tool": "verify",
              "args": args,
              "original_ir": orig_ir_code,
              "transformed_ir": "<crash during transformation>",
              "log": f"opt crashed during transformation:\n{err_msg}",
            }
          )

        # Not a crash, regular error
        raise FuncToolCallException(
          f"Failed to transform the LLVM IR code with opt. {err_msg}"
        )

      with open(transformed_ir_path, "r") as f:
        transformed_ir_code = f.read()

      cmd = f"{alive_tv_path} {args} --disable-undef-input {orig_ir_path} {transformed_ir_path}"
      try:
        result = cmdline.check_output(cmd)
        verification_result = result.decode("utf-8").strip()
        m = re.search(r"(\d+)\s+incorrect transformations", verification_result)
        return json.dumps(
          {
            "found": m and int(m.group(1)) > 0,
            "tool": "verify",
            "args": args,
            "original_ir": orig_ir_code,
            "transformed_ir": transformed_ir_code,
            "log": verification_result,
          }
        )
      except CalledProcessError as e:
        raise FuncToolCallException(
          f"Failed to verify the LLVM IR code transformation. {e.stderr.decode('utf-8').strip() if e.stderr else str(e)}"
        )
