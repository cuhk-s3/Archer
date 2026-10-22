# CheckNull
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- Do not apply the unconditional check to all contexts; the fix only strengthens borrow contexts.
- Mutable borrows appear as `MutatingUseContext::Borrow`, not the shared-borrow context, so both variants need coverage.
- The old code comment "// Get size of the pointee (zero-sized reads and writes are allowed)." reflects the pre-fix blanket exemption and should not be treated as covering borrows.
- Do not make the null check unconditional: doing so turns allowed zero-sized reads and raw borrows into false positives.
- `&raw const *ptr` is a different `PlaceContext` from `&*ptr`; raw borrows must remain under the non-ZST guard.
- Do not conflate the dereference place with the borrow of that place; naming `*ptr` is fine for a ZST, while borrowing it is UB.
- Varying both pointee size and place-use context in one test obscures which condition the check depends on.
- An outdated `error-pattern` containing the old spelling can cause a false test failure.
- CheckNull and CheckAlignment share the new `PlaceContext` parameter, but alignment consumes it as `_context`; do not attribute alignment changes to this fix.
- A run-pass negative test only shows the check was absent for those concrete inputs; it does not by itself prove general equivalence.

## Patterns Not Well Handled

### Null raw-pointer borrows are checked even for ZST pointees
When a raw pointer that is null at runtime is consumed as a shared borrow (`&*ptr`) or mutable borrow (`&mut *ptr`), the null check must fire regardless of pointee size. The historical guard `is_null && sizeof(pointee) != 0` skipped this case for ZST pointees; the corrected guard is unconditionally true for `SharedBorrow` and `Borrow` contexts. The underlying distinction is that constructing a reference to a null place is UB, whereas merely naming/reading a null ZST place is not: "// Borrows pointing to \"null\" are UB even if the pointee is a ZST." and "// Other usages of null pointers only are UB if the pointee is not a ZST." The intent is stated as: "Ensures that we check that borrows of derefs are non-null in the `CheckNull` pass **even if** it's a ZST pointee." The issue evidence confirms "As per https://github.com/rust-lang/unsafe-code-guidelines/issues/472 , access to a ptr to ZST is not UB, so  `*ptr` is ok."
Preconditions: CheckNull runs within the pointer-check MIR pass under `-C debug-assertions`.; The dereferenced raw pointer value is null at runtime.; The pointee type is zero-sized (e.g. `()`), making the old `SizeOf(pointee_ty) != 0` test false.; The place-use context is `NonMutatingUseContext::SharedBorrow` or `MutatingUseContext::Borrow`.
Pitfalls: Do not apply the unconditional check to all contexts; the fix only strengthens borrow contexts.; Mutable borrows appear as `MutatingUseContext::Borrow`, not the shared-borrow context, so both variants need coverage.; The old code comment "// Get size of the pointee (zero-sized reads and writes are allowed)." reflects the pre-fix blanket exemption and should not be treated as covering borrows.
Test strategy: UI test with `//@ run-fail` and `//@ error-pattern: null pointer dereference occurred` using a null ZST pointer borrowed as a reference, e.g. `let ptr: *const () = std::ptr::null(); let _ptr: &() = unsafe { &*ptr };`. Pair with a mutable-borrow variant so both borrow contexts are exercised, and keep pointer construction and pointee type fixed so only the borrow kind varies.
Cases: 136601-a61537f6c068eab87c79173c23837d74b7f7d0ef
Source: https://github.com/rust-lang/rust/pull/136601
> Ensures that we check that borrows of derefs are non-null in the `CheckNull` pass **even if** it's a ZST pointee.
> // Borrows pointing to "null" are UB even if the pointee is a ZST.
>     let _ptr: &() = unsafe { &*ptr };
> error: Undefined Behavior: constructing invalid value: encountered a null reference
> As per https://github.com/rust-lang/unsafe-code-guidelines/issues/472 , access to a ptr to ZST is not UB, so  `*ptr` is ok.
> this PR modifies the null check to be stricter

