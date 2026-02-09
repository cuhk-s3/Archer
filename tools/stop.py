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
      "Stop process and return the found test strategies for the patch",
      [
        FuncToolSpec.Param(
          "strategies",
          "list[tuple[string,string,string,string]]",
          True,
          "A list of bug-trigger test strategies with each being a tuple of strategy name, target, rationale and expected issue.",
        ),
        FuncToolSpec.Param(
          "thoughts",
          "string",
          True,
          'The detailed thoughts for diagnosing the fix including step-by-step "'
          '1. "Fix Understanding", '
          '2. "Assumptions Identified", '
          '3. "Potential Cases to Break Assumptions", and '
          '4. "Test Strategies".',
        ),
      ],
    )

  def _call(self, *, strategies: list[tuple[str, str, str, str]], thoughts: str) -> str:
    strategies = []
    for _, edit in enumerate(strategies):
      if len(edit) != 2:
        raise FuncToolCallException(
          f"Each edit point must be a tuple of 4 elements (strategy name, target, rationale, expected issue): {edit}"
        )
      strategies.append((edit[0].strip(), edit[1].strip()))
    return json.dumps(
      {
        "strategies": strategies,
        "thoughts": thoughts,
      },
      indent=2,
    )
