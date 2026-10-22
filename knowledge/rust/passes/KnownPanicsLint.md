# KnownPanicsLint
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- Do not assume a union field value has the type of the field used for access; the underlying layout type may differ.
- Do not try to repair union propagation by coercing or normalizing the immediate; the merged fix deliberately refuses to const-propagate union aggregates.
- Only `AggregateKind::Adt(_, _, _, _, Some(_))` indicates a union; ordinary struct, array, tuple, closure, coroutine, and coroutine-closure aggregates are not covered by this guard.
- Do not treat the `Aggregate` union early-return as independently required after the `NoPropagation` marking exists, but conversely do not remove or weaken that marking while removing the guard.
- A retained comment or test name alone does not prove the replacement is correct; verify which mechanism actually blocks union propagation.
- Do not rely on `layout_of` returning `Err` to reject a local: layout calculation can panic before producing a `Result`.
- Checking only `layout.size < Size::from_bytes(MAX_ALLOC_LIMIT)` is insufficient because the layout query itself may panic for a union.
- The union short-circuit must happen before `tcx.layout_of`; merely discarding a successfully computed layout does not prevent the ICE.
- Union const propagation is intentionally disallowed by KnownPanicsLint, so avoiding the layout query does not lose a supported optimization there.
- The regression test still emits E0517 and E0740; absence of an ICE, not successful compilation, is the relevant outcome.
- Do not generalize this fix to every pass or every non-struct type; the historical change is specifically about KnownPanicsLint's treatment of unions.
- Treating a `*WithOverflow` result as a scalar loses the overflow component or calls `to_scalar()` on a scalar pair.
- Testing `op.is_overflowing()` before normalizing plain Add/Sub/Mul causes false negatives in release builds.
- Neg has no separate overflowing unary op; using `unary_op(Neg, ...)` alone cannot report overflow and must be modeled as `0 - arg` with `SubWithOverflow`.
- Shifts are not `*WithOverflow` binops: their overflow is UB when checked and they return a scalar, so they must not be handled by the pair path.
- Do not let the scalar/pair distinction be inferred from operand types alone; it depends on the specific binop.
- A successful `usize` to `u32` conversion does not imply the value is a valid `FieldIdx`; `FieldIdx::from_u32` has a stricter upper bound and asserts on overflow-range values.
- Validation must happen before `FieldIdx::from_u32` and must use `FieldIdx::MAX_AS_U32`, not merely `u32::MAX`.
- For an unrepresentable index, returning `None` preserves the lint's unknown-value path; constructing a fake `FieldIdx` or suppressing the diagnostic would be incorrect.
- Indices above `u32::MAX` fail the earlier `try_into::<u32>` conversion and do not reach the `FieldIdx::from_u32` assertion, so tests must cover the narrower failing range.
- Nested field paths are lowered as a sum of per-hop intrinsic calls, not as one flattened `(VariantIdx, FieldIdx)` list. For `offset_of!(Alpha, z.0)`, the test expects `offset_of::<Alpha>(const 0_u32, const 2_u32)` plus `offset_of::<Beta>(const 0_u32, const 0_u32)` and an `AddWithOverflow`; folding only the first call or using conjoined `(0, 1)` omits the nested hop.
- Do not fold a generic const block such as `const generic::<T>::{constant#0}` to a concrete offset; its layout depends on `T`. The updated expectations leave these as `_1 = const generic::<T>::{constant#0}`.
- `Rvalue::NullaryOp` no longer carries a `Ty`; visitors and type checkers that previously called `visit_ty` for the nullary operand must stop doing so.
- The new `offset_of` intrinsic is intended only for const evaluation; the PR states `LLVM codegen will refuse to generate code for it`, and it is wrapped in a const block.
- Const checking only honors `span.allows_unstable` (`#[allow_internal_unstable]`) when the callee is const-stable: `if self.span.allows_unstable(feature) && is_const_stable { return; }`, avoiding bypassing recursive stability.
- `offset_of!` now emits a const block, so lint/typeck tests that matched the old direct `offset_of` expression need updating (e.g. the unused-result detection now looks through `ExprKind::ConstBlock`).

