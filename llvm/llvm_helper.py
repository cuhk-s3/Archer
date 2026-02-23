import os
import re
import subprocess
import tempfile
from multiprocessing import Pool
from pathlib import Path
from typing import Dict, List

from utils import cmdline

llvm_dir = os.environ["LAB_LLVM_DIR"]
__llvm_build_dir = os.environ["LAB_LLVM_BUILD_DIR"]
llvm_alive_tv = os.environ["LAB_LLVM_ALIVE_TV"]
dataset_dir = os.environ["LAB_DATASET_DIR"]
if "--quiet" not in subprocess.run(
  ["ninja", "--help"], capture_output=True
).stderr.decode("utf-8"):
  raise RuntimeError("Please update ninja to version 1.11.0 or later")


def git_execute(args):
  return subprocess.check_output(
    ["git", "-C", llvm_dir] + args, cwd=llvm_dir, stderr=subprocess.DEVNULL
  ).decode("utf-8")


def reset(commit):
  git_execute(["restore", "--staged", "."])
  git_execute(["clean", "-fdx"])
  git_execute(["checkout", "."])
  git_execute(["checkout", commit])


def infer_related_components(diff_files):
  prefixes = [
    "llvm/lib/Analysis/",
    "llvm/lib/Transforms/Scalar/",
    "llvm/lib/Transforms/Vectorize/",
    "llvm/lib/Transforms/Utils/",
    "llvm/lib/Transforms/IPO/",
    "llvm/lib/Transforms/",
    "llvm/lib/IR/",
  ]
  components = set()
  for file in diff_files:
    for prefix in prefixes:
      if file.startswith(prefix):
        component_name = (
          file.removeprefix(prefix)
          .split("/")[0]
          .removesuffix(".cpp")
          .removesuffix(".h")
        )
        if component_name != "":
          if (
            component_name.startswith("VPlan")
            or component_name.startswith("LoopVectoriz")
            or component_name.startswith("VPRecipe")
          ):
            component_name = "LoopVectorize"
          if component_name.startswith("ScalarEvolution"):
            component_name = "ScalarEvolution"
          if component_name.startswith("ConstantFold"):
            component_name = "ConstantFold"
          if "AliasAnalysis" in component_name:
            component_name = "AliasAnalysis"
          if component_name.startswith("Attributor"):
            component_name = "Attributor"
          if file.startswith("llvm/lib/IR"):
            component_name = "IR"
          components.add(component_name)
          break
  return components


def get_langref_desc(keywords, commit):
  langref = str(git_execute(["show", f"{commit}:llvm/docs/LangRef.rst"]))
  desc = dict()
  sep1 = ".. _"
  sep2 = "\n^^^"
  for keyword in keywords:
    matched = re.search(f"\n'``{keyword}.+\n\\^", langref)
    if matched is None:
      continue
    beg, end = matched.span()
    beg = langref.rfind(sep1, None, beg)
    end1 = langref.find(sep2, end)
    end2 = langref.rfind(sep1, None, end1)
    desc[keyword] = langref[beg:end2]
  return desc


def decode_output(output):
  if output is None:
    return ""
  return output.decode()


def build(max_build_jobs: int, additional_cmake_args=[]):
  os.makedirs(__llvm_build_dir, exist_ok=True)
  log = ""
  # TODO: we can set CCACHE_NOHASHDIR to allow ccache to reuse objects built in different directories.
  # Be careful about the debug prefix mapping though.
  try:
    log += subprocess.check_output(
      [
        "cmake",
        "-S",
        llvm_dir + "/llvm",
        "-G",
        "Ninja",
        "-DBUILD_SHARED_LIBS=ON",
        "-DCMAKE_BUILD_TYPE=RelWithDebInfo",
        "-DCMAKE_C_COMPILER_LAUNCHER=ccache",
        "-DCMAKE_CXX_COMPILER_LAUNCHER=ccache",
        "-DLLVM_ENABLE_ASSERTIONS=ON",
        "-DLLVM_ABI_BREAKING_CHECKS=WITH_ASSERTS",
        "-DLLVM_ENABLE_WARNINGS=OFF",
        "-DLLVM_APPEND_VC_REV=OFF",
        "-DLLVM_TARGETS_TO_BUILD='X86;RISCV;AArch64;SystemZ;Hexagon;PowerPC;'",
        "-DLLVM_PARALLEL_LINK_JOBS=4",
        "-DLLVM_INCLUDE_EXAMPLES=OFF",
      ]
      + additional_cmake_args,
      stderr=subprocess.STDOUT,
      cwd=__llvm_build_dir,
    ).decode()
    pos = log.find("Build files have been written to")
    if pos != -1:
      pos = log.find("\n", pos)
      if pos != -1:
        log = log[pos + 1 :]
    log += subprocess.check_output(
      ["cmake", "--build", ".", "-j", str(max_build_jobs), "--", "--quiet"],
      stderr=subprocess.STDOUT,
      cwd=__llvm_build_dir,
    ).decode()
    return (True, log)
  except subprocess.CalledProcessError as e:
    return (False, log + "\n" + decode_output(e.output))


