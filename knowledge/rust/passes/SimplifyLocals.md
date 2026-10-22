# SimplifyLocals
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- Do not describe the fix as a SimplifyLocals transformation; the rewrite occurs in HIR typeck before MIR generation.
- Do not suppress `NeverToAny` merely because the type is `!`; non-place expressions that produce values remain reads.
- Do not generalize the suppression to all destructuring: `Binding`, `Struct`, `TupleStruct`, `Tuple`, `Ref`, `Deref`, `Lit`, `Range`, `Slice`, `Path`, `Box`, and `Never` patterns count as reads.
- `Field` projection is treated as non-reading, but `(*x).0` may still be unsound for separate reasons such as inbounds projection; the fix does not make that sound.
- Edition matters: in edition 2021 and below the compiler does not fall back `!` to `()`; the supplied description notes that a `! -> ()` coercion would be UB if not explicitly disallowed.
- Finite MIR/UI tests do not prove general equivalence; no compiler build, execution, or reproduction is claimed by the supplied case.
- Do not treat the marker as an actual drop or as a control-flow terminator.
- Do not delete the marker simply because it has no ordinary semantic effect; the lint consumer relies on it.
- Do not reject or fail validation merely because the statement variant is new or carries a place.
- Do not conflate marker preservation with actual drop semantics; it is metadata for linting, not a drop operation.
- Do not delete the marker's local just because it has no other uses; deleting the local without deleting or rewriting the marker leaves invalid MIR.
- Do not rename locals without updating the marker's `place.local`; stale local indices invalidate the MIR.
- Do not treat early `Drop` terminators as always in effect; drop elaboration may remove them, so `MaybeInitializedPlaces` must be consulted before the primary effect.
- `ChunkedBitSet::subtract` and `intersect` must not be left unimplemented for the lint's domains; domain sizes must match and cached chunk counts must be maintained after mutation.
- Do not report consumed, moved, parameter, or closure-capture significant-drop values as reordered; those are the historical false positives being avoided.
- The lint change is not itself a SimplifyLocals rewrite; SimplifyLocals' role is preserving and remapping the marker's local.

## Patterns Not Well Handled

