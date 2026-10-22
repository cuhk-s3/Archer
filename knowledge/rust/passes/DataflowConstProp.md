# DataflowConstProp
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- Do not route `CoroutineClosure` through the `Coroutine` arm: `// Coroutines are never ZST, as they at least contain the implicit states.` but the zero-field coroutine-closure aggregate follows the closure ZST path.
- Do not omit `CoroutineClosure` from def-like aggregate handling in GVN; it is closure-like, not a state-machine coroutine.
- In DataflowConstProp, do not attempt to const-propagate a `CoroutineClosure` write; it should hit the unsupported-type bailout like closures.
- Body ABI is `Abi::RustCall` for a coroutine-closure, not the coroutine `Abi::Rust`; coverage must recognize `AggregateKind::CoroutineClosure` when collecting aggregate spans.
- `.discard_err()` returns `Option<T>` and genuinely ignores the error; it is only right when ignoring possible UB is acceptable, and must not replace propagation where the pass should report failure.
- Do not silently consume with `.ok()`/`.is_err()` or by letting the result fall out of scope; the guard message is `an interpreter error got improperly discarded; use `discard_err()` if this is intentional`.
- Preserve deliberate precedence when combining operations, as in `let (stack_pop_info, ()) = self.pop_stack_frame_raw(unwinding).and(copy_ret_result)?;` justified by `An error here takes precedence over the copy error.` and `let (a, ()) = self.get_ptr_alloc_mut(mplace.ptr(), size).and(misalign_res)?;` justified by `An error from get_ptr_alloc_mut takes precedence.`.
- The guard is suppressed while already panicking to avoid a double panic, so an error discarded inside another panic will not produce the guard diagnostic.
- KnownPanicsLint's `use_ecx` traces and asserts before discarding; bypassing it with a plain `.ok()?` on `layout_of` skips that assertion.
- Do not treat the marker as an actual drop or terminator in const-eval, dataflow, borrowck, coverage, coroutine analysis, or codegen.
- Do not delete the marker or its local merely because the local has no other uses; deleting the local while the marker remains leaves invalid MIR.
- When renumbering locals, update the marker's `place.local`; otherwise a stale local index remains.
- Consult `MaybeInitializedPlaces` before the primary effect because early MIR still contains `Drop` terminators that drop elaboration may remove.
- Exclude `_0`, the closure capture-struct local, descendants of BID places, and types with no significant destructor from the reordered-observer set.
- `ChunkedBitSet::subtract`/`intersect` domain sizes must match and cached chunk counts must be maintained after mutation.
- A slice's length is not generally the length of any source array; only the guarded reborrow/unsize cases are foldable, and subslices or runtime slices must remain symbolic.
- Do not replace `Len` with `PtrMetadata` as an optimization; they have different operands and semantics.
- Do not drop the projection/type guards: GVN falls back to `Some(self.insert(Value::Len(inner)))` and DataflowConstProp to `FlatSet::Top` when the place shape is not understood.
- KnownPanicsLint must not assume a length for partially initialized or unknown aggregates (`Value::Uninit => return None`).
- Do not emit `PtrMetadata` in pre-runtime MIR; the Validator now fails with `PtrMetadata should be in runtime MIR only`.
- Nested field paths lower to a sum of per-hop intrinsic calls, not one flattened `(VariantIdx, FieldIdx)` list; folding only the first call drops the remaining offset.
- Do not fold `const generic::<T>::{constant#0}` to a concrete offset; leave `_1 = const generic::<T>::{constant#0}`.
- Visitors and type checkers must stop calling `visit_ty` for a nullary operand, since `Rvalue::NullaryOp` no longer carries a `Ty`.
- The intrinsic is for const evaluation only: `The new intrinsic is only meant to be used by const-eval. LLVM codegen will refuse to generate code for it.`
- Const checking only honors `span.allows_unstable` for const-stable callees via the guard `if self.span.allows_unstable(feature) && is_const_stable { return; }`.
- Lint/typeck tests that matched the old direct `offset_of` expression must look through `ExprKind::ConstBlock`.

## Patterns Not Well Handled

