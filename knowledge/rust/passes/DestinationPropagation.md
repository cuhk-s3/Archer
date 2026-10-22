# DestinationPropagation
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- Confusing this post-copy overwrite hazard with borrowed-local restrictions or intra-statement aggregate aliasing; they are distinct safety conditions.
- Renaming all uses without respecting later definitions: post-copy writes to the source become writes to the destination and corrupt the saved value.
- Trusting a retained test name or comment that says `miscompile` rather than comparing the actual value assignments in the old and new MIR.
- Assuming the pass must leave the MIR untouched; other legal eliminations or local choices may still change, so focus on whether the saved value is clobbered.
- Assuming a destination local may always be replaced by its source simply because a local-to-local copy exists.
- Forgetting that the argument's old value can be used later, so propagating the new assignment across that boundary is unsafe.
- Treating a test comment or label as sufficient evidence without checking the actual `dummy(move [[x]])` and subsequent assignment lines.
- Expecting RenameReturnPlace behavior or its NRVO-style elimination from the replacement pass.
- Treating failure to eliminate a borrowed-local copy as evidence of a miscompile; `DestinationPropagation` explicitly does not handle borrowed locals.
- Conflating the borrowed-local restriction with the separate post-copy overwrite unsoundness of RenameReturnPlace.
- Claiming compiler execution or runtime reproduction from MIR expectation diffs alone.
- Reusing the initially saved liveness without mirroring merges, leaving later rounds with stale liveness and potentially accepting an unsafe merge.
- Mirroring in the wrong direction, giving `src` the liveness of `dest` instead of giving `dest` the liveness of `src`.
- Treating the saved approximation as exact: assignment cycles can leave extra live points and cause missed optimizations, described as suboptimal and rare, not a correctness failure.
- Mismatching the statement/terminator point used for saving liveness with the point used for conflict filtering.
- Assuming `save_as_intervals` works independently of the expected flow-state representation; it requires the analysis flow state to be `ChunkedBitSet<N>` and inserts states only at visited points.
- Conflating intra-statement overlapping aggregate reads/writes with post-copy source overwrites or borrowed-local restrictions; these are separate hazards.
- Describing the intended same-projection copy/move exception as part of the bug: marking `_b` live in `_a.stuff = {copy|move} _b.stuff` would prevent legal unification.
- Assuming the pass should leave everything untransformed; legal unification of disjoint locals may still produce a `nop`, and the old/new outputs may differ in which local holds an initial constant.
- Checking only that some transformation occurred rather than whether the aggregate destination aliases a local read by that aggregate.
- Treating a retained test name or comment as proof; compare actual field operands and locals on each side.

## Patterns Not Well Handled

