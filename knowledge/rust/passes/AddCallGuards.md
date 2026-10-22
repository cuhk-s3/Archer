# AddCallGuards
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- Do not split inline-asm edges unconditionally; only asm with outputs plus labels or an invoke-generating unwind needs the writeback edge split.
- Use pred_count[*target] > 1, not >= 1; splitting a single-predecessor target adds a redundant block.
- Check every entry of targets, not only the label target or only the fallthrough target, since each edge receives an output store.
- Do not conflate this with ordinary Call return-edge splitting; the issue is where the asm output store lands.
- The failing shape is a shared join block that is both the asm fallthrough target and the successor of a label body, allowing the asm writeback to run after the label body already stored its value.
- Treating UnwindAction::Continue or UnwindAction::Unreachable as invoke-generating would wrongly split edges with no output store path.
- Splitting an asm with outputs but neither labels nor an invoke wastes a block, because such asm only has the fallthrough edge.
- Splitting an asm with labels but no outputs is unnecessary, because there is no output writeback to place per edge.
- Applying the split outside CriticalCallEdges changes behavior beyond this fix's intended mode.
- Compute the output, label, and invoke conditions from operands and unwind rather than from the presence of any terminator edge alone.
- Checking only that some extra block exists, without checking that every callbr target stores the output once and then branches to the join, misses a partially split CFG.
- A test that only inspects IR shape can miss the stale-value overwrite; include the runtime/constant-evaluation result.
- Expect the label result to be 7 and the fallthrough result to remain the original input; do not expect the unsplit behavior of returning the stale asm value.
- Report the fixed and incorrect outcomes separately rather than claiming finite tests prove general equivalence.

## Patterns Not Well Handled

