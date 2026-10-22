# InstSimplify
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- Matching only on the intrinsic name loses whether the body is usable; `must_be_overridden` must travel with the intrinsic identity.
- Do not assume every `#[rustc_intrinsic]` is marked `must_be_overridden`: the run-pass `vtable_size` test omits the marker and still expects the backend to override its panic body.
- Checking the raw attribute in hot paths creates HIR depgraph edges; use the intrinsic query instead of `has_attr(..., sym::rustc_intrinsic_must_be_overridden)`.
- A missing backend implementation for a `must_be_overridden` intrinsic is a compiler error, not a reason to fall back to the dummy MIR/body.
- Simplifying `UbChecks` in a crate carrying `#![rustc_preserve_ub_checks]` freezes that crate's setting and can disable runtime UB checks when it is monomorphized into a crate with debug assertions.
- Do not confuse this delayed intrinsic with source-level `cfg!(debug_assertions)`; the attribute exists specifically to preserve delayed evaluation.
- The replacement must be an actual constant assignment, e.g. `_4 = const false; assume(_4);` under `-Cdebug-assertions=no`, not merely deletion of the `assume`.
- Other MIR output tests may change when the constant exposes duplicate switch targets or unreachable UB-check blocks; update expectations only where the new constant justifies it.
- A retained test name or stale comment is not evidence that the replacement pass is wrong; compare the actual assignment.
- Do not equate `ub_checks` with `debug_assertions`: inheritance is only the default, and `-Zub-checks` can override it in either direction.
- Do not confuse `ub_checks` with `overflow_checks`; they are separate gates.
- `cfg!(debug_assertions)` and `cfg!(ub_checks)` answer different questions once the flags diverge; testing only the former misses the regression.
- Run-pass-only tests can miss unwanted checks that remain in optimized IR; inspect generated code or IR when the expected behavior is check absence.
- Tests using default flag values cannot expose the historical substitution because inheritance makes both implementations agree.
- Do not equate references by their referents: constants `&DATA[0]` through `&DATA[4]` have equal pointee values but different addresses, so the array must not become a repeat.
- Do not assume non-constant move/copy operands are equal; InstSimplify cannot see through them and should leave the aggregate for GVN.
- Bail out when const evaluation fails; do not panic or substitute a guessed value.
- Respect the `fields.len() < 5` threshold so short arrays are unchanged.
- Compare full evaluated const values, not merely syntactic constants or types.

## Patterns Not Well Handled

