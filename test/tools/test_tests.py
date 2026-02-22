import json
import unittest
import sys
from pathlib import Path

# Add the root directory to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from tools.tests import Test, TestsTool
from lms.tool import FuncToolCallException


class TestTestsTool(unittest.TestCase):
    def test_tests_tool_list(self):
        tests = [
            Test(test_name="test1", test_body="body1", commands=["cmd1"]),
            Test(test_name="test2", test_body="body2", commands=["cmd2"]),
        ]
        tool = TestsTool(tests)

        # Test list action
        res_str = tool._call(action="list")
        res = json.loads(res_str)

        self.assertEqual(len(res["tests"]), 2)
        self.assertEqual(res["tests"][0]["name"], "test1")
        self.assertFalse(res["tests"][0]["tested"])
        self.assertEqual(res["tests"][1]["name"], "test2")
        self.assertFalse(res["tests"][1]["tested"])
        self.assertFalse(res["all_tested"])
        self.assertNotIn("message", res)

    def test_tests_tool_get(self):
        tests = [
            Test(test_name="test1", test_body="body1", commands=["cmd1"]),
            Test(test_name="test2", test_body="body2", commands=["cmd2"]),
        ]
        tool = TestsTool(tests)

        # Test get action
        res_str = tool._call(action="get", index=1)
        res = json.loads(res_str)

        self.assertEqual(res["test_name"], "test2")
        self.assertEqual(res["test_body"], "body2")
        self.assertEqual(res["commands"], ["cmd2"])
        self.assertFalse(res["tested"])

    def test_tests_tool_mark_tested(self):
        tests = [
            Test(test_name="test1", test_body="body1", commands=["cmd1"]),
            Test(test_name="test2", test_body="body2", commands=["cmd2"]),
        ]
        tool = TestsTool(tests)

        # Mark first test as tested
        res_str = tool._call(action="mark_tested", index=0)
        self.assertIn("There are still untested tests", res_str)
        self.assertTrue(tests[0].tested)
        self.assertFalse(tests[1].tested)

        # Check list again
        list_res = json.loads(tool._call(action="list"))
        self.assertTrue(list_res["tests"][0]["tested"])
        self.assertFalse(list_res["tests"][1]["tested"])
        self.assertFalse(list_res["all_tested"])

        # Mark second test as tested
        res_str = tool._call(action="mark_tested", index=1)
        self.assertIn("All tests have been tested", res_str)
        self.assertTrue(tests[0].tested)
        self.assertTrue(tests[1].tested)

        # Check list again
        list_res = json.loads(tool._call(action="list"))
        self.assertTrue(list_res["all_tested"])
        self.assertIn("message", list_res)

    def test_tests_tool_invalid_actions(self):
        tests = [Test(test_name="test1", test_body="body1", commands=["cmd1"])]
        tool = TestsTool(tests)

        # Invalid action
        with self.assertRaisesRegex(FuncToolCallException, "Invalid action"):
            tool._call(action="invalid_action")

        # Missing index for get
        with self.assertRaisesRegex(FuncToolCallException, "parameter is required"):
            tool._call(action="get")

        # Missing index for mark_tested
        with self.assertRaisesRegex(FuncToolCallException, "parameter is required"):
            tool._call(action="mark_tested")

        # Invalid index
        with self.assertRaisesRegex(FuncToolCallException, "Invalid index"):
            tool._call(action="get", index=5)

        with self.assertRaisesRegex(FuncToolCallException, "Invalid index"):
            tool._call(action="mark_tested", index=-1)


if __name__ == "__main__":
    unittest.main()