### Do not propagate a copied value across a later overwrite of its source local
For DestinationPropagation, a local may be copied into a destination and then overwritten. The value already copied must remain the value observed by later reads/returns; redirecting uses across the later source assignment is unsound. Historically, RenameReturnPlace renamed every use of the copied local to `_0`, including later definitions, so `_2 = _1; _0 = _2; _2 = const 'b';` became `_0 = _1; _0 = const 'b';`, clobbering the return value. The replacement transformation must instead preserve the copy into `_0` and keep the later write attached to the source local.
Preconditions: A candidate MIR assignment copies a source local into the return place or another destination, e.g. `_0 = _2` or `[[y]] = [[x]]`.; The source local is assigned again after that copy and before the copied destination value is consumed/returned, e.g. `_2 = const 'b';` or `[[x]] = const 123_i32;`.; The destination value saved before the overwrite must remain observable afterward; a condition such as `_0` not being read before `Return` is not by itself sufficient.; The test may be custom MIR encoding exact assignment order, or an ordinary Rust function such as `let y = x; x = 123;`.
Pitfalls: Confusing this post-copy overwrite hazard with borrowed-local restrictions or intra-statement aggregate aliasing; they are distinct safety conditions.; Renaming all uses without respecting later definitions: post-copy writes to the source become writes to the destination and corrupt the saved value.; Trusting a retained test name or comment that says `miscompile` rather than comparing the actual value assignments in the old and new MIR.; Assuming the pass must leave the MIR untouched; other legal eliminations or local choices may still change, so focus on whether the saved value is clobbered.
Test strategy: Use `//@ test-mir-pass: DestinationPropagation` with `EMIT_MIR` diffs. Build two custom-MIR or Rust cases differing only in whether the source is overwritten after the copy: `dest = source; source = new_value;` versus no overwrite. Assert the copied destination still receives the original value and that later writes target the source local, not the destination. For the `let y = x; x = 123;` form, assert `[[y]] = [[x]]`, then `[[x]] = const 123_i32;`, and `CHECK-NOT: {{_.*}} = [[y]];`. These concrete checks are regression evidence, not proof of universal equivalence.
Cases: 115105-5fa0ec6ad17cd002e9359345bbeae4601c03fd53, 122300-2d5a4832f30d246b81c775aa5bf9003997568b65
Source: https://github.com/rust-lang/rust/pull/115105
Source: https://github.com/rust-lang/rust/pull/122300
> This pass looks for MIR that always copies the same local into the return place and eliminates
> Replaces all uses of `self.to_rename` with `_0`.
> // This is a miscompilation, #111005 to track
> // unsound: #111005
> // Don't propagate this assignment to `y`
> // CHECK: [[y]] = [[x]]
> // CHECK: [[x]] = const 123_i32;
> // CHECK-NOT: {{_.*}} = [[y]];

### Do not propagate assignments into a still-live function argument
DestinationPropagation must not replace an assignment to a function argument when the original argument value may still be used. Assigning a new value into an argument local is safe in the program, but redirecting that assignment through the argument's source can break uses of the original argument value. Tests explicitly guard `x = dummy(x)`-style and `dummy(x); x = 5`-style boundaries.
Preconditions: The destination local is a function argument whose original value remains live or is used after the assignment.; The assignment may come from a call result, a self-assignment, or another local, as in `x = dummy(x)`.; The emitted MIR is inspected after DestinationPropagation to ensure the argument assignment was not propagated away.; The test may include mutable arguments and nearby safe cases where propagation is still permitted.
Pitfalls: Assuming a destination local may always be replaced by its source simply because a local-to-local copy exists.; Forgetting that the argument's old value can be used later, so propagating the new assignment across that boundary is unsafe.; Treating a test comment or label as sufficient evidence without checking the actual `dummy(move [[x]])` and subsequent assignment lines.
Test strategy: Use the MIR-opt FileCheck harness with `//@ test-mir-pass: DestinationPropagation`. Assert the call still uses the original argument, `// CHECK: dummy(move [[x]])`, followed by an assignment back into the same local, `// CHECK: [[x]] = move {{_.*}};`, and include a `dummy(x); x = 5` case checking `[[x]] = const 5_u8;`. Pair it with a safe temporary-destination case to show propagation can still occur when the original argument value is not needed.
Cases: 122300-2d5a4832f30d246b81c775aa5bf9003997568b65
Source: https://github.com/rust-lang/rust/pull/122300
> // Check that DestinationPropagation does not propagate an assignment to a function argument
> // (doing so can break usages of the original argument value)
> // CHECK: dummy(move [[x]])
> // CHECK: [[x]] = move {{_.*}};

