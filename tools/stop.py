import json

from lms.tool import FuncToolBase, FuncToolCallException, FuncToolSpec


class StopTool(FuncToolBase):
  def __init__(self):
    super().__init__()

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "stop",
      "Stop process and return the found test strategies for the patch",
      [
        FuncToolSpec.Param(
          "strategies",
          "list[dict]",
          True,
          "A list of bug-trigger test strategies with each being a dictionary of strategy name, target, rationale and expected issue. "
          'For example, [{"name":"Strategy 1","target":"test target","rationale":"rationale for why this strategy can trigger the bug","expected_issue":"the expected issue that can be observed when the strategy is executed"}, {...}, ...].',
          schema={
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "name": {"type": "string"},
                "target": {"type": "string"},
                "rationale": {"type": "string"},
                "expected_issue": {"type": "string"},
              },
              "required": ["name", "target", "rationale", "expected_issue"],
            },
          },
        ),
        FuncToolSpec.Param(
          "thoughts",
          "string",
          True,
          "The detailed thoughts for diagnosing the fix including "
          '1. "Fix Understanding", '
          '2. "Formal Semantic Modeling", '
          '2. "Assumptions Identified", '
          '3. "Potential Cases to Break Assumptions", and '
          '4. "Test Strategies".',
        ),
      ],
    )

  def _call(self, *, strategies, thoughts: str) -> str:
    strats = []
    if isinstance(strategies, str):
      s = strategies.strip()
      try:
        strategies = json.loads(s)
      except Exception as e:
        raise FuncToolCallException(
          f"strategies must be a JSON array of objects; got a string that cannot be parsed: {strategies}"
        ) from e
    # check if strategies is a list of dicts
    if not isinstance(strategies, list):
      raise FuncToolCallException(f"Strategies must be a list of dicts: {strategies}")
    for _, s in enumerate(strategies):
      if not isinstance(s, dict):
        raise FuncToolCallException(
          f"Each test strategy must be an object with keys "
          f"(name, target, rationale, expected_issue). For example, "
          f'{{"name":"Strategy 1","target":"test target","rationale":"rationale for why this strategy can trigger the bug","expected_issue":"the expected issue that can be observed when the strategy is executed"}}. '
          f"Got: {s}"
        )
      try:
        name = s["name"]
        target = s["target"]
        rationale = s["rationale"]
        expected_issue = s["expected_issue"]
      except KeyError as e:
        raise FuncToolCallException(f"Strategy object missing required field {e}: {s}")
      strats.append(
        (
          str(name).strip(),
          str(target).strip(),
          str(rationale).strip(),
          str(expected_issue).strip(),
        )
      )
    return json.dumps(
      {
        "strategies": strats,
        "thoughts": thoughts,
      },
      indent=2,
    )
