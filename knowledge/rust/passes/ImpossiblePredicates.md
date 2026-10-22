# ImpossiblePredicates
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- Using `predicates_of(...).predicates` alone omits parent predicates; `instantiate_identity(tcx)` is needed so inherited bounds are seen.
- `p.is_global()` and the later `!HAS_FREE_LOCAL_NAMES` filter are related but not literally identical; verify the flag-based filter does not admit non-global clauses.
- Do not assume own-body satisfiability means the body is reachable; inherited impossible bounds can invalidate descendants.
- Failure to clear the body can surface as layout/ABI ICEs such as a scalar-pair mismatch or an unknown-layout ICE, not as a clean reachability diagnostic.
- Do not feed clauses with `HAS_CT_PROJECTION` into the impossibility check; the supplied rationale is that unevaluated constants cause cycles.
- Error-referencing predicates must be handled before/alongside impossibility; otherwise error recovery can reach const evaluation and ICE.
- The pass deliberately clears error-referencing bodies, so diagnostics may change to `error[E0080]: entering unreachable code` with an evaluation-failed note; this diagnostic degradation is not by itself a correctness regression.
- Update stderr expectations and spans: diagnostics may shift from an inner type to the whole const expression.
- Moving crash repros to UI tests and adding `//@ build-pass` is part of coverage; tests still expecting the old unknown-layout message will not verify the unreachable marking.
- Do not equate `predicates.references_error()` with body taint: errors may exist only in the MIR body after typeck/borrowck while item predicates look clean.
- The pass is not a general error suppressor; it must still clear the body to a single `unreachable`.
- Extracting `has_impossible_predicates` does not itself change predicate semantics; the behavioral fix is adding the `body.tainted_by_errors.is_some()` disjunct.
- Changing which bodies are emptied changes expected diagnostics: the supplied `promoted_const_call2` case loses the `E0493` destructor-at-compile-time error and drops from 5 to 4 errors after the fix.
- Deleted `tests/crashes/*` known-bug files are not evidence that the pass is wrong; they are converted into regression tests under `tests/ui`.

## Patterns Not Well Handled

### ImpossiblePredicates must inspect inherited parent predicates, not only the body's own DefId
For ImpossiblePredicates, the full instantiated identity predicate chain must be considered when deciding that a MIR body is unreachable. The historically incorrect pass used only the body def's own global predicates, so derived impls, closures, or nested items under an impossible ancestor bound remained reachable; later MIR optimization or const-eval could then process uncomputable layouts and ICE. The corrected selector is `let predicates = tcx.predicates_of(body.source.def_id()).instantiate_identity(tcx);`, which includes inherited parent predicates.
Preconditions: The impossible/trivial bound is inherited from a parent item (struct, trait, enclosing function) rather than present directly on the body's own DefId.; The body's own predicates may be satisfiable while the inherited predicate set is impossible.; A later MIR pass or const-eval performs layout-/value-dependent work on the body, such as GVN, Inline, const propagation, promotion, or drop elaboration.; The body contains a value whose layout or const evaluation depends on the unsatisfiable predicate, e.g. `Option<str>`, `Option<&str>`, promoted closure allocations, or associated const/type projections.; Trivial global bounds generally require `trivial_bounds` (or `non_lifetime_binders` for `for<T> T: Copy`) with the expected warning allowed.
Pitfalls: Using `predicates_of(...).predicates` alone omits parent predicates; `instantiate_identity(tcx)` is needed so inherited bounds are seen.; `p.is_global()` and the later `!HAS_FREE_LOCAL_NAMES` filter are related but not literally identical; verify the flag-based filter does not admit non-global clauses.; Do not assume own-body satisfiability means the body is reachable; inherited impossible bounds can invalidate descendants.; Failure to clear the body can surface as layout/ABI ICEs such as a scalar-pair mismatch or an unknown-layout ICE, not as a clean reachability diagnostic.
Test strategy: Add UI regression tests where an impossible bound lives on a parent item and a descendant/derived body performs const or layout-dependent work. Use a derived impl or closure under `where str: Sized` / `where for<T> T: Copy`, compile with `-Zmir-enable-passes=+GVN -Zmir-enable-passes=+Inline -Zvalidate-mir --crate-type lib`, and mark `//@ build-pass`. A focused paired model distinguishes `inherited_impossible=true, own_impossible=false`: corrected behavior truncates MIR to a single unreachable block, while the historically incorrect predicate-only behavior leaves the multi-block body unchanged. Such concrete tests are regression evidence, not universal proof.
Cases: 144233-b1d88ba086ee6f34584ed4e8eb09761a03fe249d
Source: https://github.com/rust-lang/rust/pull/144233
> Consider parent predicates in ImpossiblePredicates pass.
> let predicates = tcx.predicates_of(body.source.def_id()).instantiate_identity(tcx);
> predicates_of(body.source.def_id())
> where for<T> T: Copy
> Fixes rust-lang/rust#140100
> Fixes rust-lang/rust#140365

