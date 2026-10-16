import json
import os
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

from lms.tool import FuncToolCallException
from tools.rwenum import RwenumTool


class RwenumToolTest(unittest.TestCase):
  def test_reports_missing_capabilities(self):
    with TemporaryDirectory() as tmp, patch.dict(os.environ, {
      "PATH": "", "ARCHER_LLRWT": "", "ARCHER_RWT_VALIDATOR": "",
    }, clear=False):
      result = json.loads(RwenumTool(tmp).call(
        rewrite="x * 2 => x + x", thoughts="blind enumeration", limit=10,
      ))
    self.assertFalse(result["found"])
    self.assertEqual(result["status"], "unavailable")
    self.assertEqual(result["missing_capabilities"], ["llrwt", "validator"])

  def test_rejects_unbounded_requests(self):
    with TemporaryDirectory() as tmp:
      tool = RwenumTool(tmp)
      with self.assertRaises(FuncToolCallException):
        tool.call(rewrite="x + 0 => x", thoughts="too wide", max_width=17)
      with self.assertRaises(FuncToolCallException):
        tool.call(rewrite="x + 0 => x", thoughts="too many", limit=1001)

  def test_runs_bounded_engine_with_explicit_capabilities(self):
    with TemporaryDirectory() as tmp:
      root = os.path.abspath(tmp)
      llrwt = os.path.join(root, "llrwt")
      validator = os.path.join(root, "validator")
      with open(llrwt, "w", encoding="utf-8") as out:
        out.write('#!/bin/sh\ncat "$1"\n')
      with open(validator, "w", encoding="utf-8") as out:
        out.write(
          "#!/bin/sh\nprintf 'Summary:\\n"
          "  1 correct transformation\\n"
          "  0 incorrect transformations\\n"
          "  0 failed-to-prove transformations\\n"
          "  0 Alive2 errors\\n'\n"
        )
      os.chmod(llrwt, 0o755)
      os.chmod(validator, 0o755)
      with patch.dict(os.environ, {
        "ARCHER_LLRWT": llrwt,
        "ARCHER_RWT_VALIDATOR": validator,
      }):
        result = json.loads(RwenumTool(root).call(
          rewrite="x + 0 => x", thoughts="smoke", max_width=1,
          additional_widths="", limit=1,
        ))
    self.assertFalse(result["found"])
    self.assertEqual(result["status"], "limited")
    self.assertEqual(result["completed_cases"], 1)


if __name__ == "__main__":
  unittest.main()
