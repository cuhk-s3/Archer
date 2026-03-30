#!/usr/bin/env python3
"""
This script generates a table of bug summary for the paper.
"""

import json
from pathlib import Path

review_stats = json.load(
  (Path(__file__).parent / "review_stats.json").open("r", encoding="utf-8")
)


def _count_status(items: list[dict]) -> tuple[int, int, int]:
  reported = 0
  confirmed = 0
  fixed = 0
  for item in items:
    status = item.get("status", "")
    if status == "unconfirmed":
      reported += 1
    elif status == "confirmed":
      confirmed += 1
    elif status == "fixed":
      fixed += 1
  return reported, confirmed, fixed


def gen_table_bug_report():
  open_items = list(review_stats.get("open", {}).values())
  closed_items = list(review_stats.get("closed", {}).values())

  reported_open, confirmed_open, fixed_open = _count_status(open_items)
  reported_closed, confirmed_closed, fixed_closed = _count_status(closed_items)
  total_open = len(open_items)
  total_closed = len(closed_items)

  table_str = """
    Status & Open & Closed & Total

    Reported & reported_open & reported_closed & reported_total

    Confirmed & confirmed_open & confirmed_closed & confirmed_total

    Fixed & fixed_open & fixed_closed & fixed_total

    Total & total_open & total_closed & total_all
    """

  table_str = table_str.replace("reported_open", str(reported_open))
  table_str = table_str.replace("reported_closed", str(reported_closed))
  table_str = table_str.replace("reported_total", str(reported_open + reported_closed))
  table_str = table_str.replace("confirmed_open", str(confirmed_open))
  table_str = table_str.replace("confirmed_closed", str(confirmed_closed))
  table_str = table_str.replace(
    "confirmed_total", str(confirmed_open + confirmed_closed)
  )
  table_str = table_str.replace("fixed_open", str(fixed_open))
  table_str = table_str.replace("fixed_closed", str(fixed_closed))
  table_str = table_str.replace("fixed_total", str(fixed_open + fixed_closed))
  table_str = table_str.replace("total_open", str(total_open))
  table_str = table_str.replace("total_closed", str(total_closed))
  table_str = table_str.replace("total_all", str(total_open + total_closed))

  print("Statistics of bug reports:")
  print(table_str)


if __name__ == "__main__":
  gen_table_bug_report()
