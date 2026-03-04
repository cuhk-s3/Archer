#!/usr/bin/env python3
"""
Batch extract PR data from LLVM GitHub repository.

This script fetches multiple PRs based on filters and extracts their information.
"""

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
import tqdm

sys.path.append(str(Path(__file__).parent.parent))

from llvm import llvm_helper

# Time range filter (hardcoded)
# PRs must be created within this date range
# Format: "YYYY-MM-DD" or None for no limit
PR_CREATED_AFTER = "2025-12-31"  # Only PRs created after this date
PR_CREATED_BEFORE = "2026-02-28"  # Only PRs created before this date (None = no limit)

github_token = os.environ["LAB_GITHUB_TOKEN"]
cache_dir = Path(os.path.dirname(__file__)) / "cache_prs"
pr_extract = os.path.join(os.path.dirname(__file__), "pr_extract.py")
session = requests.Session()
session.headers.update(
  {
    "X-GitHub-Api-Version": "2022-11-28",
    "Authorization": f"Bearer {github_token}",
    "Accept": "application/vnd.github+json",
  }
)


def wait(progress):
  """Wait when rate limit is exceeded"""
  try:
    rate_limit = session.get("https://api.github.com/rate_limit", timeout=10).json()
    if rate_limit["rate"]["remaining"] == 0:
      next_window = rate_limit["rate"]["reset"]
      while time.time() < next_window:
        progress.set_description(f"wait {int(next_window - time.time())}s")
        time.sleep(10)
  except Exception:
    time.sleep(60)


def fetch_pr(pr_id, state_filter="closed"):
  """Fetch and process a single PR

  Args:
    pr_id: PR ID to fetch
    state_filter: "open", "closed", or "all"
  """
  # Check if already processed (in either open or closed directory)
  data_json_paths = [
    os.path.join(llvm_helper.dataset_dir, "open", f"{pr_id}.json"),
    os.path.join(llvm_helper.dataset_dir, "closed", f"{pr_id}.json"),
  ]
  if any(os.path.exists(p) for p in data_json_paths):
    return False

  # Fetch PR metadata to check filters
  pr_url = f"https://api.github.com/repos/llvm/llvm-project/pulls/{pr_id}"
  pr = session.get(pr_url).json()

  if "message" in pr and pr["message"] == "Not Found":
    return False

  # Apply state filter
  if state_filter == "open" and pr["state"] != "open":
    return False
  elif state_filter == "closed" and pr["state"] != "closed":
    return False
  # If state_filter == "all", process both open and closed

  # Apply time range filter
  created_at = pr.get("created_at")
  if created_at:
    pr_date = datetime.fromisoformat(created_at.replace("Z", "+00:00"))

    if PR_CREATED_AFTER:
      after_date = datetime.fromisoformat(PR_CREATED_AFTER + "T00:00:00+00:00")
      if pr_date < after_date:
        return False

    if PR_CREATED_BEFORE:
      before_date = datetime.fromisoformat(PR_CREATED_BEFORE + "T23:59:59+00:00")
      if pr_date > before_date:
        return False

  # Check title: exclude PRs with "NFC" (No Functional Change)
  title = pr.get("title", "")
  if "NFC" in title:
    return False

  # Check labels: require llvm:transforms or llvm:analysis, exclude all backend:* labels
  labels = pr.get("labels", [])
  label_names = [label["name"] for label in labels]

  # Must have at least one of these labels
  has_required_label = any(
    label in label_names for label in ["llvm:transforms", "llvm:analysis"]
  )
  if not has_required_label:
    return False

  # Must not have any backend:* labels
  has_backend_label = any(label.startswith("backend:") for label in label_names)
  if has_backend_label:
    return False

  # Check if it modifies LLVM files
  files_url = pr["url"] + "/files"
  files = session.get(files_url).json()
  changed_files = [f["filename"] for f in files]

  # Filter for LLVM lib/include files
  llvm_files = [
    f for f in changed_files if f.startswith(("llvm/lib/", "llvm/include/"))
  ]

  if not llvm_files:
    return False  # No LLVM code changes

  # Check for unsupported file changes
  changed_files_str = "\n".join(changed_files)
  if "/AsmParser/" in changed_files_str or "/Bitcode/" in changed_files_str:
    return False

  # Call pr_extract.py to process the PR
  try:
    cmd = ["python3", pr_extract, str(pr_id)]
    # Always use --skip-closed-check to allow processing both open and closed PRs
    cmd.append("--skip-closed-check")

    out = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode()
    print(f"{pr_id}: {out}")
    return True
  except subprocess.CalledProcessError as e:
    print(f"{pr_id}: Error: {e.output.decode()}")
    return False


def main():
  import argparse

  parser = argparse.ArgumentParser(
    description="Batch extract PR data from LLVM GitHub repository"
  )
  parser.add_argument(
    "--pr-begin",
    type=int,
    default=1,
    help="Starting PR ID (default: 1)",
  )
  parser.add_argument(
    "--pr-end",
    type=int,
    required=True,
    help="Ending PR ID (required)",
  )
  parser.add_argument(
    "--state",
    type=str,
    default="closed",
    choices=["open", "closed", "all"],
    help="Filter PRs by state: 'open', 'closed', or 'all' (default: closed)",
  )
  args = parser.parse_args()

  pr_id_begin = args.pr_begin
  pr_id_end = args.pr_end
  state_filter = args.state

  os.makedirs(cache_dir, exist_ok=True)
  success = 0
  progress = tqdm.tqdm(range(pr_id_begin, pr_id_end + 1))

  for pr_id in progress:
    progress.set_description(f"Success {success}")
    cache_file = os.path.join(cache_dir, str(pr_id))

    if os.path.exists(cache_file):
      progress.refresh()
      continue

    while True:
      try:
        if fetch_pr(pr_id, state_filter):
          success += 1
        else:
          Path(cache_file).touch()
        break
      except KeyError as e:
        print(f"KeyError: {e}")
        wait(progress)
      except requests.exceptions.RequestException as e:
        print(f"RequestException: {e}")
        wait(progress)
      except ValueError as e:
        print(f"ValueError: {e}")
        wait(progress)
      except Exception as e:
        print(f"Exception: {type(e).__name__}: {e}")
        Path(cache_file).touch()
        break

  print(f"\nCompleted! Successfully processed {success} PRs.")


if __name__ == "__main__":
  main()
