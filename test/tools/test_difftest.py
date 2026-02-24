import json
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from lms.tool import FuncToolCallException
from tools.difftest import DiffTestTool


class TestDiffTestTool(unittest.TestCase):
  def setUp(self):
    self.build_dir = "/tmp/build"
    self.llubi_path = "/tmp/llubi"
    self.tool = DiffTestTool(self.build_dir, self.llubi_path)

  @patch("tools.difftest.transform")
  @patch("tools.difftest.subprocess.run")
  def test_difftest_success(self, mock_subprocess_run, mock_transform):
    # Setup mocks
    mock_transform.return_value = "```llvm\n; transformed code\n```"

    # Mock subprocess.run to return successful execution
    mock_completed_process = MagicMock()
    mock_completed_process.returncode = 0
    mock_completed_process.stdout = "result: 42"
    mock_completed_process.stderr = ""
    mock_subprocess_run.return_value = mock_completed_process

    orig_ir = "```llvm\n; original code\n```"
    args = "-S -passes=instcombine"
    call_instr = "call i32 @test(i32 1)"
    thoughts = "test thoughts"
    test_index = 1
    covered_strategies = ["strategy1"]

    result_json = self.tool._call(
      action="test",
      orig_ir=orig_ir,
      args=args,
      call_instr=call_instr,
      thoughts=thoughts,
      test_index=test_index,
      covered_strategies=covered_strategies,
    )
    result = json.loads(result_json)

    # Assertions
    self.assertFalse(result["found"])
    self.assertEqual(result["log"]["original_test_output"]["return_code"], 0)
    self.assertEqual(result["log"]["original_test_output"]["stdout"], "result: 42")
    self.assertEqual(result["log"]["transformed_test_output"]["return_code"], 0)
    self.assertEqual(result["thoughts"], "test thoughts")
    self.assertEqual(result["test_index"], 1)
    self.assertEqual(result["covered_strategies"], ["strategy1"])

    mock_transform.assert_called_once_with(orig_ir, args, self.tool.build_dir)
    self.assertEqual(mock_subprocess_run.call_count, 2)

  @patch("tools.difftest.transform")
  @patch("tools.difftest.subprocess.run")
  def test_difftest_mismatch(self, mock_subprocess_run, mock_transform):
    # Setup mocks
    mock_transform.return_value = "```llvm\n; transformed code\n```"

    # Mock subprocess.run to return different outputs
    process_1 = MagicMock()
    process_1.returncode = 0
    process_1.stdout = "result: 42"
    process_1.stderr = ""

    process_2 = MagicMock()
    process_2.returncode = 0
    process_2.stdout = "result: 99"
    process_2.stderr = ""

    mock_subprocess_run.side_effect = [process_1, process_2]

    orig_ir = "```llvm\n; original code\n```"
    args = "-S -passes=instcombine"
    call_instr = "call i32 @test(i32 1)"
    thoughts = "test thoughts"

    result_json = self.tool._call(
      action="test",
      orig_ir=orig_ir,
      args=args,
      call_instr=call_instr,
      thoughts=thoughts,
    )
    result = json.loads(result_json)

    # Assertions
    self.assertTrue(result["found"])
    self.assertEqual(result["log"]["original_test_output"]["stdout"], "result: 42")
    self.assertEqual(result["log"]["transformed_test_output"]["stdout"], "result: 99")
    self.assertEqual(result["thoughts"], "test thoughts")

  @patch("tools.difftest.transform")
  @patch("tools.difftest.subprocess.run")
  def test_difftest_timeout(self, mock_subprocess_run, mock_transform):
    # Setup mocks
    mock_transform.return_value = "```llvm\n; transformed code\n```"

    # Mock subprocess.run to raise TimeoutExpired
    # We simulate first call OK, second call Timeout
    process_1 = MagicMock()
    process_1.returncode = 0
    process_1.stdout = "result: 42"
    process_1.stderr = ""

    timeout_exception = subprocess.TimeoutExpired(
      cmd="cmd", timeout=10, output="partial", stderr="error"
    )
    # Note: output arg in TimeoutExpired constructor maps to stdout attribute in recent python versions,
    # but the class attribute is 'stdout'. Let's set attrs explicitly if needed or rely on constructor.
    # Python 3.10+ uses stdout/stderr args.
    timeout_exception.stdout = "partial"
    timeout_exception.stderr = "error"

    mock_subprocess_run.side_effect = [process_1, timeout_exception]

    orig_ir = "```llvm\n; original code\n```"
    args = "-S -passes=instcombine"
    call_instr = "call i32 @test(i32 1)"
    thoughts = "test thoughts"

    result_json = self.tool._call(
      orig_ir=orig_ir, args=args, call_instr=call_instr, thoughts=thoughts
    )
    result = json.loads(result_json)

    # Assertions
    self.assertTrue(result["found"])
    self.assertFalse(result["log"]["original_test_output"]["timed_out"])
    self.assertTrue(result["log"]["transformed_test_output"]["timed_out"])
    self.assertEqual(result["log"]["transformed_test_output"]["stdout"], "partial")
    self.assertEqual(result["thoughts"], "test thoughts")

  @patch("tools.difftest.transform")
  def test_invalid_call_instr(self, mock_transform):
    # Mock transform to return dummy IR so we test the call_instr validation logic
    mock_transform.return_value = "```llvm\n; transformed code\n```"

    orig_ir = "```llvm\n; original code\n```"
    args = "-S -passes=instcombine"
    call_instr = "call @test(i32 1)"
    thoughts = "test thoughts"

    with self.assertRaises(FuncToolCallException) as cm:
      self.tool._call(
        action="test",
        orig_ir=orig_ir,
        args=args,
        call_instr=call_instr,
        thoughts=thoughts,
      )
    self.assertIn("The provided call instruction is not valid", str(cm.exception))


if __name__ == "__main__":
  unittest.main()
