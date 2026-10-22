# ElaborateDrops
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- Do not emit an async drop in a cleanup block or cleanup drop ladder; the implementation asserts `Dropline is set for cleanup drop ladder` when the invariant is violated.
- Do not discard `async_fut`/`drop` when rebuilding a `Drop` terminator, or later poll/yield expansion and the dropline successor disappear.
- An async drop is a hidden yield, so it needs the same dropline preparation as a `Yield` terminator.
- For an unresumed coroutine with async drops, the clean-drop shim must return `Poll::Ready(())` rather than a sync-only `Return`.
- Dropping a coroutine after its async drop started must go to the `ResumedAfterDrop` panic path, not resume normal execution.
- Do not represent a lint-only no-op as `DropKind::Value`; give it `DropKind::ForLint` so no real `Drop` terminator is emitted.
- A lint drop must emit only `StatementKind::BackwardIncompatibleDropHint`; emitting `TerminatorKind::Drop` for it is unsound because `Drop::drop` can run multiple times.
- For `DropKind::ForLint` in `build_scope_drops`, advance `unwind_to` only when `storage_dead_on_unwind` is true; lint drops are normally omitted on unwind.
- On non-unwind paths, skip the hint for a moved local in `scope.moved_locals` 'so as not to disturb the caching mechanism.'
- `needs_cleanup` must treat both `DropKind::Value` and `DropKind::ForLint` as needing cleanup; `DropKind::Storage` does not.
- Use `DUMMY_SP` for lint-only terminator/source info so debuginfo does not place breakpoints there, especially on unwind.
- Coroutine cleanup-index construction must include `DropKind::ForLint` (with `Storage`); missing it causes an ICE while emitting the lint statement.
- Gating BID scheduling on `has_significant_drop` misses borrowck violations: 'We need to know all of them so that we can capture potential borrow-checking errors.'
- Treating every BID as `AccessDepth::Drop` when the type does not need `Drop` will 'ICE because we don't track borrows behind shared references.' Use `Shallow(None)`.
- Skip fake borrows in `check_backward_incompatible_drop`; stop after the first violation.
- Compute borrows in scope with the same Polonius-vs-non-Polonius logic as normal borrowck (`polonius.errors_at(location)` or `state.borrows`).
- Using `post_analysis` for the lint's typing environment can cycle when normalizing recursive opaques; use `non_body_analysis`.
- A BID is a lint hint, not an actual drop; the MIR fixture change only records that the hint is retained for the additional place.
- Do not treat `Err(_)` from `DropckOutlives::fully_perform` as empty successful drop data; that defers the failure to a later pass and can panic.
- Do not use infallible `normalize_erasing_regions` for a normalization that can fail due to user type errors; use `try_normalize_erasing_regions`.
- Do not rely on the `ErrorGuaranteed` from `fully_perform`, which 'comes from delay_span_bug'; rerun dropck outside the query for real fulfillment diagnostics.
- If the dropck rerun produces no errors, `span_bug!` rather than silently continuing.
- Making `adt_dtorck_constraint` infallible requires handling unresolved placeholder/bound/infer/error types via `span_delayed_bug`.
- A failed `query_normalize` in `dtorck_types` must fall back to `deeply_normalize` and return selected errors rather than discard them.
- Regression tests must assert real diagnostics (E0277/E0284) and cover async, ambiguity, GAT, and nested-projection cases, not merely absence of ICE.
- Do not assume every normalization failure was already caught and recorded by `compute_drop_data`/dropck; the old assumption is false.
- Do not use `expect`/panic-based assertions on error-recovery paths; normalization failure is not itself a compiler bug.
- `body.tainted_by_errors` is not an authoritative signal for normalization failures; it can be `None` even with prior errors.
- Test multiple unrelated earlier error classes, not just one, because the trigger arises from several kinds.
- Treating every normalization failure as a compiler bug and emitting a delayed bug is too strong for polymorphic use of rustc internal APIs.
- Substituting `Ty::new_error` changes the MIR place's field type and can break downstream consumers obtaining drop glue or full polymorphic MIR.
- The requirement is to preserve the original unnormalized type, not to skip normalization when it succeeds.
- If downstream code truly requires normalized types, that belongs in MIR validation rather than this single drop-elaboration check.
- Do not assume all `BasicBlock` indices are original body indices; `MirPatch` appends new blocks after `body.basic_blocks.len()`.
- There are two block namespaces (original body and `MirPatch::new_blocks`); resolve via `checked_sub(body.basic_blocks.len())`.
- The same old/new lookup pattern existed in `terminator_loc` and `source_info_for_location`; centralize it to avoid divergent handling.
- Checking `is_cleanup` on the wrong block can silently change async-drop construction or cause an ICE; this is not merely a refactor.
- Taking the first element of `associated_item_def_ids(drop_trait)` does not guarantee it is the drop function; associated types and other items can appear.
- Checking only `DefKind::AssocFn` is insufficient; an associated function can have an incompatible signature, so `check_args_compatible(*def_id, trait_args)` is also required.
- When validation fails, fall through to the existing sync-drop fallback/diagnostic path rather than constructing an async drop call or emitting a delayed bug for user code.
- A fix that rejects all candidates would be wrong; valid async drop implementations must still elaborate asynchronously.
- Regression tests moved from `tests/crashes/` to `tests/ui/async-await/async-drop/`, so expectations now include normal diagnostics rather than known-bug crash markers.
- Do not clear a local's drop flag inside or at the start of its destructor block; the same flag may guard later drops such as the box allocator field.
- Guard the entire ADT destructor chain (box destructor plus allocator drop) with the drop-flag test, not only the destructor call.
- The async-drop branch had the same clear-flag pattern and must be fixed alongside the synchronous path.
- The union/`ManuallyDrop` case now uses `span_bug!` when it has a destructor and a drop flag, since those are only open-dropped in `DropShimElaborator`.
- Borrow restrictions and post-copy flag overwrites are separate conditions; the observed failure is specifically the flag being cleared before the allocator drop.
- Do not treat the `//@ known-bug: #143658` async test as part of the fixed behavior; it covers an unrelated async-call bug.