### Classify new CoroutineClosure as closure-like, not coroutine-like, across MIR policy splits
When a new closure-like MIR aggregate/type variant `CoroutineClosure` is introduced (e.g. from `async || ...`), every pass that splits behaviour between `Closure` and `Coroutine` must audit the split. For DataflowConstProp, the relevant consequence is that writes of `CoroutineClosure` values must take the closure-style unsupported/const-prop bailout rather than being routed through coroutine handling. Adjacent policies in the same audit include GVN ZST/`AggregateTy::Def` classification, RemoveZsts possible-ZST classification, AbortUnwindingCalls body ABI, and coverage aggregate recognition. The underlying distinction is that coroutines are state machines with implicit states, whereas a zero-field coroutine-closure aggregate is closure-like and can be treated as ZST.
Preconditions: The input uses an async closure, producing `TyKind::CoroutineClosure` / `AggregateKind::CoroutineClosure`; this is a compiler-internal nightly lowering, not an ordinary user-named type.; A MIR optimization, const-prop, unwind-abort, or coverage pass runs over the coroutine-closure body or aggregate.; Tests must include a zero-upvar coroutine closure and controls for plain `Closure` and `Coroutine`, since the policies differ for ZST handling.
Pitfalls: Do not route `CoroutineClosure` through the `Coroutine` arm: `// Coroutines are never ZST, as they at least contain the implicit states.` but the zero-field coroutine-closure aggregate follows the closure ZST path.; Do not omit `CoroutineClosure` from def-like aggregate handling in GVN; it is closure-like, not a state-machine coroutine.; In DataflowConstProp, do not attempt to const-propagate a `CoroutineClosure` write; it should hit the unsupported-type bailout like closures.; Body ABI is `Abi::RustCall` for a coroutine-closure, not the coroutine `Abi::Rust`; coverage must recognize `AggregateKind::CoroutineClosure` when collecting aggregate spans.
Test strategy: Generate MIR for async closures with and without captures, then inspect MIR after GVN/RemoveZsts: the empty-field `AggregateKind::CoroutineClosure` should take the closure ZST path and be keyed as a def-like aggregate. Exercise the DataflowConstProp bailout, AbortUnwindingCalls ABI, and coverage paths with an async closure so the new variant is reached rather than only `Closure`/`Coroutine`. Use MIR dumps/diagnostics rather than claiming runtime execution.
Cases: 120361-ed7fca1f8805b4348b801f23f444e0dda42f7aed
Source: https://github.com/rust-lang/rust/pull/120361
> | AggregateKind::CoroutineClosure(did, substs)
> | AggregateKind::CoroutineClosure(..) => true,
> // Coroutines are never ZST, as they at least contain the implicit states.
> | ty::CoroutineClosure(..)
> ty::CoroutineClosure(..) => Abi::RustCall,

