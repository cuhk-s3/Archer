import unittest
from unittest.mock import patch, mock_open
import json
import subprocess
from tools.verify import VerifyTool
from lms.tool import FuncToolCallException


class TestVerifyTool(unittest.TestCase):
    def setUp(self):
        self.build_dir = "/tmp/build"
        self.alive_path = "/tmp/alive-tv"
        self.tool = VerifyTool(self.build_dir, self.alive_path)

    @patch("tools.verify.Path.is_file")
    @patch("tools.verify.cmdline.check_output")
    @patch("builtins.open", new_callable=mock_open, read_data="; transformed code")
    def test_verify_success_no_bugs(self, mock_file, mock_check_output, mock_is_file):
        # Setup mocks
        mock_is_file.return_value = True

        # Mock subprocess.run to return successful execution
        # First call is opt, second call is alive-tv
        mock_check_output.side_effect = [
            b"",  # opt output
            b"0 incorrect transformations",  # alive-tv output
        ]

        orig_ir = "```llvm\n; original code\n```"
        args = "-passes=instcombine"
        thoughts = "test thoughts"

        result_json = self.tool._call(orig_ir=orig_ir, args=args, thoughts=thoughts)
        result = json.loads(result_json)

        # Assertions
        self.assertFalse(result["found"])
        self.assertEqual(result["tool"], "verify")
        self.assertEqual(result["original_ir"], "; original code")
        self.assertEqual(result["transformed_ir"], "; transformed code")
        self.assertEqual(result["log"], "0 incorrect transformations")
        self.assertEqual(result["thoughts"], "test thoughts")

        self.assertEqual(mock_check_output.call_count, 2)

    @patch("tools.verify.Path.is_file")
    @patch("tools.verify.cmdline.check_output")
    @patch("builtins.open", new_callable=mock_open, read_data="; transformed code")
    def test_verify_success_with_bugs(self, mock_file, mock_check_output, mock_is_file):
        # Setup mocks
        mock_is_file.return_value = True

        # Mock subprocess.run to return successful execution
        # First call is opt, second call is alive-tv
        mock_check_output.side_effect = [
            b"",  # opt output
            b"1 incorrect transformations",  # alive-tv output
        ]

        orig_ir = "```llvm\n; original code\n```"
        args = "-passes=instcombine"
        thoughts = "test thoughts"

        result_json = self.tool._call(orig_ir=orig_ir, args=args, thoughts=thoughts)
        result = json.loads(result_json)

        # Assertions
        self.assertTrue(result["found"])
        self.assertEqual(result["tool"], "verify")
        self.assertEqual(result["original_ir"], "; original code")
        self.assertEqual(result["transformed_ir"], "; transformed code")
        self.assertEqual(result["log"], "1 incorrect transformations")
        self.assertEqual(result["thoughts"], "test thoughts")

        self.assertEqual(mock_check_output.call_count, 2)

    def test_verify_invalid_ir_format(self):
        orig_ir = "; original code without markdown fences"
        args = "-passes=instcombine"
        thoughts = "test thoughts"

        with self.assertRaises(FuncToolCallException) as cm:
            self.tool._call(orig_ir=orig_ir, args=args, thoughts=thoughts)
        self.assertIn(
            "orig_ir must be a self-contained LLVM IR code wrapped with ```llvm and ```",
            str(cm.exception),
        )

    @patch("tools.verify.Path.is_file")
    def test_verify_opt_not_found(self, mock_is_file):
        # Mock opt not found
        mock_is_file.side_effect = lambda: False if "opt" in str(self) else True

        orig_ir = "```llvm\n; original code\n```"
        args = "-passes=instcombine"
        thoughts = "test thoughts"

        with self.assertRaises(FuncToolCallException) as cm:
            self.tool._call(orig_ir=orig_ir, args=args, thoughts=thoughts)
        self.assertIn("opt tool not found", str(cm.exception))

    @patch("tools.verify.Path.is_file")
    def test_verify_alive_tv_not_found(self, mock_is_file):
        # Mock alive-tv not found
        def mock_is_file_side_effect():
            import inspect

            caller_frame = inspect.currentframe().f_back
            # A bit hacky, but we can just mock the first call (opt) to True and second (alive-tv) to False
            pass

        mock_is_file.side_effect = [True, False]

        orig_ir = "```llvm\n; original code\n```"
        args = "-passes=instcombine"
        thoughts = "test thoughts"

        with self.assertRaises(FuncToolCallException) as cm:
            self.tool._call(orig_ir=orig_ir, args=args, thoughts=thoughts)
        self.assertIn("alive-tv tool not found", str(cm.exception))

    @patch("tools.verify.Path.is_file")
    @patch("tools.verify.cmdline.check_output")
    @patch("builtins.open", new_callable=mock_open)
    def test_verify_opt_subprocess_error(
        self, mock_file, mock_check_output, mock_is_file
    ):
        mock_is_file.return_value = True

        # Mock subprocess error for opt
        error = subprocess.CalledProcessError(1, "cmd", stderr=b"opt error message")
        mock_check_output.side_effect = error

        orig_ir = "```llvm\n; original code\n```"
        args = "-passes=instcombine"
        thoughts = "test thoughts"

        with self.assertRaises(FuncToolCallException) as cm:
            self.tool._call(orig_ir=orig_ir, args=args, thoughts=thoughts)
        self.assertIn(
            "Failed to transform the LLVM IR code with opt. opt error message",
            str(cm.exception),
        )

    @patch("tools.verify.Path.is_file")
    @patch("tools.verify.cmdline.check_output")
    @patch("builtins.open", new_callable=mock_open, read_data="; transformed code")
    def test_verify_alive_tv_subprocess_error(
        self, mock_file, mock_check_output, mock_is_file
    ):
        mock_is_file.return_value = True

        # Mock subprocess error for alive-tv
        error = subprocess.CalledProcessError(
            1, "cmd", stderr=b"alive-tv error message"
        )
        mock_check_output.side_effect = [b"", error]

        orig_ir = "```llvm\n; original code\n```"
        args = "-passes=instcombine"
        thoughts = "test thoughts"

        with self.assertRaises(FuncToolCallException) as cm:
            self.tool._call(orig_ir=orig_ir, args=args, thoughts=thoughts)
        self.assertIn(
            "Failed to verify the LLVM IR code transformation. alive-tv error message",
            str(cm.exception),
        )


if __name__ == "__main__":
    unittest.main()
