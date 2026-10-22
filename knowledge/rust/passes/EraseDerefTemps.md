# EraseDerefTemps
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- Do not assume `CopyForDeref(p)` and `Use(Copy(p))` are interchangeable in every MIR phase; the description limits the rewrite to the runtime erasure boundary.
- Do not erase `CopyForDeref` before drop elaboration, because its drop behavior is not that of a normal copy at that point.
- Do not treat a `DerefTemp` as `Boring` while an analysis pass still relies on its transparent-alias metadata.
- Do not allow runtime lowering or codegen to observe `CopyForDeref` or `DerefTemp`.
- Do not allow a `DerefTemp` to be read directly instead of through a deref.
- Do not allow a `DerefTemp` to be assigned by any rvalue other than `CopyForDeref`.
- Do not validate only the copied place's dereferenceable type while omitting the local-info pairing rule.
- Do not let runtime shims or coroutine bodies recreate `CopyForDeref`/`DerefTemp` by calling `deref_finder` with metadata enabled.
- Do not rely on the removed `custom_mir` `mir_copy_for_deref` helper to build malformed cases; the supplied description notes that internal test infrastructure may be needed.
- Erasing `CopyForDeref` before drop elaboration can introduce an extra drop of the copied drop-type value.
- Treating the rewritten local as an independently owned copy changes drop counts relative to transparent-alias semantics.
- Passing runtime coroutine or shim MIR through metadata-producing deref construction can postpone or bypass the required erasure boundary.

## Patterns Not Well Handled

### EraseDerefTemps rewrites analysis-only deref constructs at the runtime-MIR boundary
EraseDerefTemps converts each `DerefTemp` local into an ordinary temporary and each `CopyForDeref` rvalue into a normal copy at the transition to runtime MIR. The supplied description states: "This pass converts all `DerefTemp` locals into normal temporaries" and "turns their `CopyForDeref` rvalues into normal copies." The expected rewrite is `CopyForDeref(p)` to `Use(Copy(p))` and the `DerefTemp` local to `Boring`; after the pass, runtime MIR should contain neither analysis-only construct. The description explicitly records the validation expectations "`CopyForDeref` should have been removed in runtime MIR" and "`DerefTemp` should have been removed in runtime MIR."
Preconditions: A `DerefTemp` local must exist only with a dereferenceable type.; `EraseDerefTemps` runs after `AddRetag`/`ElaborateDrops` but before `ElaborateBoxDerefs` and codegen.; Analysis-phase MIR may contain these constructs; runtime MIR must not.; The erasure boundary must use the transparent-alias meaning of `CopyForDeref`, not ordinary copy semantics from another MIR phase.
Pitfalls: Do not assume `CopyForDeref(p)` and `Use(Copy(p))` are interchangeable in every MIR phase; the description limits the rewrite to the runtime erasure boundary.; Do not erase `CopyForDeref` before drop elaboration, because its drop behavior is not that of a normal copy at that point.; Do not treat a `DerefTemp` as `Boring` while an analysis pass still relies on its transparent-alias metadata.; Do not allow runtime lowering or codegen to observe `CopyForDeref` or `DerefTemp`.
Test strategy: Inspect MIR dumps around the erasure boundary using mir-opt tests. Construct cases where `Derefer`/`deref_finder` creates a deref temp, then verify the post-erasure/runtime dump has `_N = copy (...)` rather than `_N = deref_copy (...)` and has no remaining `CopyForDeref` or `DerefTemp`. The supplied coroutine StateTransform and shim expectations record this exact replacement of `deref_copy` by `copy`; treat those concrete dumps as focused evidence rather than universal proof.
Cases: 145513-033474bacf62c7ca2c3d113d94422e4ef93ba4c9
Source: https://github.com/rust-lang/rust/pull/145513
> //! This pass converts all `DerefTemp` locals into normal temporaries
> //! and turns their `CopyForDeref` rvalues into normal copies.
> In runtime MIR, it is replaced with a normal `Boring` local.
> `CopyForDeref` should have been removed in runtime MIR
> `DerefTemp` should have been removed in runtime MIR
> deref_finder(tcx, &mut result, false);
> // Run derefer to fix Derefs that are not in the first place

