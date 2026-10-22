# JumpThreading
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- Assuming every SetDiscriminant writes the tag is false for niche encodings' untagged variant.
- This is not a post-copy overwrite or aliasing problem: the write itself is semantically a no-op for the discriminant.
- A retained test name or old comment does not establish correctness; compare the actual MIR value assignments and edges before and after.
- In the corrected output the MIR remains unchanged: the wrong transform would replace the switchInt with a goto.
- Do not treat an Assert terminator as equivalent to assume(cond == expected).
- Do not confuse the Assume intrinsic statement with an Assert terminator; only the former is a semantic assumption.
- The new test covers Assume, not Assert; do not claim it reproduces the Assert miscompile.
- A test file or old comment mentioning assume does not establish that Assert handling was correct.
- Keep this soundness distinction separate from borrowing restrictions or copied-place overwrite concerns.
- -0.0 == 0.0 is true even though their bit patterns differ.
- NaN != NaN is true even when both operands have the same bit pattern.
- Do not special-case only zero or NaN; reject floating-point types before try_to_scalar_int.
- Do not disable all Eq/Ne threading or integer constant comparisons.
- A test that only checks an unrelated bool branch was threaded does not prove the float comparison was handled; assert that the float switchInt remains.
- Condition::inv swaps Eq and Ne and coincides with computing Not only for bool.
- `!a == b` parses as `(!a) == b`; for integers it is not the logical negation of `a == b`.
- A bool-only guard is intentionally conservative; generalizing requires actually performing a logical/bitwise Not on the condition value, not merely allowing non-bool through.
- If condition mapping can fail during const-eval, return no condition rather than keeping a truncated partial set.
- When const-eval fails while walking a switch, discard previously discovered opportunities from that switch.
- Do not infer behavior from a retained test name; in the generalized diff the correct bitwise_not result threads to the false target, not the true target.
- Keep this distinct from copy/overwrite and aliasing issues.
- Mutating target in place can corrupt a non-threaded path that later reaches the same target.
- Cloning only after mutating or reusing a duplicate with the wrong key does not preserve the invariant.
- The source warns that modifying target in-place to avoid a clone is wrong because other edges to target may not have been created yet.
- The final PR is not presented as a confirmed semantic miscompile; the retained test records a historical buggy implementation risk.
- Threading across a loop header can create irreducible control flow; loop headers must not appear in chains.
- A block may list the same successor several times; failing to deduplicate records duplicate targets/edges and can unbalance predecessor counting.
- A general SwitchInt cannot express `discr != v0 && discr != v1`; do not synthesize a negative condition unless all branch values are accounted for.
- Do not reason through inline asm; conditions are cleared for InlineAsm.
- Assert may be a codegen no-op, so it is treated as not modifying memory.
- A given branch edge's fulfilled condition is not necessarily fulfilled in the current block when some targets go elsewhere.
- This PR is about replacing a heavy search and later performance/duplication shrinkage; it is not a confirmed semantic bug fix.
- Marking the current block visited before inspecting successors loses self-loop detection.
- Using preorder instead of postorder can misclassify ordinary acyclic forward successors as maybe loop headers.
- The postorder approximation may over-approximate true loop headers relative to dominators, reducing threading opportunities but remaining conservative.
- The old dominator definition is exact only for reducible CFGs; on irreducible CFGs both old and new logic are heuristic.
- A bad loop-header set can trip the final no-threading-through-loop-header assertion or permit threading through a header.
- The supplied patch adds no regression tests and does not establish a correctness bug in the dominator-based version.

## Patterns Not Well Handled

