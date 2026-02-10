import ast
import json

from lms.tool import FuncToolBase, FuncToolCallException, FuncToolSpec


class StopTool(FuncToolBase):
  def __init__(self):
    super.__init__(self)

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "stop",
      "Stop process and return the found test strategies for the patch",
      [
        FuncToolSpec.Param(
          "strategies",
          "list[tuple[string,string,string,string]]",
          True,
          "A list of bug-trigger test strategies with each being a tuple of strategy name, target, rationale and expected issue."
          "For example, [('Strategy 1', 'target file or function', 'rationale for why this strategy can trigger the bug', 'the expected issue that can be observed when the strategy is executed'), ...].",
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
    strats = []
    if isinstance(strategies, str):
        s = strategies.strip()
        # try json first
        try:
            strategies = json.loads(s)
        except Exception:
            try:
                strategies = ast.literal_eval(s)
            except Exception as e:
                raise FuncToolCallException(
                    f"strategies must be a list of 4-tuples; got a string that cannot be parsed: {strategies}"
                ) from e
    # check if strategies is a list of tuples of 4 elements
    if not isinstance(strategies, list):
      raise FuncToolCallException(f"Strategies must be a list of tuples: {strategies}")
    # check if it is list
    if not all(isinstance(edit, tuple) for edit in strategies):
      raise FuncToolCallException(f"Each test strategy must be a tuple: {strategies}")
    for _, edit in enumerate(strategies):
      if len(edit) != 4:
        raise FuncToolCallException(
          f"Each test strategy must be a tuple of 4 elements (strategy name, target, rationale, expected issue): {edit}"
        )
      strats.append((edit[0].strip(), edit[1].strip(), edit[2].strip(), edit[3].strip()))
    return json.dumps(
      {
        "strategies": strats,
        "thoughts": thoughts,
      },
      indent=2,
    )