### DerefTemp pairing, access, and runtime construction invariants
Before erasure, a `DerefTemp` is an analysis-only transparent alias with strict pairing and access rules. The supplied description states "It may only be written to by a `CopyForDeref` and otherwise only accessed through a deref." Validation must enforce that the local has a dereferenceable type, that its assignment uses `CopyForDeref`, and that direct reads are rejected. Runtime construction paths also need to avoid reintroducing the constructs: shims and coroutine StateTransform callers of `deref_finder` must pass the explicit no-metadata flag, as shown by "deref_finder(tcx, &mut result, false);" so those paths emit plain copies and `Boring` locals. Merely checking that the copied place type is dereferenceable is insufficient because the local-info pairing is a separate invariant.
Preconditions: A `DerefTemp` local must have a dereferenceable type: "`DerefTemp` should only be used for dereferenceable types".; A `DerefTemp` may only be written by `CopyForDeref`: "assignment to a `DerefTemp` must use `CopyForDeref`".; A `DerefTemp` may otherwise be accessed only through a deref: "`DerefTemp` locals must only be dereferenced or directly assigned to".; Runtime-MIR `deref_finder` callers such as shims and coroutine StateTransform must pass `add_deref_metadata = false`.; Validation must reject both constructs in runtime MIR and enforce their pairing in analysis MIR before erasure.
Pitfalls: Do not allow a `DerefTemp` to be read directly instead of through a deref.; Do not allow a `DerefTemp` to be assigned by any rvalue other than `CopyForDeref`.; Do not validate only the copied place's dereferenceable type while omitting the local-info pairing rule.; Do not let runtime shims or coroutine bodies recreate `CopyForDeref`/`DerefTemp` by calling `deref_finder` with metadata enabled.; Do not rely on the removed `custom_mir` `mir_copy_for_deref` helper to build malformed cases; the supplied description notes that internal test infrastructure may be needed.
Test strategy: Add focused validation tests that separately violate each invariant: `CopyForDeref` or `DerefTemp` present in runtime MIR, assignment to `DerefTemp` not using `CopyForDeref`, a direct read of `DerefTemp`, and a non-dereferenceable `DerefTemp`. For construction-path coverage, use MIR dumps for shim and coroutine StateTransform output to confirm `deref_finder(..., false)` produces plain copies and `Boring` locals. Because the public `custom_mir` helper for `CopyForDeref` was removed, malformed runtime-MIR cases may require internal test infrastructure. These concrete tests cover the listed invariants but do not by themselves establish general equivalence.
Cases: 145513-033474bacf62c7ca2c3d113d94422e4ef93ba4c9
Source: https://github.com/rust-lang/rust/pull/145513
> It may only be written to by a `CopyForDeref` and otherwise only accessed through a deref.
> `DerefTemp` locals must only be dereferenced or directly assigned to
> assignment to a `DerefTemp` must use `CopyForDeref`
> `DerefTemp` should only be used for dereferenceable types
> deref_finder(tcx, &mut result, false);

### Ordering EraseDerefTemps after drop elaboration preserves transparent-alias drop semantics
The erasure rewrite is phase-sensitive because `CopyForDeref` is not equivalent to an ordinary copy for drop elaboration. The supplied validated pair models the historical incorrect treatment of runtime `CopyForDeref`/`DerefTemp` as an ordinary copied value by erasing early to `Use(Copy)`; that makes the copied drop-type value a separate local that is dropped in addition to the original. Correct transparent-alias semantics drop only the original. This is the concrete form of the rule that EraseDerefTemps must run after `ElaborateDrops`, not before it, while still preceding `ElaborateBoxDerefs` and codegen. The supplied pass documentation supports the rewrite itself: "This pass converts all `DerefTemp` locals into normal temporaries" and "turns their `CopyForDeref` rvalues into normal copies."
Preconditions: `ElaborateDrops` must have completed before `CopyForDeref` is rewritten to `Use(Copy)`.; `AddRetag` must precede the erasure, and `ElaborateBoxDerefs` plus codegen must follow it.; During analysis before erasure, `DerefTemp` remains a transparent alias rather than an independently dropped copied value.; Runtime MIR must not retain either `CopyForDeref` or `DerefTemp` after erasure.
Pitfalls: Erasing `CopyForDeref` before drop elaboration can introduce an extra drop of the copied drop-type value.; Treating the rewritten local as an independently owned copy changes drop counts relative to transparent-alias semantics.; Passing runtime coroutine or shim MIR through metadata-producing deref construction can postpone or bypass the required erasure boundary.
Test strategy: Use a drop-counting mir-opt/runtime test with a drop-type value and a fresh `Cell` initialized to zero; run with `D { id: 7 }` and print the returned id and final drop count. The supplied validated inputs exercise exactly this pairing and distinguish early ordinary-copy erasure (extra drop) from correct after-`ElaborateDrops` transparent-alias behavior (only the original is dropped). Pair this with dump checks that the erasure boundary yields `Use(Copy)`/`Boring` and no residual `CopyForDeref`/`DerefTemp`; finite cases illustrate the ordering hazard rather than proving universal equivalence.
Cases: 145513-033474bacf62c7ca2c3d113d94422e4ef93ba4c9
Source: https://github.com/rust-lang/rust/pull/145513
> //! This pass converts all `DerefTemp` locals into normal temporaries
> //! and turns their `CopyForDeref` rvalues into normal copies.
