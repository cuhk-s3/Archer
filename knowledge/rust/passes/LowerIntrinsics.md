# LowerIntrinsics
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- Do not evaluate `cfg!(debug_assertions)` during macro expansion or const-fold/fold the intrinsic or NullOp before monomorphization.
- Do not make the runtime precondition helper generic; it is intentionally monomorphic and non-inlined.
- Do not execute the runtime check in the interpreter; it already knows the runtime state better.
- MIR and assembly tests must pin `-Cdebug-assertions` and optimization level because the checks and emitted `assume` vary with both.
- The related `InstSimplify` nounwind rule must classify `FnDef`, `Abi::RustCall` closures, and coroutine `Abi::Rust` correctly; it must not remove a call that may unwind.
- Do not reduce intrinsic identity to `intrinsic.name`; that loses whether the body is usable.
- Do not assume every `#[rustc_intrinsic]` is marked `must_be_overridden`; the `vtable_size` run-pass test deliberately lacks the attribute and still expects backend override.
- Avoid checking the raw attribute in hot paths because it creates HIR depgraph edges; use `tcx.intrinsic(def_id).is_some_and(|i| i.must_be_overridden)`.
- The query is legal for any `DefId`, so callers must handle `None` for non-function definitions.
- A missing backend implementation for a `must_be_overridden` intrinsic is a compiler error, not a reason to fall back to `Instance::new` or encode/inline/export the dummy MIR.
- Do not generalize the lowering into a GVN/peephole that converts arbitrary `Offset` on a thin pointer into `PlaceElem::Index`; the `Index` projection on a dereferenced slice pointer cares about metadata, while cast-then-offset ignores the slice length.
- Do not apply the intrinsic lowering to range `SliceIndex` implementations.
- Do not accept an indirect first argument or a non-local index; the lowering assumes neither.
- Select borrow versus raw pointer and mutability from the return type; mishandling this changes aliasing or mutability semantics.
- Do not assume the old `PtrToPtr` plus `Offset` sequence is equivalent to a slice projection.
- Guarding only the panic/check call is insufficient; side effects occur while evaluating the `requires` expression or constructing/capturing the `ensures` closure.
- The ensures checker must be optional: `None` when disabled prevents construction, while `Some(closure)` is built only when enabled.
- Do not remove contract code entirely from HIR when checks are disabled; relying on optimizer elimination preserves type-checking and avoids stale contracts.
- Removing the `contract_checks` intrinsic must be coordinated across its core definition, intrinsic type checking, and the `LowerIntrinsics` match arm.
- Do not conflate runtime panic gating with side-effect gating; `-Zcontract-checks=no` must suppress both.
- Cross-crate behavior is independent: a dependency may be compiled with contract checks enabled while the caller disables them. The early-return limitation remains: a `return` inside a contract returns from the whole function.

## Patterns Not Well Handled

