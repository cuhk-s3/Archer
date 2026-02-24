import json
from dataclasses import dataclass, field
from typing import List

from lms.tool import FuncToolBase, FuncToolCallException, FuncToolSpec


@dataclass
class Test:
  test_name: str
  test_body: str
  commands: List[str] = field(default_factory=list)
  tested: bool = False
  covered_strategies: set = field(default_factory=set)


class TestsTool(FuncToolBase):
  def __init__(self, tests: List[Test], strategies: List[dict] = None, validator=None):
    """
    tests should be a list of Test objects.
    strategies should be a list of strategy dictionaries from Phase 1.
    validator should be a callable that takes the test index being marked and returns (bool, str).
    """
    self.tests = tests
    self.strategies = strategies or []
    self.all_strategies = {s.get("name") for s in self.strategies if s.get("name")}
    self.validator = validator

  def get_uncovered_strategies(self, index: int) -> List[str]:
    if index < 0 or index >= len(self.tests):
      return []
    return list(self.all_strategies - self.tests[index].covered_strategies)

  def get_all_uncovered_strategies(self) -> dict:
    """Returns a dictionary mapping test index to its uncovered strategies."""
    uncovered = {}
    for i, t in enumerate(self.tests):
      uncov = list(self.all_strategies - t.covered_strategies)
      if uncov:
        uncovered[i] = uncov
    return uncovered

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "tests_manager",
      "Manage the list of test cases. You can list all tests to see their status, get the details of a specific test, or mark a test as tested. Your goal is to ensure all tests are tested and EVERY test covers ALL Phase 1 strategies.",
      [
        FuncToolSpec.Param(
          "action",
          "string",
          True,
          "The action to perform. Must be one of: 'list', 'get', 'mark_tested'. 'list' shows all tests and their tested status. 'get' returns the full details of a test. 'mark_tested' marks a test as completed.",
        ),
        FuncToolSpec.Param(
          "index",
          "integer",
          False,
          "The index of the test. Required when action is 'get' or 'mark_tested'.",
        ),
        FuncToolSpec.Param(
          "covered_strategies",
          "list[string]",
          False,
          "A list of strategy names from Phase 1 that this specific test covers. Required when action is 'mark_tested'.",
          schema={"type": "array", "items": {"type": "string"}},
        ),
      ],
    )

  def _call(
    self,
    *,
    action: str,
    index: int = None,
    covered_strategies: List[str] = None,
    **kwargs,
  ) -> str:
    if action == "list":
      res = []
      all_tested = True
      for i, t in enumerate(self.tests):
        res.append(
          {
            "index": i,
            "name": t.test_name,
            "tested": t.tested,
            "uncovered_strategies": self.get_uncovered_strategies(i),
          }
        )
        if not t.tested:
          all_tested = False

      output = {"tests": res, "all_tested": all_tested}
      all_uncovered = self.get_all_uncovered_strategies()

      if all_tested and not all_uncovered:
        output["message"] = (
          "All tests have been tested and EVERY test covers all strategies! You can now proceed to report."
        )
      elif all_uncovered:
        output["message"] = "Some tests have not covered all Phase 1 strategies yet."
      return json.dumps(output, indent=2)

    elif action == "get":
      if index is None:
        raise FuncToolCallException(
          "The 'index' parameter is required for the 'get' action."
        )
      if index < 0 or index >= len(self.tests):
        raise FuncToolCallException(
          f"Invalid index {index}. Must be between 0 and {len(self.tests) - 1}."
        )

      t = self.tests[index]
      return json.dumps(
        {
          "test_name": t.test_name,
          "test_body": t.test_body,
          "commands": t.commands,
          "tested": t.tested,
          "uncovered_strategies": self.get_uncovered_strategies(index),
        },
        indent=2,
      )

    elif action == "mark_tested":
      if index is None:
        raise FuncToolCallException(
          "The 'index' parameter is required for the 'mark_tested' action."
        )
      if index < 0 or index >= len(self.tests):
        raise FuncToolCallException(
          f"Invalid index {index}. Must be between 0 and {len(self.tests) - 1}."
        )
      if covered_strategies is None:
        raise FuncToolCallException(
          "The 'covered_strategies' parameter is required for the 'mark_tested' action to indicate which Phase 1 strategies this test covers."
        )

      if self.validator:
        is_valid, reason = self.validator(index)
        if not is_valid:
          return f"Test {index} NOT marked as tested. Reason: {reason}"

      # Update covered strategies for this specific test
      for s in covered_strategies:
        if s in self.all_strategies:
          self.tests[index].covered_strategies.add(s)

      uncovered_for_this_test = self.get_uncovered_strategies(index)
      if not uncovered_for_this_test:
        self.tests[index].tested = True

      all_tested = all(t.tested for t in self.tests)
      all_uncovered = self.get_all_uncovered_strategies()

      if all_tested and not all_uncovered:
        return f"Test {index} marked as tested. All tests have been tested and EVERY test covers all strategies! You can now proceed to report."
      else:
        if not uncovered_for_this_test:
          msg = f"Test {index} marked as tested."
        else:
          msg = f"Test {index} NOT marked as tested because the following strategies are still uncovered: {uncovered_for_this_test}. Please test again and call 'mark_tested' again after covering them."

        if not all_tested:
          msg += " There are still untested tests. Please continue testing them."
        return msg

    else:
      raise FuncToolCallException(
        f"Invalid action '{action}'. Must be 'list', 'get', or 'mark_tested'."
      )