def is_valid_comment(comment):
  if comment["author"] == "llvmbot":
    return False
  if comment["body"].startswith("/cherry-pick"):
    return False
  return True


def apply(patch: str):
  try:
    out = subprocess.check_output(
      ["git", "-C", llvm_dir, "apply"],
      cwd=llvm_dir,
      stderr=subprocess.STDOUT,
      input=patch.encode(),
    ).decode("utf-8")
    return (True, out)
  except subprocess.CalledProcessError as e:
    return (False, str(e) + "\n" + decode_output(e.output))


def filter_out_unsupported_feats(src: str):
  src = src.replace(" noalias ", " ")
  src = src.replace(" nofree ", " ")
  return src


def alive2_check(src: str, tgt: str, additional_args: str, repro: bool):
  try:
    with tempfile.NamedTemporaryFile() as src_file:
      with tempfile.NamedTemporaryFile() as tgt_file:
        src = filter_out_unsupported_feats(src)
        tgt = filter_out_unsupported_feats(tgt)
        src_file.write(src.encode())
        tgt_file.write(tgt.encode())
        src_file.flush()
        tgt_file.flush()

        args = [
          llvm_alive_tv,
          "--disable-undef-input",
          "--smt-to=60000",
          src_file.name,
          tgt_file.name,
        ]
        if additional_args:
          args += additional_args.strip().split(" ")

        out = subprocess.check_output(args, stderr=subprocess.STDOUT).decode()
        # NOTE: !success doesn't imply reproducible.
        # Affected issues: 136430/140444
        success = (
          "0 incorrect transformations" in out
          and "0 failed-to-prove transformations" in out
          and "0 Alive2 errors" in out
        )
        failure = (
          "0 incorrect transformations" not in out
          and "0 failed-to-prove transformations" in out
          and "0 Alive2 errors" in out
        )
        return (failure if repro else success, {"src": src, "tgt": tgt, "log": out})
  except subprocess.CalledProcessError as e:
    return (False, str(e) + "\n" + decode_output(e.output))


def copy_triple(input: str, out: bytes):
  triple_pattern = "target triple ="
  if triple_pattern in input:
    return input
  ref_out = out.decode()
  if triple_pattern in ref_out:
    triple_pos = ref_out.find(triple_pattern)
    triple_line = ref_out[triple_pos : ref_out.find("\n", triple_pos) + 1]
    return triple_line + input
  return input


def copy_datalayout(input: str, out: bytes):
  datalayout_pattern = "target datalayout ="
  if datalayout_pattern in input:
    return input
  ref_out = out.decode()
  if datalayout_pattern in ref_out:
    datalayout_pos = ref_out.find(datalayout_pattern)
    datalayout_line = ref_out[datalayout_pos : ref_out.find("\n", datalayout_pos) + 1]
    return datalayout_line + input
  return input


def verify_dispatch(
  repro: bool,
  input: str,
  args: str,
  type: str,
  additional_args: str,
):
  args_list = list(
    filter(
      lambda x: x != "",
      args.replace("< ", " ")
      .replace("%s", "-")
      .replace("2>&1", "")
      .replace("'", "")
      .replace('"', "")
      .replace("opt", os.path.join(__llvm_build_dir, "bin/opt"), 1)
      .strip()
      .split(" "),
    )
  )
  try:
    out = subprocess.run(
      args_list,
      input=input.encode(),
      timeout=600.0 if type == "crash" else 10.0,
      check=True,
      capture_output=True,
    )
    if type == "miscompilation":
      output = out.stdout
      new_input = copy_triple(input, output)
      new_input = copy_datalayout(new_input, output)
      res, log = alive2_check(new_input, output.decode(), additional_args, repro)
      if isinstance(log, str):
        log = decode_output(out.stderr) + "\n" + log
      else:
        log["opt_stderr"] = decode_output(out.stderr)
      return (res, log)
    return (not repro, "success\n" + decode_output(out.stderr))
  except subprocess.CalledProcessError as e:
    return (
      repro and type == "crash",
      str(e) + "\n" + decode_output(e.output) + "\n" + decode_output(e.stderr),
    )
  except subprocess.TimeoutExpired as e:
    return (
      repro and type == "hang",
      str(e) + "\n" + decode_output(e.output) + "\n" + decode_output(e.stderr),
    )


