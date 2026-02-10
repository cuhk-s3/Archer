import json
from pathlib import Path
import re
from subprocess import CalledProcessError
from tempfile import TemporaryDirectory

from lms.tool import FuncToolBase, FuncToolCallException, FuncToolSpec
from utils import cmdline

class VerifyTool(FuncToolBase):
  def __init__(self, llvm_dir:str, alive_path: str):
    self.llvm_dir = Path(llvm_dir).resolve().absolute()
    self.alive_path = Path(alive_path).resolve().absolute()

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
          "For example, '```llvm\n; LLVM IR code\n```\n'."
        ),
        FuncToolSpec.Param(
          "args",
          "string",
          True,
          "The arguments for alive-tv to specify the verification options. For example, '-passes=instcombine'."
        )
      ]
    )

  def _call(self, *, orig_ir: str, args: str, **kwargs) -> str:
    if not (isinstance(orig_ir, str) and orig_ir.startswith("```llvm") and orig_ir.endswith("```")):
      raise FuncToolCallException(f"orig_ir must be a self-contained LLVM IR code wrapped with ```llvm and ```: {orig_ir}")
    opt_path = self.llvm_dir / "bin" / "opt"
    if not opt_path.is_file():
      raise FuncToolCallException(f"opt tool not found at {opt_path}")
    alive_tv_path = self.alive_path / "alive-tv"
    if not alive_tv_path.is_file():
      raise FuncToolCallException(f"alive-tv tool not found at {alive_tv_path}")
    
    with TemporaryDirectory() as tmpdir:
      orig_ir_path = Path(tmpdir) / "orig.ll"
      transformed_ir_path = Path(tmpdir) / "transformed.ll"
      orig_ir_code = orig_ir[len("```llvm\n"):-len("\n```")]
      with open(orig_ir_path, "w") as f:
        f.write(orig_ir_code)

      cmd = f"{opt_path} -S {args} {orig_ir_path} -o {transformed_ir_path}"
      try:
        cmdline.check_output(cmd, cwd=self.llvm_dir)
      except CalledProcessError as e:
        raise FuncToolCallException(f"Failed to transform the LLVM IR code with opt. {e.stderr.decode('utf-8').strip() if e.stderr else str(e)}")
      
      with open(transformed_ir_path, "r") as f:
        transformed_ir_code = f.read()
      
      cmd = f"{alive_tv_path} {args} {orig_ir_path} {transformed_ir_path}"
      try:
        result = cmdline.check_output(cmd, cwd=self.alive_path)
        verification_result = result.decode("utf-8").strip()
        m = re.search(r"(\d+)\s+incorrect transformations", verification_result)
        return json.dumps(
          {
            "found": m and int(m.group(1)) > 0,
            "original_ir": orig_ir_code,
            "transformed_ir": transformed_ir_code,
            "log": verification_result,
          }
        )
      except CalledProcessError as e:
        raise FuncToolCallException(f"Failed to verify the LLVM IR code transformation. {e.stderr.decode('utf-8').strip() if e.stderr else str(e)}")
