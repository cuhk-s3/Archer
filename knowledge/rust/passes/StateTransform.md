# StateTransform
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- Adjusting `arg_count` alone is insufficient because `body.coroutine` remains populated.
- Synthetic MIR bodies derived from coroutine bodies should not automatically retain coroutine metadata; the historical note says this also applies to promoted consts and other synthetic bodies.
- Do not infer that the drop shim should keep `yield_ty`, `resume_ty`, or `coroutine_layout` merely because it was cloned from a coroutine.
- The removal of the `coroutine_layout` annotation in test expectations is evidence about drop-shim metadata, not evidence that drop control flow changed.
- Do not create or select a separate by-mut coroutine body: `Fn` and `FnMut` share the by-ref body; the old body was "actually just a copy of the by-ref body, but with a different self type".
- Do not populate the coroutine kind from `Ty::from_closure_kind` directly when constructing a coroutine from a coroutine-closure; cap `Fn` and `FnMut` together and keep only `FnOnce` distinct.
- Do not use the by-move body for the `Fn::call` path; doing so takes the receiver by move and is the confirmed historical bug.
- Deleting `by_mut_body` also requires removing its pass-manager recursion and mirror/dump expectations; an old comment or test name alone does not show the replacement is wrong.
- Do not give the `Fn`/`FnMut` shim an exact by-value self signature; it only needs an ABI-compatible shim with a mutable pointer receiver.
- The pointer-receiver construct shim is only valid without captures, so keep the unit-upvars assertion.
- Do not infer by-move from the child's `is_by_ref()` alone; only force by-move when `coroutine_capture.is_by_ref() && !parent_capture.is_by_ref()`.
- Do not use the raw capture-list index as the field index; the fixed index is `num_args + idx` after `.skip(num_args)`.
- Do not remap positionally or match by projection kinds alone; two distinct upvars can share the same projection shape, so compare the base HIR id and advance the parent cursor after use.
- Do not assume equal capture counts or a one-to-one parent/child correspondence; one parent may refine into several children.
- Do not put the prefix-length assertion before the base-HIR-id check; the predicate must be able to return false for an unrelated shorter capture instead of panicking.
- Do not drop extra precise-capture projections; re-apply them after the remapped parent field.
- Do not lose the invariant that every parent capture is used and none are left over.
- Do not conflate inserting a leading Deref for a by-ref parent with peeling a trailing Deref for a by-ref child; both can apply when the parent is by-ref and precise-capture projections exist.
- The old `needs_deref = child_capture.is_by_ref() && !parent_capture.is_by_ref()` is not equivalent to the new `peel_deref` handling; a by-ref parent still needs the leading deref insertion.
- Keep the pointee non-`Copy` in trigger tests; a `Copy` type can change the child capture to by-ref and mask the trigger.
- Only nop a fake borrow whose place is exactly a single Field projection on `CAPTURE_STRUCT_LOCAL`; fake borrows with a deref, e.g. `&fake shallow (*(_1.0))`, must remain.
- Check the third remapping tuple element (`peel_deref`): if false, the capture was not converted from reference to by-move value, so a direct fake borrow is not necessarily obsolete.
- After setting the statement to `StatementKind::Nop`, still call `self.super_statement(...)`; after retyping the capture local, call `super_local_decl(...)`.
- Do not apply the deref-projection exception when the parent capture is by-ref or when the child borrow is mutable; those still require the parent env lifetime.
- Do not treat every child capture as needing `'env`, nor every child capture as safe with its own region; decide per parent/child pair.
- Preserve the invariant that every parent capture is used and no child captures are left over, otherwise precise captures can be mis-mapped.
- A wrong lifetime heuristic is not unsoundness by itself; borrowck validates it, so tests should expect borrowck diagnostics, not arbitrary behavior.
- The `ByMoveBody` zipping extraction in the same historical patch is mechanical and not the lifetime-choice correctness fix.
- Using `ty.boxed_ty()` yields only the element type and loses the allocator argument, so the allocator is silently unchecked.
- For `Box<T, A>`, the allocator is `args.type_at(1)`; checking only index 0 misses it. Combine both checks with `||`.
- The diagnostic prefix matters: allocator recursion uses `"{}allocator "`, so the reported message names the allocator.
- Short-circuiting with `||` is intentional; do not assume the allocator check also runs when the element check already failed.
- Do not generate an async drop inside a cleanup block or cleanup drop ladder; the historical patch asserts `Dropline is set for cleanup drop ladder` if this invariant is violated.
- Do not drop `async_fut` or `drop` while rebuilding a `Drop` terminator, or the later poll/yield expansion and dropline successor disappear.
- An async drop is a hidden yield and needs the same dropline preparation as a `Yield` terminator.
- For an unresumed coroutine with async drops, the clean-drop shim must return `Poll::Ready(())` rather than the sync-only `Return`.
- Do not use a bool constant for a coroutine yield place whose type is `Poll<Option<T>>`; MIR validation rejects the incompatible assignment.
- The generic `false` constant is only appropriate for return-yields or non-async-generator gen coroutines; async generators require `AsyncGenPending` with the concrete yield type.
- Unwind and dropline blocks are separate paths: success-path `StorageDead` does not discharge cleanup/dropline liveness obligations.
- The fix required reordering `build_pin_fut` before `build_poll_switch` so the switch can reference `fut_pin_place`; merely adding a `StorageDead` elsewhere does not cover the switch path.
- Panic-abort MIR has no cleanup blocks while panic-unwind does, so a single panic strategy does not exercise the unwind `StorageDead` fix.
- `Inline` is a trigger/exposer in the storage-liveness regression, not the pass whose lowering is being corrected.
- Do not keep keying stalled predicates by individual coroutine def_id after moving to per-typeck-root checking; the new solver cannot reliably associate obligations with specific coroutines.
- Do not leave coroutine-interior `Sized` checks in the root-level `check_coroutine_obligations`; relocate them to `mir_coroutine_witnesses` where per-coroutine layout exists.
- Do not bind opaque type inference to a child coroutine's def_id; root-level checking must use the typeck root def_id.
- Flattening the predicate map into a set changes ordering/deduplication behavior; the orphaned-anon-const regression expects duplicate diagnostics when `-Z deduplicate-diagnostics=no` is used.
- Scrubbed trait errors store only TrueError/Ambiguity/Cycle classification and are insufficient for callsites that inspect obligation/code/root_obligation or call `report_fulfillment_errors`.
- Ambiguity and Cycle are not hard true errors; `is_true_error` must distinguish them from Select/Project/Subtype/ConstEquate.
- Opting in to diagnostics is a performance tradeoff: diagnostic generation does extra trait solving and can recurse or stack overflow when used inside error-reporting machinery, so only callsites that need detailed errors should use `new_with_diagnostics`.
- The coroutine callsite was migrated in the same historical PR that introduced scrubbed defaults; do not assume old `ObligationCtxt::new` semantics remain.