### Non-reading never-typed places must not create a `!` value or a diverging block in SimplifyLocals-final MIR
For source under `#![feature(never_type)]`, a syntactic place expression of type `!` whose parent context does not actually read the place must not receive an implicit `NeverToAny` coercion and must not make its containing block diverge. The affected parent contexts are address-of, field projection, assignment LHS, and match/let/let-statement patterns that do not constitute a read. This is a HIR typeck correction, not a SimplifyLocals rewrite; SimplifyLocals-final MIR is the downstream observation point. The historical incorrect transformation treated every expression of type `!` as diverging and inserted `NeverToAny`, which could allow an unread `*x: !` place to make a block coerce to an arbitrary type. The supplied MIR expectation observes whether the non-read place leaves a `!`-typed local or a diverging block.
Preconditions: The expression type is `!` (never type) and the source enables the never-type feature.; The expression is a syntactic place expression, not a value-producing expression.; The parent takes a place rather than a value: `AddrOf`, `Field`, assignment LHS, or a match/let whose pattern is non-reading.; Value-coercion paths such as coercion LUB and suggestion probes may still allow `NeverToAny`; only real expression coercion is gated by the read heuristic.; A pattern counts as a read unless it is a wildcard or an OR pattern whose subpatterns do not all read; `Struct { .. }` on `!` deliberately remains a read.
Pitfalls: Do not describe the fix as a SimplifyLocals transformation; the rewrite occurs in HIR typeck before MIR generation.; Do not suppress `NeverToAny` merely because the type is `!`; non-place expressions that produce values remain reads.; Do not generalize the suppression to all destructuring: `Binding`, `Struct`, `TupleStruct`, `Tuple`, `Ref`, `Deref`, `Lit`, `Range`, `Slice`, `Path`, `Box`, and `Never` patterns count as reads.; `Field` projection is treated as non-reading, but `(*x).0` may still be unsound for separate reasons such as inbounds projection; the fix does not make that sound.; Edition matters: in edition 2021 and below the compiler does not fall back `!` to `()`; the supplied description notes that a `! -> ()` coercion would be UB if not explicitly disallowed.; Finite MIR/UI tests do not prove general equivalence; no compiler build, execution, or reproduction is claimed by the supplied case.
Test strategy: Use paired compile-fail UI tests with `#![feature(never_type)]`: non-reading place cases such as `let _: () = *x;` or a function body ending in `&raw const *x` must now produce E0308 (`expected !`, found `()`), while reading-pattern cases retain the old behavior. Add `//@ edition: 2021` for edition-sensitive cases. Add an `// EMIT_MIR ... SimplifyLocals-final.after.mir` test and check that the non-read place leaves no `&!` local; the supplied expectation shows `debug _input => const ();` for `process_never` and `debug _input => const ZeroSized: Void;` for `process_void`. Include the Miri pass test for underscore patterns and never-typed places. The validated pair uses `input = 0x40 as *const !` and a non-reading wildcard let, exposing the block-type difference without materializing or reading a `!` value.
Cases: 129392-e8d5eb2a2b6cdddd6725501e1b54a33c278d9697
Source: https://github.com/rust-lang/rust/pull/129392
> Do not consider match/let/ref of place that evaluates to `!` to diverge, disallow coercions from them too
> Fixes #117288.
> ### (1.) Disable the `NeverToAny` coercion we implicitly insert for `!`.
> ### (2.) Disable the logic which considers expression which evaluate to `!` to diverge, which affects the type returned by the containing block.
> // EMIT_MIR uninhabited_not_read.main.SimplifyLocals-final.after.mir
> debug _input => const ();
> debug _input => const ZeroSized: Void;
> // Since `*x` is `!`, HIR typeck used to think that it diverges
> // Without a type annotation, make sure we don't implicitly coerce `!` to `()`

