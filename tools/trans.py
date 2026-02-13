from pathlib import Path
from subprocess import CalledProcessError
from tempfile import TemporaryDirectory

from llvm.llvm_helper import strip_llvm_fence
from lms.tool import FuncToolBase, FuncToolCallException, FuncToolSpec
from utils import cmdline


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
        with open(orig_ir_path, "w") as f:
            f.write(orig_ir_code)
        cmd = f"{opt_path} {args} {orig_ir_path}"
        try:
            result = cmdline.check_output(cmd)
            transformed_ir = result.decode("utf-8").strip()
            return f"```llvm\n{transformed_ir}\n```"
        except CalledProcessError as e:
            raise FuncToolCallException(
                f"Failed to transform the LLVM IR code. {e.stderr.decode('utf-8').strip() if e.stderr else str(e)}"
            )
    return f"```llvm\n{transformed_ir}\n```"


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
            ],
        )

    def _call(self, *, orig_ir: str, args: str, **kwargs) -> str:
        return self.transform(orig_ir, args, self.build_dir)