### Split critical inline-asm target edges that carry output writeback
In AddCallGuards, critical-edge splitting must cover InlineAsm terminators, not just Call terminators. An inline-asm terminator defines outputs along both its fallthrough and labeled target edges, and codegen implements that by emitting the output store directly into each target block. If a target block has more than one predecessor, the output writeback is emitted on paths that did not originate from that asm edge and can overwrite a value assigned by a label body. The pass should redirect each over-shared target through a fresh empty Goto block so every asm edge reaches a single-predecessor block before codegen places the output store.
Preconditions: The terminator is TerminatorKind::InlineAsm with asm_macro InlineAsmMacro::Asm (not another asm macro).; At least one operand is InlineAsmOperand::InOut { .. } or InlineAsmOperand::Out { .. } (has_outputs).; The asm has at least one InlineAsmOperand::Label { .. }, or generates_invoke(unwind) is true for Cleanup/Terminate.; Some entry of targets has pred_count[*target] > 1, i.e. the asm edge is critical.; The pass is running as CriticalCallEdges (if self == &CriticalCallEdges).; Each replacement bridge is a new block inheriting block.is_cleanup and the terminator source_info, redirected as *target = new_block(source_info, block.is_cleanup, *target).
Pitfalls: Do not split inline-asm edges unconditionally; only asm with outputs plus labels or an invoke-generating unwind needs the writeback edge split.; Use pred_count[*target] > 1, not >= 1; splitting a single-predecessor target adds a redundant block.; Check every entry of targets, not only the label target or only the fallthrough target, since each edge receives an output store.; Do not conflate this with ordinary Call return-edge splitting; the issue is where the asm output store lands.; The failing shape is a shared join block that is both the asm fallthrough target and the successor of a label body, allowing the asm writeback to run after the label body already stored its value.
Test strategy: Add a codegen regression test gated to only-x86_64 with -C no-prepopulate-passes, asm_goto and asm_goto_with_outputs features, and an asm! using two label {} operands plus inout("eax") a; use FileCheck to require [[OUT:%.*]] = callbr i32 asm, to label [[BB0]] [label [[BB1]], label [[BB2]]], and for each target exactly store i32 [[OUT]], ptr %a followed by br label %[[BBR]], then a load from %a and ret i32 at [[BBR]]. Pair it with a semantic reproducer (one label assigns a = 7, inout("eax") a, return a) asserting 7 rather than the original a, with and without optimizations.
Cases: 138073-02d7fc167fea5013e2300b1c5a3ca75f7a048664
Source: https://github.com/rust-lang/rust/pull/138073
> An inline asm terminator defines outputs along its target edges -- a
> fallthrough target and labeled targets. Code generation implements this
> Establish required invariant by extending existing code that breaks
> if has_outputs && (has_labels || generates_invoke(unwind)) {
> if pred_count[*target] > 1 {
> *target = new_block(source_info, block.is_cleanup, *target);
> The LLVM-IR is incorrect, as `bb2` stores the value to `ptr %a`, but `bb1` then overwrites that with the previous value in `%2`.

### Guard asm edge splitting using output, label, and invoke predicates
The inline-asm arm is entered only in CriticalCallEdges mode and splits a target only when has_outputs && (has_labels || generates_invoke(unwind)). The outputs predicate covers InOut and Out operands; the label predicate covers InlineAsmOperand::Label; the unwind predicate classifies Continue and Unreachable as non-invoke and Cleanup and Terminate as invoke-generating. This same generates_invoke predicate is reused for calls, so the invoke classification should remain shared rather than duplicated inconsistently.
Preconditions: The pass mode is CriticalCallEdges, checked with if self == &CriticalCallEdges.; has_outputs is computed over InOut { .. } and Out { .. } operands.; has_labels is computed over InlineAsmOperand::Label { .. } operands.; If the asm has no labels, an unwind of Cleanup(_) or Terminate(_) makes generates_invoke true; Continue and Unreachable do not.; A candidate target still must satisfy pred_count[*target] > 1 before it is split.
Pitfalls: Treating UnwindAction::Continue or UnwindAction::Unreachable as invoke-generating would wrongly split edges with no output store path.; Splitting an asm with outputs but neither labels nor an invoke wastes a block, because such asm only has the fallthrough edge.; Splitting an asm with labels but no outputs is unnecessary, because there is no output writeback to place per edge.; Applying the split outside CriticalCallEdges changes behavior beyond this fix's intended mode.; Compute the output, label, and invoke conditions from operands and unwind rather than from the presence of any terminator edge alone.
Test strategy: Unit-test or inspect each guard branch: asm with outputs and labels; asm with outputs and Cleanup unwind; asm with outputs and Terminate unwind; and negative cases with Continue/Unreachable unwind, with no outputs, and with no labels and no invoke. Confirm only the positive cases redirect over-shared targets to a Goto bridge, and confirm Call edge splitting still uses the same generates_invoke classification.
Cases: 138073-02d7fc167fea5013e2300b1c5a3ca75f7a048664
Source: https://github.com/rust-lang/rust/pull/138073
> if self == &CriticalCallEdges
> let has_outputs = operands.iter().any(|op| {
> matches!(op, InlineAsmOperand::InOut { .. } | InlineAsmOperand::Out { .. })
> let has_labels =
> matches!(op, InlineAsmOperand::Label { .. })
> if has_outputs && (has_labels || generates_invoke(unwind)) {
> /// Returns true if this unwind action is code generated as an invoke as opposed to a call.
> UnwindAction::Continue | UnwindAction::Unreachable => false,
> UnwindAction::Cleanup(_) | UnwindAction::Terminate(_) => true,

### Verify disjoint asm output stores and label-body semantics after splitting
Testing must check both the corrected IR placement and the observable result. In the historical unsplit CFG, the join block is shared: the label block bb2 executes store i16 7 to %a and branches to bb1, then bb1 also receives the asm output store to %a with the stale asm result, overwriting 7. The corrected shape puts the asm output store on fallthrough-only paths and then branches to a join block, so each store to the asm output occurs on a disjoint path and no asm target jumps to another callbr label. The semantic reproducer should return 7, whereas the historical behavior returns a (for example 5) with or without optimizations.
Preconditions: The test IR includes an InlineAsm callbr with output operands and at least two target edges, including a label body that falls through to the same join block used by the asm fallthrough.; The fixed CFG has distinct blocks for the asm targets, each performing the output store exactly once before a br to the join block.; The semantic test uses one label assigning a = 7, inout("eax") a, and returns a.
Pitfalls: Checking only that some extra block exists, without checking that every callbr target stores the output once and then branches to the join, misses a partially split CFG.; A test that only inspects IR shape can miss the stale-value overwrite; include the runtime/constant-evaluation result.; Expect the label result to be 7 and the fallthrough result to remain the original input; do not expect the unsplit behavior of returning the stale asm value.; Report the fixed and incorrect outcomes separately rather than claiming finite tests prove general equivalence.
Test strategy: Use FileCheck patterns that pin boundary labels and the exact store/br sequence in each target: [[OUT:%.*]] = callbr i32 asm, to label [[BB0]] [label [[BB1]], label [[BB2]]], CHECK-NEXT store i32 [[OUT]], ptr %a, CHECK-NEXT br label %[[BBR:.*]] for each of BB0, BB1, and BB2, then load from %a and ret i32 at BBR. Combine with the issue reproducer inputs (for example a = 5, label path, and fallthrough path) asserting the label path yields 7 under the fix and the fallthrough path yields the input value.
Cases: 138073-02d7fc167fea5013e2300b1c5a3ca75f7a048664
Source: https://github.com/rust-lang/rust/pull/138073
> // Regression test for #137867. Check that critical edges have been split before code generation,
> // and so all stores to the asm output occur on disjoint paths without any of them jumping to
> // another callbr label.
> // CHECK-NEXT:    store i32 [[OUT]], ptr %a
> // CHECK-NEXT:    br label %[[BBR:.*]]
> The LLVM-IR is incorrect, as `bb2` stores the value to `ptr %a`, but `bb1` then overwrites that with the previous value in `%2`.
> In particular, the value assigned to `_1` in `bb2` is returned in `bb1`.
> This should return `7`, but returns `a`, with or without optimizations.