## Patterns Not Well Handled

### Async-drop elaboration in coroutines: pinned async-drop future, dropline ladder, and sync cleanup paths
In ElaborateDrops, an async-droppable local on a non-cleanup coroutine path must be lowered to a pinned `AsyncDrop` call plus a `Drop { async_fut: Some(fut) }` chain, and the drop ladder must thread a separate `dropline` successor so a suspended coroutine can resume polling the same future. StateTransform later expands these hidden drops into yield/poll states. The gate requires the `async_drop` feature, a coroutine body, `allow_async_drops()`, a non-cleanup block, and a type where `needs_async_drop`; cleanup/unwind drops must remain synchronous. Rebuilding a `Drop` terminator without its hidden `drop`/`async_fut` fields, or emitting async-drop ladders on cleanup paths, is incorrect: it either runs the sync destructor or violates the cleanup invariant.
Preconditions: The crate enables the unstable `async_drop` feature and the enclosing MIR body is a coroutine (`body.coroutine.is_some()`).; The drop is on a non-cleanup path; cleanup/unwind drops stay synchronous.; `allow_async_drops()` is true and the dropped type `needs_async_drop`.; StateTransform expansion additionally requires an async/async-gen coroutine and `has_expandable_async_drops`.; Any pass reconstructing `TerminatorKind::Drop` preserves the hidden `drop` and `async_fut` fields.
Pitfalls: Do not emit an async drop in a cleanup block or cleanup drop ladder; the implementation asserts `Dropline is set for cleanup drop ladder` when the invariant is violated.; Do not discard `async_fut`/`drop` when rebuilding a `Drop` terminator, or later poll/yield expansion and the dropline successor disappear.; An async drop is a hidden yield, so it needs the same dropline preparation as a `Yield` terminator.; For an unresumed coroutine with async drops, the clean-drop shim must return `Poll::Ready(())` rather than a sync-only `Return`.; Dropping a coroutine after its async drop started must go to the `ResumedAfterDrop` panic path, not resume normal execution.
Test strategy: Use `//@ run-pass` plus `//@ check-run-results` with a deterministic `block_on` that polls a pinned future and then polls `async_drop_in_place(fut.get_unchecked_mut())`, asserting exact stdout ordering for active fields, nested ADTs, mid-execution drops, a suspended coroutine, and the coroutine itself being async-dropped. Run `tests/ui/async-await/async-drop/ex-ice-132103.rs` with `-Zvalidate-mir -Zinline-mir=yes`; it moved from known-bug to run-pass.
Cases: 123948-c366756a8537ef998d32c1ef57098d5aae7ca92f
Source: https://github.com/rust-lang/rust/pull/123948
> Scopes processing for generate async drop preparations. Async drop is a hidden Yield, so potentially async drops require the same dropline preparation as for Yield terminators.
> Drops in unwind path (cleanup blocks) are not expanded to async drops, only sync drops in unwind path
> Dropline is set for cleanup drop ladder
> This test used to ICE: rust-lang/rust#132103

