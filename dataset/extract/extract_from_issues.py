#!/usr/bin/env python3
# Copyright 2025 Yingwei Zheng
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import subprocess
import sys
import time
from pathlib import Path

import requests
import tqdm

sys.path.append(str(Path(__file__).parent.parent))

from llvm import llvm_helper

github_token = os.environ["LAB_GITHUB_TOKEN"]
cache_dir = Path(os.path.dirname(__file__)) / "cache"
postfix_extract = os.path.join(os.path.dirname(__file__), "postfix_extract.py")
session = requests.Session()
session.headers.update(
  {
    "X-GitHub-Api-Version": "2022-11-28",
    "Authorization": f"Bearer {github_token}",
    "Accept": "application/vnd.github+json",
  }
)

issue_id_begin = 748
issue_id_end = 181195


def wait(progress):
  try:
    rate_limit = session.get("https://api.github.com/rate_limit", timeout=10).json()
    if rate_limit["rate"]["remaining"] == 0:
      next_window = rate_limit["rate"]["reset"]
      while time.time() < next_window:
        progress.set_description(f"wait {int(next_window - time.time())}s")
        time.sleep(10)
  except Exception:
    time.sleep(60)
    pass


def fetch(issue_id):
  data_json_path = os.path.join(llvm_helper.dataset_dir, f"{issue_id}.json")
  if os.path.exists(data_json_path):
    return False

  issue_url = f"https://api.github.com/repos/llvm/llvm-project/issues/{issue_id}"
  issue = session.get(issue_url).json()
  if "message" in issue and (
    issue["message"] == "Not Found" or issue["message"] == "This issue was deleted"
  ):
    return False
  if issue["state"] != "closed" or issue["state_reason"] != "completed":
    return False
  if "issue" not in issue["html_url"]:
    return False
  has_valid_label = False
  for label in issue["labels"]:
    label_name = label["name"]
    if label_name == "miscompilation":
      has_valid_label = True
    for key in [
      "backend",
      "clang:",
      "clangd",
      "clang-tidy",
      "clang-format",
      "mlir",
      "tools:",
      "flang:",
      "lld:",
      "lldb",
      "tablegen",
      "polly",
      "PGO",
    ]:
      if key in label_name:
        return False
    if label_name in [
      "invalid",
      "wontfix",
      "duplicate",
      "undefined behavior",
      "llvm:SelectionDAG",
      "llvm:globalisel",
      "llvm:regalloc",
      "llvm:codegen",
      "llvm-reduce",
      "llvm:bitcode",
      "llvm:openmpirbuilder",
      "BOLT",
      "mc",
      "libc++",
      "coroutines",
    ]:
      return False
  if not has_valid_label:
    return False

  try:
    out = subprocess.check_output(
      ["python3", postfix_extract, str(issue_id)], stderr=subprocess.DEVNULL
    ).decode()
    if "This issue is marked as invalid" in out:
      return False
    print(f"{issue_id}: {out}")
    return True
  except subprocess.CalledProcessError as e:
    print(f"{issue_id}: {e}")
    return True


os.makedirs(cache_dir, exist_ok=True)
success = 0
progress = tqdm.tqdm(range(issue_id_begin, issue_id_end + 1))
for issue_id in progress:
  progress.set_description(f"Success {success}")
  cache_file = os.path.join(cache_dir, str(issue_id))
  if os.path.exists(cache_file):
    progress.refresh()
    continue
  while True:
    try:
      if fetch(issue_id):
        success += 1
      else:
        Path(cache_file).touch()
      break
    except KeyError:
      wait(progress)
    except requests.exceptions.RequestException:
      wait(progress)
    except ValueError:
      wait(progress)
    except Exception as e:
      print(type(e), e)
      exit(0)