### Borrowed locals are conservatively excluded from destination propagation
DestinationPropagation is a general copy/destination propagation pass, not an NRVO-only pass, but it deliberately does not handle borrowed locals. A local borrowed through `&mut` before a copy may remain in place even if an unrelated copy is eliminated. This conservative behavior is not a miscompile. The pass replaces the removed unsound RenameReturnPlace pass in the pipeline and is enabled at `mir_opt_level >= 2` rather than only at level 3.
Preconditions: A candidate MIR local is borrowed, for example `_6 = &mut _2`, before or around a copy involving that local.; DestinationPropagation is enabled by default at `mir_opt_level >= 2` and occupies the pipeline position previously used by RenameReturnPlace.; Expectations should allow the borrowed local/copy to remain; unrelated non-borrowed copies may still be eliminated.
Pitfalls: Expecting RenameReturnPlace behavior or its NRVO-style elimination from the replacement pass.; Treating failure to eliminate a borrowed-local copy as evidence of a miscompile; `DestinationPropagation` explicitly does not handle borrowed locals.; Conflating the borrowed-local restriction with the separate post-copy overwrite unsoundness of RenameReturnPlace.; Claiming compiler execution or runtime reproduction from MIR expectation diffs alone.
Test strategy: Add a case with `&mut local` before the copy and assert the borrowed local/copy is conservatively retained, while an unrelated copy such as `_4 = _1` may be eliminated. Use `//@ test-mir-pass: DestinationPropagation` and `EMIT_MIR` diffs. Keep the old RenameReturnPlace miscompile regression test for the replacement pass, but verify actual assignments rather than relying on the retained comment.
Cases: 115105-5fa0ec6ad17cd002e9359345bbeae4601c03fd53
Source: https://github.com/rust-lang/rust/pull/115105
> `DestinationPropagation` is not limited to `_0`, but does not handle borrowed locals.
> At the same time, this PR removes the `RenameReturnPlace` pass, as it is currently unsound.
> -        sess.mir_opt_level() >= 3
> +        sess.mir_opt_level() >= 2
> -            &nrvo::RenameReturnPlace,
> +            &dest_prop::DestinationPropagation,

### Mirror accepted merges into saved liveness when caching MaybeLiveLocals
DestinationPropagation historically recomputed MaybeLiveLocals for each propagation round. Saving one liveness result as a `SparseIntervalMatrix` is valid only if every accepted `src -> dest` merge is mirrored into the destination's liveness row: `liveness(destination) := liveness(destination) union liveness(source)`. Without this mirror, later rounds filter candidates against stale liveness and may accept an unsafe merge. With the mirror, the saved approximation can miss some optimizations for assignment cycles but should not introduce the stale-liveness miscompile.
Preconditions: DestinationPropagation runs multiple rounds with candidate local merges, such as `dest = src` assignments.; MaybeLiveLocals is iterated to a fixpoint once and saved via `save_as_intervals` into a `SparseIntervalMatrix`.; The liveness lookup point matches the stored point, using `point_from_location(location)` after the primary effect rather than a shifted block-entry or old seek convention.; After each accepted merge `src -> dest`, `union_rows(src, dest)` gives the destination all points where the source was live, and both locals are marked merged/used so each local participates in at most one merge per round.
Pitfalls: Reusing the initially saved liveness without mirroring merges, leaving later rounds with stale liveness and potentially accepting an unsafe merge.; Mirroring in the wrong direction, giving `src` the liveness of `dest` instead of giving `dest` the liveness of `src`.; Treating the saved approximation as exact: assignment cycles can leave extra live points and cause missed optimizations, described as suboptimal and rare, not a correctness failure.; Mismatching the statement/terminator point used for saving liveness with the point used for conflict filtering.; Assuming `save_as_intervals` works independently of the expected flow-state representation; it requires the analysis flow state to be `ChunkedBitSet<N>` and inserts states only at visited points.
Test strategy: Construct MIR with several locals and chained assignments such as `a = b; b = c; c = d;` plus reads through the eventual destination, forcing multiple rounds. Compare accepted merges and dumped `DestinationPropagation-dataflow` liveness between per-round recomputation and the saved-matrix version with the merge mirror. As negative controls, run a cached variant that omits the mirror after merges and one that mirrors in the wrong direction; these should expose stale or reversed liveness on multi-round merges. Include an assignment-cycle case to confirm only missed optimizations, not miscompilation. Use `-Zdump-mir=DestinationPropagation` / `-Zdump-mir=DestinationPropagation-dataflow` and mir-opt checks; no compiler execution is claimed here.
Cases: 115291-1d6723a77a642850e60559c7d9c64b4b5233c9be
Source: https://github.com/rust-lang/rust/pull/115291
> To get the liveness information, the pass runs `MaybeLiveLocals` dataflow analysis repeatedly, once for each propagation round. This is quite costly
> this PR proposes to save the result of the analysis into a `SparseIntervalMatrix`, and mirror merges of locals into that matrix: `liveness(destination) := liveness(destination) union liveness(source)`
> Because we only filter once per round, it is unsound to use a local for more than
> Update liveness information based on the merge we just performed.
> Every location where `src` was live, `dest` will be live.
> live.union_rows(*src, *dest);
> This approximate liveness results is only suboptimal if there are locals that fully disappear from the CFG due to an assignment cycle. These cases are quite unlikely, so we do not bother with them.