### Lint-only backwards-incompatible drops must be a distinct ForLint kind, never a real value drop
Edition-2024 `tail_expr_drop_order` uses a no-op MIR statement `BackwardIncompatibleDropHint`; the scheduled drop for it must be `DropKind::ForLint`, not `DropKind::Value` plus a `backwards_incompatible_lint` boolean. Representing it as a value drop lets drop-tree construction and unwind adjustment emit real `TerminatorKind::Drop` calls, so `Drop::drop` can run more than once (unsound). The fix gives lint drops their own kind, emits only the hint on normal exits, keeps them out of real drop terminators on unwind, counts them in `needs_cleanup`, and includes them in coroutine cleanup-index construction alongside `DropKind::Storage` to avoid an ICE.
Preconditions: The Edition 2024 `tail_expr_drop_order` lint is active (e.g. `#![deny(tail_expr_drop_order)]`).; A value with a custom destructor is dropped at a tail-expression/incompatible-drop scope.; The scope exit can unwind (panic/cleanup path) or is inside an async/coroutine body where cleanup indices are computed.; The schedule/elaboration code distinguishes lint-only drops from real value drops.
Pitfalls: Do not represent a lint-only no-op as `DropKind::Value`; give it `DropKind::ForLint` so no real `Drop` terminator is emitted.; A lint drop must emit only `StatementKind::BackwardIncompatibleDropHint`; emitting `TerminatorKind::Drop` for it is unsound because `Drop::drop` can run multiple times.; For `DropKind::ForLint` in `build_scope_drops`, advance `unwind_to` only when `storage_dead_on_unwind` is true; lint drops are normally omitted on unwind.; On non-unwind paths, skip the hint for a moved local in `scope.moved_locals` 'so as not to disturb the caching mechanism.'; `needs_cleanup` must treat both `DropKind::Value` and `DropKind::ForLint` as needing cleanup; `DropKind::Storage` does not.; Use `DUMMY_SP` for lint-only terminator/source info so debuginfo does not place breakpoints there, especially on unwind.; Coroutine cleanup-index construction must include `DropKind::ForLint` (with `Storage`); missing it causes an ICE while emitting the lint statement.
Test strategy: Add a `tests/mir-opt` test with `// skip-filecheck`, `// EMIT_MIR_FOR_EACH_PANIC_STRATEGY`, and `// EMIT_MIR tail_expr_drop_order_unwind.method_1.ElaborateDrops.after.mir`, using `#![deny(tail_expr_drop_order)]`, a custom-`Drop` guard, and a tail-expression `match` over a `Result` from a panicking helper. Verify each lint-only local gets exactly one `backward incompatible drop(...)` statement and is not also the target of a real `drop(...)` terminator, in both panic-abort and panic-unwind fixtures. Add a `tests/ui/drop` async test with `await`/loop and the lint to confirm the coroutine path diagnoses without ICE.
Cases: 134486-6564403641afde8bf445914ec2996fe7219289ab, 135048-f72c836093960d1f2027e4316ad099da049ceaa0
Source: https://github.com/rust-lang/rust/pull/134486
Source: https://github.com/rust-lang/rust/pull/135048
> In #131326, a new kind of scheduled drop (`drop_kind: DropKind::Value` + `backwards_incompatible_lint: true`) was added so that we could insert a new kind of no-op MIR statement (`backward incompatible drop`) for linting purposes.
> These drops were intended to have *no side-effects*, but drop elaboration code forgot to handle these drops specially and they were handled otherwise as normal drops in most of the code. This ends up being **unsound** since we insert more than one drop call for some values, which means that `Drop::drop` could be called more than once.
> This PR fixes this by splitting out the `DropKind::ForLint` and adjusting the code.
> Instead, this happened: Drop is called 3 times.
> Handle `DropKind::ForLint` in coroutines correctly #134575
> // Make sure we don't ICE when emitting the "lint" drop statement
> // normally lint-related drops are not emitted for unwind,