### `BackwardIncompatibleDropHint` must be a semantic no-op for MIR analyses and codegen
A MIR body may contain `StatementKind::BackwardIncompatibleDropHint { place, reason }`, a marker generated at a temporary's backwards-incompatible drop location. The marker is explicitly semantically equivalent to `Nop` and exists only to let a MIR lint detect temporary lifetime issues. SimplifyLocals runs over bodies containing it, but must not treat it as an actual drop or control-flow terminator. Historical incorrect integration would either treat the marker as a real drop/control-flow effect or reject it as an unsupported statement; the corrected integration requires all MIR consumers to ignore it semantically while preserving the syntax for the lint.
Preconditions: The marker is specified as semantically equivalent to `Nop`.; Codegen, MIRI, const-eval, borrowck, coverage, coroutine analysis, and dataflow must ignore the marker.; The marker carries a `Box<Place>` and therefore references a local.; The validator's CFG checker and type checker must accept the variant as a no-op rather than reject it or fall into an unsupported-statement path.
Pitfalls: Do not treat the marker as an actual drop or as a control-flow terminator.; Do not delete the marker simply because it has no ordinary semantic effect; the lint consumer relies on it.; Do not reject or fail validation merely because the statement variant is new or carries a place.; Do not conflate marker preservation with actual drop semantics; it is metadata for linting, not a drop operation.
Test strategy: Add MIR/opt tests whose bodies contain `BackwardIncompatibleDropHint`, run SimplifyLocals and the MIR validator, and assert that all MIR consumers accept the statement and treat it as a no-op. Assert that codegen and const-eval treat it as a no-op. No compiler was built and no execution or reproduction was performed in the supplied case.
Cases: 131326-297b618944d4619a1990b1992d9142c6cf893dc6
Source: https://github.com/rust-lang/rust/pull/131326
> +    /// This is semantically equivalent to `Nop`, so codegen and MIRI should interpret this
> +            | StatementKind::Deinit(ref place)
> +            | StatementKind::BackwardIncompatibleDropHint { ref place, reason: _ } => {
> +                    | StatementKind::BackwardIncompatibleDropHint { ref place, reason: _ }
> +            | StatementKind::BackwardIncompatibleDropHint { .. }

### Preserve and remap the marker's `Place` so the drop-reachability lint can consume it
Because `BackwardIncompatibleDropHint` carries a `Place`, SimplifyLocals' local-usage collection and local-removal helper must count that place as a use, and local-renumbering must rewrite the marker's local index. The marker is then consumed by the drop-reachability lint; that lint must consult `MaybeInitializedPlaces` so only drops actually reachable between the marker and the real drop are reported. The historical over-approximation flagged any significant-drop tail temporary whenever a significant-drop local existed, even when the value was consumed by the return value, moved into a constructor, explicitly moved or dropped before the tail, a parameter, or a closure capture. The validated pair models a consumed tuple tail such as `(LoudDropper, x.get())`: the corrected reachability check returns no reorder, while the historical transformation deliberately ignoring the consumed flag returns true.
Preconditions: The MIR body contains `StatementKind::BackwardIncompatibleDropHint { place, reason }` while SimplifyLocals and local-remapping passes run.; `UsedLocals` and `remove_unused_definitions_helper` must count the marker's place as a use.; `LocalUpdater` must remap the marker's `place.local`.; The lint consumes the marker after `mir_promoted` is available and uses `MaybeInitializedPlaces` to count only drops that are actually in effect.; When computing reordered observers, exclude `_0`, the closure capture-struct local, descendants of BID places, and types with no significant destructor.
Pitfalls: Do not delete the marker's local just because it has no other uses; deleting the local without deleting or rewriting the marker leaves invalid MIR.; Do not rename locals without updating the marker's `place.local`; stale local indices invalidate the MIR.; Do not treat early `Drop` terminators as always in effect; drop elaboration may remove them, so `MaybeInitializedPlaces` must be consulted before the primary effect.; `ChunkedBitSet::subtract` and `intersect` must not be left unimplemented for the lint's domains; domain sizes must match and cached chunk counts must be maintained after mutation.; Do not report consumed, moved, parameter, or closure-capture significant-drop values as reordered; those are the historical false positives being avoided.; The lint change is not itself a SimplifyLocals rewrite; SimplifyLocals' role is preserving and remapping the marker's local.
Test strategy: Use MIR/opt tests that run SimplifyLocals and local renumbering on a body containing the marker, checking that the marked local survives or is remapped and that the marker's place remains valid. Keep edition-2021 lint tests with `#![deny(tail_expr_drop_order)]`: positive nested-block, generic, ADT, async-future, and transient-drop cases must lint, while consumed, moved, parameter, and closure-capture cases must not. Keep an edition-2024 gated test verifying the migration lint does not fire. For the consumed case, assert that the corrected reachability check reports no reorder for a tail tuple containing a `LoudDropper` that is moved into the return value, whereas the historical over-approximation returns true. No compiler was built and no execution or reproduction was performed in the supplied case.
Cases: 131326-297b618944d4619a1990b1992d9142c6cf893dc6
Source: https://github.com/rust-lang/rust/pull/131326
> +                PlaceContext::MutatingUse(MutatingUseContext::Store),
> +            | StatementKind::BackwardIncompatibleDropHint { .. }
> -    fn expr_generates_nonlocal_droppy_value(&self, expr: &Expr<'tcx>) -> bool {
> -        if Self::expr_eventually_point_into_local(expr) {
> +fn should_not_lint_when_consumed() -> (LoudDropper, i32) {
> +    // Should not lint because `LoudDropper` is consumed by the return value
> MaybeInitializedPlaces
> #![deny(tail_expr_drop_order)]
