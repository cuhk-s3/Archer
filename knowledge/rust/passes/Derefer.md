# Derefer
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- Do not erase `CopyForDeref` before drop elaboration: it is not equivalent to a normal copy for drop elaboration.
- Do not assume `CopyForDeref(p)` and `Use(Copy(p))` are interchangeable in every MIR phase; the rewrite is only valid at the runtime erasure boundary.
- Do not allow runtime lowering/codegen to see either `CopyForDeref` or `DerefTemp`.
- Do not treat a `DerefTemp` as `Boring` while an analysis pass still relies on the transparent-alias metadata.
- Checking only that the `CopyForDeref` place is dereferenceable is insufficient; the local-info pairing must also be validated.
- Do not allow `DerefTemp` locals to be read directly.
- Do not allow `DerefTemp` locals to be assigned by non-`CopyForDeref` rvalues.
- Do not permit a non-dereferenceable `DerefTemp` type.
- Do not call `deref_finder` from runtime shim/coroutine construction without disabling deref metadata.
- Do not assume the same deref-finder mode is valid for both analysis MIR and runtime MIR.

## Patterns Not Well Handled

### Erase analysis-only deref constructs at the runtime-MIR boundary, after drop elaboration
`CopyForDeref` and `DerefTemp` are analysis-only constructs: the pass converts all `DerefTemp` locals into ordinary temporaries and turns their `CopyForDeref` rvalues into normal copies. At erasure, `CopyForDeref(place)` becomes `Use(Copy(place))` and the `DerefTemp` local becomes `Boring`. Erasure must occur after `AddRetag`/`ElaborateDrops` but before `ElaborateBoxDerefs` and codegen, so runtime MIR contains neither construct. The historical concern is that runtime MIR could retain `CopyForDeref`/`DerefTemp` and treat them as ordinary runtime values, allowing codegen or MIR passes to copy them as normal values rather than preserving their transparent-alias semantics.
Preconditions: The MIR is at the erasure/runtime phase, including shims and coroutine StateTransform output.; Analysis-phase MIR may still contain `CopyForDeref`/`DerefTemp`, but runtime MIR must not.; `EraseDerefTemps` runs after `AddRetag`/`ElaborateDrops` and before `ElaborateBoxDerefs` and codegen.; The erased `CopyForDeref` place has a dereferenceable type.
Pitfalls: Do not erase `CopyForDeref` before drop elaboration: it is not equivalent to a normal copy for drop elaboration.; Do not assume `CopyForDeref(p)` and `Use(Copy(p))` are interchangeable in every MIR phase; the rewrite is only valid at the runtime erasure boundary.; Do not allow runtime lowering/codegen to see either `CopyForDeref` or `DerefTemp`.; Do not treat a `DerefTemp` as `Boring` while an analysis pass still relies on the transparent-alias metadata.
Test strategy: Use mir-opt MIR dumps on both sides of the erasure boundary. Construct cases where `Derefer`/`deref_finder` creates a deref temp, then check that the runtime dump contains `_N = copy (...)` instead of `_N = deref_copy (...)` and no remaining `CopyForDeref`/`DerefTemp`. Include drop-sensitive values: the supplied validated historical pair models early erasure by making the copied drop-type value a separate local that is dropped in addition to the original, whereas correct transparent-alias semantics drops only the original. Run with `D { id: 7 }` and a fresh `Cell` starting at 0, then print the returned id and final drop count. This concrete pair demonstrates the phase-ordering pitfall but is not universal proof of equivalence.
Cases: 145513-033474bacf62c7ca2c3d113d94422e4ef93ba4c9
Source: https://github.com/rust-lang/rust/pull/145513
> //! This pass converts all `DerefTemp` locals into normal temporaries
> //! and turns their `CopyForDeref` rvalues into normal copies.
> In runtime MIR, it is replaced with a normal `Boring` local.
> `CopyForDeref` should have been removed in runtime MIR
> `DerefTemp` should have been removed in runtime MIR

### Validate DerefTemp write/read pairing and dereferenceability before erasure
Before erasure, a `DerefTemp` local must have a dereferenceable type, may only be written by `CopyForDeref`, and otherwise may only be accessed through a deref whose first place projection is indirect. Validation that only checks the `CopyForDeref` place type is insufficient because it misses the local-info pairing. The historical incorrect transformation allowed a `DerefTemp` to be assigned by something other than `CopyForDeref` or read directly, violating the alias invariant.
Preconditions: The MIR still contains `DerefTemp`/`CopyForDeref` and is being validated before erasure.; A `DerefTemp` local has a dereferenceable type.; Every write to a `DerefTemp` uses `CopyForDeref`.; Every non-write access to a `DerefTemp` goes through a deref (the first place projection is indirect).
Pitfalls: Checking only that the `CopyForDeref` place is dereferenceable is insufficient; the local-info pairing must also be validated.; Do not allow `DerefTemp` locals to be read directly.; Do not allow `DerefTemp` locals to be assigned by non-`CopyForDeref` rvalues.; Do not permit a non-dereferenceable `DerefTemp` type.
Test strategy: Add negative compiler tests that independently violate each invariant: `CopyForDeref`/`DerefTemp` present in runtime MIR, assignment to a `DerefTemp` not using `CopyForDeref`, direct read of a `DerefTemp`, and a non-dereferenceable `DerefTemp`. Note that the `custom_mir` `mir_copy_for_deref` helper was removed, so constructing such malformed runtime MIR may require internal test infrastructure rather than the public custom-MIR dialect.
Cases: 145513-033474bacf62c7ca2c3d113d94422e4ef93ba4c9
Source: https://github.com/rust-lang/rust/pull/145513
> It may only be written to by a `CopyForDeref` and otherwise only accessed through a deref.
> `DerefTemp` locals must only be dereferenced or directly assigned to
> assignment to a `DerefTemp` must use `CopyForDeref`
> `DerefTemp` should only be used for dereferenceable types

### Distinguish analysis MIR from runtime MIR in deref_finder callers
Runtime-MIR `deref_finder` callers, specifically shims and coroutine StateTransform, need an explicit flag to avoid recreating analysis-only deref constructs. They must pass `add_deref_metadata = false` so they emit plain copies and `Boring` locals rather than recreating `CopyForDeref`/`DerefTemp`. Without that distinction, the deref finder can create these constructs in shims and coroutine bodies, leaving runtime MIR with analysis-only constructs.
Preconditions: A caller of `deref_finder` is generating runtime MIR, such as a shim or coroutine StateTransform body.; The caller explicitly requests no deref metadata when the output must be runtime MIR.
Pitfalls: Do not call `deref_finder` from runtime shim/coroutine construction without disabling deref metadata.; Do not assume the same deref-finder mode is valid for both analysis MIR and runtime MIR.
Test strategy: Exercise shims and coroutine StateTransform bodies that contain derefs not in the first place. Inspect mir-opt dumps to confirm the runtime output uses plain `copy` and `Boring` locals, not `deref_copy`, `CopyForDeref`, or `DerefTemp`. The supplied shim and coroutine StateTransform expectations show the exact replacement of `deref_copy` by `copy`.
Cases: 145513-033474bacf62c7ca2c3d113d94422e4ef93ba4c9
Source: https://github.com/rust-lang/rust/pull/145513
> deref_finder(tcx, &mut result, false);
> // Run derefer to fix Derefs that are not in the first place