### Backward-incompatible-drop hints for all tail temporaries, with borrowck shallow checks and a non-body-analysis typing environment
BID scheduling for Rust 2024 tail-expression drop-order migration must not be gated on `has_significant_drop`; all tail temporaries need hints so borrowck can detect borrows that become invalid at the future drop location. In borrowck, a BID is checked against live borrows, skipping fake borrows and stopping at the first violation; when the hinted type does not need `Drop`, the access depth must be `AccessDepth::Shallow(None)` rather than `AccessDepth::Drop`, because borrows behind shared references (e.g. thread locals) are not tracked. The `tail_expr_drop_order` lint must use `ty::TypingEnv::non_body_analysis(tcx, def_id)` instead of `post_analysis` to avoid an opaque-normalization query cycle for recursive local opaques.
Preconditions: The crate is Edition 2021 while enabling/denying the Rust 2024 `tail_expr_drop_order` lint (regression tests use `//@ edition: 2021` and `#![deny(tail_expr_drop_order)]`).; A `StatementKind::BackwardIncompatibleDropHint` with `BackwardIncompatibleDropReason::Edition2024` is emitted for a tail-expression temporary; the type may or may not need `Drop`.; At least one non-fake borrow involving the hinted place is still live, using Polonius output or `state.borrows`.; If the hinted type does not need `Drop`, borrows behind shared references are not tracked, requiring shallow access.
Pitfalls: Gating BID scheduling on `has_significant_drop` misses borrowck violations: 'We need to know all of them so that we can capture potential borrow-checking errors.'; Treating every BID as `AccessDepth::Drop` when the type does not need `Drop` will 'ICE because we don't track borrows behind shared references.' Use `Shallow(None)`.; Skip fake borrows in `check_backward_incompatible_drop`; stop after the first violation.; Compute borrows in scope with the same Polonius-vs-non-Polonius logic as normal borrowck (`polonius.errors_at(location)` or `state.borrows`).; Using `post_analysis` for the lint's typing environment can cycle when normalizing recursive opaques; use `non_body_analysis`.; A BID is a lint hint, not an actual drop; the MIR fixture change only records that the hint is retained for the additional place.
Test strategy: Add Edition 2021 UI tests under `tests/ui/drop` with `#![deny(tail_expr_drop_order)]` exercising live borrows across tail temporaries: `let _ = { String::new().as_str() }.len();`, `f(unsafe { String::new().as_str() }.len());`, `f({ &mut || 0 })`, and `g({ &f() });`, asserting the lint label and borrow explanation. Check both panic-strategy ElaborateDrops fixtures now contain `backward incompatible drop(_4);` alongside `_2` and `_5`. Add a check-pass recursive boxed-future test (`Box::pin(test()).await?`) for no normalize cycle, and a check-pass thread-local/shared-reference test for no ICE when the type does not need `Drop`.
Cases: 135351-ce4e43f0d2169a247a8193084d35284c32392cac
Source: https://github.com/rust-lang/rust/pull/135351
> if !self.local_decls[local].ty.has_significant_drop(self.tcx, self.typing_env()) {
> // Note that we are *not* gating BIDs here on whether they have significant destructor.
> // We need to know all of them so that we can capture potential borrow-checking errors.
> backward incompatible drop(_4);
> // This is needed because we track the borrows of refs to thread locals,
> // and we'll ICE because we don't track borrows behind shared references.
> let typing_env = ty::TypingEnv::non_body_analysis(tcx, def_id);
> // Make sure we don't cycle error when normalizing types for tail expr drop order lint.

### Dropck-only type errors: rerun dropck with diagnostics in borrowck and use fallible normalization in ElaborateDrops
Because dropck is not run on HIR, a `DropckOutlives` failure can appear only during MIR borrowck/dropck (e.g. projected field types). Borrowck must not swallow `Err(_)` from `fully_perform` into default `DropData`; it must rerun dropck outside the query with diagnostics, because the `ErrorGuaranteed` comes from `delay_span_bug` and is not a real report. ElaborateDrops must then use `try_normalize_erasing_regions` and may substitute an error type only when the body was already `tainted_by_errors` by that failed dropck; otherwise the normalization failure remains an internal compiler error. Swallowing the failure converts a diagnosable type error into an ICE in drop elaboration.
Preconditions: The program reaches MIR borrowck/dropck; HIR typeck need not have errored first.; A local or field type contains a projection whose normalization fails only while dropck inspects fields (missing bound, ambiguity, GAT bound).; `ElaborateDrops` runs under `TypingMode::PostAnalysis` and needs the field type for place construction.; Recovery in `ElaborateDrops` requires `body.tainted_by_errors` to have been set by the preceding dropck diagnostic.
Pitfalls: Do not treat `Err(_)` from `DropckOutlives::fully_perform` as empty successful drop data; that defers the failure to a later pass and can panic.; Do not use infallible `normalize_erasing_regions` for a normalization that can fail due to user type errors; use `try_normalize_erasing_regions`.; Do not rely on the `ErrorGuaranteed` from `fully_perform`, which 'comes from delay_span_bug'; rerun dropck outside the query for real fulfillment diagnostics.; If the dropck rerun produces no errors, `span_bug!` rather than silently continuing.; Making `adt_dtorck_constraint` infallible requires handling unresolved placeholder/bound/infer/error types via `span_delayed_bug`.; A failed `query_normalize` in `dtorck_types` must fall back to `deeply_normalize` and return selected errors rather than discard them.; Regression tests must assert real diagnostics (E0277/E0284) and cover async, ambiguity, GAT, and nested-projection cases, not merely absence of ICE.
Test strategy: Add compile-fail UI tests under `tests/ui/dropck/` with checked `.stderr`: `dropck-only-error.rs` (missing `User: AuthUser`), `dropck-only-error-async.rs`, `dropck-only-error-ambiguity.rs` (ambiguous `<[T] as ToOwned>::Owned`), and `dropck-only-error-gat.rs`. Promote crash tests to normal UI tests, e.g. `issue-103899.rs` expecting `the trait bound \`(): BaseWithAssoc\` is not satisfied [E0277]`, removing `//@ known-bug`, `//@ failure-status: 101`, and `//@ dont-check-compiler-stderr`; keep `current` and `next` solver revisions.
Cases: 136539-49cf00c7c04e24bb27a09fbcfe9bac9278075608
Source: https://github.com/rust-lang/rust/pull/136539
> Borrowck generally assumes that any queries it runs for type checking will succeed, thinking that HIR typeck will have errored first if there was a problem. However as of #98641, dropck isn't run on HIR, so there's no direct guarantee that it doesn't error.
> While improvements to trait solving might fix this in the future, for now we go for a pragmatic solution of emitting an error from borrowck (by rerunning dropck outside of a query) and making drop elaboration check if an error has been emitted previously before panicking for a failed normalization.
> Err(_) => DropData { dropck_result: Default::default(), region_constraint_data: None },
> // We don't run dropck on HIR, and dropck looks inside fields of
> let ocx = ObligationCtxt::new_with_diagnostics(&typeck.infcx);
> span_bug!(span, "Rerunning drop data query produced no error.");
> tcx.normalize_erasing_regions(self.elaborator.typing_env(), f.ty(tcx, args));
> // The type error for normalization may have been in dropck: see
> .expect("Error in drop elaboration not found by dropck."),

### Normalization failure in ElaborateDrops must not rely on body.tainted_by_errors or panic
A field-type normalization failure during drop elaboration can be caused by many earlier unrelated errors (type-alias impl Trait/unconstrained opaque, conflicting impls, `compile_error!` in async code) that dropck did not record as body taint. The pass must not assume `body.tainted_by_errors` is `Some` and call `.expect(...)`, which turns a recoverable diagnostic path into an ICE. The corrected recovery constructs an error type using `span_delayed_bug` (rather than asserting a tainted body), so compilation reports diagnostics instead of panicking.
Preconditions: MIR drop elaboration runs under `TypingMode::PostAnalysis` and at least one elaborated field type fails `try_normalize_erasing_regions`.; The crate already emitted errors that allow analysis to continue, but dropck did not delete the body or set `body.tainted_by_errors` (it remains `None`).; Earlier error classes can include unconstrained opaque types/TAIT instability, conflicting trait impls, or `compile_error!`.
Pitfalls: Do not assume every normalization failure was already caught and recorded by `compute_drop_data`/dropck; the old assumption is false.; Do not use `expect`/panic-based assertions on error-recovery paths; normalization failure is not itself a compiler bug.; `body.tainted_by_errors` is not an authoritative signal for normalization failures; it can be `None` even with prior errors.; Test multiple unrelated earlier error classes, not just one, because the trigger arises from several kinds.
Test strategy: Promote crash repros into UI tests: `tests/ui/drop/drop_elaboration_with_errors2.rs` (replace `//@ known-bug: #137287` with the regression comment, keep the `impl Sized` alias, conflicting blanket/opaque impls, and `cast` mismatch) and `drop_elaboration_with_errors3.rs` (edition 2021, async fns, `compile_error!("bonjour")`, `fn main() {}`). Add `.stderr` annotations asserting E0658, E0119, 'unconstrained opaque type', E0308, and `error: bonjour`, with no panic/ICE from drop elaboration.
Cases: 139379-ac45a672979b28670cf2e5de5afbb0b1fb42c0b2
Source: https://github.com/rust-lang/rust/pull/139379
> Use delayed bug for normalization errors in drop elaboration
> Normalization can fail due to a lot of different earlier errors, so just use span_delayed_bug if normalization failed.
> Err(_) => Ty::new_error(
> self.tcx().dcx().span_delayed_bug(
> Error normalizing in drop elaboration.
> Error in drop elaboration not found by dropck.
> known-bug: #137287
> compile_error!("bonjour")

### Preserve unnormalized field types for polymorphic drop elaboration instead of substituting an error type
When an open ADT field type fails `try_normalize_erasing_regions` during drop elaboration, replacing it with `Ty::new_error` plus a `span_delayed_bug` is too strong for rustc-internal polymorphic consumers (e.g. extracting drop glue for `Cow`/`NonZero` fields). The field type should be computed as `field.ty(tcx, args)` and normalized with `.unwrap_or(field_ty)`, silently retaining the original unnormalized type so the resulting place keeps a usable field type. Normalization is still applied when it succeeds; only the failure fallback changes.
Preconditions: `ElaborateDrops` is elaborating an open ADT drop and constructing a place field.; The field type comes from `field.ty(tcx, args)` in the current generic/projection context.; The elaborator's typing environment is asserted to be `TypingMode::PostAnalysis`, and normalization of that field type fails (as with unnormalizable `Cow`/`NonZero` fields).
Pitfalls: Treating every normalization failure as a compiler bug and emitting a delayed bug is too strong for polymorphic use of rustc internal APIs.; Substituting `Ty::new_error` changes the MIR place's field type and can break downstream consumers obtaining drop glue or full polymorphic MIR.; The requirement is to preserve the original unnormalized type, not to skip normalization when it succeeds.; If downstream code truly requires normalized types, that belongs in MIR validation rather than this single drop-elaboration check.
Test strategy: Add a focused rustc-driver or MIR-level regression case that elaborates drop glue for a generic ADT whose field type cannot be normalized (projection-bearing fields like `Cow`/`NonZero`). Compare MIR under the two transformations: the corrected path should retain the original unnormalized field type and emit no `"Error normalizing in drop elaboration."` delayed bug, while the historical path uses an error type and reports the bug. Assert on MIR dumps/diagnostics; the supplied patch adds no test changes.
Cases: 148719-b476969e0f893734ecddd1e7ed1e81c26af94246
Source: https://github.com/rust-lang/rust/pull/148719
> Allow unnormalized types in drop elaboration
> Currently the one thing I can't get is drop glue because it fails on unnormalizable types like the fields of `Cow` or `NonZero`.
> This PR removes the one check for unnormalized types in drop elaboration. It's a `span_delay_bug` so only there to help catch mistakes.
> let field_ty = field.ty(tcx, args);
> let field_ty = tcx
> .try_normalize_erasing_regions(self.elaborator.typing_env(), field_ty)
> .unwrap_or(field_ty);
> (tcx.mk_place_field(base_place, field_idx, field_ty), subpath)

### Block-id resolution in ElaborateDrops must use MirPatch, not the original body index
During async-drop elaboration, `DropCtxt::build_drop` reads a block's `is_cleanup` flag. The block id may refer to a block newly appended by `MirPatch`, not an original `body.basic_blocks` index, so indexing the original body directly (`self.elaborator.body()[bb].is_cleanup`) can be out of range or read the wrong block, causing an ICE on partly dropped aggregates. The fix resolves the id through a shared `MirPatch::block` getter using `bb.index().checked_sub(body.basic_blocks.len())` (`Some(new) => &new_blocks[new]`, `None => &body[bb]`), and reuses the same lookup in `terminator_loc` and `source_info_for_location`.
Preconditions: `async_drop` feature enabled; body is a coroutine and async drops are allowed; the dropped type needs an async drop.; A partly dropped aggregate/tuple causes drop elaboration to query `is_cleanup` on a block id introduced by `MirPatch`.; The block id index is at or beyond `body.basic_blocks.len()`.
Pitfalls: Do not assume all `BasicBlock` indices are original body indices; `MirPatch` appends new blocks after `body.basic_blocks.len()`.; There are two block namespaces (original body and `MirPatch::new_blocks`); resolve via `checked_sub(body.basic_blocks.len())`.; The same old/new lookup pattern existed in `terminator_loc` and `source_info_for_location`; centralize it to avoid divergent handling.; Checking `is_cleanup` on the wrong block can silently change async-drop construction or cause an ICE; this is not merely a refactor.
Test strategy: Add a `build-pass` UI test `tests/ui/async-await/async-drop/partly-dropped-tuple.rs` for edition 2024 with `#![crate_type = "lib"]`, `#![allow(incomplete_features)]`, `#![feature(async_drop)]`: an async fn creates `let x = (vec![3], vec![4, 4]); drop(x.1); x.0`, exercising async-drop elaboration on a partly dropped tuple; it should compile after the fix.
Cases: 140458-cce706ec3c4ed38ecaffc61dac3b835038cdc50b
Source: https://github.com/rust-lang/rust/pull/140458
> self.elaborator.body().coroutine.is_some()

### AsyncDrop associated-item lookup must validate DefKind and argument compatibility
ElaborateDrops must not assume the first associated item of the `AsyncDrop` trait is the drop function. For malformed impls the first item can be an associated type (`type c;`/`type c = ();`) or an associated function with an incompatible signature (`fn c(d: impl Sized) {}`, `fn drop(_wrong: impl Sized) {}`); using it as the drop function ICEs instead of producing normal diagnostics. The corrected selection requires `tcx.def_kind(def_id) == DefKind::AssocFn && tcx.check_args_compatible(*def_id, trait_args)`, else returns None and falls through to the existing sync-drop fallback/`span_delayed_bug` path.
Preconditions: The crate enables `#![feature(async_drop)]` (edition 2024, incomplete-features allowance).; An `impl AsyncDrop for T` provides a malformed associated item: an associated type in place of the drop method, or a method with an incompatible signature.; A value of `T` is dropped in an async context (`async fn bar() { A; }`) so async-drop elaboration runs.; Valid async-drop impls must still take the async path; only invalid candidates are rejected.
Pitfalls: Taking the first element of `associated_item_def_ids(drop_trait)` does not guarantee it is the drop function; associated types and other items can appear.; Checking only `DefKind::AssocFn` is insufficient; an associated function can have an incompatible signature, so `check_args_compatible(*def_id, trait_args)` is also required.; When validation fails, fall through to the existing sync-drop fallback/diagnostic path rather than constructing an async drop call or emitting a delayed bug for user code.; A fix that rejects all candidates would be wrong; valid async drop implementations must still elaborate asynchronously.; Regression tests moved from `tests/crashes/` to `tests/ui/async-await/async-drop/`, so expectations now include normal diagnostics rather than known-bug crash markers.
Test strategy: Build two UI programs differing only in the malformed associated item: (1) `impl AsyncDrop for a { type c = (); }` with `impl Drop for a { fn b() {} }`, expecting E0407/E0437/E0046 without crash (#140484); (2) `impl AsyncDrop for A { fn drop(_wrong: impl Sized) {} }` with a valid `impl Drop`, expecting E0186 for missing `self: Pin<&mut Self>` (#140500). Include `async fn bar() { A; }`, edition 2024, `#![feature(async_drop)]`, `#![crate_type = "lib"]`, assert stderr matches and no ICE/delayed-bug occurs, and keep a valid-impl control confirming async elaboration.
Cases: 141677-f023a69f32352531a8da2f43e2ca4cd087317f8c
Source: https://github.com/rust-lang/rust/pull/141677
> Fixes ICE, when type is provided in AsyncDrop trait instead of `async fn drop()`.
> Fixes ICE, when async drop fn has wrong signature.
> let Some(drop_fn_def_id) =
> tcx.associated_item_def_ids(drop_trait).into_iter().nth(0).copied()
> if tcx.def_kind(def_id) == DefKind::AssocFn
> && tcx.check_args_compatible(*def_id, trait_args)
> // ex-ice: #140500
> // Ex-ice: #140484

### Do not clear a Box local's drop flag before its destructor, or the allocator drop is skipped
In `destructor_call_block`, clearing the local drop flag at the start of the destructor block and guarding only the destructor call caused the allocator field drop of a conditional `Box<T, A>` to be skipped, because the same flag guards that allocator drop. The fix removes the early shallow clear and destructor-only flag test and wraps the whole ADT destructor block (including box deallocation and allocator drop) in `self.drop_flag_test_block(destructor_block, contents_drop.0, contents_drop.1)`, leaving the flag set until the later drop-ladder code clears it. The async branch had the same pattern and is fixed alongside; union/`ManuallyDrop` with a destructor and drop flag now `span_bug!` because those are only open-dropped in `DropShimElaborator`, which has no drop flags.
Preconditions: The local is an ADT with an elaborated destructor, here `Box<T, A>` using `#![feature(allocator_api)]` (and `async_drop` for async variants).; The allocator type `A` implements `Drop`, making its drop observable, and contents `T` implements `Drop`.; The local needs a drop flag due to conditional initialization/move, e.g. contents moved out on one path and the box dropped on another.; The MIR regression test declares `//@ needs-unwind`.
Pitfalls: Do not clear a local's drop flag inside or at the start of its destructor block; the same flag may guard later drops such as the box allocator field.; Guard the entire ADT destructor chain (box destructor plus allocator drop) with the drop-flag test, not only the destructor call.; The async-drop branch had the same clear-flag pattern and must be fixed alongside the synchronous path.; The union/`ManuallyDrop` case now uses `span_bug!` when it has a destructor and a drop flag, since those are only open-dropped in `DropShimElaborator`.; Borrow restrictions and post-copy flag overwrites are separate conditions; the observed failure is specifically the flag being cleared before the allocator drop.; Do not treat the `//@ known-bug: #143658` async test as part of the fixed behavior; it covers an unrelated async-call bug.
Test strategy: Pair a run-pass semantic test with a MIR diff test. In `tests/ui/drop/box-conditional-drop-allocator.rs`, use a `DropCheckingAllocator<'a>(&'a Cell<bool>)` whose `Drop` sets the cell, construct `Box::new_in(HasDrop, DropCheckingAllocator(&dropped))` with `HasDrop: Drop`, conditionally move out with `if true { drop(*b); } else { drop(b); }`, then `assert!(dropped.get());`. Add `tests/mir-opt/box_conditional_drop_allocator.rs` with `//@ test-mir-pass: ElaborateDrops` and `//@ needs-unwind`, emitting `main.ElaborateDrops.diff`, to check the flag is not cleared before the allocator drop and the allocator drop is guarded by the still-set flag. Add async-drop run-pass tests with `//@ check-run-results` comparing sync-vs-async destructor output.
Cases: 143672-ccc2f78c3767e68005b0c873f31f79ef6680a3de
Source: https://github.com/rust-lang/rust/pull/143672
> Clearing Box's drop flag after running its destructor can cause it to skip dropping its allocator, so just don't. Its cleared by the drop ladder code afterwards already.
> Fixes rust-lang/rust#131082
> Box sometimes forgets to drop its allocator when the Box is conditionally initialized.
> Seems like there's something wrong with the drop flags.
> Making `HasDrop` not implement `Drop` causes the program to behave as expected.
> span_bug!(self.source_info.span, "open dropping partially moved union");
> self.drop_flag_test_block(destructor_block, contents_drop.0, contents_drop.1)
> //@ needs-unwind
> //@ test-mir-pass: ElaborateDrops
