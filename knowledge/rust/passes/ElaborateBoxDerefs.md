# ElaborateBoxDerefs
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- Do not accept the double deref as a valid alternate elaboration; the supplied PR description explicitly calls it wrong.
- Do not infer the defect from the test expectation alone: the decoded before-pass MIR is `debug foo => (*_1);` and the corrected after-pass MIR is `debug foo => (*(((_1.0).0).0));` with one deref.
- The old post-loop append is the duplication mechanism: `new_projections.extend_from_slice(&place.projection[last_deref..]);` after starting with `new_projections.extend_from_slice(&base.projection[last_deref..]);`.
- The reported symptom includes `deref projection of non-dereferenceable ty` during validation; the downstream async-closure ICE is incidental, with the root cause in `ElaborateBoxDerefs` on a debug varinfo.
- Do not conflate this with borrowing restrictions or post-copy overwrite failures.
- Ordinary non-debuginfo box-deref behavior should remain unchanged, so a regression test must inspect debug varinfos rather than only ordinary places.
- Do not present the lifted `Box<Box<i32>>` test as the original `Box<i32>` reproducer; it is a modeling choice that makes the duplicated deref executable.
- Do not attribute the `size_of_val` difference to return changes or unrelated transformations; it is caused by the extra dereference changing the place type.
- Avoid claiming that the concrete 4-versus-8 observation proves all box-deref cases equivalent; it differentiates the supplied modeled pair only.

## Patterns Not Well Handled

### ElaborateBoxDerefs must not duplicate a debug-varinfo place's original box Deref
For `ElaborateBoxDerefs`, a debug varinfo whose place projection dereferences `Box<T>` is rewritten by replacing that box `Deref` with the `Unique`/`NonNull`/`*const` field projections followed by exactly one `Deref`. The historical incorrect rebuilding emitted that chain and then also appended the original projection from the last-deref index, which reintroduced the original box `Deref`. As the supplied description states, the pass was turning `*(SOME_PLACE: Box<T>)` into `*(*((((SOME_PLACE).0: Unique<T>).0: NonNull<T>).0: *const T))` in debug var infos, and `In particular, notice the *double deref*, which was wrong.` The invariant is that the original deref is replaced, not retained, and projections after the box deref are appended exactly once. This is a debug-varinfo-specific path: ordinary non-debuginfo place elaboration may already be correct.
Preconditions: The MIR body has a `VarDebugInfoContents::Place`.; That place's projection includes `PlaceElem::Deref` whose `base_ty.is_box()` is true.; The box deref may be the first projection, as in `debug foo => *opt` with `opt: Box<i32>`, or other projections may surround it.; Minimal reproducer shape: `#![feature(custom_mir, core_intrinsics)]`, `#[custom_mir(dialect = "built")]`, and a body containing `debug foo => *opt;` followed by `Return()`.; Compiler-generated debug info can also hit the path, e.g. by-move async closures capturing `Box<dyn Trait>`.
Pitfalls: Do not accept the double deref as a valid alternate elaboration; the supplied PR description explicitly calls it wrong.; Do not infer the defect from the test expectation alone: the decoded before-pass MIR is `debug foo => (*_1);` and the corrected after-pass MIR is `debug foo => (*(((_1.0).0).0));` with one deref.; The old post-loop append is the duplication mechanism: `new_projections.extend_from_slice(&place.projection[last_deref..]);` after starting with `new_projections.extend_from_slice(&base.projection[last_deref..]);`.; The reported symptom includes `deref projection of non-dereferenceable ty` during validation; the downstream async-closure ICE is incidental, with the root cause in `ElaborateBoxDerefs` on a debug varinfo.; Do not conflate this with borrowing restrictions or post-copy overwrite failures.; Ordinary non-debuginfo box-deref behavior should remain unchanged, so a regression test must inspect debug varinfos rather than only ordinary places.
Test strategy: Use a focused custom-MIR test with `//@ test-mir-pass: ElaborateBoxDerefs`, `// skip-filecheck`, and an `EMIT_MIR` diff, e.g. `EMIT_MIR elaborate_box_deref_in_debuginfo.pointee.ElaborateBoxDerefs.diff`, for a function containing `debug foo => *opt;` where `opt: Box<i32>`. Check that the corrected output is a single dereference after the field chain, matching `debug foo => (*(((_1.0: std::ptr::Unique<i32>).0: std::ptr::NonNull<i32>).0: *const i32));`, not an additional outer deref. Keep ordinary non-debuginfo box-deref tests unchanged, and add the async-closure run-pass regression `tests/ui/async-await/async-closures/box-deref-in-debuginfo.rs` with `block-on.rs` to cover the downstream ICE path. This MIR-diff evidence is concrete for the supplied cases; finite tests do not establish universal equivalence.
Cases: 128572-2e52d6180724ee0cbd8b47bc7806a53bf13ab240
Source: https://github.com/rust-lang/rust/pull/128572
> Fix `ElaborateBoxDerefs` on debug varinfo
> Slightly simplifies the `ElaborateBoxDerefs` pass to fix cases where it was applying the wrong projections to debug var infos containing places that deref boxes.
> What happens is that the pass was turning `*(SOME_PLACE: Box<T>)` into `*(*((((SOME_PLACE).0: Unique<T>).0: NonNull<T>).0: *const T))` in debug var infos. In particular, notice the *double deref*, which was wrong.
> we don't actually have any tests (or code anywhere, really) that exercise `debug x => *(...: Box<T>)`
> new_projections.extend_from_slice(&base.projection[last_deref..]);
> new_projections.extend_from_slice(&place.projection[last_deref..]);
> -     debug foo => (*_1);
> +     debug foo => (*(((_1.0: std::ptr::Unique<i32>).0: std::ptr::NonNull<i32>).0: *const i32));
> debug foo => *opt;
> deref projection of non-dereferenceable ty
> ICE in async closure that takes ref to boxed dyn trait

