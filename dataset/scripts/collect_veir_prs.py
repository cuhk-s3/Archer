#!/usr/bin/env python3
"""Backfill the review dataset from merged VeIR PRs in local git history."""

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dataset import get_store
from veir.helper import veir_dir


def merged_pr_ids(limit: int):
  log = subprocess.check_output(
    ["git", "-C", veir_dir, "log", "--first-parent", "--format=%s", f"-n{limit}"],
    text=True,
  )
  seen = set()
  for subject in log.splitlines():
    match = re.search(r"\(#(\d+)\)\s*$", subject)
    if match and int(match.group(1)) not in seen:
      pr_id = int(match.group(1))
      seen.add(pr_id)
      yield pr_id, subject


def main():
  parser = argparse.ArgumentParser(description="Collect merged opencompl/veir PRs")
  parser.add_argument("--history", type=int, default=500)
  parser.add_argument("--max-prs", type=int, default=100)
  parser.add_argument("--dry-run", action="store_true")
  args = parser.parse_args()

  store = get_store()
  extractor = Path(__file__).with_name("pr_extract.py")
  selected = []
  for pr_id, subject in merged_pr_ids(args.history):
    if store.get_latest_version(pr_id) is None:
      selected.append((pr_id, subject))
    if len(selected) >= args.max_prs:
      break

  for pr_id, subject in selected:
    print(f"PR #{pr_id}: {subject}")
    if not args.dry_run:
      proc = subprocess.run([sys.executable, str(extractor), str(pr_id), "--skip-closed-check"])
      if proc.returncode:
        print(f"warning: PR #{pr_id} was skipped", file=sys.stderr)


if __name__ == "__main__":
  main()
