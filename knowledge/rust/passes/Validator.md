# Validator
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- Do not conflate this with the older documented duplicate-variant rule; the supplied patch does not add a duplicate-variant-index check.
- Do not accept a non-immediate later `Field` as satisfying the invariant.
- The successor may be consumed while checking, so tests must reason about adjacency over the projection list rather than independent membership.
- The supplied regression expectation only updates an unrelated `Deref` diagnostic, so it does not by itself assert the new `Downcast` failure.
- Do not use the body's MIR phase as the criterion for transmute validity; pre-runtime transmute casts are permitted.
- Do not drop the sizedness checks when removing the phase gate: both normalized source and target types must still be `Sized`.
- Do not equate MIR transmute with `mem::transmute`; the source says a MIR `Transmute` is well-formed "for any two `Sized` types, just potentially UB to run."
- The historical pre-runtime representation as a call terminator does not make a pre-runtime transmute cast invalid.
- A `check-pass` test name alone is insufficient; validation must actually be enabled for pre-runtime MIR.
- Do not treat the marker as a real drop or control-flow terminator; it is a no-op for borrowck, const-eval, codegen, coverage, coroutine analysis, and dataflow.
- Do not delete the marker's local merely because there are no other uses; deleting the local without rewriting or deleting the marker can leave invalid MIR.
- When locals are renumbered, the marker's place local must be remapped too.
- For drop-reachability linting, early MIR drops may be removed by drop elaboration; consult `MaybeInitializedPlaces` so unreachable drops are not counted.
- Do not fall back to an HIR over-approximation that flags a droppy tail temporary even when it is consumed into the return value, moved into a constructor, a parameter, or a closure capture.
- Do not erase `CopyForDeref` before drop elaboration; it is not equivalent to a normal copy for drop elaboration.
- Do not treat `CopyForDeref(place)` and a normal copy as interchangeable in every MIR phase; the rewrite is valid at the runtime erasure boundary.
- Do not treat a `DerefTemp` as `Boring` while an analysis pass still relies on its transparent-alias metadata.
- Checking only that the copied place is dereferenceable is insufficient; the local-info pairing and access rules must also be validated.
- Do not allow a `DerefTemp` to be read directly or assigned by a non-`CopyForDeref` rvalue.
- Do not unwrap or propagate `coroutine_layout` errors from Validator; retain the raw-layout fallback and then treat no layout as a skipped check.
- Do not collapse `TooGeneric` back into `Unknown`; the distinction is the purpose of the change.
- Preserve raw-layout preference for the caller body and for coroutine-closure by-move bodies before querying the general coroutine layout.
- Do not infer invalid MIR merely because a validation layout lookup failed.
- Do not reject PtrMetadata on references; the updated validator accepts `ty::Ref(..)` as well as raw pointers.
- Do not permit PtrMetadata in non-Runtime MIR.
- Do not imply that allowing PtrMetadata on references permits eliminating metadata-removing pointer casts.
- Do not fold PtrMetadata for casts other than array-to-slice unsizing; only that cast stores the array length in fat-pointer metadata.
- When metadata types are known and differ, equality of tail types alone is not sufficient; known and unknown metadata results are distinct.

## Patterns Not Well Handled

### Downcast projections require an immediate Field successor
Validator place checking must reject a place whose projection sequence contains `ProjectionElem::Downcast` without an immediately following `ProjectionElem::Field`. The historical validator inspected other place constraints but did not enforce this adjacency, so terminal `Downcast` and `Downcast` followed by another non-`Field` projection could pass. This is an adjacency invariant over the projection sequence, not a duplicate-variant-index rule. The supplied history changes the documentation from the old duplicate-variant statement to: "A `Downcast` projection must always be followed immediately by a `Field` projection."
Preconditions: Validation reaches a place containing a `Downcast` projection.; The very next projection is absent or is not `Field`; a later `Field` after another projection does not satisfy the rule.; The check belongs in the Validator place visitor and therefore applies wherever validated MIR places are inspected.
Pitfalls: Do not conflate this with the older documented duplicate-variant rule; the supplied patch does not add a duplicate-variant-index check.; Do not accept a non-immediate later `Field` as satisfying the invariant.; The successor may be consumed while checking, so tests must reason about adjacency over the projection list rather than independent membership.; The supplied regression expectation only updates an unrelated `Deref` diagnostic, so it does not by itself assert the new `Downcast` failure.
Test strategy: Compare two otherwise identical MIR places: one with `Downcast` immediately followed by `Field` as the valid control, and one with that `Field` removed or replaced by a non-`Field` projection. Exercise the Validator path and assert that only the malformed place produces the downcast diagnostic. Pair this with the updated unrelated `Deref` diagnostic expectation rather than treating that expectation as downcast coverage.
Cases: 125616-7d24f8706823e2f56f42ab7597f50d1b679f0eea
Source: https://github.com/rust-lang/rust/pull/125616
> MIR validation: ensure that downcast projection is followed by field projection
> +///    given one, and makes no other changes. A `Downcast` projection must always be followed
> +///    immediately by a `Field` projection.
> +                            "place {place:?} has `Downcast` projection not followed by `Field`"

