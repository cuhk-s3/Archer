import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import hints as hints
import requests
from unidiff import PatchSet

sys.path.append(str(Path(__file__).parent.parent))

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

subprocess.check_output(["llvm-extract", "--version"])

parser = argparse.ArgumentParser(description="Extract and process LLVM issue data.")
parser.add_argument("issue", type=str, help="The ID of the LLVM issue to process.")
parser.add_argument(
  "-f", "--force", action="store_true", help="Force override existing data."
)
args = parser.parse_args()

issue_id = args.issue
force = args.force

if force:
  print("Force override")

data_json_path = os.path.join(llvm_helper.dataset_dir, f"{issue_id}.json")
if not force and os.path.exists(data_json_path):
  print(f"Error: Item {issue_id}.json already exists (--force not set).")
  exit(1)

issue_url = f"https://api.github.com/repos/llvm/llvm-project/issues/{issue_id}"
print(f"Fetching {issue_url}")
issue = session.get(issue_url).json()
if (issue["state"] != "closed" or issue["state_reason"] != "completed") and not force:
  print("The issue/PR should be closed")
  exit(1)

knowledge_cutoff = issue["created_at"]
timeline = session.get(issue["timeline_url"]).json()
fix_commit = None

for event in timeline:
  if event["event"] == "closed":
    commit_id = event["commit_id"]
    if commit_id is not None:
      fix_commit = commit_id
      break
  if event["event"] == "referenced" and fix_commit is None:
    commit = event["commit_id"]
    if llvm_helper.is_valid_fix(commit):
      fix_commit = commit

if fix_commit is None:
  if force:
    fix_commit = llvm_helper.git_execute(["rev-parse", "origin/main"]).strip()
  else:
    print("Cannot find the fix commit")
    exit(0)

issue_type = "unknown"
for label in issue["labels"]:
  label_name = label["name"]
  if label_name == "miscompilation":
    issue_type = "miscompilation"
  if "crash" in label_name:
    print("Crash issues are ignored for now.")
    exit(1)
  if "hang" in label_name:
    print("Hang issues are ignored for now.")
    exit(1)
  if label_name in [
    "invalid",
    "wontfix",
    "duplicate",
    "undefined behavior",
    "miscompilation:undef",
  ]:
    print("This issue is marked as invalid")
    exit(1)

base_commit = llvm_helper.git_execute(["rev-parse", fix_commit + "~"]).strip()
changed_files = llvm_helper.git_execute(
  ["show", "--name-only", "--format=", fix_commit]
).strip()
if "/AsmParser/" in changed_files or "/Bitcode/" in changed_files:
  print("This issue is marked as invalid")
  exit(0)

# Component level
components = llvm_helper.infer_related_components(changed_files.split("\n"))
# Extract patch
patch = llvm_helper.git_execute(
  ["show", fix_commit, "--", "llvm/lib/*", "llvm/include/*"]
)
patchset = PatchSet(patch)
# Line level
bug_location_lineno = {}
for file in patchset:
  location = hints.get_line_loc(file)
  if len(location) != 0:
    bug_location_lineno[file.path] = location


# Function level

bug_location_funcname = {}
for file in patchset.modified_files:
  print(f"Parsing {file.path}")
  source_code = llvm_helper.git_execute(["show", f"{base_commit}:{file.path}"])
  modified_funcs_valid = hints.get_funcname_loc(file, source_code)
  if len(modified_funcs_valid) != 0:
    bug_location_funcname[file.path] = sorted(modified_funcs_valid)

# Extract tests
test_patchset = PatchSet(
  llvm_helper.git_execute(["show", fix_commit, "--", "llvm/test/*"])
)


def remove_target_suffix(path):
  targets = [
    "X86",
    "AArch64",
    "ARM",
    "Mips",
    "RISCV",
    "PowerPC",
    "LoongArch",
    "AMDGPU",
    "SystemZ",
    "Hexagon",
  ]
  for target in targets:
    path = path.removesuffix("/" + target)
  return path


lit_test_dir = set(
  map(
    lambda x: remove_target_suffix(os.path.dirname(x)),
    filter(lambda x: x.count("llvm/test/"), changed_files.split("\n")),
  )
)
tests = []
# FIXME: Run line extraction is fragile. It doesn't handle the cases that involve macros.
# FIXME: The comments in regression tests may leak information about the original issue.
runline_pattern = re.compile(r"; RUN: (.+)\| FileCheck")
testname_pattern = re.compile(r"define .+ @([.\w]+)\(")
for file in test_patchset:
  test_file = llvm_helper.git_execute(["show", f"{fix_commit}:{file.path}"])
  commands = []
  for match in re.findall(runline_pattern, test_file):
    commands.append(match.strip())
  if issue_type != "miscompilation" and file.is_added_file:
    print(file.path, "full")

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
    tests.append(
      {
        "file": file.path,
        "commands": commands,
        "tests": [{"test_name": "<module>", "test_body": normalized_body}],
      }
    )
    continue
  test_names = set()
  for hunk in file:
    matched = re.search(testname_pattern, hunk.section_header)
    if matched:
      test_names.add(matched.group(1))
    for line in hunk.target:
      for match in re.findall(testname_pattern, line):
        test_names.add(match.strip())
  print(file.path, test_names)
  subtests = []
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
      pass
  if len(subtests) != 0:
    tests.append({"file": file.path, "commands": commands, "tests": subtests})

# Extract full issue context
issue_comments = []
comments = session.get(issue["comments_url"]).json()
for comment in comments:
  comment_obj = {
    "author": comment["user"]["login"],
    "body": comment["body"],
  }
  if llvm_helper.is_valid_comment(comment_obj):
    issue_comments.append(comment_obj)
normalized_issue = {
  "title": issue["title"],
  "body": issue["body"],
  "author": issue["user"]["login"],
  "labels": list(map(lambda x: x["name"], issue["labels"])),
  "comments": issue_comments,
}

bug_func_count = 0
for item in bug_location_funcname.values():
  bug_func_count += len(item)
is_single_file_fix = (
  len(set(bug_location_funcname.keys()) | set(bug_location_lineno.keys())) == 1
)
is_single_func_fix = bug_func_count == 1

# Write to file
metadata = {
  "bug_id": issue_id,
  "issue_url": issue["html_url"],
  "bug_type": issue_type,
  "base_commit": base_commit,
  "knowledge_cutoff": knowledge_cutoff,
  "lit_test_dir": sorted(lit_test_dir),
  "hints": {
    "fix_commit": fix_commit,
    "components": sorted(components),
    "bug_location_lineno": bug_location_lineno,
    "bug_location_funcname": bug_location_funcname,
  },
  "patch": patch,
  "tests": tests,
  "issue": normalized_issue,
  "properties": {
    "is_single_file_fix": is_single_file_fix,
    "is_single_func_fix": is_single_func_fix,
    "difficulty": "easy"
    if is_single_file_fix and is_single_func_fix
    else "medium"
    if is_single_file_fix
    else "hard",
  },
}
print(json.dumps(metadata, indent=2))
with open(data_json_path, "w") as f:
  json.dump(metadata, f, indent=2, sort_keys=True)
print(f"Saved to {data_json_path}")