### Explicitly consume speculative interpreter errors in const-prop instead of silently dropping them
DataflowConstProp (like GVN, JumpThreading, and KnownPanicsLint) speculatively invokes InterpCx operations and treats interpreter errors as conservative fallbacks (`FlatSet::Top`, `None`, or unknown). With the guarded interpreter-result type, an error-containing result that is dropped unconsumed panics. Pass sites must make intent explicit: call `.discard_err()` where ignoring the error and continuing conservatively is correct, propagate with `?` where the error should surface, or `report_err()` where it should be reported. `.ok()`/`.is_err()`/implicit drop must not be used merely to inspect and then discard an error. When two independent operations can fail, combine them so the intended error takes precedence.
Preconditions: The compiler's `InterpResult` carries a drop guard that panics if an error-containing result is dropped without being consumed.; The optimized MIR drives pass-time interpreter evaluation to `Err`, e.g. invalid projections or discriminants, invalid casts, arithmetic failure, uninitialized reads, or failed constant evaluation.; The pass intends to fall back conservatively rather than emit a compile error.
Pitfalls: `.discard_err()` returns `Option<T>` and genuinely ignores the error; it is only right when ignoring possible UB is acceptable, and must not replace propagation where the pass should report failure.; Do not silently consume with `.ok()`/`.is_err()` or by letting the result fall out of scope; the guard message is `an interpreter error got improperly discarded; use `discard_err()` if this is intentional`.; Preserve deliberate precedence when combining operations, as in `let (stack_pop_info, ()) = self.pop_stack_frame_raw(unwinding).and(copy_ret_result)?;` justified by `An error here takes precedence over the copy error.` and `let (a, ()) = self.get_ptr_alloc_mut(mplace.ptr(), size).and(misalign_res)?;` justified by `An error from get_ptr_alloc_mut takes precedence.`.; The guard is suppressed while already panicking to avoid a double panic, so an error discarded inside another panic will not produce the guard diagnostic.; KnownPanicsLint's `use_ecx` traces and asserts before discarding; bypassing it with a plain `.ok()?` on `layout_of` skips that assertion.
Test strategy: Force each speculative interpreter operation to fail with small MIR inputs (bad projection indices, invalid enum discriminant/niche, failing cast/arithmetic, constant-eval failure). Under a guarded compiler, an intentional discard must fall back to `Top`/`None` without a guard panic, while an accidental `.ok()`/implicit drop must panic with the guard message rather than silently miss UB. Add paired failing-operation cases to confirm frame-pop vs return-copy and allocation-access vs misalignment precedence. Treat these as construction/analysis tests, not executed compiler reproductions.
Cases: 130885-c4ce8c114b06840c3521a189ee44958b713fb33a
Source: https://github.com/rust-lang/rust/pull/130885
> One important invariant of Miri is that when an interpreter error is raised (*in particular* a UB error), those must not be discarded: it's not okay to just check `foo().is_err()` and then continue executing.
> an interpreter error got improperly discarded; use `discard_err()` if this is intentional
> Discard the error information in this result. Only use this if ignoring Undefined Behavior is okay!
> self.ecx.eval_mir_constant(value, DUMMY_SP, None).discard_err()?
> TrackElem::Field(idx) => self.ecx.project_field(op, idx.as_usize()).discard_err(),
> An error here takes precedence over the copy error.
> An error from get_ptr_alloc_mut takes precedence.