### Transmute validity is type sizedness, not the MIR phase
A MIR `CastKind::Transmute` in pre-runtime MIR must not be rejected merely because the body is not in `MirPhase::Runtime`. The historical phase-gated validator failed all non-runtime transmutes with "Transmute is not supported in non-runtime phase {:?}." even when both normalized source and target types were `Sized`. The corrected rule applies the same sizedness well-formedness check in all phases: both normalized operand and target types must be `Sized`. This is validation correctness, not an optimization claim: MIR transmute is well-formed for any two `Sized` types and may still be UB to execute.
Preconditions: MIR validation is enabled for a body containing `CastKind::Transmute`.; The body may be in a non-runtime phase, such as pre-runtime MIR emitted before runtime lowering.; The normalized operand and target types are both `Sized` for the valid case that the old phase gate incorrectly rejected.
Pitfalls: Do not use the body's MIR phase as the criterion for transmute validity; pre-runtime transmute casts are permitted.; Do not drop the sizedness checks when removing the phase gate: both normalized source and target types must still be `Sized`.; Do not equate MIR transmute with `mem::transmute`; the source says a MIR `Transmute` is well-formed "for any two `Sized` types, just potentially UB to run."; The historical pre-runtime representation as a call terminator does not make a pre-runtime transmute cast invalid.; A `check-pass` test name alone is insufficient; validation must actually be enabled for pre-runtime MIR.
Test strategy: Use a pre-runtime MIR case with a transmute cast and validation enabled, plus runtime controls with both types `Sized`. Add negative cases where the normalized source or target is non-`Sized` and assert those still fail with the corresponding sizedness diagnostics. The historical test change adds validation to a pattern-type matching test so the pre-runtime path is actually exercised.
Cases: 142124-c677dc26b4d9d5e742ff860ace924a270a2266b6
Source: https://github.com/rust-lang/rust/pull/142124
> if let MirPhase::Runtime(..) = self.body.phase {
> Transmute is not supported in non-runtime phase {:?}.
> // Unlike `mem::transmute`, a MIR `Transmute` is well-formed
> // for any two `Sized` types, just potentially UB to run.
> I don't think they have any issues using them before runtime, we just checked for them because we didn't have code exercising those code paths

### Analysis-only marker statements must be inert to Validator and visible to local-use handling
A new MIR marker such as `StatementKind::BackwardIncompatibleDropHint` is semantically a no-op for execution-oriented consumers, but it carries a `Place` reference that lint analysis needs. Validator CFG and type checking must accept the marker as a no-op instead of rejecting it or falling into an unsupported-statement path. Local-usage and remapping logic must also count the marked place as used and rewrite its local when locals are renamed or removed. The supplied source states the marker is "semantically equivalent to `Nop`, so codegen and MIRI should interpret this" as a no-op, while the lint relies on the marker's place. The related lint fix avoids reporting significant-drop temporaries that are actually consumed, moved, parameters, or closure captures by consulting move/initialization state rather than an HIR over-approximation.
Preconditions: The MIR body contains the marker statement and optimization/validation passes run over it.; The marker carries a boxed place referencing a local that must remain valid through optimization.; Validator's CFG and type checkers encounter the marker variant.; Any local-usage/removal pass must treat the marker's place as a use, and any local remapper must update that place's local index.
Pitfalls: Do not treat the marker as a real drop or control-flow terminator; it is a no-op for borrowck, const-eval, codegen, coverage, coroutine analysis, and dataflow.; Do not delete the marker's local merely because there are no other uses; deleting the local without rewriting or deleting the marker can leave invalid MIR.; When locals are renumbered, the marker's place local must be remapped too.; For drop-reachability linting, early MIR drops may be removed by drop elaboration; consult `MaybeInitializedPlaces` so unreachable drops are not counted.; Do not fall back to an HIR over-approximation that flags a droppy tail temporary even when it is consumed into the return value, moved into a constructor, a parameter, or a closure capture.
Test strategy: Run SimplifyLocals and Validator on a MIR body containing the marker and verify that all validation consumers accept it and that the marked local survives or is correctly renumbered. Include lint UI cases where consumed, moved, parameter, and closure-capture droppy values do not lint, while nested-block, generic, ADT, async-future, and transient-drop cases do. Keep an edition-2024 migration check that the lint does not fire.
Cases: 131326-297b618944d4619a1990b1992d9142c6cf893dc6
Source: https://github.com/rust-lang/rust/pull/131326
> +    /// This is semantically equivalent to `Nop`, so codegen and MIRI should interpret this
> +    /// The only use case of this statement is for linting in MIR to detect temporary lifetime
> +            | StatementKind::BackwardIncompatibleDropHint { ref place, reason: _ } => {
> +fn should_not_lint_when_consumed() -> (LoudDropper, i32) {
> #![deny(tail_expr_drop_order)]
> MaybeInitializedPlaces

### Runtime MIR must not retain analysis-only deref temporaries
`CopyForDeref` and `DerefTemp` are analysis constructs that must be erased before runtime MIR reaches codegen. `DerefTemp` locals must be dereferenceable, may only be written by `CopyForDeref`, and otherwise may only be accessed through a deref. The erasure rewrites `CopyForDeref(place)` to a normal copy and turns the `DerefTemp` into a `Boring` local only after drop elaboration; validation must reject either construct if it remains in runtime MIR. The source says the pass "converts all `DerefTemp` locals into normal temporaries" and "turns their `CopyForDeref` rvalues into normal copies." Runtime callers of the deref finder must disable deref-temp creation so shims and coroutine bodies do not recreate them.
Preconditions: A `DerefTemp` local exists only while analysis metadata is still needed; its type must be dereferenceable.; Any write to a `DerefTemp` uses `CopyForDeref`; other accesses go through a deref.; Erasure runs after drop elaboration but before later deref expansion and codegen.; Runtime-MIR deref-finder callers explicitly avoid adding deref metadata.
Pitfalls: Do not erase `CopyForDeref` before drop elaboration; it is not equivalent to a normal copy for drop elaboration.; Do not treat `CopyForDeref(place)` and a normal copy as interchangeable in every MIR phase; the rewrite is valid at the runtime erasure boundary.; Do not treat a `DerefTemp` as `Boring` while an analysis pass still relies on its transparent-alias metadata.; Checking only that the copied place is dereferenceable is insufficient; the local-info pairing and access rules must also be validated.; Do not allow a `DerefTemp` to be read directly or assigned by a non-`CopyForDeref` rvalue.
Test strategy: Use MIR dumps around the erasure boundary to verify that deref copies become ordinary copies and no `CopyForDeref` or `DerefTemp` remains in runtime MIR, including shim and coroutine StateTransform outputs. Add negative validator cases for a runtime `CopyForDeref`/`DerefTemp`, a `DerefTemp` assigned by a non-`CopyForDeref` rvalue, a direct read, and a non-dereferenceable `DerefTemp`.
Cases: 145513-033474bacf62c7ca2c3d113d94422e4ef93ba4c9
Source: https://github.com/rust-lang/rust/pull/145513
> //! This pass converts all `DerefTemp` locals into normal temporaries
> //! and turns their `CopyForDeref` rvalues into normal copies.
> It may only be written to by a `CopyForDeref` and otherwise only accessed through a deref.
> `CopyForDeref` should have been removed in runtime MIR
> `DerefTemp` should have been removed in runtime MIR
> assignment to a `DerefTemp` must use `CopyForDeref`
> `DerefTemp` should only be used for dereferenceable types

### Coroutine layout failures distinguish TooGeneric from Unknown, and Validator treats missing layout as advisory
When coroutine layout queries move from `Option` to `Result<_, &LayoutError>`, failure reasons must remain distinct. A not-fully-specialized `async_drop_in_place<T>::{closure}` coroutine whose first argument has placeholders or a non-region parameter yields `LayoutError::TooGeneric`; a missing raw coroutine layout, such as MIR tainted by errors, yields `LayoutError::Unknown`. `Validator` intentionally converts an unavailable layout back to an option rather than rejecting the MIR, preserving its raw-layout fallback. The supplied source says `async_drop_coroutine_layout` returns `LayoutError::TooGeneric` for not-fully-specialized async-drop coroutines, and `layout_of_uncached` maps missing raw layout to `LayoutError::Unknown`.
Preconditions: The queried type is a coroutine, including async-drop coroutines and coroutine-closure by-move bodies.; For `TooGeneric`, the async-drop coroutine's first generic argument has placeholders or a non-region parameter.; For `Unknown`, the raw coroutine layout is absent.; Validator must be able to skip checks whose layout cannot be obtained.
Pitfalls: Do not unwrap or propagate `coroutine_layout` errors from Validator; retain the raw-layout fallback and then treat no layout as a skipped check.; Do not collapse `TooGeneric` back into `Unknown`; the distinction is the purpose of the change.; Preserve raw-layout preference for the caller body and for coroutine-closure by-move bodies before querying the general coroutine layout.; Do not infer invalid MIR merely because a validation layout lookup failed.
Test strategy: Compare a fully specialized async-drop coroutine with placeholder-bearing and non-region-parameter variants, asserting the distinct `TooGeneric` path rather than merely that layout lookup failed. Add a missing-raw-layout case to exercise `Unknown`, plus coroutine-closure by-move and error-tainted coroutine controls. Separately assert Validator continues safely when layout is unavailable while still using raw layout for the current body.
Cases: 140926-ba80d820e5b4fb975f12eabac19e2a9c264a3afb
Source: https://github.com/rust-lang/rust/pull/140926
> `coroutine_layout` fn is now returns `Result` with `LayoutError` to have consistent error with `layout_of_uncached`.
> `async_drop_coroutine_layout` fn is now return `LayoutError::TooGeneric` in case of not-fully-specialized `async_drop_in_place<T>::{closure}` coroutine.
> return Err(self.layout_error(LayoutError::TooGeneric(ty())));
> mir.coroutine_layout_raw().ok_or_else(|| self.layout_error(LayoutError::Unknown(ty())))
> .or_else(|| self.tcx.coroutine_layout(def_id, args).ok())

### PtrMetadata operand validation is phase- and type-shape-specific
For the Validator portion of the PtrMetadata work, Runtime MIR may contain `UnOp::PtrMetadata` only when its operand is a raw pointer or reference; non-pointer, non-reference operands must be rejected. The historical validator allowed only `ty::RawPtr(..)`, but the corrected validator also accepts `ty::Ref(..)`, with the supplied diagnostic "Cannot PtrMetadata non-pointer non-reference type {:?}". PtrMetadata remains Runtime-only and must still be rejected outside Runtime MIR. A separate but adjacent optimization invariant is that any normalization of PtrMetadata must preserve pointer metadata: casts that remove or change metadata, such as `*const [T]` to `*const T`, must not be erased, and only an array-to-slice unsizing cast may supply the array length as metadata.
Preconditions: The validated body is in Runtime MIR and contains `Rvalue::UnaryOp(UnOp::PtrMetadata, arg)`.; The operand type is either `ty::RawPtr(..)` or `ty::Ref(..)` for the valid case.; Outside Runtime MIR, PtrMetadata remains invalid regardless of operand shape.; If testing adjacent optimizer behavior, a `PtrToPtr` cast may be skipped only when the computed metadata types or tail types are equal, and constant folding requires an array-to-slice unsizing cast.
Pitfalls: Do not reject PtrMetadata on references; the updated validator accepts `ty::Ref(..)` as well as raw pointers.; Do not permit PtrMetadata in non-Runtime MIR.; Do not imply that allowing PtrMetadata on references permits eliminating metadata-removing pointer casts.; Do not fold PtrMetadata for casts other than array-to-slice unsizing; only that cast stores the array length in fat-pointer metadata.; When metadata types are known and differ, equality of tail types alone is not sufficient; known and unknown metadata results are distinct.
Test strategy: For Validator coverage, compare Runtime MIR PtrMetadata operations on a raw pointer, a reference, a non-pointer scalar, and PtrMetadata in a non-Runtime body; only the raw-pointer and reference Runtime cases should validate. If checking the adjacent normalization behavior, use paired MIR-dump cases for metadata-removing versus metadata-matching casts and array-to-slice unsizing, including generic pointees where metadata may be unknown.
Cases: 126541-55d13379ac57227a08ba537316adcf2d3c388f57
Source: https://github.com/rust-lang/rust/pull/126541
> Cannot PtrMetadata non-pointer non-reference type {:?}
> It's critical that this not eliminate cases like
> which remove metadata.
> // Metadata usize -> (), do not optimize.
> We have an unsizing cast, which assigns the length to fat pointer metadata.
> let r_value = Rvalue::UnaryOp(UnOp::PtrMetadata, arg.node.clone());
