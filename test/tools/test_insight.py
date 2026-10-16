import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dataset.store import ArcherStore
from lms.tool import FuncToolCallException
from tools.insight import InsightTool


class InsightToolTest(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.root = Path(self.tmp.name)
    self.knowledge_patch = patch(
      "dataset.store.KNOWLEDGE_FILE", self.root / "insights.jsonl"
    )
    self.knowledge_patch.start()
    self.store = ArcherStore(self.root / "test.db")
    self.evidence = {}
    self.tool = InsightTool(
      self.store, ["InstCombine"], 280, None, None, "deadbeef",
      lambda name: self.evidence.get(name),
    )

  def tearDown(self):
    self.store.close()
    self.knowledge_patch.stop()
    self.tmp.cleanup()

  def test_unverified_record_is_searchable_but_not_exported(self):
    result = json.loads(self.tool.call(
      action="record", topic="integer constants", content="Check narrow widths",
      kind="hypothesis",
    ))
    self.assertEqual(result["status"], "unverified")
    self.assertEqual(json.loads(self.tool.call(
      action="search", query="narrow"))["count"], 1)
    self.assertFalse((self.root / "insights.jsonl").exists())

  def test_verified_requires_evidence_and_exports(self):
    with self.assertRaisesRegex(FuncToolCallException, "no verify result"):
      self.tool.call(action="record", topic="poison",
        content="Poison is preserved", verification="verified",
        source_tool="verify")
    self.evidence["verify"] = {"tool": "verify", "found": False, "log": "same"}
    result = json.loads(self.tool.call(
      action="record", topic="poison", content="Poison is preserved",
      kind="observation", verification="verified", source_tool="verify",
    ))
    self.assertEqual(result["status"], "verified")
    self.assertEqual(self.store.search_insights(
      verified_only=True)[0]["evidence_tool"], "verify")
    record = json.loads((self.root / "insights.jsonl").read_text().strip())
    self.assertEqual(record["topic"], "poison")

  def test_regression_requires_found_evidence(self):
    self.evidence["rwenum"] = {"tool": "rwenum", "found": False}
    with self.assertRaisesRegex(FuncToolCallException, "found=true"):
      self.tool.call(action="record", topic="flags", content="Flag mismatch",
        kind="regression", verification="verified", source_tool="rwenum")

  def test_dedup_upgrade_and_component_filtering(self):
    args = dict(action="record", topic="width",
      content="Narrow constants truncate", kind="observation")
    first = json.loads(self.tool.call(**args))["id"]
    self.evidence["difftest"] = {"tool": "difftest", "found": True}
    second = json.loads(self.tool.call(
      **args, verification="verified", source_tool="difftest"))["id"]
    self.assertEqual(first, second)
    self.assertEqual(self.store.search_insights(components=["Other"]), [])
    self.assertTrue(self.store.search_insights(
      components=["InstCombine"], verified_only=True)[0]["verified"])


if __name__ == "__main__":
  unittest.main()