### Do not thread over writes that are semantic no-ops: niche-encoded SetDiscriminant
JumpThreading must not model a write-like MIR statement as defining a queried value unless the operation actually writes that value. For an enum with a niche tag encoding, SetDiscriminant to the untagged variant does not write the discriminant, so the old discriminant remains. Feeding a synthesized discriminant into value analysis and threading a later Discriminant/switchInt is therefore unsound. The corrected logic processes the discriminant update only after checking the enum layout: Single/Direct encodings write, while a Niche encoding skips threading when the assigned variant is exactly the untagged variant.
Preconditions: The place type has a computable layout via layout_of(param_env.and(enum_ty)).; The enum layout is Variants::Multiple with TagEncoding::Niche, and the SetDiscriminant variant_index equals the niche untagged_variant.; A discriminant target exists through value analysis, and a later branch reads Discriminant(place) and would otherwise be threaded.; For comparison, Single encodings must still assert that the written index matches, and Direct tag encodings always write.
Pitfalls: Assuming every SetDiscriminant writes the tag is false for niche encodings' untagged variant.; This is not a post-copy overwrite or aliasing problem: the write itself is semantically a no-op for the discriminant.; A retained test name or old comment does not establish correctness; compare the actual MIR value assignments and edges before and after.; In the corrected output the MIR remains unchanged: the wrong transform would replace the switchInt with a goto.
Test strategy: Use custom MIR to build an enum value, SetDiscriminant(e, <untagged variant>), Discriminant(e), and a two-arm match. Cover both a concrete E<char> and a generic E<T>. Emit JumpThreading diffs for both panic modes and assert with `// CHECK-NOT: goto` plus `// CHECK: switchInt(` that the switch remains. Add runtime assertions such as `assert_eq!(f(), 0);` and `assert_eq!(generic::<char>(), 0);`. Use these tests as focused regression evidence, not as universal proof of equivalence.
Cases: 119675-41eb9a49aff07255f0cc28f6e435527a4435714a
Source: https://github.com/rust-lang/rust/pull/119675
> Skip threading over no-op SetDiscriminant.
> `SetDiscriminant` may be a no-op if the assigned variant is the untagged variant
> // `SetDiscriminant` does not actually write anything if the chosen variant is the untagged variant
> => *variant_index != untagged_variant,
> // CHECK-NOT: goto
> // CHECK: switchInt(
> SetDiscriminant(e, 1);
> a = Discriminant(e);

### Assert terminators are not Assume facts
JumpThreading may use genuine Assume facts, represented as a NonDivergingIntrinsic::Assume statement, but must not treat a TerminatorKind::Assert as guaranteeing cond == expected. An Assert can be compiled away at codegen time, so threading its successor to the asserted target can skip the behavior of the real runtime condition. The corrected pass ignores Assert in the opportunity finder while retaining threading through Assume. The supplied patch adds a positive Assume test; it does not add an explicit Assert-bug regression case.
Preconditions: The opportunity finder reaches an Assert terminator whose condition place has tracked conditions matching the assert's expected boolean; the old code registered an opportunity to c.target.; The assert may be a codegen no-op, so cond == expected is not a semantic invariant.; For the positive case, an Assume(b) statement is followed by a switchInt(b), allowing the edge after the assume to be retargeted to the branch matching b == true.; The custom MIR test should be run under both panic-abort and panic-unwind variants.
Pitfalls: Do not treat an Assert terminator as equivalent to assume(cond == expected).; Do not confuse the Assume intrinsic statement with an Assert terminator; only the former is a semantic assumption.; The new test covers Assume, not Assert; do not claim it reproduces the Assert miscompile.; A test file or old comment mentioning assume does not establish that Assert handling was correct.; Keep this soundness distinction separate from borrowing restrictions or copied-place overwrite concerns.
Test strategy: Build custom MIR with Assume(b); Goto(bb); switchInt(b) -> [false: bb4, otherwise: bb5] and check that JumpThreading preserves the assume and redirects the assume-derived edge to the true branch. For the Assert risk, construct an Assert whose condition/expected match a tracked condition and verify that no threading opportunity to that condition's target is registered. Compare actual block edges and value assignments, not only test names or comments. Finite MIR checks are regression evidence, not proof of semantic equivalence.
Cases: 120171-afaac75ac76cfbc38066d0474f8ca69d92ca184d
Source: https://github.com/rust-lang/rust/pull/120171
> Fix assume and assert in jump threading
> Do not thread through Assert terminator.
> Add test for jump-threading assume.
> TerminatorKind::Assert { ref cond, expected, .. }
> TerminatorKind::Assert { .. } => None

