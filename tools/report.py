import json
from lms.tool import FuncToolBase, FuncToolCallException, FuncToolSpec

class ReportTool(FuncToolBase):
  def __init__(self):
    super().__init__()

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "report",
      "Stop and report found bug cases for the fix",
      [
        FuncToolSpec.Param(
          "test",
          "list[string, string]",
          True,
          "A self-contained LLVM IR wrapped with ```llvm and ``` and the command to trigger the bug. "
          "For example, ['```llvm\n; LLVM IR code\n```', 'the command to trigger the bug'].",
          schema={
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
            "maxItems": 2,
          }
        ),
        FuncToolSpec.Param(
          "thoughts",
          "string",
          True,
          'The detailed thoughts for analyzing the bug including '
          '1. "Bug Triggering Analysis" for why the provided test can trigger the bug, and '
          '2. "Fix Weakness Analysis" for why the provided test can reveal the weakness.'
        )
      ]
    )
  
  def _call(self, *, test: list[str], thoughts: str) -> str:
    if not isinstance(test, list) or len(test) != 2:
      raise FuncToolCallException(f"Test must be a list of two elements: {test}")
    if not (isinstance(test[0], str) and test[0].startswith("```llvm") and test[0].endswith("```")):
      raise FuncToolCallException(f"The first element of test must be a self-contained LLVM IR wrapped with ```llvm and ```: {test[0]}")
    return json.dumps(
      {
        "test": [test[0].strip(), test[1].strip()],
        "thoughts": thoughts.strip(),
      },
      indent=2,
    )
