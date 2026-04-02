#!/usr/bin/env python3

import json
from collections import defaultdict
from pathlib import Path


def load_cases_from_review_stats(review_stats_path: Path) -> list[tuple[str, str]]:
  with open(review_stats_path, "r", encoding="utf-8") as f:
    stats = json.load(f)

  cases: list[tuple[str, str]] = []
  for state in ["open", "closed"]:
    state_cases = stats.get(state, {})
    for case_id in state_cases.keys():
      cases.append((state, case_id))

  cases.sort(key=lambda x: int(x[1]))
  return cases


def get_case_files(dataset_root: Path, case_state: str, case_id: str) -> list[str]:
  case_path = dataset_root / case_state / f"{case_id}.json"
  if not case_path.exists():
    print(f"Warning: Missing dataset case file: {case_path}")
    return []

  with open(case_path, "r", encoding="utf-8") as f:
    data = json.load(f)

  patch_location = data.get("patch_location_lineno", {})
  if not isinstance(patch_location, dict):
    return []
  return list(patch_location.keys())


def filter(files_per_commit: list[list[str]]) -> list[list[str]]:
  filtered_files = []
  for files in files_per_commit:
    new_files = []
    for file in files:
      if (
        file.startswith("llvm/test")
        or file.startswith("clang/test")
        or file.startswith("cross-project-tests")
        or file.startswith("compiler-rt")
        or file.startswith("gcc/testsuite")
        or file.startswith("libgomp")
        or file.startswith("gcc/flag-types.h")
        or file == "gcc/tree.h"
        or file == "gcc/wide-int.h"
        or file == "gcc/stor-layout.h"
        or file.startswith("llvm/docs")
      ):
        continue
      new_files.append(file)
    filtered_files.append(new_files)
  return filtered_files


