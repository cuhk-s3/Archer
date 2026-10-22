# RenameReturnPlace
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- Do not read the eligibility conditions as a liveness or non-overlap proof; the backward scan can stop at the nearest `_0 = local` assignment and miss a later redefinition of `local`.
- Renaming StorageLive/StorageDead and all uses of the source local is unsound when the source local still has a live post-copy write.
- The return place is special: any later `_0 = ...` before `Return` overwrites the copied value, so `_0` cannot be treated as an ordinary destination for a still-live source local.
- Do not conflate this post-copy overwrite with borrowing restrictions; they are separate reasons a naive rename is unsafe.
- Do not claim runtime reproduction or compiler execution from these patch-derived MIR expectations.
- The 'only definition of the return place reaching Return' check concerns `_0`, not the source local, so it does not prevent a post-copy write from being renamed onto `_0`.
- Nop'ing the return copy and the source local's storage annotations is unsafe if the source local still has a later live definition.
- Treat the documented eligibility rules as prerequisites, not as a soundness proof.
- Do not attribute this scan's weakness to borrowed-local handling; borrowing is a distinct constraint.
- Do not conflate the borrowed-local restriction with the #111005 post-copy overwrite bug; they are independent conditions.
- Do not treat the absence of copy elimination for a borrowed local as evidence that the replacement pass is wrong.
- Do not use the shared `nrvo_*` test naming to argue destination propagation is incorrect; inspect the actual borrow and copy statements.
- A `&mut T` versus `&T` debug-declaration mismatch is documented as an expected possibility, not the miscompile.
- Do not assume `DestinationPropagation` is wrong merely because a retained test filename or comment mentions an NRVO miscompile.
- Do not treat `// FIXME: This is wrong:` or `// CHECK-NEXT: _0 = const 'b';` as an assertion about the replacement pass.
- Do not claim the patch contains runtime reproductions; the evidence is source changes and MIR expectation diffs.
- The correct old `DestinationPropagation` output for the same test was `nop; _0 = _1; _1 = const 'b';`, preserving the copied value; the clobbering form belongs to the removed pass.
- Do not conflate the performance-motivated opt-level-3 gate with the correctness bug; the gate is restored because of a keccak regression.
- Do not compare MIR dumps from different pipeline positions as if they were the same input; DSE can remove statements before destination propagation sees them.
- Do not expect `RenameReturnPlace` to run in the default pipeline; it is removed or guarded as unsound.
- MIR-dump test names, pass annotations, and CHECK patterns must be updated together when the pass is moved or removed.

## Patterns Not Well Handled

### Post-copy overwrite of the NRVO source local makes whole-local rename to `_0` unsound
The central `RenameReturnPlace` trigger is a local copied into the return place and then redefined before `Return`. In the historical MIR `_2 = _1; _0 = _2; _2 = const 'b';`, the function should return the value derived from `_1`, but renaming every use of `_2` to `_0` produces `_0 = _1; _0 = const 'b';`, so the later write intended for `_2` clobbers the return value. The corrective replacement output is `nop; _0 = _1; _1 = const 'b';`: the copy into `_0` is preserved and the later write remains on the source local. The invariant is that a write occurring after `_0 = local` must not be redirected into `_0`.
Preconditions: A whole-local assignment into the return place, e.g. `_0 = _2`, is found on the path reaching `Return`.; The return place is not read before `Return`, and that whole-local assignment is the only definition of `_0` reaching `Return`; these checks alone do not establish safety.; The selected source local is a `Temp` (not an `Arg`) shared across return blocks, and it is written again after the `_0 = local` copy and before `Return`.; The old pass applies its whole-use rename ("Replaces all uses of `self.to_rename` with `_0`.") without excluding post-copy definitions of the source local.; The replacement behavior is destination propagation, which preserves the later write on the source local rather than moving it to `_0`.
Pitfalls: Do not read the eligibility conditions as a liveness or non-overlap proof; the backward scan can stop at the nearest `_0 = local` assignment and miss a later redefinition of `local`.; Renaming StorageLive/StorageDead and all uses of the source local is unsound when the source local still has a live post-copy write.; The return place is special: any later `_0 = ...` before `Return` overwrites the copied value, so `_0` cannot be treated as an ordinary destination for a still-live source local.; Do not conflate this post-copy overwrite with borrowing restrictions; they are separate reasons a naive rename is unsafe.; Do not claim runtime reproduction or compiler execution from these patch-derived MIR expectations.
Test strategy: Build `#[custom_mir(dialect = "runtime", phase = "initial")]` cases whose MIR is `_2 = copy _1; _0 = copy _2; _2 = const 'b'; return`, and assert the emitted MIR keeps `_0` holding the copied value and leaves the later write as `_1 = const 'b';` rather than `_0 = const 'b';`. Add a control case differing only in whether the source local is overwritten after the return-place copy, so the two outputs isolate the transformation. Use `//@ test-mir-pass: DestinationPropagation` with `// EMIT_MIR ...diff` and panic-strategy variants where relevant.
Cases: 115105-5fa0ec6ad17cd002e9359345bbeae4601c03fd53, 125794-e110567dcdf7b77cda5f3413af7c6fadec899a9a, 142915-44c1a00a2f9929cff1641b18f4c2b5f2d2833e3e
Source: https://github.com/rust-lang/rust/pull/115105
Source: https://github.com/rust-lang/rust/pull/125794
Source: https://github.com/rust-lang/rust/pull/142915
> This pass looks for MIR that always copies the same local into the return place and eliminates
> the copy by renaming all uses of that local to `_0`.
> Replaces all uses of `self.to_rename` with `_0`.
> -         _2 = _1;
> -         _2 = const 'b';
> +         _0 = _1;
> +         _0 = const 'b';
> // CHECK-NEXT: _0 = const 'b';
> // CHECK-NEXT: _1 = const 'b';