### Keep intra-statement reads live to avoid overlapping aggregate assignments
DestinationPropagation's liveness construction previously marked only Def/PartialWrite places at the statement's second half, so a local read inside an aggregate rvalue could appear dead before the statement finished. That allowed unifying an aggregate destination with a local read by the same aggregate. A swap-like `_2 = copy _1; _1 = (_2.1, _2.0)` could then become the self-overlapping `_1 = (_1.1, _1.0)`, where writing one field destroys a value still needed for another field. The fix treats statement reads as live through the statement by default, with a narrow exception for simple same-projection copy/move assignments.
Preconditions: The MIR statement's rvalue interleaves reads and writes, canonically `Rvalue::Aggregate` with multiple field operands, such as `_1 = (copy (_2.1), copy (_2.0))`.; The aggregate destination local is otherwise eligible for unification with a local read in that same statement.; Under the old scheme, the read local's interval ended at the statement's `twostep` because only `DefUse::Def | DefUse::PartialWrite` were marked live for the second half.; The exception applies only to simple assignments where `lhs.projection == rhs.projection`; those must remain unifiable, so tests must not globally forbid all statement reads from being marked live.
Pitfalls: Conflating intra-statement overlapping aggregate reads/writes with post-copy source overwrites or borrowed-local restrictions; these are separate hazards.; Describing the intended same-projection copy/move exception as part of the bug: marking `_b` live in `_a.stuff = {copy|move} _b.stuff` would prevent legal unification.; Assuming the pass should leave everything untransformed; legal unification of disjoint locals may still produce a `nop`, and the old/new outputs may differ in which local holds an initial constant.; Checking only that some transformation occurred rather than whether the aggregate destination aliases a local read by that aggregate.; Treating a retained test name or comment as proof; compare actual field operands and locals on each side.
Test strategy: Use `//@ test-mir-pass: DestinationPropagation`, `EMIT_MIR_FOR_EACH_PANIC_STRATEGY`, and `// EMIT_MIR <name>.DestinationPropagation.diff` for both panic strategies. Construct custom MIR for a swap-like aggregate and assert a distinct source local remains: `_0 = (copy (_2.1: ...), copy (_2.0: ...))` with `_2 = copy _0`, and that the aggregate is not rewritten as `_0 = (copy (_0.1), copy (_0.0))` or `_1 = (copy (_1.1), copy (_1.0))`. Include a scalar rewrap case confirming legal unification still occurs, and a separate simple same-projection copy/move case guarding the exemption.
Cases: 146516-d58061e6131f6141985faadb6794af540f81b1db
Source: https://github.com/rust-lang/rust/pull/146516
> DestinationPropagation: avoid creating overlapping assignments.
> Some rvalues interleave reads and writes, for instance `Rvalue::Aggregate`, see
> as behaving so by default.
> We make an exception for simple assignments `_a.stuff = {copy|move} _b.stuff`,
> as marking `_b` live here would prevent unification.
> DefUse::Use if !is_simple_assignment => {
> lhs.projection == rhs.projection
> +         _0 = (copy (_2.1: std::mem::MaybeUninit<[u8; 10]>), copy (_2.0: std::mem::MaybeUninit<[u8; 10]>));