### Never use integer ScalarInt bit-pattern equality for floating-point Eq/Ne
JumpThreading stores known values as u128/ScalarInt and historically evaluated Eq/Ne as integer bit-pattern comparisons. That is unsound for floating point: -0.0 equals 0.0 despite different bit patterns, and NaN is unequal to itself even with the same pattern. The corrected pass rejects floating-point constants before converting them with try_to_scalar_int, so no float-equality condition is synthesized and the original switchInt remains. Integer equality threading remains in scope.
Preconditions: JumpThreading has a known constant for the compared operand.; The operation is BinOp::Eq or BinOp::Ne, the comparisons mapped to ScalarInt::TRUE or ScalarInt::FALSE.; The constant's type satisfies is_floating_point(), so bitwise equality would diverge from language equality.; The resulting condition would otherwise be used to thread a branch.
Pitfalls: -0.0 == 0.0 is true even though their bit patterns differ.; NaN != NaN is true even when both operands have the same bit pattern.; Do not special-case only zero or NaN; reject floating-point types before try_to_scalar_int.; Do not disable all Eq/Ne threading or integer constant comparisons.; A test that only checks an unrelated bool branch was threaded does not prove the float comparison was handled; assert that the float switchInt remains.
Test strategy: Use a MIR-opt function such as `let x = if true { -0.0 } else { 1.0 }; if x == 0.0 { 0 } else { 1 }`, with `// CHECK: switchInt(` and an EMIT_MIR diff for both panic modes. The earlier `if true` branch may legitimately be threaded, so check the right function and the retained float comparison. Add NaN and `!=` variants for stronger coverage, and keep an integer control case that may thread correctly. Runtime assertions such as `assert_eq!(floats(), 0)` are useful regression checks, but finite tests do not prove equivalence.
Cases: 128271-f305e188041b586fb162161f961298f1532fe83b, 128635-1cc8da5c1015f8ce0268f856a4de42cb9e77e218, 129033-ef56e6fe483d736ced737629245931c92aeddad7
Source: https://github.com/rust-lang/rust/pull/128271
Source: https://github.com/rust-lang/rust/pull/128635
Source: https://github.com/rust-lang/rust/pull/129033
> Disable jump threading of float equality
> Jump threading stores values as `u128` (`ScalarInt`) and does its comparisons for equality as integer comparisons.
> Floats famously have wonky equality semantcs, with `NaN!=NaN` and `0.0 == -0.0`. This does not match our beautiful integer bitpattern equality and therefore causes things to go horribly wrong.
> if value.const_.ty().is_floating_point() {
> // Floating point equality does not follow bit-patterns.
> // -0.0 and NaN both have special rules for equality,
> // and therefore we cannot use integer comparisons for them.
> // Avoid handling them, though this could be extended in the future.
> // Test for issue #128243, where float equality was assumed to be bitwise.
> // When adding float support, it must be ensured that this continues working properly.
> let value = value.const_.normalize(self.tcx, self.param_env).try_to_scalar_int()?;
> let x = if true { -0.0 } else { 1.0 };
> if x == 0.0 { 0 } else { 1 }
> // CHECK: switchInt(
> // EMIT_MIR jump_threading.floats.JumpThreading.diff

### Invert condition polarity only for bool Not; compute bitwise Not for integers
JumpThreading's condition transfer through UnOp::Not is valid as logical negation only for bool. For an integer wider than one bit, `!a` is a bitwise complement, so `!a == b` is not equivalent to `a != b`. The historical transformation inverted condition polarity for all Not operands, changing branch behavior. A conservative corrected pass guards with is_bool() and declines the transfer for non-bool operands; a more general corrected approach evaluates UnOp::Not on the tracked scalar constant, makes condition mapping fallible, and discards opportunities when const-eval fails.
Preconditions: JumpThreading sees Rvalue::UnaryOp(UnOp::Not, Operand::Move(place) | Operand::Copy(place)).; The assignment left-hand side has tracked conditions, and the source place is found in the condition map.; For the bug, the operand is a non-bool integer such as i32; for valid polarity inversion, the operand type must be bool.; If computing the integer Not, a layout must be obtainable and const-evaluation of the Not must succeed.
Pitfalls: Condition::inv swaps Eq and Ne and coincides with computing Not only for bool.; `!a == b` parses as `(!a) == b`; for integers it is not the logical negation of `a == b`.; A bool-only guard is intentionally conservative; generalizing requires actually performing a logical/bitwise Not on the condition value, not merely allowing non-bool through.; If condition mapping can fail during const-eval, return no condition rather than keeping a truncated partial set.; When const-eval fails while walking a switch, discard previously discovered opportunities from that switch.; Do not infer behavior from a retained test name; in the generalized diff the correct bitwise_not result threads to the false target, not the true target.; Keep this distinct from copy/overwrite and aliasing issues.
Test strategy: Add MIR-opt coverage for `let mut a: i32 = 0; a = 1; if !a == 0 { 1 } else { 0 }` and assert the non-bool switchInt is retained in the conservative fix, or, under a generalized fix, that it threads to the correct false branch. Add a bool logical_not case to confirm valid inversion still occurs. Exercise concrete values such as -2, -1, 0, 1, 2 and both panic modes. Include a const-eval-error case to verify no partial opportunities survive. These are regression checks, not universal equivalence proofs.
Cases: 131201-f0bfba258330884df9c9d14a0aafd741ca9bbdc9, 131203-41a5d8ef3da4769bdd4349ef540110a6e80e6c1e, 131423-1439844faaa86a593c5e20fe22dd72f1332b1dbc
Source: https://github.com/rust-lang/rust/pull/131201
Source: https://github.com/rust-lang/rust/pull/131203
Source: https://github.com/rust-lang/rust/pull/131423
> Disable jump threading `UnOp::Not` for non-bool
> Fix #131195, where jumpthreading was optimizing `!a == b` into `a != b` for non-bool, where this is definitely not true.
> if !place.ty(self.body, self.tcx).ty.is_bool() {
> // Constructing the conditions by inverting the polarity
> // of equality is only correct for bools. That is to say,
> // `!a == b` is not `a != b` for integers greater than 1 bit.
> let conds = conditions.map(self.arena, Condition::inv);
> // Transfer the conditions on the copy rhs, after inverting the value of the condition.
> // FIXME: I think This could be generalized to not bool if we
> // actually perform a logical not on the condition's value.
> // Test for #131195, which was optimizing `!a == b` into `a != b`.
> if !a == 0 { 1 } else { 0 }
> // EMIT_MIR jump_threading.bitwise_not.JumpThreading.diff
> // If we have any const-eval errors discard any opportunities found
> finder.opportunities.truncate(old_len);
> +         goto -> bb2;
> +         goto -> bb1;

### Never mutate a shared target when applying chained conditions
When applying a chained condition to a successor target, JumpThreading may still need the original target for other, not-yet-created predecessor edges, or for later duplicates. Rewriting that block in place is therefore wrong; the implementation must create or reuse a duplicate keyed by (target, condition) and leave the original target intact. A regression was specifically described as a version that mutated a block that would later be duplicated.
Preconditions: The condition graph has registered a Chain effect into a target block.; Other edges may still need the unmodified target, including edges from blocks not yet processed or future duplicates.; The duplicate cache is keyed by target and condition; the original target block must remain available.
Pitfalls: Mutating target in place can corrupt a non-threaded path that later reaches the same target.; Cloning only after mutating or reusing a duplicate with the wrong key does not preserve the invariant.; The source warns that modifying target in-place to avoid a clone is wrong because other edges to target may not have been created yet.; The final PR is not presented as a confirmed semantic miscompile; the retained test records a historical buggy implementation risk.
Test strategy: Use a nested match or chained conditions where a shared target has both a threaded edge and a non-threaded edge. The concrete differential pair can keep source behavior identical and vary only whether the threaded edge is taken: for example, with discr = 7 and take_threaded_edge = false, the original should return 27, while an in-place-mutated target incorrectly follows the discr == 0 arm and returns 17. Assert under MIR that a specialized duplicate is used and the original target still switches on the discriminant. This is focused regression evidence, not proof of general equivalence.
Cases: 142821-223620f3c6e3e276bde157c13ae20da93f1199a1
Source: https://github.com/rust-lang/rust/pull/142821
> One version of the implementation was buggy and mutated a bb that would be duplicated later.

### Condition-graph invariants: deduplicate targets, avoid loop headers, respect switch expressiveness and aliasing
The postorder condition-graph construction must preserve control-flow invariants while replacing the older backward per-switch search. Conditions may be fulfilled on some incoming paths but not others; repeated successors and duplicate Chain effects must be deduplicated; loop headers must not be threaded through; static-if switches can generate both equality and inequality predicates, while a general switch can express only equality predicates unless all branch values account for the otherwise edge. Statement writes must flood/remove conditions on aliasing places, InlineAsm clears active conditions, and Assert is treated as not modifying memory. Costs and fulfilled targets are bounded and simplified before application.
Preconditions: Cleanup blocks are skipped when building entry states, and the relevant terminator is SwitchInt whose discriminant maps to a ValueIndex.; Do not thread through maybe-loop-headers; avoid creating irreducible control flow.; For static-if, generate both `discr == value -> then` and `discr != value -> else`; for a general switch, generate only equality predicates.; When using outgoing edges, require distinct switch targets; for Ne, check all branch constants against the target values before using the otherwise edge.; Deduplicate repeated successors and duplicate EdgeEffect::Chain entries for the same condition.; A statement that mutates or partially assigns a place must flood conditions on aliasing places.; Costs are bounded by MAX_COST = 100 and MAX_PLACES = 100; cyclic costs start at MAX_COST and use saturating addition, and costly chains are removed after simplification.; Only mark an existing condition fulfilled when all its targets are covered; otherwise create a new condition index.
Pitfalls: Threading across a loop header can create irreducible control flow; loop headers must not appear in chains.; A block may list the same successor several times; failing to deduplicate records duplicate targets/edges and can unbalance predecessor counting.; A general SwitchInt cannot express `discr != v0 && discr != v1`; do not synthesize a negative condition unless all branch values are accounted for.; Do not reason through inline asm; conditions are cleared for InlineAsm.; Assert may be a codegen no-op, so it is treated as not modifying memory.; A given branch edge's fulfilled condition is not necessarily fulfilled in the current block when some targets go elsewhere.; This PR is about replacing a heavy search and later performance/duplication shrinkage; it is not a confirmed semantic bug fix.
Test strategy: Exercise `two_reads` to confirm a proven equality becomes a goto while both return arms remain correct. Use aggregate and copy forms to verify threading through aggregate constants and copies. Add `chained_conditions` with a nested match, Option<String>, string guards, and an enum so multiple conditions on one block are exercised. Include multiple-match, disappearing-block, custom-discriminant, renumbered-block, duplicate-chain, and too-complex cases for repeated successors, block reuse, and cost trimming. For differential testing, keep source behavior identical and vary only the condition-transfer shape, then compare before/after MIR. These tests are not a proof of universal equivalence.
Cases: 142821-223620f3c6e3e276bde157c13ae20da93f1199a1
Source: https://github.com/rust-lang/rust/pull/142821
> One version of the implementation was buggy and mutated a bb that would be duplicated later.

### Approximate loop headers conservatively with postorder and preserve self-loop ordering
JumpThreading avoids threading through loop headers to prevent irreducible control flow, but exact dominator-based loop-header detection can be expensive. The historical change replaces the dominator test with a postorder approximation: a maybe-loop-header is a block visited after its predecessor in postorder. This is a performance heuristic, not a confirmed bug fix, and can over-approximate headers. Its correctness edge is ordering: mark a block visited only after inspecting its successors, otherwise self-loops such as `bb1: goto -> bb1;` are missed.
Preconditions: JumpThreading has recorded threading opportunities and consults the loop-header set before starting from a switch and during the opportunity walk.; A final assertion verifies that no chain block is in the maybe-loop-header set, so debug assertions should be enabled when testing.; The CFG may contain self-loops, nested loops, switches, cleanup blocks, back edges, and irreducible CFGs.; Postorder traversal is used, and the current block is marked visited only after its successors have been checked.
Pitfalls: Marking the current block visited before inspecting successors loses self-loop detection.; Using preorder instead of postorder can misclassify ordinary acyclic forward successors as maybe loop headers.; The postorder approximation may over-approximate true loop headers relative to dominators, reducing threading opportunities but remaining conservative.; The old dominator definition is exact only for reducible CFGs; on irreducible CFGs both old and new logic are heuristic.; A bad loop-header set can trip the final no-threading-through-loop-header assertion or permit threading through a header.; The supplied patch adds no regression tests and does not establish a correctness bug in the dominator-based version.
Test strategy: Create focused MIR tests for a self-loop `bb1: goto -> bb1;`, a simple back edge, nested loops, a switch whose threading opportunity would pass through a loop header, an irreducible CFG, and an acyclic diamond. Compile with debug assertions so the final no-loop-header assertion is checked. Compare emitted MIR between dominator-based and postorder-approximation implementations. Also test the irreducible case where the exact dominator set is empty but the postorder heuristic marks a block such as 3. The supplied patch has no test changes, so these must be added; finite tests do not prove the heuristic preserves all CFG invariants.
Cases: 146829-d13a5b0a6c12837007c51f229cb8c58b614cfb5b
Source: https://github.com/rust-lang/rust/pull/146829
> This PR proposes to approximate according to the post-order traversal order. We define a "maybe" loop header as a block which is visited after its predecessor in post-order.
> +            maybe_loop_headers: maybe_loop_headers(body),
>             if !visited.contains(succ) {
