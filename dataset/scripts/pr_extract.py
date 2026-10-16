#!/usr/bin/env python3
"""
Extract and process PR data from the opencompl/veir GitHub repository.

This script fetches PR information, extracts patches, tests, and patch location information,
and saves them to the dataset directory.
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

import requests
from unidiff import PatchSet

sys.path.append(str(Path(__file__).parent.parent))
# Project root, so the ``dataset`` package (the SQLite-backed source of truth)
# is importable.
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from veir import helper as veir_helper
from dataset import get_store

github_token = os.environ.get("LAB_GITHUB_TOKEN")
if not github_token:
  print("Error: The environment variable LAB_GITHUB_TOKEN is not set.")
  exit(1)

session = requests.Session()
session.headers.update(
  {
    "X-GitHub-Api-Version": "2022-11-28",
    "Authorization": f"Bearer {github_token}",
    "Accept": "application/vnd.github+json",
  }
)


def get_line_locations(patched_file):
  locations = []
  for hunk in patched_file:
    source_lines = [line.source_line_no for line in hunk.source_lines()]
    if source_lines:
      locations.append([min(source_lines), max(source_lines)])
  return locations

def filter_patch_exclude_tests(full_patch: str) -> str:
  """Filter out test file changes from a patch, keeping only code changes"""
  try:
    patchset = PatchSet(full_patch)
  except Exception as e:
    print(f"Warning: Failed to parse patch for filtering: {e}")
    return full_patch  # Return original if parsing fails

  # Keep files that are NOT test files
  filtered_files = [f for f in patchset if not f.path.startswith(("Test/", "UnitTest/"))]

  if not filtered_files:
    return ""  # Return empty if all files are tests

  # Reconstruct patch from filtered files
  result = ""
  for file in filtered_files:
    result += str(file)
  return result


def extract_tests_from_patch(full_patch: str) -> list:
  """Extract tests from patch after it has been applied

  This should be called AFTER the patch has been applied to the repo.
  At that point, HEAD contains the patch and we can read the test files.
  """
  tests = []

  # Parse only test files from the patch
  try:
    patchset = PatchSet(full_patch)
  except Exception as e:
    print(f"Warning: Failed to parse patch: {e}")
    return tests

  runline_pattern = re.compile(r"// RUN:\s*(.+)", re.IGNORECASE)
  veir_dir = veir_helper.veir_dir

  for file in patchset:
    # Only process test files
    if not file.path.startswith(("Test/", "UnitTest/")):
      continue

    # Skip removed files (they don't exist after applying patch)
    if file.is_removed_file:
      continue

    # Read file from working directory (patch has been applied)
    test_file_path = os.path.join(veir_dir, file.path)
    try:
      with open(test_file_path, "r") as f:
        test_file = f.read()
    except Exception as e:
      print(f"Warning: Could not read {file.path}: {e}")
      continue

    # Extract RUN commands
    commands = []
    for match in re.findall(runline_pattern, test_file):
      commands.append(match.strip())

    def is_source(line: str):
      stripped = line.strip()
      return not stripped.startswith(("// RUN:", "// CHECK", "// NOTE"))

    body = "\n".join(filter(is_source, test_file.splitlines())).strip()
    if body:
      tests.append({"file": file.path, "commands": commands,
        "tests": [{"test_name": file.path, "test_body": body}]})

  return tests


def main():
  parser = argparse.ArgumentParser(
    description="Extract and process VeIR PR data from GitHub."
  )
  parser.add_argument("pr_id", type=int, help="The PR ID to process.")
  parser.add_argument(
    "-f", "--force", action="store_true", help="Force override existing data."
  )
  parser.add_argument(
    "--skip-closed-check",
    action="store_true",
    help="Deprecated no-op: open/closed no longer gates extraction (kept for compat).",
  )
  args = parser.parse_args()

  pr_id = args.pr_id
  force = args.force

  if force:
    print("Force override enabled")

  # Determine output directory based on PR state (will be determined after fetching)
  pr_url = f"https://api.github.com/repos/opencompl/veir/pulls/{pr_id}"
  print(f"Fetching {pr_url}")
  pr = session.get(pr_url).json()

  if "message" in pr and pr["message"] == "Not Found":
    print(f"Error: PR #{pr_id} not found")
    exit(1)

  # PR state is kept only as metadata now; open/closed no longer decides where
  # data is stored nor whether we process it. The commit SHA is the identity.
  pr_state = pr["state"]

  # The head commit identifies this version. Dedup on ``(pr_id, fix_commit)``.
  fix_commit = pr["head"]["sha"]

  store = get_store()
  if not force and store.has_version(pr_id, fix_commit):
    print(
      f"Item PR #{pr_id} @ {fix_commit[:10]} already exists in DB (--force not set)."
    )
    exit(1)

  # Fetch the patch
  patch_response = session.get(
    f"https://api.github.com/repos/opencompl/veir/pulls/{pr_id}",
    headers={"Accept": "application/vnd.github.v3.diff"},
  )
  patch = patch_response.text

  # Get files changed
  files_url = pr["url"] + "/files"
  files = session.get(files_url).json()
  changed_files = [f["filename"] for f in files]

  # Check for invalid file changes
  changed_files_str = "\n".join(changed_files)
  if "/AsmParser/" in changed_files_str or "/Bitcode/" in changed_files_str:
    print("This PR contains changes to AsmParser or Bitcode which are not supported")
    exit(1)

  components = veir_helper.infer_related_components(changed_files)

  if not components:
    print("This PR does not modify a supported VeIR source directory")
    exit(1)

  # Get commit information (fix_commit was already read above for dedup).
  base_commit = pr["base"]["sha"]

  print(f"Base commit: {base_commit}")
  print(f"Head commit: {fix_commit}")
  print(f"Components: {components}")

  # Extract full PR context including comments
  pr_comments = []
  comments = session.get(pr["comments_url"]).json()
  for comment in comments:
    comment_obj = {
      "author": comment["user"]["login"],
      "body": comment["body"],
    }
    if comment_obj["author"] not in {"github-actions", "dependabot[bot]"}:
      pr_comments.append(comment_obj)

  # Extract labels
  labels = [label["name"] for label in pr.get("labels", [])]

  # Extract knowledge cutoff (PR creation time)
  knowledge_cutoff = pr["created_at"]

  # Extract PR URL
  pr_url = pr["html_url"]

  # Checkout base commit and apply patch
  print("Checking out base commit...")
  try:
    veir_helper.reset(base_commit)
  except Exception as e:
    print(f"Warning: Failed to reset HEAD to {base_commit}: {e}")
    print("Syncing repository and trying again...")
    veir_helper.reset("main")
    veir_helper.git_execute(["pull", "origin", "main"])
    try:
      veir_helper.reset(base_commit)
    except Exception as e:
      print(f"Error: Failed to reset HEAD to {base_commit}: {e}")
      exit(1)

  # Apply the patch
  print("Applying patch...")
  success, log = veir_helper.apply(patch)
  if not success:
    print(f"Error: Failed to apply patch: {log}")
    veir_helper.reset("main")
    exit(1)

  # Extract patch location information (line numbers and function names)
  # Line level location
  patch_location_lineno = {}
  try:
    patchset = PatchSet(patch)
    for file in patchset:
      # Skip removed files and added files (no meaningful location in base commit)
      if file.is_removed_file or file.is_added_file:
        continue
      location = get_line_locations(file)
      if len(location) != 0:
        patch_location_lineno[file.path] = location
  except Exception as e:
    print(f"Warning: Failed to extract line locations: {e}")

  # Lean declarations are recovered by the review agent from line-level context.
  patch_location_funcname = {}

  # Extract tests from the applied patch
  print("Extracting tests from patch...")
  tests = extract_tests_from_patch(patch)
  print(f"Extracted {len(tests)} test file(s)")

  # Check if tests are empty - skip PRs without tests
  if not tests or len(tests) == 0:
    print("No tests found in this PR. Skipping.")
    veir_helper.reset("main")
    exit(1)

  # Filter out test files from patch
  code_only_patch = filter_patch_exclude_tests(patch)

  # Reset repository
  print("Resetting repository...")
  veir_helper.reset("main")

  # Save PR information
  pr_info = {
    "pr_id": pr_id,
    "pr_url": pr_url,
    "state": pr_state,
    "title": pr["title"],
    "author": pr["user"]["login"],
    "base_commit": base_commit,
    "fix_commit": fix_commit,
    "patch": code_only_patch,
    "components": sorted(components),
    "description": pr.get("body", "") or "",
    "tests": tests,
    "labels": labels,
    "comments": pr_comments,
    "knowledge_cutoff": knowledge_cutoff,
    "patch_location_lineno": patch_location_lineno,
    "patch_location_funcname": patch_location_funcname,
  }

  if force:
    version_id = store.replace_pr_version(pr_info)
    print(
      f"Force-updated PR #{pr_id} @ {fix_commit[:10]} in DB (version_id={version_id})."
    )
    return

  version_id, created = store.upsert_pr_version(pr_info)
  if created:
    print(
      f"Successfully saved PR #{pr_id} @ {fix_commit[:10]} to DB "
      f"(version_id={version_id})."
    )
  else:
    print(
      f"PR #{pr_id} @ {fix_commit[:10]} already present in DB "
      f"(version_id={version_id}); no changes."
    )


if __name__ == "__main__":
  main()