### Non-borrow uses of null ZST pointees stay exempt (plain reads and raw borrows)
Reads and raw borrows of a null pointer whose pointee is zero-sized remain permitted and must not trigger the null check; the non-ZST guard applies to all other contexts. The fix's comment contrasts the two rules: "// Other usages of null pointers only are UB if the pointee is not a ZST." and the refined condition text: "// We want to throw an exception if the pointer is null and the pointee is not unconditionally" "// allowed (which for all non-borrow place uses, is when the pointee is ZST)." A plain read (`let _ = *ptr;`) and a raw borrow (`let _ = &raw const *ptr;`) therefore both run to completion, which the tests assert with "// Make sure that we don't insert a check for places that do not read."
Preconditions: The pointer is null and the pointee size is zero.; The place-use context is neither shared borrow nor mutable borrow (e.g. plain read of the dereferenced place, or a raw borrow).
Pitfalls: Do not make the null check unconditional: doing so turns allowed zero-sized reads and raw borrows into false positives.; `&raw const *ptr` is a different `PlaceContext` from `&*ptr`; raw borrows must remain under the non-ZST guard.; Do not conflate the dereference place with the borrow of that place; naming `*ptr` is fine for a ZST, while borrowing it is UB.
Test strategy: Add `//@ run-pass` programs reading a null ZST (`let _ = *ptr;`) and taking a raw borrow (`let _ = &raw const *ptr;`). Pair ZST and non-ZST variants (as with `place_without_read` / `place_without_read_zst`) so pointee size is the only varying dimension, and assert absence of the null-check diagnostic.
Cases: 136601-a61537f6c068eab87c79173c23837d74b7f7d0ef
Source: https://github.com/rust-lang/rust/pull/136601
> // Other usages of null pointers only are UB if the pointee is not a ZST.
> // We want to throw an exception if the pointer is null and the pointee is not unconditionally
> // allowed (which for all non-borrow place uses, is when the pointee is ZST).
> // Get size of the pointee (zero-sized reads and writes are allowed).
> // We want to throw an exception if the pointer is null and doesn't point to a ZST.
> // Make sure that we don't insert a check for places that do not read.
> let _ = &raw const *ptr;
> As per https://github.com/rust-lang/unsafe-code-guidelines/issues/472 , access to a ptr to ZST is not UB, so  `*ptr` is ok.

### Isolating the varying dimension and keeping expected diagnostics current
Tests for this behavior are only interpretable when exactly one dimension varies: pointee size (ZST vs non-ZST) or place-use context (shared borrow, mutable borrow, plain read, raw borrow), while null-pointer construction stays fixed. The patch follows this with `borrowed_null`/`borrowed_null_zst` and `place_without_read`/`place_without_read_zst` pairs. Separately, the change also corrects the diagnostic spelling from "occured" to "occurred" and updates UI error patterns; a stale pattern can make a correct run appear to fail. The context parameter added to `insert_alignment_check` is named `_context`, so alignment behavior should not be inferred to change from this patch.
Preconditions: The test harness supports UI-style `run-pass`/`run-fail` plus `error-pattern` matching under `-C debug-assertions`.; The generator can hold null-pointer construction constant while varying pointee type or place-use context.
Pitfalls: Varying both pointee size and place-use context in one test obscures which condition the check depends on.; An outdated `error-pattern` containing the old spelling can cause a false test failure.; CheckNull and CheckAlignment share the new `PlaceContext` parameter, but alignment consumes it as `_context`; do not attribute alignment changes to this fix.; A run-pass negative test only shows the check was absent for those concrete inputs; it does not by itself prove general equivalence.
Test strategy: Build a small matrix: same null pointer construction, crossed with {ZST, non-ZST} and {shared borrow, mutable borrow, plain read, raw borrow}. Expect `run-fail` with "null pointer dereference occurred" only for the two borrow contexts with null pointers, and `run-pass` for read/raw-borrow ZST cases. Keep the diagnostic string synchronized with the corrected "occurred" spelling.
Cases: 136601-a61537f6c068eab87c79173c23837d74b7f7d0ef
Source: https://github.com/rust-lang/rust/pull/136601
> Ensures that we check that borrows of derefs are non-null in the `CheckNull` pass **even if** it's a ZST pointee.
> // Borrows pointing to "null" are UB even if the pointee is a ZST.
> // Make sure that we don't insert a check for places that do not read.
> As per https://github.com/rust-lang/unsafe-code-guidelines/issues/472 , access to a ptr to ZST is not UB, so  `*ptr` is ok.
> this PR modifies the null check to be stricter