def verify_test_group(repro: bool, input, type: str):
  test_res = []
  overall_test_res = not repro
  for test in input:
    file = test["file"]
    commands = test["commands"]
    tests = test["tests"]
    for subtest in tests:
      name = subtest["test_name"]
      body = subtest["test_body"]
      for args in commands:
        res, log = verify_dispatch(
          repro,
          body,
          args,
          type,
          subtest.get("additional_args"),
        )
        test_res.append(
          {
            "file": file,
            "args": args,
            "name": name,
            "body": body,
            "result": res,
            "log": log,
          }
        )
        if repro:
          overall_test_res = overall_test_res or res
        else:
          overall_test_res = overall_test_res and res
  return (overall_test_res, test_res)


def verify_lit(
  test_commit, dirs, max_test_jobs, test_commit_checkout_changed_files_only
):
  try:
    # In some edge cases, we cannot find a suitable test commit that is buildable and green.
    # We only checkout the changed files instead.
    if test_commit_checkout_changed_files_only:
      files = (
        git_execute(["show", "--name-only", "--format=", test_commit, "--"] + dirs)
        .strip()
        .splitlines()
      )
      for file in files:
        git_execute(["checkout", test_commit, file])
    else:
      git_execute(["checkout", test_commit, "llvm/test"])
    test_dirs = [os.path.join(llvm_dir, x) for x in dirs]
    # TODO: use --order=random/--max-tests/--max-time for test sampling
    out = cmdline.check_output(
      " ".join(
        [
          os.path.join(__llvm_build_dir, "bin/llvm-lit"),
          "--no-progress-bar",
          "-j",
          str(max_test_jobs),
          "--max-failures",
          "1",
          "--order",
          "lexical",
          "-sv",
        ]
        + test_dirs
      ),
      timeout=300,
    ).decode()
    return (True, out)
  except subprocess.CalledProcessError as e:
    return (False, str(e) + "\n" + decode_output(e.output))
  except subprocess.TimeoutExpired as e:
    return (False, str(e) + "\n" + decode_output(e.output))


# TODO: Use https://github.com/llvm/llvm-project/blob/main/.ci/generate_test_report_lib.py for pretty test result reporting.
def get_first_failed_test(test_result):
  for res in test_result:
    if not res["result"]:
      return res
  return None


def is_valid_fix(commit):
  if commit is None:
    return False
  try:
    branches = git_execute(["branch", "--contains", commit])
    if "main\n" not in branches:
      return False
    changed_files = (
      subprocess.check_output(
        [
          "git",
          "-C",
          llvm_dir,
          "show",
          "--name-only",
          "--format=",
          commit,
        ],
        stderr=subprocess.DEVNULL,
      )
      .decode()
      .strip()
    )
    if "llvm/test/" in changed_files and (
      "llvm/lib/" in changed_files or "llvm/include/" in changed_files
    ):
      return True
  except subprocess.CalledProcessError:
    pass
  return False


def remove_path_from_output(output: str) -> str:
  output = output.replace(str(Path(llvm_dir).resolve()) + "/", "")
  output = output.replace(str(Path(__llvm_build_dir).resolve()) + "/", "")
  return output


def pretty_render_log(log) -> str:
  if isinstance(log, str):
    return remove_path_from_output(log)
  if isinstance(log, dict):
    pretty_log = ""
    for key, value in log.items():
      pretty_log += f"--- {key} ---\n{pretty_render_log(value)}\n\n"
    return pretty_log
  return remove_path_from_output(str(log))


def set_llvm_build_dir(new_dir: str):
  global __llvm_build_dir
  __llvm_build_dir = new_dir


def get_llvm_build_dir() -> str:
  return __llvm_build_dir


def compute_O3_output(file: str) -> str:
  opt_path = os.path.join(get_llvm_build_dir(), "bin", "opt")
  try:
    output = subprocess.check_output(
      [opt_path, "-O3", file, "-S"], timeout=60.0, stderr=subprocess.DEVNULL
    )
    res = output.decode("utf-8")
    return file, res
  except Exception:
    return file, None


def batch_compute_O3_output(tasks: List[str], jobs: int) -> Dict[str, str]:
  hashes = dict()
  with Pool(processes=jobs) as pool:
    for res in pool.imap_unordered(compute_O3_output, tasks):
      file, hash = res
      if not hash:
        continue
      hashes[file] = hash
  return hashes


def strip_llvm_fence(s: str) -> str:
  s = s.strip()
  if s.startswith("```"):
    lines = s.splitlines()
    # Drop opening fence (```llvm / ```), keep body, drop trailing fence if present.
    if len(lines) >= 1 and lines[0].startswith("```"):
      lines = lines[1:]
    if len(lines) >= 1 and lines[-1].strip() == "```":
      lines = lines[:-1]
    return "\n".join(lines).strip()
  return s
