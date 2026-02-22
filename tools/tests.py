import json
from typing import List
from dataclasses import dataclass, field
from lms.tool import FuncToolBase, FuncToolCallException, FuncToolSpec


@dataclass
class Test:
    test_name: str
    test_body: str
    commands: List[str] = field(default_factory=list)
    tested: bool = False


class TestsTool(FuncToolBase):
    def __init__(self, tests: List[Test]):
        """
        tests should be a list of Test objects.
        """
        self.tests = tests

    def spec(self) -> FuncToolSpec:
        return FuncToolSpec(
            "tests_manager",
            "Manage the list of test cases. You can list all tests to see their status, get the details of a specific test, or mark a test as tested. Your goal is to ensure all tests are tested.",
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
            ],
        )

    def _call(self, *, action: str, index: int = None, **kwargs) -> str:
        if action == "list":
            res = []
            all_tested = True
            for i, t in enumerate(self.tests):
                res.append({"index": i, "name": t.test_name, "tested": t.tested})
                if not t.tested:
                    all_tested = False

            output = {"tests": res, "all_tested": all_tested}
            if all_tested:
                output["message"] = (
                    "All tests have been tested! You can now proceed to report."
                )
            return json.dumps(output, indent=2)

        elif action == "get":
            if index is None:
                raise FuncToolCallException(
                    "The 'index' parameter is required for the 'get' action."
                )
            if index < 0 or index >= len(self.tests):
                raise FuncToolCallException(
                    f"Invalid index {index}. Must be between 0 and {len(self.tests)-1}."
                )

            t = self.tests[index]
            return json.dumps(
                {
                    "test_name": t.test_name,
                    "test_body": t.test_body,
                    "commands": t.commands,
                    "tested": t.tested,
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
                    f"Invalid index {index}. Must be between 0 and {len(self.tests)-1}."
                )

            self.tests[index].tested = True

            all_tested = all(t.tested for t in self.tests)
            if all_tested:
                return f"Test {index} marked as tested. All tests have been tested! You can now proceed to report."
            else:
                return f"Test {index} marked as tested. There are still untested tests."

        else:
            raise FuncToolCallException(
                f"Invalid action '{action}'. Must be 'list', 'get', or 'mark_tested'."
            )