### Preserve full intrinsic identity when InstSimplify resolves intrinsic calls
For InstSimplify, a call whose callee is `ty::FnDef(def_id, args)` and for which `tcx.intrinsic(def_id)` succeeds may be simplified only when a real simplification exists. Intrinsic identity must include whether the definition is backend-required (`must_be_overridden`), not just its name. A dummy/placeholder body is not a usable fallback: for a `must_be_overridden` intrinsic, the correct behavior is backend lowering or a compiler error, whereas a name-only model can leave the call to be treated as an ordinary function/body. The original path used `let Some(intrinsic) = tcx.intrinsic(def_id)` and returned `Some((intrinsic.name, args))`; the corrected model carries `IntrinsicDef { name, must_be_overridden }` and checks e.g. `if tcx.intrinsic(def_id).is_some_and(|i| i.must_be_overridden) {`.
Preconditions: The callee type is `ty::FnDef(def_id, _)` and `tcx.intrinsic(def_id)` returns `Some`.; The definition is a function-like `DefKind`; the enriched query returns `None` for other definition kinds, so callers must handle that.; `must_be_overridden` is true only for definitions annotated `#[rustc_intrinsic_must_be_overridden]`; the dummy body exists only to satisfy type checking.; For intrinsics that `LowerIntrinsics` replaces with MIR operations, the body becomes irrelevant after those calls are lowered.
Pitfalls: Matching only on the intrinsic name loses whether the body is usable; `must_be_overridden` must travel with the intrinsic identity.; Do not assume every `#[rustc_intrinsic]` is marked `must_be_overridden`: the run-pass `vtable_size` test omits the marker and still expects the backend to override its panic body.; Checking the raw attribute in hot paths creates HIR depgraph edges; use the intrinsic query instead of `has_attr(..., sym::rustc_intrinsic_must_be_overridden)`.; A missing backend implementation for a `must_be_overridden` intrinsic is a compiler error, not a reason to fall back to the dummy MIR/body.
Test strategy: Use paired UI tests that differ only in the intrinsic marker and expected outcome: a run-pass `vtable_size` intrinsic without `#[rustc_intrinsic_must_be_overridden]`, called through a trait-object vtable and expecting backend-provided size `0`; and a build-fail `const_deallocate` intrinsic with `#[rustc_intrinsic_must_be_overridden]` and an empty body, expecting the diagnostic `must be overridden by codegen backend, but isn't` rather than silent execution. For pass-level verification, inspect MIR before/after `InstSimplify`; these are targeted source/MIR checks, not execution proof.
Cases: 120675-c04f0caaff5b09a2202bb220579ef45722e74ed2
Source: https://github.com/rust-lang/rust/pull/120675
> This PR demonstrates the dummy-body scheme with the `vtable_size` intrinsic.
> Whether the intrinsic has no meaningful body and all backends need to shim all calls to it.
> intrinsic {} must be overridden by codegen backend, but isn't
> cause an error instead of silently invoking the body.
> gets overridden by llvm backend even if there is no
> `#[rustc_intrinsic_must_be_overridden]` to the function to ensure that backends don't
> The body is never used, as calls to the intrinsic do not exist
> && let Some(intrinsic) = tcx.intrinsic(def_id)
> return Some((intrinsic.name, args));
> if tcx.intrinsic(def_id).is_some_and(|i| i.must_be_overridden) {

### Do not fold UbChecks in crates carrying rustc_preserve_ub_checks
InstSimplify may replace `Rvalue::NullaryOp(NullOp::UbChecks, _)` with a boolean constant, enabling other MIR passes to treat UB-check gating as constant after inlining UB-check helpers. The transformation must be guarded: when the crate has `#![rustc_preserve_ub_checks]`, the `UbChecks()` assignment must remain delayed so monomorphization into a downstream crate can evaluate the downstream UB-check setting. The historical incorrect transformation folds `UbChecks` unconditionally, freezing the preserving standard-library crate's setting and losing runtime UB checks in a downstream crate. The historic guard is `if !preserve_ub_checks { ctx.simplify_ub_check(&statement.source_info, rvalue); }`, with `preserve_ub_checks` sourced from `attr::contains_name(tcx.hir().krate_attrs(), sym::rustc_preserve_ub_checks);`.
Preconditions: The MIR rvalue is exactly `Rvalue::NullaryOp(NullOp::UbChecks, _)`.; The crate being optimized does not contain the crate-level attribute `rustc_preserve_ub_checks`.; The replacement boolean comes from the compilation setting in effect for UB checks; the quoted pre-separation implementation names `tcx.sess.opts.debug_assertions`.; The original statement's source info/span is reused for the new constant operand so diagnostics stay tied to the `UbChecks` site.
Pitfalls: Simplifying `UbChecks` in a crate carrying `#![rustc_preserve_ub_checks]` freezes that crate's setting and can disable runtime UB checks when it is monomorphized into a crate with debug assertions.; Do not confuse this delayed intrinsic with source-level `cfg!(debug_assertions)`; the attribute exists specifically to preserve delayed evaluation.; The replacement must be an actual constant assignment, e.g. `_4 = const false; assume(_4);` under `-Cdebug-assertions=no`, not merely deletion of the `assume`.; Other MIR output tests may change when the constant exposes duplicate switch targets or unreachable UB-check blocks; update expectations only where the new constant justifies it.; A retained test name or stale comment is not evidence that the replacement pass is wrong; compare the actual assignment.
Test strategy: Add an `InstSimplify` MIR-opt test compiled with `//@ compile-flags: -Cdebug-assertions=no -Zinline-mir` and `//@ unit-test: InstSimplify`, using an inlined `Option::unwrap_unchecked` path. Assert `// CHECK-NOT: UbChecks()`, then `// CHECK: [[assume:_.*]] = const false;` and `// CHECK-NEXT: assume([[assume]]);`. Add a companion crate-level `#![rustc_preserve_ub_checks]` case and verify the `UbChecks()` assignment is retained; the guard condition is the semantic core. These emitted-MIR checks test specific cases, not universal equivalence.
Cases: 122975-47ed73a7b510b416a191f343c2f07826e8072396
Source: https://github.com/rust-lang/rust/pull/122975
> The purpose of this PR is to allow other passes to treat `UbChecks` as constants in MIR for optimization after #122629.
> Eliminate `UbCheck` for non-standard libraries
> if !preserve_ub_checks {
> ctx.simplify_ub_check(&statement.source_info, rvalue);
> attr::contains_name(tcx.hir().krate_attrs(), sym::rustc_preserve_ub_checks);
> fn simplify_ub_check(&self, source_info: &SourceInfo, rvalue: &mut Rvalue<'tcx>) {
> if let Rvalue::NullaryOp(NullOp::UbChecks, _) = *rvalue {
> let const_ = Const::from_bool(self.tcx, self.tcx.sess.opts.debug_assertions);
> `#![rustc_preserve_ub_checks]` prevents the designated crate from evaluating whether UB checks are enabled when optimizing MIR
> flags: if the crate has debug assertions enabled or carries the `#[rustc_preserve_ub_checks]`
> //@ unit-test: InstSimplify
> //@ compile-flags: -Cdebug-assertions=no -Zinline-mir
> // CHECK-NOT: UbChecks()
> // CHECK: [[assume:_.*]] = const false;
> // CHECK-NEXT: assume([[assume]]);

### Fold NullOp::UbChecks using Session::ub_checks(), not debug_assertions directly
`-Zub-checks` defaults to `-Cdebug-assertions` but explicitly overrides it. InstSimplify folding `NullOp::UbChecks` must therefore use `sess.ub_checks()` (`unstable_opts.ub_checks.unwrap_or(debug_assertions)`), not `sess.opts.debug_assertions` directly. The historical transformation `let const_ = Const::from_bool(self.tcx, self.tcx.sess.opts.debug_assertions);` is wrong when the flags diverge: with debug assertions enabled and UB checks disabled it retains checks that should be absent, and with debug assertions disabled and UB checks enabled it removes checks that should be present. The corrected fold uses `Const::from_bool(self.tcx, self.tcx.sess.ub_checks());`.
Preconditions: The compilation contains a `NullOp::UbChecks` value; without one the flag choice has no observable effect on this fold.; `-Zub-checks` is absent or explicitly divergent from `-Cdebug-assertions`; when absent, UB checks inherit debug assertions and the old and corrected source agree.; The test should distinguish actual UB-check behavior in optimized code, because the folding changes emitted IR/runtime behavior.; Using user-source `cfg!(ub_checks)` additionally requires the `cfg_ub_checks` feature gate.
Pitfalls: Do not equate `ub_checks` with `debug_assertions`: inheritance is only the default, and `-Zub-checks` can override it in either direction.; Do not confuse `ub_checks` with `overflow_checks`; they are separate gates.; `cfg!(debug_assertions)` and `cfg!(ub_checks)` answer different questions once the flags diverge; testing only the former misses the regression.; Run-pass-only tests can miss unwanted checks that remain in optimized IR; inspect generated code or IR when the expected behavior is check absence.; Tests using default flag values cannot expose the historical substitution because inheritance makes both implementations agree.
Test strategy: Use a codegen test compiled with `-O -Cdebug-assertions=yes`, with revisions `DEBUG` and `NOCHECKS` where `NOCHECKS` adds `-Zub-checks=no`. For `pub unsafe fn slice_get_unchecked(x: &[i32], i: usize) -> &i32 { x.get_unchecked(i) }`, check for `icmp ult`, `br i1`, `call core::panicking::panic_nounwind`, and `unreachable` in the enabled case, and for `tail call void @llvm.assume` plus `getelementptr inbounds` in the disabled case. Also use divergent `-Cdebug-assertions=no -Zub-checks=yes` coverage and a default test asserting inheritance. These are focused flag-selection checks, not proof of universal behavior.
Cases: 123411-a7912cb421db4f4039048cdba2b7fc98ae295342
Source: https://github.com/rust-lang/rust/pull/123411
> -            let const_ = Const::from_bool(self.tcx, self.tcx.sess.opts.debug_assertions);
> +            let const_ = Const::from_bool(self.tcx, self.tcx.sess.ub_checks());
> By default, `-Zub-checks` flag inherits the value of `-Cdebug-assertions`.
> This test ensures that such a runtime check is *not* emitted when debug-assertions are enabled,
> but ub-checks are explicitly disabled.
> //@ [NOCHECKS] compile-flags: -Zub-checks=no
> //@ compile-flags: -O -Cdebug-assertions=yes
> // NOCHECKS: tail call void @llvm.assume
> //    DEBUG: call core::panicking::panic_nounwind
> assert_eq!(cfg!(ub_checks), cfg!(debug_assertions));

### Repeated-array folding must compare full const-evaluated values, including addresses
`InstSimplify::simplify_repeated_aggregate` may rewrite an array aggregate of at least five identical constant elements into `Rvalue::Repeat`, e.g. `[0, 0, 0, 0, 0]` into `[0; 5]`. Soundness requires comparing full const-evaluation results. The historical incorrect transformation collapses distinct constant references that point to equal referents, i.e. decides equality by referent/value rather than by the full const value including pointer address. The negative test states `// All of these consts refer to the same value, but the addresses are all different.` and `// It would be wrong to apply the optimization here.` Another incorrect variant treats move/copy local operands as equal; the `local` case retains `_0 = [move _2, move _3, move _4, move _5, move _6];` with the note `// InstSimplify isn't able to see through the move operands, but GVN can.`
Preconditions: The rvalue is `Rvalue::Aggregate(box AggregateKind::Array(_), fields)`.; `fields.len() >= 5`.; Every field is `Operand::Constant`; no `move`/`copy` local operands are handled by this InstSimplify rule.; Const evaluation of every field succeeds under `self.typing_env`.; All const-evaluated field values are exactly equal to the first, including pointer provenance/address for reference types.
Pitfalls: Do not equate references by their referents: constants `&DATA[0]` through `&DATA[4]` have equal pointee values but different addresses, so the array must not become a repeat.; Do not assume non-constant move/copy operands are equal; InstSimplify cannot see through them and should leave the aggregate for GVN.; Bail out when const evaluation fails; do not panic or substitute a guessed value.; Respect the `fields.len() < 5` threshold so short arrays are unchanged.; Compare full evaluated const values, not merely syntactic constants or types.
Test strategy: Use a `//@ test-mir-pass: InstSimplify-after-simplifycfg` mir-opt test with `// EMIT_MIR` diffs and CHECK lines. Positive cases: `literals` (`[0,0,0,0,0]` to `[const 0_u8; 5]`), `const_items` (distinct const names with equal values to `[const const_items::A; 5]`), and `strs` (repeated `&str` to `[const "a"; 5]`). Negative guard cases: `equal_referents` must keep the five distinct const reference operands, and `local` must keep `[move _2, move _3, move _4, move _5, move _6]`. These checks target address-sensitive equality and the non-constant boundary, not a general proof.
Cases: 135274-a285d202cf2ea695751e127ac0b2e0664bbd98f3
Source: https://github.com/rust-lang/rust/pull/135274
> Transform aggregates like [0, 0, 0, 0, 0] into [0; 5].
> GVN can also do this optimization, but GVN is only run at mir-opt-level 2 so having this in
> fn simplify_repeated_aggregate(&self, rvalue: &mut Rvalue<'tcx>) {
> let Rvalue::Aggregate(box AggregateKind::Array(_), fields) = rvalue else {
> if fields.len() < 5 {
> let first = &fields[rustc_abi::FieldIdx::ZERO];
> let Ok(first_val) = first.const_.eval(self.tcx, self.typing_env, first.span) else {
> field == Ok(first_val)
> *rvalue = Rvalue::Repeat(Operand::Constant(first.clone()), len);