### Error-referencing and unevaluated-const-projection clauses must be guarded; unreachable-body diagnostics may legitimately degrade
The corrected ImpossiblePredicates transformation filters predicate clauses with `!p.has_type_flags(TypeFlags::HAS_FREE_LOCAL_NAMES | TypeFlags::HAS_CT_PROJECTION)` and clears the body when `predicates.references_error() || traits::impossible_predicates(...)`. Error-referencing predicates must short-circuit so error recovery cannot reach const evaluation. Clauses with unevaluated constant projections must not be fed into the impossibility check because they can cause cycles. The pass is intentionally double-edged: it avoids some ICEs but changes const-eval diagnostics to unreachable-code errors.
Preconditions: Predicates may reference error types, e.g. unknown or disallowed paths in bounds such as `fn a() where b: Sized` or `fn f() -> &'static str where Self: Sized`.; Predicates may contain unevaluated const projections, including generic-const-expr type-alias bounds.; The body performs const evaluation, const promotion, array-length evaluation, or layout-dependent operations.; The expected behavior is body clearing plus ordinary diagnostics, not continued const evaluation of an erroneous body.
Pitfalls: Do not feed clauses with `HAS_CT_PROJECTION` into the impossibility check; the supplied rationale is that unevaluated constants cause cycles.; Error-referencing predicates must be handled before/alongside impossibility; otherwise error recovery can reach const evaluation and ICE.; The pass deliberately clears error-referencing bodies, so diagnostics may change to `error[E0080]: entering unreachable code` with an evaluation-failed note; this diagnostic degradation is not by itself a correctness regression.; Update stderr expectations and spans: diagnostics may shift from an inner type to the whole const expression.; Moving crash repros to UI tests and adding `//@ build-pass` is part of coverage; tests still expecting the old unknown-layout message will not verify the unreachable marking.
Test strategy: Add UI tests for error bounds and const-projection cases. For error bounds use `fn a() where b: Sized` and `fn f() -> &'static str where Self: Sized` with `-C opt-level=1 -Zvalidate-mir`, expecting normal name-resolution errors but no ICE. Assert the new diagnostic `error[E0080]: entering unreachable code` plus the note for cases such as `[(); { let _a: Option<str> = None; 0 }]`, `size_of::<<() as Project>::Assoc>()`, and generic-const-expr type-alias bounds. Follow the historical test additions and run old crash repros as build-pass tests after adding `#![expect(trivial_bounds)]` / `#![expect(incomplete_features)]`. No compiler was built in the supplied evidence, so these tests were not executed or reproduced there.
Cases: 144233-b1d88ba086ee6f34584ed4e8eb09761a03fe249d
Source: https://github.com/rust-lang/rust/pull/144233
> This pass is double edged. It avoids some ICEs (yay!) but also degrades diagnostics from constant evaluation.
> // Clauses that refer to unevaluated constants as they cause cycles.
> | TypeFlags::HAS_CT_PROJECTION,
> if predicates.references_error() || traits::impossible_predicates(tcx, predicates) {
> error[E0080]: entering unreachable code
> evaluation of `ct_unused_1::AliasConstUnused::{constant#0}` failed here
> Got a scalar pair where a scalar was expected

### Tainted MIR bodies must be cleared to unreachable even when predicates alone look clean
ImpossiblePredicates must also treat a body with `body.tainted_by_errors.is_some()` as impossible and replace it with a single `unreachable`. The historically incorrect predicate-only pass left bodies that failed typeck or borrowck intact when their elaborated predicates neither referenced errors nor were impossible; later drop elaboration or state transform could then ICE. The corrected condition is `let impossible = body.tainted_by_errors.is_some() || has_impossible_predicates(tcx, body.source.def_id());`, with the existing clearing comment stating that the body is reduced to a single `unreachable` statement.
Preconditions: The function, const, or coroutine body failed typeck or borrowck and therefore has `body.tainted_by_errors` set.; The item's elaborated predicates do not themselves reference errors and are not impossible, so the old predicate-only condition is false.; A later MIR phase such as drop elaboration or state transform runs on the body before compilation aborts.; Regression shapes include `type_alias_impl_trait` opaque aliases with recursive calls feeding drop elaboration, coroutines moving across yields, and const/promoted expressions with borrow errors.
Pitfalls: Do not equate `predicates.references_error()` with body taint: errors may exist only in the MIR body after typeck/borrowck while item predicates look clean.; The pass is not a general error suppressor; it must still clear the body to a single `unreachable`.; Extracting `has_impossible_predicates` does not itself change predicate semantics; the behavioral fix is adding the `body.tainted_by_errors.is_some()` disjunct.; Changing which bodies are emptied changes expected diagnostics: the supplied `promoted_const_call2` case loses the `E0493` destructor-at-compile-time error and drops from 5 to 4 errors after the fix.; Deleted `tests/crashes/*` known-bug files are not evidence that the pass is wrong; they are converted into regression tests under `tests/ui`.
Test strategy: Use UI regression tests with `-Zvalidate-mir` for tainted-body cases and verify ordinary diagnostics rather than ICEs. Convert known-bug crash tests into UI tests as historically done, including `tests/ui/coroutine/moved-twice.rs` (#122630), `tests/ui/type-alias-impl-trait/recursive-drop-elaboration.rs` (#122904), `tests/ui/type-alias-impl-trait/recursive-drop-elaboration-2.rs` (#139556), and `tests/ui/type-alias-impl-trait/type-error-drop-elaboration.rs` (#125185). Include a paired program with the same structure but without the failing move/type error to show the body is only emptied when tainted. For const promotion, adjust `tests/ui/consts/promoted_const_call2` expectations because the tainted const body is now unreachable and the `E0493` drop-elaboration error disappears. The concrete pair covers all four taint/impossible-predicate combinations, with `(tainted_by_errors=true, impossible_predicates=false)` as the distinguishing case: the old predicate-only transformation leaves the body value intact, while the corrected taint-aware transformation clears it. These are regression checks, not universal proof.
Cases: 146659-3934fc9eb29061168327640ba7b9ca8f79ba01e2
Source: https://github.com/rust-lang/rust/pull/146659
> Consider errors in MIR as impossible predicates to empty the body.
> The ICEs come from elaborating drops or performing state transform in MIR bodies that fail typeck or borrowck.
> If the body is tainted, replace it with `unreachable`.
> let impossible = body.tainted_by_errors.is_some()
> if predicates.references_error() || traits::impossible_predicates(tcx, predicates) {
> // Clear the body to only contain a single `unreachable` statement.
> -error: aborting due to 5 previous errors
> +error: aborting due to 4 previous errors
