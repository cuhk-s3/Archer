#!/usr/bin/env python3
"""Backfill the Archer SQLite store from the legacy JSON dataset.

The old extraction layout stored one file per PR under
``dataset/{open,closed}/{pr_id}.json``. This script imports each of those files
into the DB as a PR + a commit version (deduped on ``(pr_id, fix_commit)``), so
the DB becomes the single source of truth without re-fetching from GitHub.

Usage::

    python3 dataset/scripts/migrate_json_to_db.py               # migrate open+closed
    python3 dataset/scripts/migrate_json_to_db.py --dry-run      # report only
    python3 dataset/scripts/migrate_json_to_db.py --dataset-dir /path/to/dataset
    python3 dataset/scripts/migrate_json_to_db.py --db /path/to/archer.db
"""

import argparse
import json
import sys
from pathlib import Path

# Project root so ``store`` is importable.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

from store import ArcherStore, default_db_path  # noqa: E402

# Keys that map onto a PR version in the store.
_KNOWN_KEYS = {
  "pr_id",
  "pr_url",
  "state",
  "title",
  "author",
  "base_commit",
  "fix_commit",
  "patch",
  "components",
  "description",
  "tests",
  "labels",
  "comments",
  "knowledge_cutoff",
  "patch_location_lineno",
  "patch_location_funcname",
}


def _iter_json_files(dataset_dir: Path, subdirs):
  for sub in subdirs:
    d = dataset_dir / sub
    if not d.is_dir():
      continue
    for path in sorted(d.glob("*.json")):
      yield path


def migrate(dataset_dir: Path, db_path: Path, subdirs, dry_run: bool) -> None:
  store = None if dry_run else ArcherStore(db_path)

  created = 0
  skipped = 0
  failed = 0
  total = 0

  for path in _iter_json_files(dataset_dir, subdirs):
    total += 1
    try:
      with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    except Exception as e:
      print(f"[FAIL] {path}: cannot read/parse ({e})")
      failed += 1
      continue

    pr_id = data.get("pr_id")
    fix_commit = data.get("fix_commit")
    if pr_id is None or not fix_commit:
      print(f"[FAIL] {path}: missing pr_id/fix_commit")
      failed += 1
      continue

    pr = {k: v for k, v in data.items() if k in _KNOWN_KEYS}

    if dry_run:
      print(f"[DRY ] would import PR #{pr_id} @ {str(fix_commit)[:10]} ({path.name})")
      continue

    try:
      version_id, was_created = store.upsert_pr_version(pr)
      if was_created:
        created += 1
        print(f"[NEW ] PR #{pr_id} @ {str(fix_commit)[:10]} -> version {version_id}")
      else:
        skipped += 1
        print(f"[SKIP] PR #{pr_id} @ {str(fix_commit)[:10]} already present")
    except Exception as e:
      failed += 1
      print(f"[FAIL] {path}: {type(e).__name__}: {e}")

  print(
    f"\nDone. scanned={total} created={created} skipped={skipped} failed={failed}"
    + (" (dry-run)" if dry_run else f" db={db_path}")
  )


def main():
  parser = argparse.ArgumentParser(
    description="Backfill the Archer SQLite store from legacy JSON dataset files."
  )
  parser.add_argument(
    "--dataset-dir",
    type=str,
    default=str(PROJECT_ROOT / "dataset"),
    help="Path to the dataset directory (default: <root>/dataset).",
  )
  parser.add_argument(
    "--db",
    type=str,
    default=None,
    help="Path to the target SQLite DB (default: store.default_db_path()).",
  )
  parser.add_argument(
    "--subdirs",
    type=str,
    default="open,closed",
    help="Comma-separated subdirectories to scan (default: open,closed).",
  )
  parser.add_argument(
    "--dry-run",
    action="store_true",
    help="Report what would be imported without writing to the DB.",
  )
  args = parser.parse_args()

  dataset_dir = Path(args.dataset_dir)
  db_path = Path(args.db) if args.db else default_db_path()
  subdirs = [s.strip() for s in args.subdirs.split(",") if s.strip()]

  print(f"Dataset dir: {dataset_dir}")
  print(f"Target DB:   {db_path}")
  print(f"Subdirs:     {subdirs}\n")

  migrate(dataset_dir, db_path, subdirs, args.dry_run)


if __name__ == "__main__":
  main()
