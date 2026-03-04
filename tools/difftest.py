import json
import re
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from llvm.llvm_helper import strip_llvm_fence
from lms.tool import FuncToolBase, FuncToolCallException, FuncToolSpec
from tools.trans import transform

TEMPLATE = """
{ir}

define {type} @main(i32 %argc, ptr %argv) {{
entry:
  {call_instr}
  {ret_instr}
}}
"""


class DiffTestTool(FuncToolBase):
  def __init__(self, build_dir: str, llubi_path: str):
    self.build_dir = Path(build_dir).resolve().absolute()
    self.llubi_path = Path(llubi_path).resolve().absolute()
    # lli is typically in the same directory as other LLVM tools
    self.lli_path = self.build_dir / "bin" / "lli"

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "difftest",
      "Perform differential testing on the input LLVM IR code and another transformed by opt, "
      "then use llubi (or lli as fallback) to execute to see if there is any difference. "
      "You can also use this tool to confirm whether a previously found difference is a real bug."
      "If you encountered a crash when using llubi, please set `use_lli` to true to use lli for execution. ",
      [
        FuncToolSpec.Param(
          "action",
          "string",
          True,
          "The action to perform. Must be either 'test' (to run the differential test) or 'confirm' (to confirm if a found difference is a real bug).",
        ),
        FuncToolSpec.Param(
          "orig_ir",
          "string",
          False,
          "Required when action is 'test'. The orginal LLVM IR code to be transformed. The code should be wrapped with ```llvm and ```. "
          "For example, '```llvm\n; LLVM IR code\n```\n'.",
        ),
        FuncToolSpec.Param(
          "args",
          "string",
          False,
          "Required when action is 'test'. The arguments for opt to specify the optimization pass and other options. For example, '-S -passes=instcombine'.",
        ),
        FuncToolSpec.Param(
          "call_instr",
          "string",
          False,
          "Required when action is 'test'. A single LLVM `call` instruction (without the leading `%r =`) to be inserted/executed for testing. "
          "It must be valid LLVM IR and include concrete argument values (inline constants "
          "or constant expressions such as `bitcast (...)` are allowed). "
          "The call signature must match the target function defined in `orig_ir`. "
          "Example: `call float @test(i1 true, float 1.0, float bitcast (i32 2139095040 to float))`.",
        ),
        FuncToolSpec.Param(
          "use_lli",
          "boolean",
          False,
          "Optional. If true, use lli instead of llubi for execution. Use this if llubi crashes or has issues. Defaults to false (use llubi).",
        ),
        FuncToolSpec.Param(
          "is_bug",
          "boolean",
          False,
          "Required when action is 'confirm'. Whether the difference found by the previous 'test' action is a real bug.",
        ),
        FuncToolSpec.Param(
          "thoughts",
          "string",
          True,
          "When action is 'test', explain what mutation strategies were used to generate the original IR and what is expected. "
          "When action is 'confirm', explain why the difference is a real bug or not.",
        ),
        FuncToolSpec.Param(
          "test_index",
          "integer",
          False,
          "The index of the test case in `tests_manager` that is being verified. "
          "Required when action is 'test' and the test case is derived from an existing test.",
        ),
        FuncToolSpec.Param(
          "covered_strategy",
          "string",
          False,
          "The strategy name from Phase 1 that this verification covers. "
          "Required when action is 'test' and `test_index` is provided.",
        ),
      ],
    )

  def _call(
    self,
    *,
    action: str,
    thoughts: str,
    orig_ir: str = None,
    args: str = None,
    call_instr: str = None,
    use_lli: bool = False,
    is_bug: bool = None,
    test_index: int = None,
    covered_strategy: str = None,
    **kwargs,
  ) -> str:
    if action == "confirm":
      if is_bug is None:
        raise FuncToolCallException(
          "The 'is_bug' parameter is required when action is 'confirm'."
        )
      return json.dumps(
        {
          "found": is_bug,
          "tool": "difftest",
          "action": "confirm",
          "thoughts": thoughts,
        }
      )
    elif action == "test":
      if not orig_ir or not args or not call_instr:
        raise FuncToolCallException(
          "The 'orig_ir', 'args', and 'call_instr' parameters are required when action is 'test'."
        )

      transformed_ir = transform(orig_ir, args, self.build_dir)

      # Require a single call (no leading "%r ="); main will assign it to %r.
      call_regex = (
        r'\s*call\s+(.+?)\s+@(?:[-$._A-Za-z0-9]+|"(?:[^"\\]|\\.)+")\s*\(.*\)\s*$'
      )
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

        if not call_type == "void":
          call_instr = f"%r = {call_instr.strip()}"
          ret_instr = f"ret {call_type} %r"
        else:
          call_instr = call_instr.strip()
          ret_instr = "ret void"

        original_program = TEMPLATE.format(
          ir=orig_ir_body,
          type=call_type,
          call_instr=call_instr.strip(),
          ret_instr=ret_instr.strip(),
        )

        transformed_program = TEMPLATE.format(
          ir=transformed_ir_body,
          type=call_type,
          call_instr=call_instr.strip(),
          ret_instr=ret_instr.strip(),
        )

        orig_ir_path.write_text(
          original_program,
          encoding="utf-8",
        )
        transformed_ir_path.write_text(
          transformed_program,
          encoding="utf-8",
        )

        def run(path, timeout_s: int = 10):
          # Choose executor based on use_lli flag
          executor = self.lli_path if use_lli else self.llubi_path
          executor_name = "lli" if use_lli else "llubi"

          try:
            res = subprocess.run(
              [str(executor), str(path)],
              capture_output=True,
              timeout=timeout_s,
            )
            return {
              "timed_out": False,
              "return_code": res.returncode,
              "stdout": res.stdout.decode("utf-8", errors="replace").strip(),
              "stderr": res.stderr.decode("utf-8", errors="replace").strip(),
              "executor": executor_name,
            }
          except subprocess.TimeoutExpired as e:
            return {
              "timed_out": True,
              "return_code": None,
              "stdout": (
                e.stdout.decode("utf-8", errors="replace") if e.stdout else ""
              ).strip(),
              "stderr": (
                e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
              ).strip(),
              "executor": executor_name,
            }

        out1 = run(orig_ir_path)
        out2 = run(transformed_ir_path)

        return json.dumps(
          {
            "found": False,
            "tool": "difftest",
            "action": "test",
            "original_ir": original_program,
            "transformed_ir": transformed_program,
            "log": {
              "original_test_output": out1,
              "transformed_test_output": out2,
            },
            "thoughts": thoughts,
            "test_index": test_index,
            "covered_strategy": covered_strategy,
          }
        )
    else:
      raise FuncToolCallException(
        f"Invalid action '{action}'. Must be 'test' or 'confirm'."
      )