### Defer debug_assertions lowering to a caller-resolved MIR NullOp
For `assert_unsafe_precondition!`, `LowerIntrinsics` may lower `debug_assertions()` into `Rvalue::NullaryOp(NullOp::DebugAssertions, bool)` plus a `Goto`, but the value must remain unresolved until monomorphization/codegen, where it is read from `sess.opts.debug_assertions`. The predicate belongs to the monomorphizing caller, not to the defining library; expansion-time `cfg!(debug_assertions)` or MIR const-folding of the NullOp would bake in the wrong setting.
Preconditions: A call to `sym::debug_assertions` has a target block; lowering pushes the NullOp assignment to the destination and turns the terminator into `Goto { target }`.; The intrinsic is registered as safe and typed as `(0, Vec::new(), tcx.types.bool)`.; `ConstPropLint` and `GVN` return `None` for `NullOp::DebugAssertions`, and codegen materializes `sess.opts.debug_assertions` as a bool.; The interpreter evaluates `NullOp::DebugAssertions` to `false` because it performs the relevant checks itself.; Other MIR consumers, including `PromoteTemps`, must accept the new NullOp; `PromoteTemps` accepts it rather than making a valid candidate unpromotable.; The runtime `precondition_check` is monomorphic, `#[inline(never)]`, and `#[rustc_nounwind]`.
Pitfalls: Do not evaluate `cfg!(debug_assertions)` during macro expansion or const-fold/fold the intrinsic or NullOp before monomorphization.; Do not make the runtime precondition helper generic; it is intentionally monomorphic and non-inlined.; Do not execute the runtime check in the interpreter; it already knows the runtime state better.; MIR and assembly tests must pin `-Cdebug-assertions` and optimization level because the checks and emitted `assume` vary with both.; The related `InstSimplify` nounwind rule must classify `FnDef`, `Abi::RustCall` closures, and coroutine `Abi::Rust` correctly; it must not remove a call that may unwind.
Test strategy: Use mir-opt `EMIT_MIR` diffs for `DataflowConstProp`/`GVN` to verify the expected MIR still contains `_8 = cfg!(debug_assertions);` and a `precondition_check` call instead of a folded constant. For inlining tests, compile with `-Zmir-opt-level=2 -Zinline-mir -Cdebug-assertions=no` so the `#[inline(never)]` check does not suppress the target inlining. Add UI `run-fail` tests with `-Copt-level=3 -Cdebug-assertions=yes` matching messages such as `unsafe precondition(s) violated: slice::from_raw_parts` and `unsafe precondition(s) violated: hint::assert_unchecked`. For assembly/codegen disappearance checks, use optimized builds with `-Cdebug-assertions=no`. These are patch-visible test directives, not claims of execution.
Cases: 120594-dbf817bae1f25f0fa2fbb1e40ab74afc892d9a60
Source: https://github.com/rust-lang/rust/pull/120594
> Adds a new intrinsic, `debug_assertions` which is lowered to a new MIR NullOp, and only to a constant after monomorphization
> Rvalue::NullaryOp(NullOp::DebugAssertions, tcx.types.bool),
> NullOp::DebugAssertions => return None,
> let val = bx.tcx().sess.opts.debug_assertions;
> // The checks hidden behind this are always better done by the interpreter
> #[inline(never)]
> fn precondition_check($($name:$ty),*) {
> if ::core::intrinsics::debug_assertions() {
> if cfg!(debug_assertions) {
> ctx.simplify_nounwind_call(block.terminator.as_mut().unwrap());

### Preserve intrinsic identity and must_be_overridden when deciding whether LowerIntrinsics may replace a call
`LowerIntrinsics` and related MIR consumers must use the richer intrinsic definition (`name` plus `must_be_overridden`), not just the name. A dummy-bodied intrinsic marked `#[rustc_intrinsic_must_be_overridden]` must force backend implementation or an error; it must never be treated as an ordinary function with a usable fallback body. Only when the pass has a real lowering should it replace the call.
Preconditions: The callee type is `ty::FnDef(def_id, _)` and `tcx.intrinsic(def_id)` returns `Some`, as in `&& let Some(intrinsic) = tcx.intrinsic(def_id)` and `tcx.intrinsic(def_id)?`.; The definition is `DefKind::Fn` or `DefKind::AssocFn`; the query returns `None` for other definition kinds.; `must_be_overridden` is true only when the definition carries `#[rustc_intrinsic_must_be_overridden]`; the dummy body exists only to satisfy type checking.; For intrinsics replaced by MIR operations, calls no longer exist after lowering/analyses, so the body is irrelevant.
Pitfalls: Do not reduce intrinsic identity to `intrinsic.name`; that loses whether the body is usable.; Do not assume every `#[rustc_intrinsic]` is marked `must_be_overridden`; the `vtable_size` run-pass test deliberately lacks the attribute and still expects backend override.; Avoid checking the raw attribute in hot paths because it creates HIR depgraph edges; use `tcx.intrinsic(def_id).is_some_and(|i| i.must_be_overridden)`.; The query is legal for any `DefId`, so callers must handle `None` for non-function definitions.; A missing backend implementation for a `must_be_overridden` intrinsic is a compiler error, not a reason to fall back to `Instance::new` or encode/inline/export the dummy MIR.
Test strategy: Use paired Rust UI tests differing only in the marker: a run-pass `vtable_size` intrinsic without `#[rustc_intrinsic_must_be_overridden]`, called through a trait-object vtable and asserting the backend-provided size; and a build-fail `const_deallocate` intrinsic with `#[rustc_intrinsic_must_be_overridden]` whose empty body is never executed, expecting `must be overridden by codegen backend, but isn't`. For pass-level checks, inspect MIR before/after `LowerIntrinsics`/`InstSimplify`; do not infer compiler execution from these directives.
Cases: 120675-c04f0caaff5b09a2202bb220579ef45722e74ed2
Source: https://github.com/rust-lang/rust/pull/120675
> This PR demonstrates the dummy-body scheme with the `vtable_size` intrinsic.
> Whether the intrinsic has no meaningful body and all backends need to shim all calls to it.
> intrinsic {} must be overridden by codegen backend, but isn't
> cause an error instead of silently invoking the body.
> The body is never used, as calls to the intrinsic do not exist
> && let Some(intrinsic) = tcx.intrinsic(def_id)
> return Some((intrinsic.name, args));
> if tcx.intrinsic(def_id).is_some_and(|i| i.must_be_overridden) {

### Lower slice_get_unchecked only to a direct MIR slice projection with explicit argument-shape checks
`LowerIntrinsics` lowers `sym::slice_get_unchecked` with exactly two arguments to a deeper place using `ProjectionElem::Deref` then `ProjectionElem::Index(index_local)`, emitting `Rvalue::RawPtr` or `Rvalue::Ref` according to the intrinsic return type. This makes `<usize as SliceIndex<[T]>>::get`/`get_mut`/`get_unchecked*` look like the built-in `slice[i]` projection after bounds checks, instead of thin-pointer casts plus `intrinsics::offset`.
Preconditions: The intrinsic has exactly two arguments: `let Ok([ptrish, index]) = take_array(args) else { span_bug!(...) }`.; The first argument is a place and is non-indirect: `let place = ptrish.node.place().unwrap(); assert!(!place.is_indirect());`.; The index argument resolves to a local: `index.node.place().unwrap().as_local().unwrap()` for `ProjectionElem::Index`.; The return type is `ty::RawPtr(_, Mutability::Not|Mut)`, `ty::Ref(region, _, Mutability::Not)`, or `ty::Ref(region, _, Mutability::Mut)`; other return types hit `bug!("Unknown return type {ret_ty:?}")`.; The slice pointer is one of `&[T]`, `&mut [T]`, `*const [T]`, or `*mut [T]`, constrained by the library `ChangePointee` bound.; The caller establishes `index < PtrMetadata(slice_ptr)` and in-bounds allocation; safe variants check `self < slice.len()`, unchecked variants use `assume`/`assert_unsafe_precondition`.; Range indexing is excluded because `slice[i..]` and `slice[..k]` use fenceposts, not indices.
Pitfalls: Do not generalize the lowering into a GVN/peephole that converts arbitrary `Offset` on a thin pointer into `PlaceElem::Index`; the `Index` projection on a dereferenced slice pointer cares about metadata, while cast-then-offset ignores the slice length.; Do not apply the intrinsic lowering to range `SliceIndex` implementations.; Do not accept an indirect first argument or a non-local index; the lowering assumes neither.; Select borrow versus raw pointer and mutability from the return type; mishandling this changes aliasing or mutability semantics.; Do not assume the old `PtrToPtr` plus `Offset` sequence is equivalent to a slice projection.
Test strategy: Extend `tests/mir-opt/lower_intrinsics.rs` with functions taking `&[i8]`, `&mut [i16]`, `*const [i32]`, and `*mut [i64]` plus a `usize` index. Use `// EMIT_MIR lower_intrinsics.slice_get.LowerIntrinsics.diff` and CHECK patterns `= &(*_{{[0-9]+}})[_{{[0-9]+}}]`, `= &mut (*_{{[0-9]+}})[_{{[0-9]+}}]`, `= &raw const (*_{{[0-9]+}})[_{{[0-9]+}}]`, and `= &raw mut (*_{{[0-9]+}})[_{{[0-9]+}}]`. Check both panic-abort and panic-unwind diffs, where `#[rustc_nounwind]` keeps the intrinsic's unwind edge unreachable before lowering. Update pre-codegen tests such as `slice_index.slice_get_mut_usize` to show `_5 = &mut (*_1)[_2];` replacing `&raw mut (*_1)` + `PtrToPtr` + `Offset`, and keep range tests showing `PtrToPtr`/`Offset`/`aggregate_raw_ptr`.
Cases: 139118-4668124cc709372c76a0a9a0b2108a3cadd98b78
Source: https://github.com/rust-lang/rust/pull/139118
> `slice.get(i)` should use a slice projection in MIR, like `slice[i]` does
> This PR adds a `slice_get_unchecked` intrinsic for `impl SliceIndex for usize` to use
> This is *not* used for the range versions, since `slice[i..]` and `slice[..k]` can't use the mir Slice projection as they're using fenceposts, not indices.
> I originally tried to do this with some kind of GVN pattern, but realized that I'm pretty sure it's not legal to optimize `BinOp::Offset` to `PlaceElem::Index` without an extremely complicated condition.
> the `Index` projection on a dereferenced slice pointer *cares about the metadata*
> Zero backend changes, because it just lowers to MIR
> assert!(!place.is_indirect());
> ProjectionElem::Index(
> _5 = &mut (*_1)[_2];
> sym::slice_get_unchecked =>

### Do not lower contract-check gating to a runtime intrinsic when contract construction has side effects
The historical contract bug guarded only the final runtime check via `contract_checks()`/`NullOp::ContractChecks` while still constructing/executing `requires` expressions and `ensures` checker closures. The fix guards contract code at compile time using `tcx.sess.contract_checks()` as an HIR boolean, builds the ensures checker only as `Some(closure)` when enabled (`None` otherwise), and removes the `contract_checks` intrinsic together with its `LowerIntrinsics` arm. `LowerIntrinsics` must not be used as the sole gate for contract checks.
Preconditions: The function uses `#[requires(...)]` and/or `#[ensures(...)]` under `#![feature(contracts)]`.; A contract expression or ensures closure construction has an observable side effect, such as mutating a reference argument during capture.; Contract checks are disabled with `-Zcontract-checks=no`.; `LowerIntrinsics` previously lowered `sym::contract_checks` to `Rvalue::NullaryOp(NullOp::ContractChecks, tcx.types.bool)`; after the fix that arm and intrinsic are removed.; Contract HIR is kept and type-checked even when checks are disabled, so `if false`-guarded code is optimized away rather than becoming stale.
Pitfalls: Guarding only the panic/check call is insufficient; side effects occur while evaluating the `requires` expression or constructing/capturing the `ensures` closure.; The ensures checker must be optional: `None` when disabled prevents construction, while `Some(closure)` is built only when enabled.; Do not remove contract code entirely from HIR when checks are disabled; relying on optimizer elimination preserves type-checking and avoids stale contracts.; Removing the `contract_checks` intrinsic must be coordinated across its core definition, intrinsic type checking, and the `LowerIntrinsics` match arm.; Do not conflate runtime panic gating with side-effect gating; `-Zcontract-checks=no` must suppress both.; Cross-crate behavior is independent: a dependency may be compiled with contract checks enabled while the caller disables them. The early-return limitation remains: a `return` inside a contract returns from the whole function.
Test strategy: Add a run-pass/UI test such as `contracts-disabled-side-effect-ensures.rs` with `#[ensures({*x = 0; |_ret| true})]` and `assert_eq!(x, 110);` compiled with `-Zcontract-checks=no`. Exercise requires-only, ensures-only, and both under enabled/disabled revisions, plus cross-crate dependency/caller flag combinations. Update internal-intrinsic tests to pass `Some(closure)` to `contract_check_ensures` and verify `None` skips checking. Add MIR/codegen checks that `if false`-guarded contract code is eliminated.
Cases: 144438-4d23c4135e3d62e1429bce1e851ad7672626bf6e
Source: https://github.com/rust-lang/rust/pull/144438
> Refactor contract HIR lowering to ensure no contract code is executed when contract-checks are disabled.
> The call to `contract_checks` is moved to inside the lowered fn body, and contract closures are built conditionally, ensuring no side-effects present in contracts occur when those are disabled.
> The optimiser should be able to eliminate all contract code guarded
> Rvalue::NullaryOp(NullOp::ContractChecks, tcx.types.bool)
> sym::contract_checks => (0, 0, Vec::new(), tcx.types.bool),
> (2, 0, vec![Ty::new_option(tcx, param(0)), param(1)], param(1))
> If `cond` is `None`, then no postcondition checking is performed.
> #[ensures({*x = 0; |_ret| true})]
> assert_eq!(x, 110);
> It is still possible to early return from the *function* from within a contract
