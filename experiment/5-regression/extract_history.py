#!/usr/bin/env python3

import json
import re
import subprocess
import sys
from argparse import ArgumentParser
from pathlib import Path

from unidiff import PatchSet

# Add the root directory to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from llvm import llvm_helper


def parse_args():
  parser = ArgumentParser(description="Extract commit history for a given issue ID")
  parser.add_argument(
    "--issue",
    type=str,
    required=True,
    help="The issue ID to extract history for.",
  )
  return parser.parse_args()


def load_input_data(input_json_path):
  if not input_json_path.exists():
    print(f"Error: Input file not found: {input_json_path}")
    sys.exit(1)

  with open(input_json_path, "r") as jf:
    try:
      input_data = json.load(jf)
    except Exception as e:
      print(f"Error: Failed to parse JSON {input_json_path}: {e}")
      sys.exit(1)

  return input_data


def get_commit_info(commit_sha):
  # Verify commit exists
  try:
    full_commit_sha = llvm_helper.git_execute(["rev-parse", commit_sha]).strip()
  except subprocess.CalledProcessError:
    print(f"Error: Commit {commit_sha} not found in repository")
    sys.exit(1)

  # Get commit message
  try:
    commit_message = llvm_helper.git_execute(
      ["log", "-1", "--format=%B", full_commit_sha]
    ).strip()
    commit_subject = llvm_helper.git_execute(
      ["log", "-1", "--format=%s", full_commit_sha]
    ).strip()
    commit_author = llvm_helper.git_execute(
      ["log", "-1", "--format=%an <%ae>", full_commit_sha]
    ).strip()
    commit_date = llvm_helper.git_execute(
      ["log", "-1", "--format=%aI", full_commit_sha]
    ).strip()
  except subprocess.CalledProcessError as e:
    print(f"Error: Failed to get commit information: {e}")
    sys.exit(1)

  return full_commit_sha, commit_message, commit_subject, commit_author, commit_date


def extract_tests(full_commit_sha):
  test_patch = llvm_helper.git_execute(["show", full_commit_sha, "--", "llvm/test/*"])

  tests = []
  if not test_patch.strip():
    return tests

  test_patchset = PatchSet(test_patch)
  testname_pattern = re.compile(r"define .+ @([.\w]+)\(")

  for file in test_patchset:
    # Get full test file content
    try:
      test_file = llvm_helper.git_execute(["show", f"{full_commit_sha}:{file.path}"])
    except subprocess.CalledProcessError:
      continue

    # Extract RUN commands
    runline_patterns = [
      re.compile(r"; RUN: (.+)\| (FileCheck .*)"),
      re.compile(r"; RUN: (.+)\\.*\| (FileCheck .*)"),
    ]

    # Merge multi-line RUN commands
    test_file_lines = test_file.splitlines()
    merged_lines = []
    i = 0
    while i < len(test_file_lines):
      line = test_file_lines[i]
      if line.strip().startswith("; RUN:"):
        merged_line = line
        while merged_line.rstrip().endswith("\\"):
          i += 1
          if i < len(test_file_lines):
            next_line = test_file_lines[i].strip()
            if next_line.startswith("; RUN:"):
              next_line = next_line[6:].strip()
            merged_line = merged_line.rstrip("\\").rstrip() + " " + next_line
          else:
            break
        merged_lines.append(merged_line)
      else:
        merged_lines.append(line)
      i += 1

    test_file_merged = "\n".join(merged_lines)

    # Extract commands
    commands = []
    for pattern in runline_patterns:
      for match in re.findall(pattern, test_file_merged):
        commands.append([match[0].strip(), match[1].strip()])

    # Extract test names from the diff
    test_names = set()
    for hunk in file:
      matched = re.search(testname_pattern, hunk.section_header)
      if matched:
        test_names.add(matched.group(1))
      for line in hunk.target:
        for match in re.findall(testname_pattern, line):
          test_names.add(match.strip())

    # Extract test bodies
    subtests = []
    if test_names:
      for test_name in test_names:
        try:
          test_body = subprocess.check_output(
            ["llvm-extract", f"--func={test_name}", "-S", "-"],
            input=test_file.encode(),
            stderr=subprocess.DEVNULL,
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
        except subprocess.CalledProcessError:
          pass
    else:
      # If no specific test names, include the full file
      subtests.append(
        {
          "test_name": "<module>",
          "test_body": test_file,
        }
      )

    if subtests:
      tests.append(
        {
          "file": file.path,
          "commands": commands,
          "tests": subtests,
        }
      )

  return tests


def update_history(input_data, metadata, input_json_path):
  existing_history = input_data.get("history")
  if existing_history is None:
    # nothing existed before, set to metadata
    input_data["history"] = metadata
  else:
    # if history is a list, append; if dict, convert to list
    if isinstance(existing_history, list):
      existing_history.append(metadata)
      input_data["history"] = existing_history
    elif isinstance(existing_history, dict):
      input_data["history"] = [existing_history, metadata]
    else:
      # unknown format: overwrite
      input_data["history"] = metadata

  with open(input_json_path, "w") as jf:
    json.dump(input_data, jf, indent=2, ensure_ascii=False)


def main():
  args = parse_args()
  issue_id = args.issue

  dataset_dir = Path(__file__).parent / "mis"
  input_json_path = dataset_dir / f"{issue_id}.json"

  input_data = load_input_data(input_json_path)

  if "history" in input_data and input_data["history"]:
    print(f"Skipping {issue_id}: history already exists.")
    sys.exit(0)

  if "bisect" not in input_data:
    print("Error: Input JSON must contain a 'bisect' field with the commit SHA")
    sys.exit(1)

  commit_sha = str(input_data["bisect"]).strip()

  # Validate commit SHA format (basic check)
  if not re.match(r"^[0-9a-f]{7,40}$", commit_sha, re.IGNORECASE):
    print(f"Error: Invalid commit SHA format: {commit_sha}")
    sys.exit(1)

  full_commit_sha, commit_message, commit_subject, commit_author, commit_date = (
    get_commit_info(commit_sha)
  )

  # Extract patch (only lib and include directories)
  patch = llvm_helper.git_execute(
    ["show", full_commit_sha, "--", "llvm/lib/*", "llvm/include/*"]
  )

  tests = extract_tests(full_commit_sha)

  # Get changed files and infer components
  changed_files = (
    llvm_helper.git_execute(["show", "--name-only", "--format=", full_commit_sha])
    .strip()
    .split("\n")
  )

  components = llvm_helper.infer_related_components(changed_files)

  # Build metadata
  metadata = {
    "commit_sha": full_commit_sha,
    "commit_sha_short": commit_sha[:12],
    "commit_subject": commit_subject,
    "commit_message": commit_message,
    "commit_author": commit_author,
    "commit_date": commit_date,
    "components": sorted(components),
    "changed_files": changed_files,
    "patch": patch,
    "tests": tests,
  }

  update_history(input_data, metadata, input_json_path)

  print(f"Successfully updated {input_json_path}")


if __name__ == "__main__":
  main()
