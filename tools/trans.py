import json
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


def transform(orig_ir: str, args: str, build_dir: str) -> str:
  if not (
    isinstance(orig_ir, str)
    and orig_ir.startswith("```llvm")
    and orig_ir.endswith("```")
  ):
    raise FuncToolCallException(
      f"orig_ir must be a self-contained LLVM IR code wrapped with ```llvm and ```: {orig_ir}"
    )
  orig_ir_code = strip_llvm_fence(orig_ir)
  opt_path = build_dir / "bin" / "opt"
  if not opt_path.is_file():
    raise FuncToolCallException(f"opt tool not found at {opt_path}")
  with TemporaryDirectory() as tmpdir:
    orig_ir_path = Path(tmpdir) / "orig.ll"
    with open(orig_ir_path, "w", encoding="utf-8") as f:
      f.write(orig_ir_code)
    cmd = f"{opt_path} -S {args} {orig_ir_path}"
    try:
      result = cmdline.check_output(cmd)
      transformed_ir = result.decode("utf-8", errors="replace").strip()
      return f"```llvm\n{transformed_ir}\n```"
    except CalledProcessError as e:
      err_msg = ""
      if e.stderr:
        err_msg = e.stderr.decode("utf-8", errors="replace")
      elif e.stdout:
        err_msg = e.stdout.decode("utf-8", errors="replace")
      else:
        err_msg = str(e)

      # Check if this is an opt crash (bug found)
      if is_opt_crash(err_msg):
        # Return JSON indicating a crash bug was found
        return json.dumps(
          {
            "is_crash": True,
            "found": True,
            "tool": "trans",
            "args": args,
            "original_ir": orig_ir_code,
            "transformed_ir": "<crash during transformation>",
            "log": f"opt crashed during transformation:\n{err_msg.strip()}",
          }
        )

      # Not a crash, regular error
      raise FuncToolCallException(
        f"Failed to transform the LLVM IR code. {err_msg.strip()}"
      )


class TransTool(FuncToolBase):
  def __init__(self, build_dir: str):
    self.build_dir = Path(build_dir).resolve().absolute()

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "trans",
      "Transform the original LLVM IR code to optimized LLVM IR code using opt with specified optimization pass.",
      [
        FuncToolSpec.Param(
          "orig_ir",
          "string",
          True,
          "The original LLVM IR code to be transformed. The code should be wrapped with ```llvm and ```. "
          "For example, '```llvm\n; LLVM IR code\n```\n'.",
        ),
        FuncToolSpec.Param(
          "args",
          "string",
          True,
          "The arguments for opt to specify the optimization pass and other options. For example, '-S -passes=instcombine'.",
        ),
        FuncToolSpec.Param(
          "thoughts",
          "string",
          True,
          "The thoughts explaining what is expected to be verified by this transformation.",
        ),
      ],
    )

  def _call(self, *, orig_ir: str, args: str, thoughts: str, **kwargs) -> str:
    result = transform(orig_ir, args, self.build_dir)

    # Check if result is a crash report (JSON string starting with {)
    if isinstance(result, str) and result.strip().startswith("{"):
      try:
        crash_data = json.loads(result)
        if crash_data.get("is_crash"):
          # Add thoughts to the crash report
          crash_data["thoughts"] = thoughts
          crash_data["args"] = args
          return json.dumps(crash_data)
      except (json.JSONDecodeError, KeyError):
        pass

    return result
