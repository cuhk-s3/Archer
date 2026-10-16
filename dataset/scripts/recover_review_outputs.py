#!/usr/bin/env python3
"""Recover persisted review artifacts after a post-review export failure."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dataset import get_store
from utils.log import Bug, RunStats, generate_review
from veir.lab_env import PREnvironment


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("review_id", type=int)
  parser.add_argument("output_dir", type=Path)
  args = parser.parse_args()

  store = get_store()
  row = store.get_review(args.review_id)
  if row is None:
    raise SystemExit(f"review {args.review_id} not found")
  history = json.loads(row["history"] or "[]")

  existing = store.list_bugs_for_review(args.review_id)
  if not existing:
    for message in history:
      if message.get("type") != "function_call_output":
        continue
      try:
        result = json.loads(message.get("output", ""))
      except (TypeError, json.JSONDecodeError):
        continue
      if result.get("tool") != "verify" or not result.get("found"):
        continue
      bug_id = store.add_bug(
        int(row["pr_id"]), int(row["version_id"]), int(row["id"]),
        {
          "repro_kind": "verify",
          "original_ir": result.get("original_ir"),
          "transformed_ir": result.get("transformed_ir"),
          "args": result.get("args"),
          "call_instr": result,
          "log": result.get("log"),
          "thoughts": result.get("thoughts"),
        },
      )
      # The completed run checked this reproducer on the base commit and it
      # still triggered, so the finding is real but not patch-specific.
      store.set_bug_baseline(bug_id, True)

  args.output_dir.mkdir(parents=True, exist_ok=True)
  (args.output_dir / "history.json").write_text(
    json.dumps(history, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
  )
  stats = {key: row[key] for key in row.keys() if key != "history"}
  (args.output_dir / "stats.json").write_text(
    json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
  )
  pr_info = PREnvironment._pr_info_from_dict(
    store.to_pr_info(int(row["pr_id"]), int(row["version_id"]))
  )
  pr_info.components = pr_info.components or []
  run_stats = RunStats(command={})
  for key in (
    "error", "errmsg", "traceback", "input_tokens", "output_tokens",
    "cached_tokens", "total_tokens", "chat_cost", "chat_rounds",
    "phase1_round", "phase2_round", "total_time_sec", "reason_thou", "report",
  ):
    if key in row.keys():
      setattr(run_stats, key, row[key])
  run_stats.strategies = json.loads(row["strategies"] or "[]")
  for bug_row in store.list_bugs_for_review(args.review_id):
    run_stats.bugs.append(Bug(
      original_ir=bug_row["original_ir"] or "",
      transformed_ir=bug_row["transformed_ir"] or "",
      log=bug_row["log"] or "",
      thoughts=bug_row["thoughts"],
      repro_kind=bug_row["repro_kind"],
      args=bug_row["args"],
      baseline_checked=bool(bug_row["baseline_checked"]),
      baseline_triggered=(
        bool(bug_row["baseline_triggered"])
        if bug_row["baseline_triggered"] is not None else None
      ),
      non_patch_specific=bool(bug_row["non_patch_specific"]),
    ))
  review = generate_review(
    pr_info, run_stats,
    {"version_id": int(row["version_id"])},
  )
  (args.output_dir / "review.md").write_text(review, encoding="utf-8")


if __name__ == "__main__":
  main()