conversion_map = {
  "llvm/lib/Analysis/CaptureTracking.cpp": "Escape Analysis",
  "llvm/lib/Transforms/InstCombine/InstructionCombining.cpp": "Peephole Optimizations",
  "llvm/lib/Transforms/AggressiveInstCombine/AggressiveInstCombine.cpp": "Peephole Optimizations",
  "llvm/lib/Transforms/InstCombine/InstCombineSelect.cpp": "Peephole Optimizations",
  "llvm/lib/Transforms/InstCombine/InstCombineNegator.cpp": "Peephole Optimizations",
  "llvm/lib/Transforms/InstCombine/InstCombineAndOrXor.cpp": "Peephole Optimizations",
  "llvm/lib/Transforms/InstCombine/InstCombineSimplifyDemanded.cpp": "Peephole Optimizations",
  "llvm/lib/Transforms/Utils/Local.cpp": "Peephole Optimizations",
  "llvm/lib/Analysis/InstructionSimplify.cpp": "Peephole Optimizations",
  "llvm/include/llvm/Transforms/Utils/Local.h": "Peephole Optimizations",
  "llvm/include/llvm/Transforms/Utils/InstructionWorklist.h": "Peephole Optimizations",
  "llvm/include/llvm/Transforms/InstCombine/InstCombine.h": "Peephole Optimizations",
  "llvm/include/llvm/Transforms/InstCombine/InstCombiner.h": "Peephole Optimizations",
  "llvm/lib/Transforms/InstCombine/InstCombineCalls.cpp": "Peephole Optimizations",
  "llvm/lib/Transforms/InstCombine/InstCombineCompares.cpp": "Peephole Optimizations",
  "llvm/lib/Transforms/InstCombine/InstCombineLoadStoreAlloca.cpp": "Peephole Optimizations",
  "llvm/lib/Transforms/InstCombine/InstCombineInternal.h": "Peephole Optimizations",
  "llvm/lib/Analysis/ValueTracking.cpp": "Value Range Analysis",
  "llvm/include/llvm/Analysis/ValueTracking.h": "Value Range Analysis",
  "llvm/lib/Support/KnownBits.cpp": "Value Range Analysis",
  "llvm/include/llvm/Support/KnownBits.h": "Value Range Analysis",
  "llvm/lib/Analysis/LazyValueInfo.cpp": "Value Range Analysis",
  "llvm/lib/Analysis/AliasSetTracker.cpp": "Alias Analysis",
  "llvm/include/llvm/Analysis/AliasSetTracker.h": "Alias Analysis",
  "llvm/unittests/Analysis/AliasSetTrackerTest.cpp": "Alias Analysis",
  "llvm/lib/Transforms/Utils/SimplifyCFG.cpp": "CFG Transformations",
  "llvm/lib/Transforms/Scalar/CorrelatedValuePropagation.cpp": "Value Range Propagation",
  "llvm/include/llvm/Transforms/IPO/FunctionAttrs.h": "Interprocedural Analysis",
  "llvm/lib/Transforms/IPO/FunctionAttrs.cpp": "Interprocedural Analysis",
  "llvm/lib/Transforms/IPO/ArgumentPromotion.cpp": "Interprocedural Optimization",
  "llvm/lib/Analysis/CGSCCPassManager.cpp": "Pass Management",
  "llvm/lib/Passes/PassBuilder.cpp": "Pass Management",
  "llvm/lib/Passes/PassBuilderPipelines.cpp": "Pass Management",
  "llvm/lib/Passes/PassRegistry.def": "Pass Management",
  "llvm/lib/Transforms/Scalar/JumpThreading.cpp": "Jump Threading",
  "llvm/include/llvm/Transforms/Scalar/GVN.h": "Global Value Numbering",
  "llvm/lib/Transforms/Scalar/GVN.cpp": "Global Value Numbering",
  "llvm/lib/Transforms/Scalar/DeadStoreElimination.cpp": "Dead Store Elimination",
  "llvm/lib/Transforms/Scalar/LICM.cpp": "Loop Transformations",
  "llvm/lib/Transforms/Scalar/LoopRerollPass.cpp": "Loop Transformations",
  "llvm/lib/Transforms/Scalar/SimpleLoopUnswitch.cpp": "Loop Transformations",
  "llvm/lib/Transforms/Utils/LoopUnroll.cpp": "Loop Transformations",
  "llvm/lib/Transforms/Utils/LoopPeel.cpp": "Loop Transformations",
  "llvm/lib/Transforms/Scalar/ConstraintElimination.cpp": "Dominance based Optimizations",
  "llvm/include/llvm/Transforms/Utils/LoopUtils.h": "Loop Transformations",
  "llvm/lib/Analysis/AssumptionCache.cpp": "Assumption Handling",
  "llvm/lib/Transforms/Scalar/EarlyCSE.cpp": "CSE",
  "gcc/tree-data-ref.cc": "Data Dependence Analysis",
  "gcc/value-query.cc": "Value Range Analysis",
  "gcc/value-range-storage.cc": "Value Range Analysis",
  "gcc/value-range-storage.h": "Value Range Analysis",
  "gcc/value-range.cc": "Value Range Analysis",
  "gcc/value-range.h": "Value Range Analysis",
  "gcc/vr-values.cc": "Value Range Analysis",
  "gcc/vr-values.h": "Value Range Analysis",
  "gcc/tree-vrp.h": "Value Range Propagation",
  "gcc/tree-vrp.c": "Value Range Propagation",
  "gcc/tree-vrp.cc": "Value Range Propagation",
  "gcc/tree-ssa-threadbackward.c": "Jump Threading",
  "gcc/tree-ssa-threadbackward.cc": "Jump Threading",
  "gcc/tree-ssa-threadedge.c": "Jump Threading",
  "gcc/tree-ssa-threadedge.cc": "Jump Threading",
  "gcc/tree-ssa-threadedge.h": "Jump Threading",
  "gcc/tree-ssa-threadupdate.c": "Jump Threading",
  "gcc/tree-ssa-threadupdate.h": "Jump Threading",
  "gcc/tree-ssa-dse.c": "Dead Store Elimination",
  "gcc/tree-ssa-dse.cc": "Dead Store Elimination",
  "gcc/tree-cfg.cc": "CFG Transformations",
  "gcc/tree-cfg.h": "CFG Transformations",
  "gcc/tree-ssa-dce.cc": "Dead Code Elimination",
  "gcc/tree-ssa-dce.h": "Dead Code Elimination",
  "gcc/tree-inline.cc": "Inlining",
  "gcc/tree-ssa-ccp.cc": "Constant Propagation",
  "gcc/gimple-range-cache.cc": "Value Range Analysis",
  "gcc/gimple-range-cache.h": "Value Range Analysis",
  "gcc/gimple-range-edge.cc": "Value Range Analysis",
  "gcc/gimple-range-edge.h": "Value Range Analysis",
  "gcc/gimple-range-gori.cc": "Value Range Analysis",
  "gcc/gimple-range-infer.cc": "Value Range Analysis",
  "gcc/gimple-range-infer.h": "Value Range Analysis",
  "gcc/gimple-range-path.cc": "Value Range Analysis",
  "gcc/tree-vect-loop-manip.cc": "Loop Transformations",
  "gcc/tree-ssa-loop-ch.cc": "Loop Transformations",
  "gcc/tree-ssa-loop-im.c": "Loop Transformations",
  "gcc/tree-ssa-loop-im.cc": "Loop Transformations",
  "gcc/tree-ssa-loop-manip.cc": "Loop Transformations",
  "gcc/tree-ssa-loop-manip.h": "Loop Transformations",
  "gcc/tree-ssa-loop-unswitch.cc": "Loop Transformations",
  "gcc/tree-loop-distribution.cc": "Loop Transformations",
  "gcc/tree-parloops.cc": "Loop Transformations",
  "gcc/gimple-loop-jam.cc": "Loop Transformations",
  "gcc/tree-if-conv.cc": "Loop Transformations",
  "gcc/match.pd": "Peephole Optimizations",
  "gcc/generic-match-head.cc": "Peephole Optimizations",
  "gcc/tree-scalar-evolution.cc": "Loop Analysis",
  "gcc/tree-ssa-sccvn.cc": "Value Numbering",
  "gcc/params.opt": "Pass Management",
  "gcc/passes.cc": "Pass Management",
  "gcc/passes.def": "Pass Management",
  "gcc/tree-pass.h": "Pass Management",
  "gcc/range-op.cc": "Value Range Propagation",
  "gcc/fold-const.cc": "Constant Propagation",
  "gcc/gimple-fold.cc": "Constant Propagation",
  "gcc/predict.cc": "Branch Prediction",
  "gcc/profile-count.h": "Profile Guided Optimizations",
  "gcc/tree-core.h": "IR Data Structures",
  "gcc/tree-ssa-strlen.cc": "IR Data Structures",
  "gcc/tree-ssanames.cc": "IR Data Structures",
  "gcc/tree-ssa-propagate.cc": "Value Range Propagation",
  "gcc/tree-ssa-dom.cc": "CFG Transformations",
  "gcc/tree-ssa-phiopt.cc": "CFG Transformations",
  "gcc/tree-ssa-pre.cc": "Redundancy Elimination",
  # added by someone1:
  "gcc/combine.cc": "Peephole Optimizations",
  "gcc/config/i386/i386.md": "Peephole Optimizations",
  "gcc/gimple-match-head.cc": "Peephole Optimizations",
  "gcc/gimple-range-fold.cc": "Value Range Analysis",
  "gcc/stor-layout.h,gcc": "Loop Transformations",
  "gcc/tree-predcom.cc": "Predictive Commoning",
  "gcc/tree-ssa-ifcombine.cc": "CFG Transformations",
  "gcc/tree-ssa-live.cc": "Liveness Analysis",
  "gcc/tree-ssa-live.h": "Liveness Analysis",
  "gcc/tree-ssa-loop-ivcanon.cc": "Loop Transformations",
  "gcc/tree-ssa-loop-ivopts.cc": "Loop Transformations",
  "gcc/tree-ssa-reassoc.cc": "Peephole Optimizations",
  "gcc/tree-ssa-sink.cc": "IR Data Structures",
  "gcc/tree-vect-data-refs.cc": "Vectorization",
  "gcc/tree-vect-loop.cc": "Vectorization",
  "gcc/tree-vect-patterns.cc": "Vectorization",
  "gcc/range": "Value Range Analysis",
  "gcc/ipa-cp.cc": "IPA constant propagation",
  "gcc/simplify-rtx.cc": "Peephole Optimizations",
  "llvm/include/llvm/Analysis/AliasAnalysis.h": "Alias Analysis",
  "llvm/include/llvm/Analysis/CaptureTracking.h": "Alias Analysis",
  "llvm/include/llvm/Analysis/IVUsers.h": "Induction Variable Users Analysis",
  "llvm/include/llvm/Analysis/ScalarEvolution.h": "Scalar Evolution Analysis",
  "llvm/include/llvm/CodeGen/TargetInstrInfo.h": "Backend",
  "llvm/include/llvm/Transforms/Utils/ScalarEvolutionExpander.h": "Scalar Evolution Analysis",
  "llvm/lib/Analysis/BasicAliasAnalysis.cpp": "Alias Analysis",
  "llvm/lib/Analysis/IVUsers.cpp": "Induction Variable Transformations",
  "llvm/lib/Analysis/ScalarEvolution.cpp": "Scalar Evolution Analysis",
  "llvm/lib/CodeGen/LiveDebugValues/InstrRefBasedImpl.cpp": "Backend",
  "llvm/lib/CodeGen/LiveDebugValues/VarLocBasedImpl.cpp": "Backend",
  "llvm/lib/CodeGen/SelectionDAG/DAGCombiner.cpp": "Selection DAG",
  "llvm/lib/CodeGen/SelectionDAG/SelectionDAGAddressAnalysis.cpp": "Selection DAG",
  "llvm/lib/CodeGen/SelectionDAG/TargetLowering.cpp": "Selection DAG",
  "llvm/lib/Target/AArch64/AArch64InstrInfo.cpp": "Backend",
  "llvm/lib/Target/X86/X86ISelDAGToDAG.cpp": "Backend",
  "llvm/lib/Target/X86/X86ISelLowering.cpp": "Backend",
  "llvm/lib/Transforms/IPO/PassManagerBuilder.cpp": "Pass Management",
  "llvm/lib/Transforms/InstCombine/InstCombineCasts.cpp": "Peephole Optimizations",
  "llvm/lib/Transforms/InstCombine/InstCombineMulDivRem.cpp": "Peephole Optimizations",
  "llvm/lib/Transforms/Scalar/IndVarSimplify.cpp": "Induction Variable Transformations",
  "llvm/lib/Transforms/Scalar/LoopFlatten.cpp": "Loop Transformations",
  "llvm/lib/Transforms/Scalar/LoopStrengthReduce.cpp": "Loop Transformations",
  "llvm/lib/Transforms/Utils/ScalarEvolutionExpander.cpp": "Scalar Evolution Analysis",
  "llvm/lib/Transforms/Utils/SimplifyIndVar.cpp": "Induction Variable Transformations",
  "llvm/lib/Transforms/Vectorize/LoopVectorize.cpp": "Loop Transformations",
  "llvm/lib/Transforms/Vectorize/SLPVectorizer.cpp": "SLP Vectorization",
  "llvm/lib/Transforms/Vectorize/VPlanRecipes.cpp": "Loop Transformations",
  "llvm/lib/Transforms/Vectorize/VectorCombine.cpp": "Vectorization Optimization",
  "llvm/gvn": "Global Value Numbering",
  "llvm/backend": "Backend",
  "llvm/peephole": "Peephole Optimizations",
  # added by someone2
  "gcc/cfgexpand.cc": "Backend",  # https://gcc.gnu.org/bugzilla/show_bug.cgi?id=117426
  "gcc/expr.cc": "Backend",  # https://gcc.gnu.org/bugzilla/show_bug.cgi?id=118684
  "gcc/tree-eh.cc": "Loop Invariant Motion",  # Loop Invariant Motion? https://github.com/gcc-mirror/gcc/commit/f1e776ce58ae4a6ae67886adb4ae806598e2c7ef
  "gcc/tree-ssa-loop-niter.cc": "Number of Iterations Analysis",
  "llvm/include/llvm/ADT/APFloat.h": "Selection DAG",  # https://github.com/llvm/llvm-project/pull/128618
  "llvm/include/llvm/Analysis/MemorySSAUpdater.h": "Loop Invariant Code Motion",  # https://github.com/llvm/llvm-project/issues/116228
  "llvm/lib/Analysis/MemorySSAUpdater.cpp": "Loop Invariant Code Motion",  # https://github.com/llvm/llvm-project/issues/116228
  "llvm/lib/Support/APFloat.cpp": "Selection DAG",  # https://github.com/llvm/llvm-project/pull/128618
  "llvm/lib/Transforms/InstCombine/InstCombinePHI.cpp": "Peephole Optimizations",
  "llvm/lib/Transforms/Vectorize/VPRecipeBuilder.h": "Vectorization Optimization",
  "llvm/lib/Transforms/Vectorize/VPlanTransforms.cpp": "Vectorization Optimization",
  "llvm/lib/Transforms/Vectorize/VPlanUtils.h": "Vectorization Optimization",
  "llvm/lib/CodeGen/CodeGenPrepare.cpp": "Backend",
  # added in archer
  "llvm/include/llvm/Analysis/PtrUseVisitor.h": "Alias Analysis",
  "llvm/include/llvm/IR/FMF.h": "Peephole Optimizations",
  "llvm/include/llvm/IR/PatternMatch.h": "Peephole Optimizations",
  "llvm/include/llvm/Transforms/Scalar/TailRecursionElimination.h": "Loop Transformations",
  "llvm/include/llvm/Transforms/Utils/Cloning.h": "Inlining",
  "llvm/include/llvm/Transforms/Vectorize/LoopVectorizationLegality.h": "Loop Transformations",
  "llvm/lib/Analysis/ConstantFolding.cpp": "Constant Propagation",
  "llvm/lib/Analysis/Delinearization.cpp": "Loop Transformations",
  "llvm/lib/Analysis/MemoryDependenceAnalysis.cpp": "Alias Analysis",
  "llvm/lib/Analysis/PtrUseVisitor.cpp": "Alias Analysis",
  "llvm/lib/Transforms/Coroutines/CoroCleanup.cpp": "Coroutines",
  "llvm/lib/Transforms/Coroutines/CoroEarly.cpp": "Coroutines",
  "llvm/lib/Transforms/IPO/ForceFunctionAttrs.cpp": "Interprocedural Analysis",
  "llvm/lib/Transforms/IPO/IROutliner.cpp": "Interprocedural Optimization",
  "llvm/lib/Transforms/Scalar/LowerMatrixIntrinsics.cpp": "Loop Transformations",
  "llvm/lib/Transforms/Scalar/Reassociate.cpp": "Peephole Optimizations",
  "llvm/lib/Transforms/Scalar/TailRecursionElimination.cpp": "Loop Transformations",
  "llvm/lib/Transforms/Utils/BasicBlockUtils.cpp": "CFG Transformations",
  "llvm/lib/Transforms/Utils/CloneFunction.cpp": "Inlining",
  "llvm/lib/Transforms/Utils/InlineFunction.cpp": "Inlining",
  "llvm/lib/Transforms/Utils/SimplifyLibCalls.cpp": "Peephole Optimizations",
  "llvm/lib/Transforms/Vectorize/LoopIdiomVectorize.cpp": "Loop Transformations",
  "llvm/lib/Transforms/Vectorize/LoopVectorizationLegality.cpp": "Loop Transformations",
  "llvm/lib/Transforms/Vectorize/LoopVectorizationPlanner.h": "Loop Transformations",
  "llvm/lib/Transforms/Vectorize/VPlan.cpp": "Loop Transformations",
  "llvm/lib/Transforms/Vectorize/VPlanConstruction.cpp": "Loop Transformations",
  "llvm/lib/Transforms/Vectorize/VPlanTransforms.h": "Vectorization Optimization",
  "llvm/utils/profcheck-xfail.txt": "Pass Management",
}