## Patterns Not Well Handled

### Strip coroutine metadata from synthetic coroutine drop shims
When StateTransform builds the synthetic drop shim for a coroutine by cloning the coroutine MIR body, the clone must be made non-coroutine before adjusting ABI shape. Retaining `body.coroutine` after only setting `arg_count = 1` leaves stale `CoroutineInfo` on a body that is not itself a coroutine, so helper queries such as `yield_ty` and `coroutine_kind` misclassify the shim. The historical incorrect transformation adjusted only the argument count; the corrected transformation takes the field out with `let _ = body.coroutine.take();` before `body.arg_count = 1`.
Preconditions: The source MIR body is a coroutine lowered through StateTransform and carries `Some(CoroutineInfo)`.; The pass constructs the coroutine drop shim by cloning that body.; The shim is intended to be a `drop_in_place`-style synthetic body, not a coroutine body.; Changing only `arg_count` does not remove the `coroutine` field or its helpers' observable metadata.
Pitfalls: Adjusting `arg_count` alone is insufficient because `body.coroutine` remains populated.; Synthetic MIR bodies derived from coroutine bodies should not automatically retain coroutine metadata; the historical note says this also applies to promoted consts and other synthetic bodies.; Do not infer that the drop shim should keep `yield_ty`, `resume_ty`, or `coroutine_layout` merely because it was cloned from a coroutine.; The removal of the `coroutine_layout` annotation in test expectations is evidence about drop-shim metadata, not evidence that drop control flow changed.
Test strategy: Use a MIR-opt regression with a coroutine storing a drop-requiring local such as `String` across a suspend point (`coroutine_drop_cleanup`). Check the generated `coroutine_drop` shim lacks coroutine metadata, matching expectations where the `/* coroutine_layout = CoroutineLayout { ... } */` block is removed. Cover both panic-abort and panic-unwind. Directly test that `yield_ty` and `coroutine_kind` return `None` on the drop-shim body.
Cases: 120330-07b7c777059032aa50e451f07a750ed4c9ac3df5
Source: https://github.com/rust-lang/rust/pull/120330
> Remove coroutine info when building coroutine drop body
> Coroutine drop shims are not themselves coroutines
>     // Take the coroutine info out of the body, since the drop shim is
>     let _ = body.coroutine.take();
>     body.arg_count = 1; // make sure the resume argument is not included here
> /* coroutine_layout = CoroutineLayout {
> /// Note that the coroutine drop shim, any promoted consts, and other synthetic MIR
> /// bodies that come from processing a coroutine body are not typically coroutines

### Distinguish only by-ref and by-move coroutine bodies for async closures; do not create a by-mut body
For async coroutine-closures, generated MIR distinguishes only the by-ref coroutine body (used by `Fn` and `FnMut`) and the by-move body (used by `FnOnce`). The historically incorrect transformation tracked and generated a third `by_mut_body`, effectively a copy of the by-ref body with a different self type, and could select a by-move body for `Fn::call`, taking the async-closure receiver by move. The corrected transformation caps `Fn`/`FnMut` to the same by-ref coroutine kind (`i16`), uses the by-move body (`i32`) only for `FnOnce`, deletes `by_mut_body`, and makes the `Fn`/`FnMut` shim take a `*mut Self` receiver while returning the `FnOnce`-flavored coroutine.
Preconditions: The input is an async closure / coroutine-closure, not an ordinary coroutine or closure.; A by-move body exists from the by-move-body transform; only by-ref and by-move bodies should be distinguished.; The `Fn`/`FnMut` shim path takes the closure receiver by reference but returns a coroutine whose kind is `FnOnce`.; The `receiver_by_ref` construct shim path expects no captures, asserted via `tupled_upvars_ty() == unit`.
Pitfalls: Do not create or select a separate by-mut coroutine body: `Fn` and `FnMut` share the by-ref body; the old body was "actually just a copy of the by-ref body, but with a different self type".; Do not populate the coroutine kind from `Ty::from_closure_kind` directly when constructing a coroutine from a coroutine-closure; cap `Fn` and `FnMut` together and keep only `FnOnce` distinct.; Do not use the by-move body for the `Fn::call` path; doing so takes the receiver by move and is the confirmed historical bug.; Deleting `by_mut_body` also requires removing its pass-manager recursion and mirror/dump expectations; an old comment or test name alone does not show the replacement is wrong.; Do not give the `Fn`/`FnMut` shim an exact by-value self signature; it only needs an ABI-compatible shim with a mutable pointer receiver.; The pointer-receiver construct shim is only valid without captures, so keep the unit-upvars assertion.
Test strategy: Use `tests/mir-opt/async_closure_shims.rs` with `EMIT_MIR` for `coroutine_closure_by_move`, `coroutine_closure_by_ref`, and `coroutine_by_move`. The by-ref test should show a pointer receiver such as `_1: *mut {async closure...}` and a coroutine construction using `move`. Add a generic `call_normal<F: Future<Output = ()>>(f: &impl Fn(i32) -> F)` path alongside `call_mut` and `call_once`. Check by-mut EMIT_MIR entries and `.coroutine_by_mut` files are gone, and verify the by-move body is still emitted for the `FnOnce`/`AsyncFnOnce` path.
Cases: 120717-541858ed787a66bbb00a4edd21f924ed0f208a9d
Source: https://github.com/rust-lang/rust/pull/120717
> This also fixes a bug where `<{async closure} as Fn>::call` was returning a body that takes the async-closure receiver *by move*.
> Really, the only distinction we need to make with these bodies is "by ref" and "by move".
> This is actually just a copy of the by-ref body, but with a different self type.
> ty::ClosureKind::Fn | ty::ClosureKind::FnMut => tcx.types.i16,
> // still take their receiver by ref.
> // We use `*mut Self` here because we only need to emit an ABI-compatible shim body,
> assert_eq!(args.as_coroutine_closure().tupled_upvars_ty(), tcx.types.unit);
> return tcx.optimized_mir(coroutine_def_id).coroutine_by_move_body().unwrap().clone();

### Pair child and parent coroutine-closure captures by base upvar and precise-capture prefix
The by-move body for a coroutine-closure remaps inner child captures onto the parent closure's by-value upvars. The inner capture list begins with synthetic argument captures, so analysis must skip `num_args` before pairing the remainder with `tcx.closure_captures(parent_def_id)`. Under edition-2021 precise captures, one parent capture can refine into several child captures with additional projections, so a positional zip alone is wrong. Correct pairing matches the base HIR id (`parent_base.var_path.hir_id == child_base.var_path.hir_id`) plus projection-prefix compatibility, only forces a child by-ref capture by move when the parent capture is by-move, uses the renumbered parent field index, and re-applies extra child projections. Length assertions belong after a matching pair is selected, not inside the predicate that filters unrelated captures.
Preconditions: An async coroutine-closure requires the by-move shim (`FnOnce`/`AsyncFnOnce` path).; The inner `closure_captures(coroutine_def_id)` list includes argument captures first; `.skip(num_args)` isolates the closure upvars.; The coroutine kind is not already `FnOnce` for the body-building path; such bodies early-return because upvars are already by value.; `tcx.local_parent(coroutine_def_id)` is a `ty::CoroutineClosure` providing upvars, signature inputs, and captures.; Edition 2021 precise captures may split a parent capture into multiple children and add Field/Deref projections.
Pitfalls: Do not infer by-move from the child's `is_by_ref()` alone; only force by-move when `coroutine_capture.is_by_ref() && !parent_capture.is_by_ref()`.; Do not use the raw capture-list index as the field index; the fixed index is `num_args + idx` after `.skip(num_args)`.; Do not remap positionally or match by projection kinds alone; two distinct upvars can share the same projection shape, so compare the base HIR id and advance the parent cursor after use.; Do not assume equal capture counts or a one-to-one parent/child correspondence; one parent may refine into several children.; Do not put the prefix-length assertion before the base-HIR-id check; the predicate must be able to return false for an unrelated shorter capture instead of panicking.; Do not drop extra precise-capture projections; re-apply them after the remapped parent field.; Do not lose the invariant that every parent capture is used and none are left over.
Test strategy: Use run-pass UI tests with output assertions under edition 2021, exercising normal call, `async FnOnce`, and forced `FnOnce` revisions. Cover by-ref value and reference captures, consumed captures forcing `AsyncFnOnce`, `move` with and without consumption, precise struct-field captures, `&mut` fields, and overlapping projection shapes with two `&mut` variables to verify base-identity matching. Add a case where unrelated captures have different projection lengths (`async || { println!("{}", s.t); println!("{}", t); }`) to ensure no assertion ICE.
Cases: 123349-ec74a304bb737f24d6e7f2fb8c3a2b3cf3575f0f, 123518-ad0fcac72b4fbd5a6558fa1d440882156eafae33, 123701-69b690f0f69c7d7bc783df6295bdc6b14d65f07b
Source: https://github.com/rust-lang/rust/pull/123349
Source: https://github.com/rust-lang/rust/pull/123518
Source: https://github.com/rust-lang/rust/pull/123701
> The check we were doing to figure out if a coroutine was borrowing from its parent coroutine-closure was flat-out wrong -- a misunderstanding of mine of the way that `tcx.closure_captures` represents its captures.
> .skip(num_args)
> .zip_eq(tcx.closure_captures(parent_def_id))
> if coroutine_capture.is_by_ref() && !parent_capture.is_by_ref() {
> by_ref_fields.insert(FieldIdx::from_usize(num_args + idx));
> the number of upvars may differ *and/or* the inner coroutine may have additional projections applied to an upvar.
> if parent_base.var_path.hir_id != child_base.var_path.hir_id
> assert_eq!(parent_captures.next(), None, "leftover parent captures?");
> assertion failed: child_capture.place.projections.len() >=
> child_capture.place.projections.len() >= parent_capture.place.projections.len()
> This analysis only makes sense if the parent capture is a
> prefix of the child capture.

### Adjust ByMoveBody projections and fake borrows when capture modes differ
In the by-move body, a child capture's place is rebuilt from the parent upvar field plus selected projections. Two independent adjustments are needed: when the parent capture is by-ref but the child is by-value, insert a leading `Deref` projection to go from `&&Ty` to `&Ty`; and when the child capture was by-ref (`&Foo`) but the by-move body owns the value (`Foo`, `peel_deref == true`), remove direct fake shallow borrows of that upvar field (replace the statement with `nop`). The historical incorrect transformation omitted the inserted leading deref, producing type-incorrect MIR (`left-hand side has type: Ty`, `right-hand side has type: &Ty`) caught by `-Zvalidate-mir`, and retained obsolete direct fake borrows, associated with an ICE about a missing deref on an upvar initialization. Fake borrows through a deref and remaps without `peel_deref` must not be removed.
Preconditions: `#![feature(async_closure)]` coroutine-closure whose by-move body is generated by ByMoveBody/MakeByMoveBody.; A parent/child capture pairing has been established using base upvar and projection-prefix matching.; For the leading-deref case: parent capture is by-ref and child capture is by-value, typically from moving a non-`Copy` value out of a shared reference, so parent type is `&&Ty` and child type is `&Ty`.; For the fake-borrow case: the child capture was `&Foo`, the by-move body owns `Foo`, `field_remapping` has `peel_deref == true`, and a fake shallow borrow place is exactly `CAPTURE_STRUCT_LOCAL.Field(idx, _)` with no deref.
Pitfalls: Do not conflate inserting a leading Deref for a by-ref parent with peeling a trailing Deref for a by-ref child; both can apply when the parent is by-ref and precise-capture projections exist.; The old `needs_deref = child_capture.is_by_ref() && !parent_capture.is_by_ref()` is not equivalent to the new `peel_deref` handling; a by-ref parent still needs the leading deref insertion.; Keep the pointee non-`Copy` in trigger tests; a `Copy` type can change the child capture to by-ref and mask the trigger.; Only nop a fake borrow whose place is exactly a single Field projection on `CAPTURE_STRUCT_LOCAL`; fake borrows with a deref, e.g. `&fake shallow (*(_1.0))`, must remain.; Check the third remapping tuple element (`peel_deref`): if false, the capture was not converted from reference to by-move value, so a direct fake borrow is not necessarily obsolete.; After setting the statement to `StatementKind::Nop`, still call `self.super_statement(...)`; after retyping the capture local, call `super_local_decl(...)`.
Test strategy: Add a UI regression with `-Zvalidate-mir`, edition 2021, `#![feature(async_closure)]`, a non-`Copy` `struct Ty;`, and `async || { *x; }` from `x: &Ty`; expect `E0507: cannot move out of `*x` which is behind a shared reference` rather than a broken-MIR ICE. For fake borrows, add a MIR-opt test emitting parent and by-move child MIR for `async move || match f { Foo::Bar if true => {} _ => {} }`; assert the direct fake shallow borrow becomes `nop;` while deref fake borrows remain (`_3 = &fake shallow (*(_1.0: &Foo))`). Include controls where the fake borrow has a deref or `peel_deref` is false.
Cases: 129101-1e1d8393881f60781ac6b13e2d7667afaee2d764, 138514-e54bde6d473941ff45643f494a902f23b19e7c9a
Source: https://github.com/rust-lang/rust/pull/129101
Source: https://github.com/rust-lang/rust/pull/138514
> we weren't applying an additional deref projection to convert the parent capture into the child capture
> If the parent capture is by-ref, then we need to apply an additional
> Projection { ty: parent_capture.place.ty(), kind: ProjectionKind::Deref },
> left-hand side has type: Ty
> right-hand side has type: &Ty
> broken MIR in CoroutineKindShim { coroutine_def_id:
> Remove fake borrows of closure captures if that capture has been replaced with a by-move version of that capture.
> we never have an upvar of type `&Foo`, and we should replace it with a `nop`.
> There should be at least a single deref for an upvar local initialization, found []
> statement.kind = mir::StatementKind::Nop;

### Choose coroutine-closure by-ref capture lifetime per parent/child pair, not always the env lifetime
When computing `coroutine_captures_by_ref_ty`, the historical overly restrictive transformation applied the closure-env lifetime to every by-ref child capture. Correct behavior uses the child capture's own region when no reborrow from the parent environment is needed, and uses the env lifetime when the parent capture is by-ref, when the child borrows closure-owned data (by-move parent whose child does not begin with a deref after the parent prefix), or when the child capture is mutable. The heuristic is not a soundness boundary: borrowck still validates the choices, so the observable failure mode is unnecessary borrowck errors rather than unsound code.
Preconditions: The parent capture is a prefix of the child capture; `analyze_coroutine_closure_captures` asserts this and that every parent is used at least once.; Flattened child captures include argument-move captures first; skip the number of tuple input fields before pairing with parent captures.; One parent capture may correspond to several child captures because of edition-2021 precise captures, so match by shared projection prefix.; The deref exception applies only when the parent capture is by-move and the next child projection after the parent prefix is `ProjectionKind::Deref`.; Mutable child captures always need the parent coroutine-closure env lifetime because `&'env mut &'a mut i32` cannot be reborrowed as `&'a mut i32`.
Pitfalls: Do not apply the deref-projection exception when the parent capture is by-ref or when the child borrow is mutable; those still require the parent env lifetime.; Do not treat every child capture as needing `'env`, nor every child capture as safe with its own region; decide per parent/child pair.; Preserve the invariant that every parent capture is used and no child captures are left over, otherwise precise captures can be mis-mapped.; A wrong lifetime heuristic is not unsoundness by itself; borrowck validates it, so tests should expect borrowck diagnostics, not arbitrary behavior.; The `ByMoveBody` zipping extraction in the same historical patch is mechanical and not the lifetime-choice correctness fix.
Test strategy: Add edition-2021 UI tests where `*value` is borrowed with `'a` rather than the containing coroutine-closure lifetime (moro-example), and no-borrow-from-env tests for `async`/`async move` closures capturing `&'a i32`, field captures `S<'a>`, and `&S<'a>`, passed directly and through an `async FnOnce` helper. Add an edition-2018 version expecting borrowck errors without ICE. Include mutable-reference cases that must keep the env lifetime, and update escaping-closure expectations to remove spurious extra `E0515` errors.
Cases: 123660-599d456a7532aa5de020b42fd1d9d936fa647573
Source: https://github.com/rust-lang/rust/pull/123660
> Currently, we treat all the by-(mut/)ref borrows of a coroutine-closure as having a "closure env" borrowed lifetime.
> We will return a future whose captures contain `&'env i32` instead of `&'a i32`, which is way more restrictive than necessary.
> If the closure borrows data from inside the closure's captures. This is not true if the parent capture is by-ref, OR if the parent capture is by-move and the child capture begins with a deref projection.
> If we're dealing with mutable references, since we cannot reborrow `&'env mut &'a mut i32` into `&'a mut i32`, *only* `&'env mut i32`.
> luckily, if this heuristic is not correct, then the program is not unsound, since we still borrowck and validate the choices made from this function
> if needs_ref { Some(closure_env_region) } else { child_capture.region }
> // One parent capture may correspond to several child captures if we end up
> // refining the set of captures via edition-2021 precise captures.

### Check both element and custom allocator for Box in the must-not-suspend lint
The must-not-suspend analysis in the coroutine state transform historically matched `ty::Adt(..) if ty.is_box()` and recursed only into `ty.boxed_ty()`, silently ignoring the custom allocator type argument of `Box<T, A>`. The corrected check matches `ty::Adt(_, args)`, derives both `args.type_at(0)` and `args.type_at(1)`, and combines them with `||`, labeling the recursions `"{}boxed "` and `"{}allocator "`. A `#[must_not_suspend]` allocator held across an await must be reported even when the boxed element is not annotated.
Preconditions: The crate enables `must_not_suspend` and, for custom allocators, `allocator_api`.; An `async fn` binds a `Box<T, A>` before an `.await` and keeps it live across the suspend point.; The allocator type `A` is annotated `#[must_not_suspend]`, directly or through nested types reachable by the recursive check.; The coroutine state-transform code runs the box arm rather than treating the ADT generically.
Pitfalls: Using `ty.boxed_ty()` yields only the element type and loses the allocator argument, so the allocator is silently unchecked.; For `Box<T, A>`, the allocator is `args.type_at(1)`; checking only index 0 misses it. Combine both checks with `||`.; The diagnostic prefix matters: allocator recursion uses `"{}allocator "`, so the reported message names the allocator.; Short-circuiting with `||` is intentional; do not assume the allocator check also runs when the element check already failed.
Test strategy: Add a UI regression (`tests/ui/lint/must_not_suspend/allocator.rs`) with edition 2021, `#![feature(must_not_suspend, allocator_api)]`, `#![deny(must_not_suspend)]`, a `#[must_not_suspend]` allocator implementing `Allocator`, and `let x = Box::new_in(1i32, MyAllocatorWhichMustNotSuspend); suspend().await; drop(x);`. Expect one error naming the allocator as held across a suspend point, with the await span marked.
Cases: 122701-0db06bf0046b70dee03de07fd6b455173a90c117
Source: https://github.com/rust-lang/rust/pull/122701
> If the Box has a custom allocator, then that will not be checked at all.
> Detect allocator for box in must_not_suspend lint
> let boxed_ty = ty.boxed_ty();
> ty::Adt(_, args) if ty.is_box() => {
> let boxed_ty = args.type_at(0);
> let allocator_ty = args.type_at(1);
> &format!("{}allocator ", data.descr_pre)
> error: allocator `MyAllocatorWhichMustNotSuspend` held across a suspend point, but should not be

### Preserve async-drop successors and use the correct pending value and storage lifetime
Async-drop lowering elaborates a drop into a pinned async-drop future plus a dropline ladder, then StateTransform expands hidden drops into yield/poll states. Correct lowering gates async drops on non-cleanup coroutine blocks, `allow_async_drops()`, the feature, and `needs_async_drop`, and preserves the hidden `Drop { async_fut, drop }` successors and dropline. The historically incorrect variants: leave an ordinary sync drop with no async future; emit async drops in cleanup/unwind blocks; drop the async successors while rebuilding the terminator; use the generic bool `false` for the pending yield of an async generator whose yield type is `Poll<Option<T>>`; or omit `StorageDead` for the pinned future temporary on the poll-switch, unwind, or dropline paths. Correct behavior builds an unevaluated `AsyncGenPending` constant with the full yield type for async generators, reorders `build_pin_fut` before `build_poll_switch`, and emits `StorageDead(fut_pin_place.local)` in the switch plus `StorageDead(fut.local)` at the start of unwind and dropline blocks.
Preconditions: The unstable features are enabled: `async_drop`, and `gen_blocks` for async generators.; The enclosing MIR body is a coroutine (`body.coroutine.is_some()`) and, for StateTransform expansion, the coroutine is async/async-gen with `has_expandable_async_drops`.; The drop is on a non-cleanup path; cleanup/unwind drops remain synchronous.; `allow_async_drops()` is true and the dropped type `needs_async_drop`.; Any pass cloning or reconstructing `TerminatorKind::Drop` preserves the hidden `drop` and `async_fut` fields.; For the async-gen pending value, the coroutine kind is `CoroutineKind::Desugared(CoroutineDesugaring::AsyncGen, _)` and the yield type is `Poll<Option<T>>`.; For storage liveness, a pinned future local receives `StorageLive` and must receive `StorageDead` on every path; panic-unwind and Inline expose missing closes.
Pitfalls: Do not generate an async drop inside a cleanup block or cleanup drop ladder; the historical patch asserts `Dropline is set for cleanup drop ladder` if this invariant is violated.; Do not drop `async_fut` or `drop` while rebuilding a `Drop` terminator, or the later poll/yield expansion and dropline successor disappear.; An async drop is a hidden yield and needs the same dropline preparation as a `Yield` terminator.; For an unresumed coroutine with async drops, the clean-drop shim must return `Poll::Ready(())` rather than the sync-only `Return`.; Do not use a bool constant for a coroutine yield place whose type is `Poll<Option<T>>`; MIR validation rejects the incompatible assignment.; The generic `false` constant is only appropriate for return-yields or non-async-generator gen coroutines; async generators require `AsyncGenPending` with the concrete yield type.; Unwind and dropline blocks are separate paths: success-path `StorageDead` does not discharge cleanup/dropline liveness obligations.; The fix required reordering `build_pin_fut` before `build_poll_switch` so the switch can reference `fut_pin_place`; merely adding a `StorageDead` elsewhere does not cover the switch path.; Panic-abort MIR has no cleanup blocks while panic-unwind does, so a single panic strategy does not exercise the unwind `StorageDead` fix.; `Inline` is a trigger/exposer in the storage-liveness regression, not the pass whose lowering is being corrected.
Test strategy: Use run-pass plus check-run-results tests with a deterministic `block_on` and `async_drop_in_place`, asserting exact stdout for active fields, nested ADTs, and mid-execution drops. Include a suspended coroutine whose async-droppable local invokes `AsyncDrop` rather than sync `Drop`. For async generators, add a UI build-pass test with edition 2024 and `#![feature(async_drop, gen_blocks)]` for `async gen fn a() { _ = async {} }`, checking MIR validation does not see `Assign((_0, const false))` into `Poll<Option<T>>`. For storage liveness, add `-Zlint-mir` check-pass cases and a MIR-opt test with `EMIT_MIR_FOR_EACH_PANIC_STRATEGY`, verifying `StorageDead` in the poll-switch block and at the start of unwind/dropline blocks; include `-Zmir-enable-passes=+Inline -Zvalidate-mir -Zlint-mir` to expose the Inline-triggered crash.
Cases: 123948-c366756a8537ef998d32c1ef57098d5aae7ca92f, 141932-d5a9a005188322cd08dca018402e1593d3a5ebd5, 142347-d6a9081612e55b4d755163ce54d94ea0a96e4a2b
Source: https://github.com/rust-lang/rust/pull/123948
Source: https://github.com/rust-lang/rust/pull/141932
Source: https://github.com/rust-lang/rust/pull/142347
> Scopes processing for generate async drop preparations. Async drop is a hidden Yield, so potentially async drops require the same dropline preparation as for Yield terminators.
> Drops in unwind path (cleanup blocks) are not expanded to async drops, only sync drops in unwind path
> Dropline is set for cleanup drop ladder
> Fixed when re-work async drop to shim drop glue coroutine scheme.
> value needed only for return-yields or gen-coroutines, so just const here
> const_: Const::from_bool(tcx, false),
> // For AsyncGen we need `yield Poll<OptRet>::Pending`
> tcx.require_lang_item(LangItem::AsyncGenPending, None)
> ICE: encountered `Assign((_0, const false))` with incompatible types: left-hand side has type: std::task::Poll<std::option::Option<()>> right-hand side has type: bool
> StorageLive/StorageDead codegen is corrected for pinned async drop future.
> +    let storage_dead =
> +        statements: [storage_dead, discr_assign].to_vec(),
> +        // StorageDead(fut) in unwind block (at the begin)
> +        // StorageDead(fut) in dropline block (at the begin)
> //@ compile-flags: -Zmir-enable-passes=+Inline -Zvalidate-mir -Zlint-mir --crate-type lib

### Check coroutine obligations once per typeck root and keep full diagnostics for field-Sized checks
Coroutine obligation checking is performed once per typeck root, with stalled predicates stored as a flat `FxIndexSet<(Predicate, ObligationCause)>` on the root rather than a `LocalDefIdMap` keyed by coroutine. The historically incorrect transformation either looked up the root id in a map still keyed by individual coroutine def_ids (registering zero predicates) or kept layout-dependent sized-field checks in the root-level checker. Correct behavior registers all root predicates using `tcx.typeck(def_id)` and `param_env` under `with_opaque_type_inference(root)`, and moves `Sized` checks for `coroutine_layout.field_tys` into `mir_coroutine_witnesses`, where the per-coroutine layout and def_id are available. Separately, StateTransform's `check_field_tys_sized` must use `ObligationCtxt::new_with_diagnostics` rather than the scrubbed default, because it reports fulfillment errors and needs per-obligation code/root/span data.
Preconditions: `check_coroutine_obligations` receives the typeck root def_id, asserted by `debug_assert!(!tcx.is_typeck_child(def_id.to_def_id()));`.; Stalled predicates are stored for the whole typeck root as `FxIndexSet<(ty::Predicate<'tcx>, ObligationCause<'tcx>)>`, not keyed by coroutine def_id.; Field-`Sized` checks run inside `mir_coroutine_witnesses`, after `compute_layout` and `check_suspend_tys`, where `coroutine_layout.field_tys` and coroutine `def_id` are in scope.; Field-sized checking early-returns unless `tcx.features().unsized_locals` or `tcx.features().unsized_fn_params` is enabled.; Opaque type inference is bound to the typeck root via `with_opaque_type_inference(def_id)`.; The `check_field_tys_sized` callsite consumes or reports fulfillment errors rather than only probing truth/ambiguity.
Pitfalls: Do not keep keying stalled predicates by individual coroutine def_id after moving to per-typeck-root checking; the new solver cannot reliably associate obligations with specific coroutines.; Do not leave coroutine-interior `Sized` checks in the root-level `check_coroutine_obligations`; relocate them to `mir_coroutine_witnesses` where per-coroutine layout exists.; Do not bind opaque type inference to a child coroutine's def_id; root-level checking must use the typeck root def_id.; Flattening the predicate map into a set changes ordering/deduplication behavior; the orphaned-anon-const regression expects duplicate diagnostics when `-Z deduplicate-diagnostics=no` is used.; Scrubbed trait errors store only TrueError/Ambiguity/Cycle classification and are insufficient for callsites that inspect obligation/code/root_obligation or call `report_fulfillment_errors`.; Ambiguity and Cycle are not hard true errors; `is_true_error` must distinguish them from Select/Project/Subtype/ConstEquate.; Opting in to diagnostics is a performance tradeoff: diagnostic generation does extra trait solving and can recurse or stack overflow when used inside error-reporting machinery, so only callsites that need detailed errors should use `new_with_diagnostics`.; The coroutine callsite was migrated in the same historical PR that introduced scrubbed defaults; do not assume old `ObligationCtxt::new` semantics remain.
Test strategy: Use UI tests putting several coroutines in one typeck root and separately in different roots, verifying every expected `Copy`/`Clone` trait-bound diagnostic still appears. Include a coroutine inside an orphaned anonymous const (`Self::Assoc<{ async {} }>`) and check diagnostics rather than an ICE, with `-Z deduplicate-diagnostics=no` for duplicates. For field-Sized checking, enable `unsized_locals`/`unsized_fn_params` and verify `SizedCoroutineInterior` errors still arise from the layout/witness path with source spans. For the diagnostics callsite, compile coroutine fields that fail or are ambiguous for `Sized` and verify span-bearing fulfillment diagnostics rather than missing data or ICE, alongside a control where all fields are Sized.
Cases: 123993-a8c9a0bd8167c99557c9d475631c844775883336, 125864-a41c44f21c1a6fd96eb8d68fbdb298610443cff5
Source: https://github.com/rust-lang/rust/pull/123993
Source: https://github.com/rust-lang/rust/pull/125864
> Do `check_coroutine_obligations` once per typeck root
> We only need to do `check_coroutine_obligations` once per typeck root, especially since the new solver can't really (easily) associate which obligations correspond to which coroutines.
> This requires us to move the checks for sized coroutine fields into `mir_coroutine_witnesses`, but that's fine imo.
> +    debug_assert!(!tcx.is_typeck_child(def_id.to_def_id()));
> +    pub coroutine_stalled_predicates: FxIndexSet<(ty::Predicate<'tcx>, ObligationCause<'tcx>)>,
> +            tcx.ensure().check_coroutine_obligations(
> +    check_field_tys_sized(tcx, &coroutine_layout, def_id);
> Opt-in to `FulfillmentError` generation to avoid doing extra work in the new solver
> introduce `ObligationCtxt::new_with_diagnostics` for the callsites that actually inspect their `FulfillmentError`s.
> fn check_field_tys_sized<'tcx>(
> let ocx = ObligationCtxt::new_with_diagnostics(&infcx);
> for field_ty in &coroutine_layout.field_tys {
> A trait error with most of its information removed. This is the error
> ScrubbedTraitError::Ambiguity | ScrubbedTraitError::Cycle(_) => false,
