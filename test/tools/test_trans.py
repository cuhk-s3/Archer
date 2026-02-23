import subprocess
import unittest
from unittest.mock import patch

from lms.tool import FuncToolCallException
from tools.trans import TransTool


class TestTransTool(unittest.TestCase):
  def setUp(self):
    self.build_dir = "/tmp/build"
    self.tool = TransTool(self.build_dir)

  @patch("tools.trans.Path.is_file")
  @patch("tools.trans.cmdline.check_output")
  def test_transform_success(self, mock_check_output, mock_is_file):
    # Setup mocks
    mock_is_file.return_value = True
    mock_check_output.return_value = b"; transformed code"

    orig_ir = "```llvm\n; original code\n```"
    args = "-S -passes=instcombine"

    result = self.tool._call(orig_ir=orig_ir, args=args)

    # Assertions
    self.assertEqual(result, "```llvm\n; transformed code\n```")
    mock_check_output.assert_called_once()
    self.assertTrue(
      mock_check_output.call_args[0][0].startswith(f"/tmp/build/bin/opt {args}")
    )

  def test_transform_invalid_ir_format(self):
    orig_ir = "; original code without markdown fences"
    args = "-S -passes=instcombine"

    with self.assertRaises(FuncToolCallException) as cm:
      self.tool._call(orig_ir=orig_ir, args=args)
    self.assertIn(
      "orig_ir must be a self-contained LLVM IR code wrapped with ```llvm and ```",
      str(cm.exception),
    )

  @patch("tools.trans.Path.is_file")
  def test_transform_opt_not_found(self, mock_is_file):
    mock_is_file.return_value = False
    orig_ir = "```llvm\n; original code\n```"
    args = "-S -passes=instcombine"

    with self.assertRaises(FuncToolCallException) as cm:
      self.tool._call(orig_ir=orig_ir, args=args)
    self.assertIn("opt tool not found", str(cm.exception))

  @patch("tools.trans.Path.is_file")
  @patch("tools.trans.cmdline.check_output")
  def test_transform_subprocess_error(self, mock_check_output, mock_is_file):
    mock_is_file.return_value = True

    # Mock subprocess error
    error = subprocess.CalledProcessError(1, "cmd", stderr=b"opt error message")
    mock_check_output.side_effect = error

    orig_ir = "```llvm\n; original code\n```"
    args = "-S -passes=instcombine"

    with self.assertRaises(FuncToolCallException) as cm:
      self.tool._call(orig_ir=orig_ir, args=args)
    self.assertIn(
      "Failed to transform the LLVM IR code. opt error message", str(cm.exception)
    )


if __name__ == "__main__":
  unittest.main()
