import os
import re
import subprocess
from pathlib import Path

llvm_dir = os.environ["LAB_LLVM_DIR"]
__llvm_build_dir = os.environ["LAB_LLVM_BUILD_DIR"]
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
      [
        "cmake",
        "--build",
        ".",
        "--target",
        "opt",
        "-j",
        str(max_build_jobs),
        "--",
        "--quiet",
      ],
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


def set_llvm_build_dir(new_dir: str):
  global __llvm_build_dir
  __llvm_build_dir = new_dir


def get_llvm_build_dir() -> str:
  return __llvm_build_dir


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