### Treat new MIR marker statements as semantic no-ops while preserving their place use
A newly introduced marker statement such as `StatementKind::BackwardIncompatibleDropHint { place, reason }` is semantically equivalent to `Nop` for codegen, MIRI, const-eval, borrowck, coverage, coroutine analysis, and dataflow consumers, but it carries a `Place` whose local must remain valid and correctly indexed through optimization. Local-usage and remapping passes must count the marker's place as a use and rewrite its local. This case is about marker integration and the drop-reachability lint, not about const-prop folding; it should not be treated as a value-producing const-prop operation. Independently, the lint must use `MaybeInitializedPlaces` reachability to avoid flagging droppy tail temporaries that are consumed by the return value, moved into a constructor, explicitly moved/dropped, parameters, or closure captures.
Preconditions: The MIR body contains `StatementKind::BackwardIncompatibleDropHint { place, reason }` while optimization/validation passes run.; The marker is specified as semantically equivalent to `Nop` and therefore must not act as a drop or control-flow terminator.; SimplifyLocals' `UsedLocals`/`remove_unused_definitions_helper` count the marker place, and `LocalUpdater` remaps the marker's local.; The Validator's CFG and type checkers accept the variant as a no-op.; The lint consumes the marker after `mir_promoted`, consulting `MaybeInitializedPlaces` for drops actually in effect.
Pitfalls: Do not treat the marker as an actual drop or terminator in const-eval, dataflow, borrowck, coverage, coroutine analysis, or codegen.; Do not delete the marker or its local merely because the local has no other uses; deleting the local while the marker remains leaves invalid MIR.; When renumbering locals, update the marker's `place.local`; otherwise a stale local index remains.; Consult `MaybeInitializedPlaces` before the primary effect because early MIR still contains `Drop` terminators that drop elaboration may remove.; Exclude `_0`, the closure capture-struct local, descendants of BID places, and types with no significant destructor from the reordered-observer set.; `ChunkedBitSet::subtract`/`intersect` domain sizes must match and cached chunk counts must be maintained after mutation.
Test strategy: Run SimplifyLocals and Validator on a MIR body containing `BackwardIncompatibleDropHint` and check the marked local survives/remaps and all consumers accept the statement; assert codegen/const-eval treat it as a no-op. For the lint, use edition 2021 with `#![deny(tail_expr_drop_order)]`: positive cases (nested block, generic, ADT, async future, transient drops) must lint, while consumed/moved/parameter/closure-capture cases must not, and an edition-2024 gated test verifies the migration lint does not fire. Do not claim compiler execution or reproduction was performed.
Cases: 131326-297b618944d4619a1990b1992d9142c6cf893dc6
Source: https://github.com/rust-lang/rust/pull/131326
> +    /// This is semantically equivalent to `Nop`, so codegen and MIRI should interpret this
> +            | StatementKind::Deinit(ref place)
> +            | StatementKind::BackwardIncompatibleDropHint { ref place, reason: _ } => {
> +                PlaceContext::MutatingUse(MutatingUseContext::Store),
> +fn should_not_lint_when_consumed() -> (LoudDropper, i32) {
> +    // Should not lint because `LoudDropper` is consumed by the return value
> +fn should_not_lint_when_moved() -> i32 {
> +    // Should not lint because `x` is not live
> +    // ^ closure captures like `x` are always dropped last by contract
> -    fn expr_generates_nonlocal_droppy_value(&self, expr: &Expr<'tcx>) -> bool {

### Fold Rvalue::Len only from exact array type or tracked bare-deref slice metadata
DataflowConstProp folds `Rvalue::Len(place)` using the place type: for `ty::Array` it uses the static length, and for a slice it may use tracked wide-pointer length only when the projection is exactly `[ProjectionElem::Deref]`; any other projection must yield `FlatSet::Top`. GVN likewise folds arrays, simple `[Deref]` reborrows, and `PointerCoercion::Unsize` array-to-slice casts, but otherwise retains a symbolic `Value::Len`. `Len` is not interchangeable with `PtrMetadata`: `Len` consumes a place and can be computed from type/tracked metadata, whereas `PtrMetadata` consumes a pointer value. Over-eagerly using a source array's length for a subslice is incorrect because slicing or runtime construction changes the length.
Preconditions: A statement `_l = Len(place)` exists in built/runtime MIR, e.g. from indexing/bounds checks or custom MIR.; `place.ty` is exactly `ty::Array(..)` or `ty::Slice(..)`, as enforced by the Validator.; For arrays, the length const must evaluate to a target `usize`.; DataflowConstProp may consult state only for `[ProjectionElem::Deref]`; GVN may cross only a reborrow whose value is `Value::Address { place: borrowed, .. }` with `[PlaceElem::Deref]`, or an unsize from array to slice.
Pitfalls: A slice's length is not generally the length of any source array; only the guarded reborrow/unsize cases are foldable, and subslices or runtime slices must remain symbolic.; Do not replace `Len` with `PtrMetadata` as an optimization; they have different operands and semantics.; Do not drop the projection/type guards: GVN falls back to `Some(self.insert(Value::Len(inner)))` and DataflowConstProp to `FlatSet::Top` when the place shape is not understood.; KnownPanicsLint must not assume a length for partially initialized or unknown aggregates (`Value::Uninit => return None`).; Do not emit `PtrMetadata` in pre-runtime MIR; the Validator now fails with `PtrMetadata should be in runtime MIR only`.
Test strategy: Use the `tests/mir-opt/dataflow-const-prop/slice_len.rs` pattern with `//@ test-mir-pass: DataflowConstProp`, `//@ compile-flags: -Zmir-enable-passes=+InstSimplify-after-simplifycfg`, and per-panic-strategy/per-bit-width modifiers; assert `// CHECK-NOT: {{_.*}} = Len(`, `// CHECK-NOT: assert(move _`, and `// CHECK: {{_.*}} = const 3_usize;` for a coerced array slice and a promoted const slice. Use `tests/mir-opt/instsimplify/combine_array_len.rs` (`// CHECK-NOT: Len(`) for a fixed array. Force the rvalue with `#[custom_mir(dialect = "built")]` and `let c = Len(x);`. Pair a direct array/unsize constant-fold case with a slice parameter or subslice that must keep a symbolic `Len` to catch over-eager folds. Check MIR dumps, not runtime execution.
Cases: 135709-c69dea90d70212bb430f183df62edc09c8c8a89f
Source: https://github.com/rust-lang/rust/pull/135709
> +            Rvalue::Len(place) => {
> +                } else if let [ProjectionElem::Deref] = place.projection[..] {
> +                    state.get_len(place.local.into(), &self.map)
> +        // The length information is stored in the wide pointer.
> +        // Reborrowing copies length information from one pointer to the other.
> +            && let [PlaceElem::Deref] = borrowed.projection[..]
> +            && let CastKind::PointerCoercion(ty::adjustment::PointerCoercion::Unsize, _) = kind
> +        // Fallback: a symbolic `Len`.
> +                        Value::Uninit => return None,
> // CHECK: {{_.*}} = const 3_usize;
> // CHECK-NOT: {{_.*}} = Len(
> let c = Len(x);

### Do not retain direct OffsetOf rvalue folding after offset_of! lowers to summed intrinsic const blocks
After `offset_of!` lowering changed, MIR no longer contains `Rvalue::NullaryOp(NullOp::OffsetOf(fields), ty)`. Instead the expression is a const block summing one `offset_of::<T>(variant: u32, field: u32)` intrinsic call per path hop. DataflowConstProp, GVN, and KnownPanicsLint must stop folding a dedicated OffsetOf rvalue; any constant folding happens by evaluating the const block, and only when the container is concrete enough. Generic containers such as `Gamma<T>` leave a symbolic `const generic::<T>::{constant#0}` because layout depends on `T`. Nested paths need all per-hop contributions, not just the outer field.
Preconditions: The expression originates from `std::mem::offset_of!`, now expanded to `const { builtin # offset_of(...) }` and desugared at THIR-building time.; The new intrinsic is `pub const fn offset_of<T: PointeeSized>(variant: u32, field: u32) -> usize` with `#[lang = "offset_of"]` and `#[rustc_intrinsic_const_stable_indirect]`.; `Rvalue::NullaryOp` carries only `NullOp::RuntimeChecks` and no type operand; `NullOp::OffsetOf` no longer exists.; The const block's container types must be concrete for layout evaluation to fold to a constant.
Pitfalls: Nested field paths lower to a sum of per-hop intrinsic calls, not one flattened `(VariantIdx, FieldIdx)` list; folding only the first call drops the remaining offset.; Do not fold `const generic::<T>::{constant#0}` to a concrete offset; leave `_1 = const generic::<T>::{constant#0}`.; Visitors and type checkers must stop calling `visit_ty` for a nullary operand, since `Rvalue::NullaryOp` no longer carries a `Ty`.; The intrinsic is for const evaluation only: `The new intrinsic is only meant to be used by const-eval. LLVM codegen will refuse to generate code for it.`; Const checking only honors `span.allows_unstable` for const-stable callees via the guard `if self.span.allows_unstable(feature) && is_const_stable { return; }`.; Lint/typeck tests that matched the old direct `offset_of` expression must look through `ExprKind::ConstBlock`.
Test strategy: Use MIR dump tests. At `-Zmir-opt-level=0`, check generated const bodies in `tests/mir-opt/building/offset_of.rs`: `_0 = offset_of::<Alpha>(const 0_u32, const 0_u32)`, enum `_0 = offset_of::<Blah>(const 1_u32, const 1_u32)`, and `AddWithOverflow` for nested `z.0`/`z.1`. Use `//@ test-mir-pass: GVN` diffs to verify concrete `const concrete::{constant#0}` becomes `_1 = const 4_usize` while generic `const generic::<T>::{constant#0}` stays unfolded. Add UI tests for offset_of! in array lengths and unsized tails. Do not claim runtime execution.
Cases: 148151-e7991602edc786052e94e00777518cd5093209e4
Source: https://github.com/rust-lang/rust/pull/148151
> Replace OffsetOf by an actual sum of calls to intrinsic.
> This PR proposes to replace it by an inline constant which sums calls to a new intrinsic `offset_of(variant index, field index)`.
> The new intrinsic is only meant to be used by const-eval. LLVM codegen will refuse to generate code for it.
> NullOp::OffsetOf(fields) => self
> // CHECK: [[z:_.*]] = offset_of::<Alpha>(const 0_u32, const 2_u32)
> // CHECK: [[sum:_.*]] = AddWithOverflow(copy [[z]], copy [[z0]]);
> _1 = const concrete::{constant#0};
> _1 = const 4_usize;
> _1 = const generic::<T>::{constant#0};
> if self.span.allows_unstable(feature) && is_const_stable {