def convert_files_to_categories(
  files_per_case: list[list[str]], case_labels: list[str]
) -> list[list[str]]:
  categories_per_case = []

  for i, files in enumerate(files_per_case):
    categories = []
    case_label = case_labels[i]
    print(f"\n[Case {case_label}]")
    for file in files:
      if file not in conversion_map:
        print(f"  WARNING: unmapped file skipped: {file}")
        continue
      category = conversion_map[file]
      categories.append(category)
      print(f"  {file} -> {category}")
    categories_per_case.append(categories)

  return categories_per_case


def compute_category_stats(
  categories_per_commit: list[list[str]],
) -> list[tuple[str, int, int]]:
  category_commits: dict[str, int] = defaultdict(int)
  category_files: dict[str, int] = defaultdict(int)
  for categories in categories_per_commit:
    for category in set(categories):
      category_commits[category] += 1
    for category in categories:
      category_files[category] += 1
  return [
    (category, category_commits[category], category_files[category])
    for category in sorted(category_files.keys())
  ]


def print_table_and_stats(
  compiler: str, category_stats: list[tuple[str, int, int]]
) -> None:
  num = 0
  print(f"\nAffected {compiler} components:\n")
  print("Component\t#Bugs")
  print("-" * 30)
  for stat in category_stats:
    print(f"{stat[0]}, {stat[1]}")
    num += int(stat[1])
  print(f"Total: {num}")
  print("*" * 30)


if __name__ == "__main__":
  review_stats_path = Path("review_stats.json")
  dataset_root = Path("/data/archer/projects/Archer/dataset")
  print(f"Reading {review_stats_path}...")

  assert review_stats_path.exists(), f"Missing {review_stats_path}"
  assert dataset_root.exists(), f"Missing {dataset_root}"

  cases = load_cases_from_review_stats(review_stats_path)
  case_labels = [f"{state}/{case_id}" for state, case_id in cases]
  files_per_case = [
    get_case_files(dataset_root, case_state, case_id) for case_state, case_id in cases
  ]
  files_per_case = filter(files_per_case)

  unknown_files = set(
    file for files in files_per_case for file in files if file not in conversion_map
  )
  if unknown_files:
    print("\nWarning: Unknown files found (will be skipped):")
    for file in sorted(unknown_files):
      print(file)

  llvm_categories_per_case = convert_files_to_categories(files_per_case, case_labels)
  llvm_category_stats = compute_category_stats(llvm_categories_per_case)

  print_table_and_stats(
    "LLVM", sorted(llvm_category_stats, key=lambda x: x[1], reverse=True)
  )
