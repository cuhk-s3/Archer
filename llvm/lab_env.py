import datetime
import json
import os
import re
import subprocess
import tempfile
import time
from typing import Optional, Union

import dateparser

import llvm.llvm_helper as llvm_helper


class TimeCompensationGuard:
  def __init__(self, environment):
    self.environment = environment

  def __enter__(self):
    self.start_time = time.time()
    self.environment.interaction_time_compensation_enter += 1

  def __exit__(self, exception_type, exception_value, exception_traceback):
    self.environment.interaction_time_compensation_enter -= 1
    if self.environment.interaction_time_compensation_enter == 0:
      self.environment.interaction_time_compensation += time.time() - self.start_time


class Environment:
  def __init__(
    self,
    issue_id,
    base_model_knowledge_cutoff: str,
    *,
    max_build_jobs=None,
    max_test_jobs=None,
    use_entire_regression_test_suite=False,
    additional_cmake_args=[],
  ):
    with open(os.path.join(llvm_helper.dataset_dir, f"{issue_id}.json")) as f:
      self.data = json.load(f)
    self.base_commit = self.data["base_commit"]
    self.knowledge_cutoff = dateparser.parse(self.data["knowledge_cutoff"])
    self.bug_type = self.data["bug_type"]
    self.test_commit = self.data.get("test_commit", self.data["hints"]["fix_commit"])
    self.test_commit_checkout_changed_files_only = self.data.get(
      "test_commit_checkout_changed_files_only", False
    )
    self.used_knowledge = dict()
    self.use_knowledge("base_model", base_model_knowledge_cutoff)
    self.interaction_time_compensation = 0.0
    self.interaction_time_compensation_enter = 0
    self.build_count = 0
    self.build_failure_count = 0
    self.fast_check_count = 0
    self.full_check_count = 0
    self.fast_check_pass = False
    self.full_check_pass = False
    if max_build_jobs is None:
      self.max_build_jobs = os.cpu_count()
    else:
      self.max_build_jobs = max_build_jobs
    if max_test_jobs is None:
      self.max_test_jobs = max_build_jobs
    else:
      self.max_test_jobs = max_test_jobs
    self.additional_cmake_args = additional_cmake_args
    self.use_entire_regression_test_suite = use_entire_regression_test_suite
    self.start_time = time.time()

  def use_knowledge(self, url: str, date: Union[str, datetime.datetime]):
    if isinstance(date, str):
      date = dateparser.parse(date)
    if date <= self.knowledge_cutoff:
      self.used_knowledge[url] = min(self.used_knowledge.get(url, date), date)
    else:
      raise ValueError("Knowledge is newer than the cutoff date")

  def reset(self):
    with TimeCompensationGuard(self):
      llvm_helper.reset(self.base_commit)
      
  def apply(self):
    with TimeCompensationGuard(self):
      llvm_helper.apply(self.test_commit)

  def verify_head(self):
    head = llvm_helper.git_execute(["rev-parse", "HEAD"]).strip()
    if head != self.base_commit:
      raise RuntimeError("invalid HEAD")

  def build(self):
    with TimeCompensationGuard(self):
      self.build_count += 1
      self.verify_head()
      res, log = llvm_helper.build(self.max_build_jobs, self.additional_cmake_args)
      if not res:
        self.build_failure_count += 1
      return res, log

  def dump(self, log=None):
    wall_time = time.time() - self.start_time - self.interaction_time_compensation
    self.verify_head()
    patch = self.dump_patch()
    used_knowledge = []
    for url, t in self.used_knowledge.items():
      used_knowledge.append((url, t.strftime("%Y-%m-%d%z")))
    return {
      "wall_time": wall_time,
      "knowledge": used_knowledge,
      "build_count": self.build_count,
      "build_failure_count": self.build_failure_count,
      "fast_check_count": self.fast_check_count,
      "full_check_count": self.full_check_count,
      "fast_check_pass": self.fast_check_pass,
      "full_check_pass": self.full_check_pass,
      "patch": patch,
      "log": log,
    }

  def dump_patch(self):
    return llvm_helper.git_execute(
      ["diff", self.base_commit, "--", "llvm/lib/*", "llvm/include/*"]
    )

  def check_fast(self):
    with TimeCompensationGuard(self):
      self.fast_check_count += 1
      res, reason = self.build()
      if not res:
        return (False, reason)
      res, log = llvm_helper.verify_test_group(
        repro=False, input=self.data["tests"], type=self.bug_type
      )
      if not res:
        return (False, log)
      self.fast_check_pass = True
      return (True, log)

  def check_regression(self):
    with TimeCompensationGuard(self):
      self.full_check_count += 1
      res, reason = self.build()
      if not res:
        return (False, reason)
      # If use_entire_regression_test_suite is True, run the entire regression test suite.
      # By default, only run the tests in the specified lit_test_dir to save time.
      return llvm_helper.verify_lit(
        test_commit=self.test_commit,
        dirs=["llvm/test/Transforms", "llvm/test/Analysis"]
        if self.use_entire_regression_test_suite
        else self.data["lit_test_dir"],
        max_test_jobs=self.max_build_jobs,
        test_commit_checkout_changed_files_only=self.test_commit_checkout_changed_files_only,
      )

  # Please disable ASLR and compile LLVM with -DLLVM_ABI_BREAKING_CHECKS=FORCE_OFF
  # to ensure deterministic output.
  def check_regression_diff(self, seeds_dir: Optional[str] = None):
    with open("/proc/sys/kernel/randomize_va_space", "r") as f:
      if int(f.read().strip()) != 0:
        print("Warning: ASLR is enabled. Please disable it for deterministic output.")
        return (True, "ASLR is enabled")
    if "-DLLVM_ABI_BREAKING_CHECKS=FORCE_OFF" not in self.additional_cmake_args:
      print(
        "Warning: Please compile LLVM with -DLLVM_ABI_BREAKING_CHECKS=FORCE_OFF for deterministic output."
      )
      return (True, "LLVM_ABI_BREAKING_CHECKS is enabled")
    with TimeCompensationGuard(self):
      self.full_check_count += 1
      patch = self.dump_patch()

      self.reset()
      llvm_helper.apply(self.data["patch"])
      res, reason = self.build()
      if not res:
        self.reset()
        llvm_helper.apply(patch)
        return (False, reason)

      tasks = []
      if seeds_dir is None:
        seeds_dir = os.path.join(llvm_helper.llvm_dir, "llvm", "test")
      for r, _, fs in os.walk(seeds_dir):
        for f in fs:
          if f.endswith(".ll"):
            src_path = os.path.join(r, f)
            tasks.append(src_path)

      gold_result = llvm_helper.batch_compute_O3_output(tasks, self.max_test_jobs)

      self.reset()
      llvm_helper.apply(patch)
      res, reason = self.build()
      if not res:
        return (False, reason)
      patch_result = llvm_helper.batch_compute_O3_output(
        list(gold_result.keys()), self.max_test_jobs
      )

      valid_count = 0
      for file, res in patch_result.items():
        if gold_result[file] == res:
          valid_count += 1
        else:
          # use llvm-diff for structural comparison
          with tempfile.NamedTemporaryFile("w") as f_gold, tempfile.NamedTemporaryFile(
            "w"
          ) as f_patch:
            f_gold.write(gold_result[file])
            f_gold.flush()
            f_patch.write(res)
            f_patch.flush()
            try:
              subprocess.check_call(
                [
                  os.path.join(llvm_helper.get_llvm_build_dir(), "bin", "llvm-diff"),
                  f_gold.name,
                  f_patch.name,
                ],
                stderr=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
              )
              valid_count += 1
            except subprocess.CalledProcessError:
              pass
      if valid_count == len(gold_result):
        return (True, "success")
      return (False, f"failure ({valid_count}/{len(gold_result)})")

  def check_full(self):
    with TimeCompensationGuard(self):
      self.full_check_count += 1
      res, reason = self.build()
      if not res:
        return (False, reason)
      res, log = llvm_helper.verify_test_group(
        repro=False, input=self.data["tests"], type=self.bug_type
      )
      if not res:
        return (False, log)
      self.fast_check_pass = True
      # If use_entire_regression_test_suite is True, run the entire regression test suite.
      # By default, only run the tests in the specified lit_test_dir to save time.
      res, log = llvm_helper.verify_lit(
        test_commit=self.test_commit,
        dirs=["llvm/test/Transforms", "llvm/test/Analysis"]
        if self.use_entire_regression_test_suite
        else self.data["lit_test_dir"],
        max_test_jobs=self.max_build_jobs,
        test_commit_checkout_changed_files_only=self.test_commit_checkout_changed_files_only,
      )
      if not res:
        return (False, log)
      self.full_check_pass = True
      return (True, log)

  def get_bug_type(self):
    return self.bug_type

  def get_base_commit(self):
    return self.base_commit

  def get_tests(self):
    return self.data["tests"]

  def get_reference_patch(self):
    return self.data["patch"]

  def get_hint_fix_commit(self):
    self.use_knowledge("hint:fix_commit", self.knowledge_cutoff)
    return self.data["hints"].get("fix_commit")

  def get_hint_components(self):
    self.use_knowledge("hint:components", self.knowledge_cutoff)
    return self.data["hints"].get("components")

  def get_hint_files(self):
    self.use_knowledge("hint:files", self.knowledge_cutoff)
    lineno = self.data["hints"].get("bug_location_lineno")
    if lineno is None:
      return None
    return sorted(lineno.keys())

  def get_hint_bug_functions(self):
    self.use_knowledge("hint:bug_functions", self.knowledge_cutoff)
    return self.data["hints"].get("bug_location_funcname")

  def get_hint_line_level_bug_locations(self):
    self.use_knowledge("hint:line_level_bug_locations", self.knowledge_cutoff)
    return self.data["hints"].get("bug_location_lineno")

  def get_hint_issue(self):
    self.use_knowledge("hint:issue", self.knowledge_cutoff)
    return self.data.get("issue")

  def get_ir_keywords(self, ir: str):
    keywords = set()
    # instructions
    instruction_pattern = re.compile(r"%.+ = (\w+) ")
    for match in re.findall(instruction_pattern, ir):
      keywords.add(match)
    # intrinsics
    intrinsic_pattern = re.compile(r"@(llvm.\w+)\(")
    for match in re.findall(intrinsic_pattern, ir):
      keywords.add(match)
    keywords.discard("call")
    return keywords

  def get_langref_desc(self, keywords):
    self.use_knowledge("llvm/docs/LangRef.rst", self.knowledge_cutoff)
    return llvm_helper.get_langref_desc(keywords, self.base_commit)

  # NOTE: It is not a hint.
  def is_single_func_fix(self):
    self.use_knowledge("is_single_func_fix", self.knowledge_cutoff)
    return self.data.get("properties").get("is_single_func_fix")

  # NOTE: It is not a hint.
  def is_single_file_fix(self):
    self.use_knowledge("is_single_file_fix", self.knowledge_cutoff)
    return self.data.get("properties").get("is_single_file_fix")