## Patterns Not Well Handled

### KnownPanicsLint must not const-propagate union aggregate fields
For the KnownPanicsLint const propagator, a union aggregate must not be evaluated field-by-field into an immediate. A union is encoded as `AggregateKind::Adt(_, _, _, _, Some(_))`; evaluating its fields as ordinary ADT fields can produce a value whose type disagrees with the union's underlying layout type. The safe behavior is to refuse propagation for such aggregates (`return None`). After union-typed locals are marked `ConstPropMode::NoPropagation` in `CanConstProp::check()`, the aggregate early-return becomes redundant, but that marking is the load-bearing safeguard: the aggregate guard may only be removed while the union-local `NoPropagation` marking remains. Rust has no active-variant concept for unions, so union fields cannot be treated as independently propagated aggregate members.
Preconditions: The body is processed by KnownPanicsLint's const propagator (`ConstPropagator` / `CanConstProp`).; A union participates either as an `AggregateKind::Adt` whose final tuple element is `Some(_)`, or as a local whose type satisfies `ty.is_union()`.; The union's fields may be read/written through different types sharing the same storage size, so a propagated immediate can disagree with the underlying layout type.; A later operation consumes the propagated value; in the historical ICE this reached `check_binary_op` and `overflowing_binary_op`.; If the `Aggregate` early-return is absent, `CanConstProp::check()` must mark every union local `NoPropagation`; this is what prevents any attempt to const-propagate unions.
Pitfalls: Do not assume a union field value has the type of the field used for access; the underlying layout type may differ.; Do not try to repair union propagation by coercing or normalizing the immediate; the merged fix deliberately refuses to const-propagate union aggregates.; Only `AggregateKind::Adt(_, _, _, _, Some(_))` indicates a union; ordinary struct, array, tuple, closure, coroutine, and coroutine-closure aggregates are not covered by this guard.; Do not treat the `Aggregate` union early-return as independently required after the `NoPropagation` marking exists, but conversely do not remove or weaken that marking while removing the guard.; A retained comment or test name alone does not prove the replacement is correct; verify which mechanism actually blocks union propagation.
Test strategy: Use focused UI/MIR tests whose MIR exercises a union local written through one field and read through an overlapping differently-typed field, plus a union aggregate construction. Assert compilation succeeds without a layout-calc or binop-evaluation ICE and that the union local/aggregate is not propagated. Construct two otherwise identical configurations: one where `CanConstProp::check()` marks union locals `NoPropagation` (expected safe) and one where that marking is absent while only the redundant `Aggregate` guard is removed (the unsafe configuration that can propagate layout-mismatched union values). For the historical bincode failure, the merged regression uses `union Union { u32_field: u32, i32_field: i32 }`, initializes variants with `2` and `3`, reads both through `u32_field`, and computes `let _diff = a - b;` under `//@ build-pass`. Prefer MIR/UI assertions over runtime behavior because the invariant is a compile-time propagation restriction.
Cases: 121628-633c92cd6de9e269b9c5b10f341fc10280503f0c, 124550-741d40f327291404172b3f35377d8464688c2fe7
Source: https://github.com/rust-lang/rust/pull/121628
Source: https://github.com/rust-lang/rust/pull/124550
> Do not const pop unions
> as they can made to produce values whose types don't
> underlying layout's type (see ICE #121534).
> if let AggregateKind::Adt(_, _, _, _, Some(_)) = **kind {
> invalid asymmetric binary op Sub: 4294967294 (i32), 2 (u32)
> Tests that no ICE occurs in KnownPanicsLint when it
> layout types even though they have the same type.
> Remove redundant union check in `KnownPanicsLint` const prop
> because we are already marking unions `NoPropagation` in
> `CanConstProp::check()`. That is enough to prevent any attempts
> *val = ConstPropMode::NoPropagation;
> // Unions are incompatible with the current implementation of
> // const prop because Rust has no concept of an active
> // variant of a union

### Mark union-typed locals NoPropagation before any layout query
KnownPanicsLint's can-const-prop refinement must short-circuit union-typed locals with `ty.is_union()` and set `ConstPropMode::NoPropagation` before calling `tcx.layout_of`. The old path requested layout for every candidate local and relied on `layout_of` returning `Err` to reject it. For some unions, layout calculation panics inside `rustc_abi` instead of returning an error, specifically when the union contains an enum with an unsupported `#[repr(packed)]`, producing the assertion `non-Aggregate field with matching ABI but differing alignment`. Nothing is lost by skipping the query because KnownPanicsLint does not const-propagate unions anyway. The check must occur before `layout_of`; computing layout first and then discarding it is insufficient.
Preconditions: The local is present in `cpv.can_const_prop` when KnownPanicsLint performs its can-const-prop refinement.; `body.local_decls[local].ty` is a union type.; The implementation lacks an early `ty.is_union()` check and therefore invokes `tcx.layout_of` for that local.; The union's layout calculation can panic in `layout_of_union`, for example when the union contains an enum with an unsupported repr such as `#[repr(packed)]`.; `CanConstProp::check()` is present and is the actual mechanism marking every union local as non-propagatable.
Pitfalls: Do not rely on `layout_of` returning `Err` to reject a local: layout calculation can panic before producing a `Result`.; Checking only `layout.size < Size::from_bytes(MAX_ALLOC_LIMIT)` is insufficient because the layout query itself may panic for a union.; The union short-circuit must happen before `tcx.layout_of`; merely discarding a successfully computed layout does not prevent the ICE.; Union const propagation is intentionally disallowed by KnownPanicsLint, so avoiding the layout query does not lose a supported optimization there.; The regression test still emits E0517 and E0740; absence of an ICE, not successful compilation, is the relevant outcome.; Do not generalize this fix to every pass or every non-struct type; the historical change is specifically about KnownPanicsLint's treatment of unions.
Test strategy: Add a UI regression test for a union whose field is an enum annotated with `#[repr(packed)]` and `#[repr(u32)]`, then construct the union. Expected stderr should contain E0517 for the invalid enum repr and E0740 for the non-`Copy`/non-`ManuallyDrop` union field, but no rustc ICE or layout panic. The proposed test removes the former `tests/crashes/123710.rs` known-bug case, reflecting that this is now a fixed regression. For MIR-level testing, model the layout query outcome explicitly (e.g. an `Err`/`Panic` variant) rather than reproducing a compiler panic, and assert that union-typed locals take the `NoPropagation` path before any layout request.
Cases: 124504-254a9fbe86a4a6d3c0481f7924c4b0393e1a230e, 124550-741d40f327291404172b3f35377d8464688c2fe7
Source: https://github.com/rust-lang/rust/pull/124504
Source: https://github.com/rust-lang/rust/pull/124550
> Mark unions non-const-propagatable in `KnownPanicsLint` without calling layout
> The ICE occurs during the layout calculation of the union `InvalidTag` in #123710 because the following assert fails
> So in this fix I skip the call to layout and just mark the local non-const propagatable if it is a union.
> as they have a potential to ICE during layout calculation
> if ty.is_union() {
> *val = ConstPropMode::NoPropagation;
> assertion `left == right` failed: non-Aggregate field with matching ABI but differing alignment
> error[E0517]: attribute should be applied to a struct or union
> error[E0740]: field must implement `Copy` or be wrapped in `ManuallyDrop<...>` to be used in a union
> It is not needed because after PR #124504 we mark unions as `NoPropagation` over here
> because we are already marking unions `NoPropagation` in
> `CanConstProp::check()`. That is enough to prevent any attempts

### KnownPanicsLint must normalize plain Add/Sub/Mul to overflowing binops before checking overflow
In KnownPanicsLint, the overflow-lint check must handle both explicit `*WithOverflow` operators and plain Add/Sub/Mul. MIR in release builds uses plain Add/Sub/Mul, and overflow assertions exist only in debug builds, so testing `op.is_overflowing()` before normalization misses release-mode overflow. The correct sequence is to normalize with `op.wrapping_to_overflowing().unwrap_or(op)` and then verify the normalized op is overflowing. The result of an overflowing binop is a scalar pair `(value, overflow)`, not a scalar; the lint must consume the overflow component correctly. Neg has no separate overflowing unary op, so overflow must be modeled as `0 - arg` with `SubWithOverflow`.
Preconditions: KnownPanicsLint evaluates an integral `Rvalue::BinaryOp` whose op is Add, Sub, Mul, or an explicit `*WithOverflow` variant, or examines an integral `UnOp::Neg`.; `binary_op` is op-dependent: it produces a scalar for ordinary ops and a scalar pair for `*WithOverflow` ops.; `wrapping_to_overflowing()` maps Add/Sub/Mul to their `*WithOverflow` forms; `is_overflowing()` is true only for the overflowing forms.; The lint must normalize before testing `is_overflowing()` because plain Add/Sub/Mul in release MIR are not themselves overflowing operators.
Pitfalls: Treating a `*WithOverflow` result as a scalar loses the overflow component or calls `to_scalar()` on a scalar pair.; Testing `op.is_overflowing()` before normalizing plain Add/Sub/Mul causes false negatives in release builds.; Neg has no separate overflowing unary op; using `unary_op(Neg, ...)` alone cannot report overflow and must be modeled as `0 - arg` with `SubWithOverflow`.; Shifts are not `*WithOverflow` binops: their overflow is UB when checked and they return a scalar, so they must not be handled by the pair path.; Do not let the scalar/pair distinction be inferred from operand types alone; it depends on the specific binop.
Test strategy: Exercise KnownPanicsLint overflow checks with constant operands in release mode where MIR uses plain Add/Sub/Mul, and assert the arithmetic-overflow lint fires. Include `Op::Add` with `(i32::MAX, 1)`, `Op::AddWithOverflow` with `(i32::MAX, 1)`, and a non-overflowing `Op::Add` with `(2, 3)`; also test `Neg` at the minimum value (`i32::MIN`) and non-overflowing boundaries. Assert that the explicit `*WithOverflow` case consumes the overflow component as a scalar pair rather than treating the result as a scalar. Prefer MIR/UI tests around the lint's evaluation path over broad compile tests, and inspect MIR after the pass where possible.
Cases: 125359-cb5319483e0691393bd3e09a808f734321a23d20
Source: https://github.com/rust-lang/rust/pull/125359
> Whether this produces a scalar or a pair depends on the specific `bin_op`.
> Rvalue::BinaryOp(op, box (left, right)) if !op.is_overflowing() => {
> // The overflowing operators are handled in `handle_assign`.
> if matches!(val.layout.abi, Abi::ScalarPair(..)) {
> let (val, overflow) = val.to_scalar_pair();
> let op = op.wrapping_to_overflowing().unwrap_or(op);
> // lint in release builds as well, so we check on the operation instead.
> // Compute this as `0 - arg` so we can use `SubWithOverflow` to check for overflow.
> .binary_op(BinOp::SubWithOverflow, &ImmTy::from_int(0, arg.layout), &arg)?
> So normalize to the "overflowing" operator, and then ensure that it
> actually is an overflowing operator.

### Validate aggregate index against FieldIdx::MAX_AS_U32 before constructing FieldIdx
In KnownPanicsLint's `Value::get_const`, the `(PlaceElem::Index(idx), Value::Aggregate { fields, .. })` branch must validate a constant index against `FieldIdx::MAX_AS_U32` before calling `FieldIdx::from_u32`. A target-`usize` index may fit in `u32` but still exceed `FieldIdx`'s representable range; `FieldIdx::from_u32` asserts `value <= 0xFFFF_FF00`, so large indices such as `u32::MAX` or `u32::MAX - 1` previously caused an assertion failure/ICE. Out-of-range indices must return `None` so the normal out-of-bounds lint diagnostics proceed; they must not be coerced to a fake `FieldIdx` or suppressed.
Preconditions: MIR contains constant indexing of an aggregate/array that KnownPanicsLint attempts to evaluate.; The index constant is resolvable as a target `usize`.; The index is greater than `FieldIdx::MAX_AS_U32` (`0xFFFF_FF00`) but still fits in `u32`, such as `u32::MAX` or `u32::MAX - 1`.; The historical code converts the index to `u32` and calls `FieldIdx::from_u32` without checking the stricter `FieldIdx` upper bound.
Pitfalls: A successful `usize` to `u32` conversion does not imply the value is a valid `FieldIdx`; `FieldIdx::from_u32` has a stricter upper bound and asserts on overflow-range values.; Validation must happen before `FieldIdx::from_u32` and must use `FieldIdx::MAX_AS_U32`, not merely `u32::MAX`.; For an unrepresentable index, returning `None` preserves the lint's unknown-value path; constructing a fake `FieldIdx` or suppressing the diagnostic would be incorrect.; Indices above `u32::MAX` fail the earlier `try_into::<u32>` conversion and do not reach the `FieldIdx::from_u32` assertion, so tests must cover the narrower failing range.
Test strategy: Add a build-fail UI regression for constant indexing with both an ordinary out-of-bounds case and the high-index case. The historical test uses `[64][200]` plus `let _n = [64][u32::MAX as usize - 1];`, asserts both emit `unconditional_panic`, and checks the high-index stderr reports `index out of bounds: the length is 1 but the index is 4294967294` rather than an ICE. Remove the former `tests/crashes/121126.rs` known-bug case once the behavior is a normal UI diagnostic. At MIR level, assert that an index of `4_294_967_294usize` returns `None` rather than panicking.
Cases: 125821-d3c8e6788cfbcc64ab7710cab7a56e276e7d5a7a
Source: https://github.com/rust-lang/rust/pull/125821
> fixes #121126
> check `idx <= FieldIdx::MAX_AS_U32` before calling `FieldIdx::from_u32` to avoid panic.
> -                    fields.get(FieldIdx::from_u32(idx.try_into().ok()?)).unwrap_or(&Value::Uninit)
> +                    if idx <= FieldIdx::MAX_AS_U32 {
> assertion failed: value <= 0xFFFF_FF00
> // issue #121126, test index value between 0xFFFF_FF00 and u32::MAX
> let _n = [64][u32::MAX as usize - 1];
> index out of bounds: the length is 1 but the index is 4294967294

### Do not fold removed NullOp::OffsetOf; evaluate offset_of! const blocks per hop
`offset_of!` lowering changed from a dedicated `Rvalue::NullaryOp(NullOp::OffsetOf(fields), ty)` to a const block that sums calls to a new `offset_of::<T>(variant: u32, field: u32)` intrinsic, one call per path hop. KnownPanicsLint must therefore stop recognizing and directly folding `NullOp::OffsetOf`; that rvalue no longer exists. The const block may be folded to a concrete `usize` only when the container type is sufficiently concrete for layout evaluation. For nested paths, folding only the first intrinsic call or treating the expression as a single flattened offset is wrong; `offset_of!(Alpha, z.0)` lowers to the sum of the `Alpha` hop and the `Beta` hop plus an `AddWithOverflow`. Generic containers such as `generic::<T>` must remain opaque and unfolded because their layout depends on `T`.
Preconditions: The expression originates from `std::mem::offset_of!`, which now expands to a const block and is desugared at THIR-building time.; The new intrinsic is declared `pub const fn offset_of<T: PointeeSized>(variant: u32, field: u32) -> usize` with `#[lang = "offset_of"]` and `#[rustc_intrinsic_const_stable_indirect]`.; The MIR rvalue model no longer has `NullOp::OffsetOf`; `Rvalue::NullaryOp` carries only `NullOp::RuntimeChecks`, with no separate type operand.; For folding to a constant, the const block's container types must be concrete enough for layout evaluation; generic containers leave the const block in place.
Pitfalls: Nested field paths are lowered as a sum of per-hop intrinsic calls, not as one flattened `(VariantIdx, FieldIdx)` list. For `offset_of!(Alpha, z.0)`, the test expects `offset_of::<Alpha>(const 0_u32, const 2_u32)` plus `offset_of::<Beta>(const 0_u32, const 0_u32)` and an `AddWithOverflow`; folding only the first call or using conjoined `(0, 1)` omits the nested hop.; Do not fold a generic const block such as `const generic::<T>::{constant#0}` to a concrete offset; its layout depends on `T`. The updated expectations leave these as `_1 = const generic::<T>::{constant#0}`.; `Rvalue::NullaryOp` no longer carries a `Ty`; visitors and type checkers that previously called `visit_ty` for the nullary operand must stop doing so.; The new `offset_of` intrinsic is intended only for const evaluation; the PR states `LLVM codegen will refuse to generate code for it`, and it is wrapped in a const block.; Const checking only honors `span.allows_unstable` (`#[allow_internal_unstable]`) when the callee is const-stable: `if self.span.allows_unstable(feature) && is_const_stable { return; }`, avoiding bypassing recursive stability.; `offset_of!` now emits a const block, so lint/typeck tests that matched the old direct `offset_of` expression need updating (e.g. the unused-result detection now looks through `ExprKind::ConstBlock`).
Test strategy: Use MIR dump tests. At `-Zmir-opt-level=0`, check the generated const bodies directly: `_0 = offset_of::<Alpha>(const 0_u32, const 0_u32)`, enum `_0 = offset_of::<Blah>(const 1_u32, const 1_u32)`, and nested `AddWithOverflow` for `z.0`/`z.1`. For constant propagation, use MIR pass diffs to check that a concrete `const concrete::{constant#0}` becomes `_1 = const 4_usize`, while `const generic::<T>::{constant#0}` stays unfolded. Add UI tests for `offset_of!` inside array lengths and for unsized tails. For the nested-hop regression, a stale pass that folds only the outer `OffsetOf(Alpha, z)` returns 4 for `repr(C) Alpha { x:u8, y:u16, z:Beta }` with `offset_of!(Alpha, z.1)`, whereas the correct per-hop sum is `offset_of!(Alpha, z) = 4` plus `offset_of!(Beta, 1) = 1`, giving 5.
Cases: 148151-e7991602edc786052e94e00777518cd5093209e4
Source: https://github.com/rust-lang/rust/pull/148151
> Replace OffsetOf by an actual sum of calls to intrinsic.
> This PR proposes to replace it by an inline constant which sums calls to a new intrinsic `offset_of(variant index, field index)`.
> The new intrinsic is only meant to be used by const-eval. LLVM codegen will refuse to generate code for it.
> NullOp::OffsetOf(fields) => self
> pub enum NullOp {
> RuntimeChecks(RuntimeChecks),
> NullaryOp(NullOp),
> // CHECK: [[z:_.*]] = offset_of::<Alpha>(const 0_u32, const 2_u32)
> // CHECK: [[sum:_.*]] = AddWithOverflow(copy [[z]], copy [[z0]]);
> _1 = const concrete::{constant#0};
> _1 = const 4_usize;
> _1 = const generic::<T>::{constant#0};
> if self.span.allows_unstable(feature) && is_const_stable {
> #[rustc_intrinsic_const_stable_indirect]
> #[lang = "offset_of"]
