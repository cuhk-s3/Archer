#!/usr/bin/env python3
"""
This script generates a table of bug summary for the paper.
"""

import json
from pathlib import Path

review_stats = json.load(
  (Path(__file__).parent / "review_stats.json").open("r", encoding="utf-8")
)


def gen_table_bug_symptom():
  open_items = list(review_stats.get("open", {}).values())
  closed_items = list(review_stats.get("closed", {}).values())

  crash_open = sum(1 for item in open_items if item.get("type") == "crash")
  crash_closed = sum(1 for item in closed_items if item.get("type") == "crash")
  mis_open = sum(1 for item in open_items if item.get("type") == "miscompilation")
  mis_closed = sum(1 for item in closed_items if item.get("type") == "miscompilation")

  table_str = """
    Symptom & Open & Closed & Total

    Crash & crash_open & crash_closed & crash_total

    Miscompilation & mis_open & mis_closed & miscompilation_total

    """

  table_str = table_str.replace("crash_open", str(crash_open))
  table_str = table_str.replace("crash_closed", str(crash_closed))
  table_str = table_str.replace("crash_total", str(crash_open + crash_closed))
  table_str = table_str.replace("mis_open", str(mis_open))
  table_str = table_str.replace("mis_closed", str(mis_closed))
  table_str = table_str.replace("miscompilation_total", str(mis_open + mis_closed))

  print("Symptoms of bugs:")
  print(table_str)


if __name__ == "__main__":
  gen_table_bug_symptom()
