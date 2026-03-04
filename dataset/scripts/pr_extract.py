#!/usr/bin/env python3
"""
Extract and process PR data from LLVM GitHub repository.

This script fetches PR information, extracts patches, tests, and patch location information,
and saves them to the dataset directory.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import requests
from unidiff import PatchSet

sys.path.append(str(Path(__file__).parent.parent))

import hints

import llvm.llvm_helper as llvm_helper

if os.environ.get("LLVM_AUTOREVIEW_HOME_DIR") is None:
  print("Error: The llvm-autoreview environment has not been brought up.")
  exit(1)

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

# Check llvm-extract availability
subprocess.check_output(["llvm-extract", "--version"])


def filter_patch_exclude_tests(full_patch: str) -> str:
  """Filter out test file changes from a patch, keeping only code changes"""
  try:
    patchset = PatchSet(full_patch)
  except Exception as e:
    print(f"Warning: Failed to parse patch for filtering: {e}")
    return full_patch  # Return original if parsing fails

  # Keep files that are NOT test files
  filtered_files = [f for f in patchset if not f.path.startswith("llvm/test/")]

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

  runline_pattern = re.compile(r"; RUN: (.+)\| FileCheck")
  testname_pattern = re.compile(r"define .+ @([.\w]+)\(")

  llvm_dir = os.environ["LAB_LLVM_DIR"]

  for file in patchset:
    # Only process test files
    if not file.path.startswith("llvm/test/"):
      continue

    # Read file from working directory (patch has been applied)
    test_file_path = os.path.join(llvm_dir, file.path)
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

    # Determine which test functions to extract
    test_names = set()

    if file.is_added_file:
      # For newly added files, extract all function definitions
      for match in re.findall(testname_pattern, test_file):
        test_names.add(match.strip())
    else:
      # For modified files, extract only the test functions that were modified
      for hunk in file:
        matched = re.search(testname_pattern, hunk.section_header)
        if matched:
          test_names.add(matched.group(1))
        for line in hunk.target:
          for match in re.findall(testname_pattern, line):
            test_names.add(match.strip())

    # Extract each test function using llvm-extract
    subtests = []
    if test_names:
      for test_name in test_names:
        try:
          test_body = subprocess.check_output(
            ["llvm-extract", f"--func={test_name}", "-S", "-"],
            input=test_file.encode(),
          ).decode()
          test_body = test_body.removeprefix(
            "; ModuleID = '<stdin>'\nsource_filename = \"<stdin>\"\n"
          ).removeprefix("\n")
          subtests.append(
            {
              "test_name": test_name,
              "test_body": test_body,
            }
          )
        except Exception:
          # llvm-extract may fail for some functions, skip them
          pass

    # If no functions were found or extracted, use the whole file as one test (fallback)
    if not subtests:

      def is_valid_test_line(line: str):
        line = line.strip()
        if (
          line.startswith("; NOTE")
          or line.startswith("; RUN")
          or line.startswith("; CHECK")
        ):
          return False
        return True

      normalized_body = "\n".join(filter(is_valid_test_line, test_file.splitlines()))
      if normalized_body.strip():  # Only add if there's actual content
        tests.append(
          {
            "file": file.path,
            "commands": commands,
            "tests": [{"test_name": "<module>", "test_body": normalized_body}],
          }
        )
    else:
      tests.append({"file": file.path, "commands": commands, "tests": subtests})

  return tests


def main():
  parser = argparse.ArgumentParser(
    description="Extract and process LLVM PR data from GitHub."
  )
  parser.add_argument("pr_id", type=int, help="The PR ID to process.")
  parser.add_argument(
    "-f", "--force", action="store_true", help="Force override existing data."
  )
  parser.add_argument(
    "--skip-closed-check",
    action="store_true",
    help="Skip the check for PR being closed (allow open/closed PRs).",
  )
  args = parser.parse_args()

  pr_id = args.pr_id
  force = args.force
  skip_closed_check = args.skip_closed_check

  if force:
    print("Force override enabled")

  # Determine output directory based on PR state (will be determined after fetching)
  pr_url = f"https://api.github.com/repos/llvm/llvm-project/pulls/{pr_id}"
  print(f"Fetching {pr_url}")
  pr = session.get(pr_url).json()

  if "message" in pr and pr["message"] == "Not Found":
    print(f"Error: PR #{pr_id} not found")
    exit(1)

  # Determine if PR is open or closed
  pr_state = pr["state"]
  if pr_state == "closed":
    output_subdir = "closed"
  else:
    output_subdir = "open"

  # Check if we should skip closed PRs (unless skip_closed_check is set)
  if not skip_closed_check and pr_state != "closed":
    print("Warning: PR is not closed. Use --skip-closed-check to process open PRs.")
    # Don't exit, just warn

  # Prepare output path
  pr_dir = Path(llvm_helper.dataset_dir) / output_subdir
  pr_dir.mkdir(parents=True, exist_ok=True)
  data_json_path = pr_dir / f"{pr_id}.json"

  if not force and data_json_path.exists():
    print(f"Error: Item {pr_id}.json already exists (--force not set).")
    exit(1)

  # Fetch the patch
  patch_response = session.get(
    f"https://api.github.com/repos/llvm/llvm-project/pulls/{pr_id}",
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

  # Filter for LLVM lib/include files and infer components
  llvm_files = [
    f for f in changed_files if f.startswith(("llvm/lib/", "llvm/include/"))
  ]
  components = llvm_helper.infer_related_components(llvm_files)

  if not components:
    print("This PR does not modify any LLVM lib/include files")
    exit(1)

  # Get commit information
  base_commit = pr["base"]["sha"]
  fix_commit = pr["head"]["sha"]

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
    if llvm_helper.is_valid_comment(comment_obj):
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
    llvm_helper.reset(base_commit)
  except Exception as e:
    print(f"Warning: Failed to reset HEAD to {base_commit}: {e}")
    print("Syncing repository and trying again...")
    llvm_helper.reset("main")
    llvm_helper.git_execute(["pull", "origin", "main"])
    try:
      llvm_helper.reset(base_commit)
    except Exception as e:
      print(f"Error: Failed to reset HEAD to {base_commit}: {e}")
      exit(1)

  # Apply the patch
  print("Applying patch...")
  success, log = llvm_helper.apply(patch)
  if not success:
    print(f"Error: Failed to apply patch: {log}")
    llvm_helper.reset("main")
    exit(1)

  # Extract patch location information (line numbers and function names)
  # Line level location
  patch_location_lineno = {}
  try:
    patchset = PatchSet(patch)
    for file in patchset:
      location = hints.get_line_loc(file)
      if len(location) != 0:
        patch_location_lineno[file.path] = location
  except Exception as e:
    print(f"Warning: Failed to extract line locations: {e}")

  # Function level location
  patch_location_funcname = {}
  try:
    patchset = PatchSet(patch)
    for file in patchset.modified_files:
      print(f"Parsing {file.path}")
      source_code = llvm_helper.git_execute(["show", f"{base_commit}:{file.path}"])
      modified_funcs_valid = hints.get_funcname_loc(file, source_code)
      if len(modified_funcs_valid) != 0:
        patch_location_funcname[file.path] = sorted(modified_funcs_valid)
  except Exception as e:
    print(f"Warning: Failed to extract function names: {e}")

  # Extract tests from the applied patch
  print("Extracting tests from patch...")
  tests = extract_tests_from_patch(patch)
  print(f"Extracted {len(tests)} test file(s)")

  # Filter out test files from patch
  code_only_patch = filter_patch_exclude_tests(patch)

  # Reset repository
  print("Resetting repository...")
  llvm_helper.reset("main")

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

  with open(data_json_path, "w") as f:
    json.dump(pr_info, f, indent=2)

  print(f"Successfully saved PR data to {data_json_path}")


if __name__ == "__main__":
  main()