### Return-place eligibility checks are necessary but not sufficient to permit renaming
`RenameReturnPlace` documents two eligibility conditions: "The return place must not be read prior to the `Return` terminator." and "A simple assignment of a whole local to the return place (e.g., `_0 = _1`) must be the only definition of the return place reaching the `Return` terminator." These conditions constrain `_0`, but they do not constrain later writes to the selected source local. The pass scans backward from each `Return` for `if lhs.as_local() == Some(mir::RETURN_PLACE)`, nops the copy and the source local's storage statements, ignores the implicit `Return` use, and copies the source local's declaration/debug info onto `_0`. A candidate that satisfies both documented conditions can still be unsafe when the source local is redefined after the return-place assignment.
Preconditions: The return place is not read before the `Return` terminator.; A whole-local assignment to `_0` is the only definition of `_0` reaching `Return`.; The source local is a `Temp`, not an `Arg`; `LocalKind::Arg` is rejected.; The source local is redefined/overwritten after the `_0 = local` assignment but before `Return`, a condition the backward scan does not exclude.
Pitfalls: The 'only definition of the return place reaching Return' check concerns `_0`, not the source local, so it does not prevent a post-copy write from being renamed onto `_0`.; Nop'ing the return copy and the source local's storage annotations is unsafe if the source local still has a later live definition.; Treat the documented eligibility rules as prerequisites, not as a soundness proof.; Do not attribute this scan's weakness to borrowed-local handling; borrowing is a distinct constraint.
Test strategy: Construct paired `custom_mir` functions: one where the source local is unchanged after `_0 = local`, and one where it is overwritten immediately afterward. Run the pass and compare the after-MIR, checking that only the safe case eliminates the copy/return assignment and that the unsafe case retains the later write on the source local. Inspect the actual assignment targets in the emitted MIR rather than relying on test names.
Cases: 115105-5fa0ec6ad17cd002e9359345bbeae4601c03fd53, 125794-e110567dcdf7b77cda5f3413af7c6fadec899a9a, 142915-44c1a00a2f9929cff1641b18f4c2b5f2d2833e3e
Source: https://github.com/rust-lang/rust/pull/115105
Source: https://github.com/rust-lang/rust/pull/125794
Source: https://github.com/rust-lang/rust/pull/142915
> The return place must not be read prior to the `Return` terminator.
> A simple assignment of a whole local to the return place (e.g., `_0 = _1`) must be the
> only definition of the return place reaching the `Return` terminator.
> if lhs.as_local() == Some(mir::RETURN_PLACE) {
> stmt.kind = mir::StatementKind::Nop;
> // Remove assignments of the local being replaced to the return place, since it is now the
> // Remove storage annotations for the local being replaced:
> Ignore the implicit "use" of the return place in a `Return` statement.

### Borrowed candidate locals are a separate restriction from post-copy overwrite
The removed pass did not restrict itself to non-borrowed locals, whereas the replacement destination propagation "does not handle borrowed locals." In the borrowed-local scenario, the expected replacement MIR retains the borrow and the return copy, e.g. `debug buf => _2;`, `_6 = &mut _2;`, and `_0 = copy _2;`, while the deleted NRVO output instead showed `debug buf => _0;`, `_6 = &mut _0;`, and no return copy. Lack of NRVO-like elimination for a borrowed local is conservative behavior, not a miscompile.
Preconditions: The candidate local is address-taken or borrowed, e.g. `_6 = &mut _2`, before or around the copy into the return place.; The replacement pass is `DestinationPropagation`, which is "not limited to `_0`, but does not handle borrowed locals."; The simple `nrvo` case taking `&mut _2` is correctly rewritten to `&mut _0`; borrowing alone must not be cited as the cause of the post-copy clobbering bug.
Pitfalls: Do not conflate the borrowed-local restriction with the #111005 post-copy overwrite bug; they are independent conditions.; Do not treat the absence of copy elimination for a borrowed local as evidence that the replacement pass is wrong.; Do not use the shared `nrvo_*` test naming to argue destination propagation is incorrect; inspect the actual borrow and copy statements.; A `&mut T` versus `&T` debug-declaration mismatch is documented as an expected possibility, not the miscompile.
Test strategy: Add a borrowed-local MIR case with `&mut local` and assert the pass conservatively leaves the borrow on the original local and retains the return copy, rather than producing `&mut _0`. Pair it with a simple non-overwritten NRVO case to show that borrowing is handled separately from the post-copy write case. Use `// EMIT_MIR` diff output and compare the actual `debug ... => _N`, borrow, and copy lines.
Cases: 115105-5fa0ec6ad17cd002e9359345bbeae4601c03fd53, 125794-e110567dcdf7b77cda5f3413af7c6fadec899a9a, 142915-44c1a00a2f9929cff1641b18f4c2b5f2d2833e3e
Source: https://github.com/rust-lang/rust/pull/115105
Source: https://github.com/rust-lang/rust/pull/125794
Source: https://github.com/rust-lang/rust/pull/142915
> `DestinationPropagation` is not limited to `_0`, but does not handle borrowed locals.
> debug buf => _2;
> debug buf => _0;
> _6 = &mut _2;
> _6 = &mut _0;
> _0 = copy _2;
> Sometimes, the return place is assigned a local of a different but coercible type, for
> // example `&mut T` instead of `&T`.

### Distinguish the old wrong NRVO output from the replacement pass output in historical MIR tests
The regression tests carry names and FIXME comments such as "// This is a miscompilation, #111005 to track", "// FIXME: This is wrong:", and "// CHECK-NEXT: _0 = const 'b';". These describe the old `RenameReturnPlace` rewrite, not the replacement pass. The old pass turned `_2 = _1; _0 = _2; _2 = const 'b';` into `_0 = _1; _0 = const 'b';`, while destination propagation produced `nop; _0 = _1; _1 = const 'b';` and preserved the return value. A retained test name or comment is not evidence that the replacement pass is incorrect; compare the actual assignments in decoded before/after MIR.
Preconditions: A test is named for `nrvo_miscompile_111005` or retains an "unsound"/"miscompilation" comment from the removed pass.; The MIR dump contains both a historical wrong form (`_0 = const 'b';`) and a corrected form (`_1 = const 'b';`) attributable to different passes.; The pass under test is identified by its own `test-mir-pass` annotation, e.g. `//@ test-mir-pass: DestinationPropagation` or `//@ test-mir-pass: RenameReturnPlace`.
Pitfalls: Do not assume `DestinationPropagation` is wrong merely because a retained test filename or comment mentions an NRVO miscompile.; Do not treat `// FIXME: This is wrong:` or `// CHECK-NEXT: _0 = const 'b';` as an assertion about the replacement pass.; Do not claim the patch contains runtime reproductions; the evidence is source changes and MIR expectation diffs.; The correct old `DestinationPropagation` output for the same test was `nop; _0 = _1; _1 = const 'b';`, preserving the copied value; the clobbering form belongs to the removed pass.
Test strategy: Keep the historical regression as a regression for the replacement pass, but rewrite or annotate expectations so the wrong form is clearly marked. Assert the replacement output contains `_1 = const 'b';` and not `_0 = const 'b';`. Run the relevant `test-mir-pass` annotations separately for the removed and replacement passes where historical expectations are preserved, and inspect the actual assignment targets instead of trusting filenames or comments.
Cases: 115105-5fa0ec6ad17cd002e9359345bbeae4601c03fd53, 125794-e110567dcdf7b77cda5f3413af7c6fadec899a9a, 142915-44c1a00a2f9929cff1641b18f4c2b5f2d2833e3e
Source: https://github.com/rust-lang/rust/pull/115105
Source: https://github.com/rust-lang/rust/pull/125794
Source: https://github.com/rust-lang/rust/pull/142915
> // This is a miscompilation, #111005 to track
> // unsound: #111005
> // FIXME: This is wrong:
> // CHECK-NEXT: _0 = const 'b';
> // CHECK-NEXT: _1 = const 'b';
> -//@ test-mir-pass: RenameReturnPlace
> +//@ test-mir-pass: DestinationPropagation

### Destination-propagation enablement gate and pipeline position change what MIR is observed
The default-enable change moved destination propagation into the slot formerly occupied by `RenameReturnPlace`, changed its gate from `sess.mir_opt_level() >= 3` to `sess.mir_opt_level() >= 2`, and placed it after `DeadStoreElimination::Final`. The revert restores the gate to `sess.mir_opt_level() >= 3` because of a documented 30% keccak performance regression, and restores the pass before `SimplifyConstCondition::Final` while returning `RenameReturnPlace` after final DSE under `sess.mir_opt_level() > 0 && sess.opts.unstable_opts.unsound_mir_opts`. Pipeline position matters: a dead `_2 = const 1_u32;` visible before DSE can become `nop;` when destination propagation runs after DSE.
Preconditions: DestinationPropagation is gated at `sess.mir_opt_level() >= 2` in the default-enable state and at `sess.mir_opt_level() >= 3` after the revert.; The removed NRVO pass is gated under `sess.mir_opt_level() > 0 && sess.opts.unstable_opts.unsound_mir_opts`.; Pipeline ordering differs: destination propagation is moved to the former NRVO slot after `DeadStoreElimination::Final` in one state, and restored before final simplification in the reverted state.; Test expectations must be updated together with the pass annotation, gate, and pipeline placement.
Pitfalls: Do not conflate the performance-motivated opt-level-3 gate with the correctness bug; the gate is restored because of a keccak regression.; Do not compare MIR dumps from different pipeline positions as if they were the same input; DSE can remove statements before destination propagation sees them.; Do not expect `RenameReturnPlace` to run in the default pipeline; it is removed or guarded as unsound.; MIR-dump test names, pass annotations, and CHECK patterns must be updated together when the pass is moved or removed.
Test strategy: Inspect MIR at `-Zmir-opt-level=2` and `-Zmir-opt-level=3` to verify the enablement gate and the pass's effect. Include the `dest-prop/union` case to confirm whether dead stores are visible before or after DSE at the selected pipeline position. Run `//@ test-mir-pass: DestinationPropagation` expectations under the intended gate and compare pass output before and after the pipeline move.
Cases: 115105-5fa0ec6ad17cd002e9359345bbeae4601c03fd53, 125794-e110567dcdf7b77cda5f3413af7c6fadec899a9a, 142915-44c1a00a2f9929cff1641b18f4c2b5f2d2833e3e
Source: https://github.com/rust-lang/rust/pull/115105
Source: https://github.com/rust-lang/rust/pull/125794
Source: https://github.com/rust-lang/rust/pull/142915
> sess.mir_opt_level() >= 3
> sess.mir_opt_level() >= 2
> sess.mir_opt_level() > 0 && sess.opts.unstable_opts.unsound_mir_opts
> //  2. Despite being an overall perf improvement, this still causes a 30% regression in
> //     keccak.
> &dest_prop::DestinationPropagation,
> &nrvo::RenameReturnPlace,
> -        sess.mir_opt_level() >= 3
> +        sess.mir_opt_level() >= 2
> This PR proposes to enable the destination propagation pass by default.
> At the same time, this PR removes the `RenameReturnPlace` pass, as it is currently unsound.