### Concrete differentiator for the duplicated deref by lifting the boxed input
The supplied validated pair models the historical debug-varinfo projection rebuild on a lifted input where duplication becomes executable: rather than `Box<i32>` yielding an invalid extra `*i32`, use `Box<Box<i32>>`, so the original place `*opt` has type `Box<i32>` and the historical output adds a second `Deref` corresponding to `**opt`. The wrong place then has type `i32` instead of the original `Box<i32>`. On the test target, observing `size_of_val` of the resulting place distinguishes these as 4 versus 8. This difference comes solely from the duplicated deref, not from arbitrary return-value changes. It is concrete evidence for this case, not universal proof of equivalence.
Preconditions: Model the old debug-varinfo rebuilding behavior for a place whose projection contains a box deref.; Use a lifted input such as `opt = Box::new(Box::new(7_i32))` so the duplicated deref is executable by Miri instead of immediately producing an invalid dereference type.; The original place is `*opt`, whose value type is the inner `Box<i32>`.; The historical wrong pass emits the generated pointer-field chain plus a `Deref` and then appends the original place projection from index 0, adding the original `Deref` a second time.
Pitfalls: Do not present the lifted `Box<Box<i32>>` test as the original `Box<i32>` reproducer; it is a modeling choice that makes the duplicated deref executable.; Do not attribute the `size_of_val` difference to return changes or unrelated transformations; it is caused by the extra dereference changing the place type.; Avoid claiming that the concrete 4-versus-8 observation proves all box-deref cases equivalent; it differentiates the supplied modeled pair only.
Test strategy: Construct the lifted input `opt = Box::new(Box::new(7_i32))`, apply the modeled old projection rebuild, and compare the resulting place type via `size_of_val`: the wrong place should behave as `i32` (4 on the test target) rather than the original `Box<i32>` (8). Pair this concrete differentiator with the MIR-diff regression that checks `debug foo => *opt` produces exactly one deref after elaboration.
Cases: 128572-2e52d6180724ee0cbd8b47bc7806a53bf13ab240
Source: https://github.com/rust-lang/rust/pull/128572
> Fix `ElaborateBoxDerefs` on debug varinfo
> Slightly simplifies the `ElaborateBoxDerefs` pass to fix cases where it was applying the wrong projections to debug var infos containing places that deref boxes.
> What happens is that the pass was turning `*(SOME_PLACE: Box<T>)` into `*(*((((SOME_PLACE).0: Unique<T>).0: NonNull<T>).0: *const T))` in debug var infos. In particular, notice the *double deref*, which was wrong.
> we don't actually have any tests (or code anywhere, really) that exercise `debug x => *(...: Box<T>)`
> new_projections.extend_from_slice(&base.projection[last_deref..]);
> new_projections.extend_from_slice(&place.projection[last_deref..]);
> -     debug foo => (*_1);
> +     debug foo => (*(((_1.0: std::ptr::Unique<i32>).0: std::ptr::NonNull<i32>).0: *const i32));
> debug foo => *opt;
> deref projection of non-dereferenceable ty
> ICE in async closure that takes ref to boxed dyn trait
