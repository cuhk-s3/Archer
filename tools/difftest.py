import json
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory

from lms.tool import FuncToolBase, FuncToolCallException, FuncToolSpec
from tools.trans import transform
from llvm.llvm_helper import strip_llvm_fence


TEMPLATE = """
{ir}

define {type} @main(i32 %argc, ptr %argv) {{
entry:
  %r = {call_instr}
  ret {type} %r
}}
"""


class DiffTestTool(FuncToolBase):
  def __init__(self, build_dir: str, llubi_path: str):
    self.build_dir = Path(build_dir).resolve().absolute()
    self.llubi_path = Path(llubi_path).resolve().absolute()

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "difftest",
      "Perform differential testing on the input LLVM IR code and another transformed by opt, "
      "then use llubi to execute to see if there is any difference. ",
      [
        FuncToolSpec.Param(
          "orig_ir",
          "string",
          True,
          "The orginal LLVM IR code to be transformed. The code should be wrapped with ```llvm and ```. "
          "For example, '```llvm\n; LLVM IR code\n```\n'.",
        ),
        FuncToolSpec.Param(
          "args",
          "string",
          True,
          "The arguments for opt to specify the optimization pass and other options. For example, '-S -passes=instcombine'.",
        ),
        FuncToolSpec.Param(
          "call_instr",
          "string",
          True,
          "A single LLVM `call` instruction (without the leading `%r =`) to be inserted/executed for testing. "
          "It must be valid LLVM IR and include concrete argument values (inline constants "
          "or constant expressions such as `bitcast (...)` are allowed). "
          "The call signature must match the target function defined in `orig_ir`. "
          "Example: `call float @test(i1 true, float 1.0, float bitcast (i32 2139095040 to float))`.",
        ),
        FuncToolSpec.Param(
          "thoughts",
          "string",
          True,
          "The thoughts explaining what mutation strategies were used to generate the original IR and what is expected.",
        ),
      ],
    )

  def _call(self, *, orig_ir: str, args: str, call_instr: str, thoughts: str, **kwargs) -> str:
    transformed_ir = transform(orig_ir, args, self.build_dir)

    # Require a single call (no leading "%r ="); main will assign it to %r.
    call_regex = r"\s*call\s+(.+?)\s+@[\w\d_]+\s*\(.*\)\s*$"
    m = re.fullmatch(call_regex, call_instr.strip())
    if not m:
      raise FuncToolCallException(
        f"The provided call instruction is not valid: {call_instr}. "
        "It must be a single LLVM call instruction (without the leading `%r =`) with concrete argument values. "
        "For example, `call float @test(i1 true, float 1.0, float bitcast (i32 2139095040 to float))`."
      )
    call_type = m.group(1).strip()

    orig_ir_body = strip_llvm_fence(orig_ir)
    transformed_ir_body = strip_llvm_fence(transformed_ir)

    with TemporaryDirectory() as tmpdir:
      tmpdir = Path(tmpdir)
      orig_ir_path = tmpdir / "orig.ll"
      transformed_ir_path = tmpdir / "transformed.ll"

      orig_ir_path.write_text(
        TEMPLATE.format(ir=orig_ir_body, type=call_type, call_instr=call_instr.strip()),
        encoding="utf-8"
      )
      transformed_ir_path.write_text(
        TEMPLATE.format(ir=transformed_ir_body, type=call_type, call_instr=call_instr.strip()),
        encoding="utf-8"
      )

      def run(path, timeout_s: int = 10):
        try:
          res = subprocess.run(
            [str(self.llubi_path), str(path)],
            capture_output=True,
            timeout=timeout_s,
          )
          return {
            "timed_out": False,
            "return_code": res.returncode,
            "stdout": res.stdout.decode('utf-8', errors='replace').strip(),
            "stderr": res.stderr.decode('utf-8', errors='replace').strip(),
          }
        except subprocess.TimeoutExpired as e:
          return {
            "timed_out": True,
            "return_code": None,
            "stdout": (e.stdout.decode('utf-8', errors='replace') if e.stdout else "").strip(),
            "stderr": (e.stderr.decode('utf-8', errors='replace') if e.stderr else "").strip(),
          }

      out1 = run(orig_ir_path)
      out2 = run(transformed_ir_path)

      # Strict oracle: everything must match (including timeout status).
      test_result = out1 == out2

      return json.dumps(
        {
          "found": test_result is False,
          "tool": "difftest",
          "original_ir": orig_ir_body,
          "transformed_ir": transformed_ir_body,
          "log": {
            "original_test_output": out1,
            "transformed_test_output": out2,
          },
          "thoughts": thoughts,
        }
      )
