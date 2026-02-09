import json
from pathlib import Path

from lms.tool import FuncToolBase, FuncToolCallException, FuncToolSpec
from tools.llvm_mixins import LlvmDirMixin


class StopTool(FuncToolBase, LlvmDirMixin):
  def __init__(self, llvm_dir: str):
    self.llvm_dir = Path(llvm_dir).resolve().absolute()

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "stop",
      "Stop process and return the found bugs for the patch",
      [
        FuncToolSpec.Param(
          "bugs",
          "list[tuple[string,string]]",
          True,
          "A list of bugs with each being a tuple of the verified LLVM IR and the detected bug description.",
        ),
        FuncToolSpec.Param(
          "thoughts",
          "string",
          True,
          'The detailed thoughts for diagnosing the fix including step-by-step "'
          '1. Understanding the Fix", '
          '2. "Potential Issue Analysis", '
          '3. "Proposed Bug Strategies(s)", and '
          '4. "Conclusion".',
        ),
      ],
    )

  def _call(self, *, bugs: list[tuple[str, str]], thoughts: str) -> str:
    bugs = []
    for _, edit in enumerate(bugs):
      if len(edit) != 2:
        raise FuncToolCallException(
          f"Each edit point must be a tuple of 2 elements (LLVM IR, bug description): {edit}"
        )
      bugs.append((edit[0].strip(), edit[1].strip()))
    return json.dumps(
      {
        "bugs": bugs,
        "thoughts": thoughts,
      },
      indent=2,
    )
