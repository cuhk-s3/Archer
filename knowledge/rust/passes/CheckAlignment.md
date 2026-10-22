# CheckAlignment
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- Do not equate `ub_checks` with `debug_assertions`: the default is inheritance, not identity, and `-Zub-checks` can override in either direction.
- Do not confuse `ub_checks` with `overflow_checks`; they are separate gating mechanisms.
- `cfg!(debug_assertions)` and `cfg!(ub_checks)` answer different questions once flags diverge; testing only `cfg!(debug_assertions)` misses the regression.
- A run-pass-only test can miss unwanted checks still present in optimized IR; inspect codegen/IR when the expectation is that a check is absent.
- Do not overgeneralize from default-flag tests: `By default, \`-Zub-checks\` flag inherits the value of \`-Cdebug-assertions\`.` makes both implementations agree.
- Do not skip borrows for the alignment pass; excluding them misses misaligned shared/mutable references created from raw pointers.
- Do not check the raw pointer's pointee type for `&(*ptr).a`; the resulting reference must be aligned according to the field type (`&u32` in the test) and not the pointer type.
- Do not blindly follow projections for every pointer pass: the null check uses `BorrowedFieldProjectionMode::NoFollowProjections` intentionally.
- The old comment `// We have to exclude borrows here: in `&x.field`, the exact` justifies exclusion only because the code would otherwise check the wrong type; the fix is to follow the field type, not merely include borrows with the pointer type.
- Respect excluded trivially aligned pointees and array-element alignment extraction when deciding whether a program should fail.
- Do not describe the change as fixing MSVC; it suppresses detection of the platform's unsoundness. The source says `Every target that returns less than `Align::MAX` here is still has a soundness bug.` and the change `would detect this unsoundness.`
- Do not reintroduce the early `return false` for i686-pc-windows-msvc; the pass should remain enabled with a weakened mask so that misalignment beyond the reliable alignment is still flagged.
- Do not limit the mitigation to MSVC only: the condition is `is_like_windows && self.arch == "x86"`, and regression codegen tests ignore both i686-pc-windows-msvc and i686-pc-windows-gnu.
- The mask must be `max_align.bytes() - 1`, not the alignment value itself.
- Clamping applies to loads and stores and to ABI pointee alignment (`Some(pointee.align.min(cx.tcx().sess.target.max_reliable_alignment()));`); dropping any of these over-promises alignment.
- Do not claim the compiled compiler was executed/reproduced unless actually built; the PR text describes the mitigation, and ignore annotations are regression-suite accommodations.

## Patterns Not Well Handled

### Gate CheckAlignment on ub_checks(), not debug_assertions
CheckAlignment (and UB-check constant folding) must consult the UB-check setting rather than raw `-Cdebug-assertions`. `-Zub-checks` is optional and defaults to `-Cdebug-assertions`, but can explicitly override it in either direction, so `sess.ub_checks() != sess.opts.debug_assertions` is possible. Historical behavior used `sess.opts.debug_assertions` directly: `-            let const_ = Const::from_bool(self.tcx, self.tcx.sess.opts.debug_assertions);` / `+            let const_ = Const::from_bool(self.tcx, self.tcx.sess.ub_checks());` and `-        sess.opts.debug_assertions` / `+        sess.ub_checks()`. This retains UB checks that were explicitly disabled and removes checks that were explicitly enabled. Gating only the alignment pass is insufficient if the same flag confusion exists elsewhere (e.g. folding `NullOp::UbChecks`); the invariant is one source of truth for all UB-check decisions.
Preconditions: The compilation contains a `NullOp::UbChecks` value or code CheckAlignment would instrument (e.g. raw-pointer dereferences, `slice::get_unchecked`, `slice::from_raw_parts`, `cfg!(ub_checks)`); otherwise the flag choice has no observable effect.; `-Zub-checks` is set explicitly and diverges from `-Cdebug-assertions`; with no `-Zub-checks`, UB checks inherit debug assertions and old/new behavior agree.; CheckAlignment still has its historical target exclusion (i686-pc-windows-msvc early return) or its replacement reliable-alignment clamping; changing the flag gate alone does not remove target handling.; Using `cfg(ub_checks)` in test source requires the `cfg_ub_checks` feature gate.
Pitfalls: Do not equate `ub_checks` with `debug_assertions`: the default is inheritance, not identity, and `-Zub-checks` can override in either direction.; Do not confuse `ub_checks` with `overflow_checks`; they are separate gating mechanisms.; `cfg!(debug_assertions)` and `cfg!(ub_checks)` answer different questions once flags diverge; testing only `cfg!(debug_assertions)` misses the regression.; A run-pass-only test can miss unwanted checks still present in optimized IR; inspect codegen/IR when the expectation is that a check is absent.; Do not overgeneralize from default-flag tests: `By default, \`-Zub-checks\` flag inherits the value of \`-Cdebug-assertions\`.` makes both implementations agree.
Test strategy: Use paired codegen/runtime tests changing only the flag. For folding, compile with `//@ compile-flags: -O -Cdebug-assertions=yes` and a `//@ [NOCHECKS] compile-flags: -Zub-checks=no` revision; check enabled output for `icmp ult`, `br i1`, `call core::panicking::panic_nounwind`, `unreachable`, and disabled output for `// NOCHECKS: tail call void @llvm.assume` plus `getelementptr inbounds`. For CheckAlignment, runtime-fail tests with `//@ compile-flags: -Copt-level=3 -Cdebug-assertions=no -Zub-checks=yes` and `//@ error-pattern: unsafe precondition(s) violated: slice::from_raw_parts`, plus `slice::get_unchecked requires` for OOB. For cfg behavior, `-Zub-checks=no` must make `cfg!(ub_checks)` false and select `#[cfg(not(ub_checks))]`, `-Zub-checks=yes` true; default tests should assert `assert_eq!(cfg!(ub_checks), cfg!(debug_assertions));` under both `-Cdebug-assertions=yes` and `=no`. Also test the missing feature gate expects E0658.
Cases: 123411-a7912cb421db4f4039048cdba2b7fc98ae295342
Source: https://github.com/rust-lang/rust/pull/123411
> -            let const_ = Const::from_bool(self.tcx, self.tcx.sess.opts.debug_assertions);
> +            let const_ = Const::from_bool(self.tcx, self.tcx.sess.ub_checks());
> -        sess.opts.debug_assertions
> +        sess.ub_checks()
> By default, `-Zub-checks` flag inherits the value of `-Cdebug-assertions`.
> This test ensures that such a runtime check is *not* emitted when debug-assertions are enabled,
> but ub-checks are explicitly disabled.
> //@ [NOCHECKS] compile-flags: -Zub-checks=no
> //@ compile-flags: -O -Cdebug-assertions=yes
> // NOCHECKS: tail call void @llvm.assume
> //    DEBUG: call core::panicking::panic_nounwind
> //@ compile-flags: -Copt-level=3 -Cdebug-assertions=no -Zub-checks=yes
> //@ error-pattern: unsafe precondition(s) violated: slice::from_raw_parts
> assert_eq!(cfg!(ub_checks), cfg!(debug_assertions));

### CheckAlignment must instrument raw-pointer borrows using the projected field type
The old alignment pass treated borrows from raw pointers as out of scope (`BorrowCheckMode::ExcludeBorrows`), so `&(*ptr)` or `&mut (*ptr)` and `&(*ptr).field` produced no alignment assertion. Additionally, when a borrow was checked, the shared helper used the raw pointer's pointee type even for a field projection: `let pointee_ty = pointer_ty.builtin_deref(true).expect("no builtin_deref for an raw pointer");`. Correct behavior includes borrows and, for field projections, checks the initial place's type: `pointee_ty = place.ty(self.local_decls, self.tcx).ty;`, i.e. the field type. The null check deliberately keeps `NoFollowProjections` and still checks the pointer's pointee type, because following a projection would validate the wrong thing for nullness.
Preconditions: Debug assertions enabled (`-C debug-assertions`), which is when the alignment checks are generated.; The place is indirect and based on a raw pointer (`ty::RawPtr`) with a sized pointee.; The pointee/element type is not one of the trivially aligned excluded types `bool`, `i8`, `u8`.; The use context is a borrow: `NonMutatingUseContext::SharedBorrow` or `MutatingUseContext::Borrow`.; For a field-projection borrow, the relevant type is the initial place type (the field type), not the raw pointer's pointee type.; Target is not subject to a separate reliable-alignment clamp/exclusion when assessing the expected failure.
Pitfalls: Do not skip borrows for the alignment pass; excluding them misses misaligned shared/mutable references created from raw pointers.; Do not check the raw pointer's pointee type for `&(*ptr).a`; the resulting reference must be aligned according to the field type (`&u32` in the test) and not the pointer type.; Do not blindly follow projections for every pointer pass: the null check uses `BorrowedFieldProjectionMode::NoFollowProjections` intentionally.; The old comment `// We have to exclude borrows here: in `&x.field`, the exact` justifies exclusion only because the code would otherwise check the wrong type; the fix is to follow the field type, not merely include borrows with the pointer type.; Respect excluded trivially aligned pointees and array-element alignment extraction when deciding whether a program should fail.
Test strategy: Add `run-fail` UI tests under `tests/ui/mir/alignment` with `-C debug-assertions` and `//@ error-pattern: misaligned pointer dereference: address must be a multiple of 0x4 but is` covering shared borrow `let _ptr = &(*(ptr.byte_add(1)));`, mutable borrow `let _ptr = &mut (*(ptr.byte_add(1)));`, and field projection `let _ptr: &u32 = unsafe { &(*ptr).a };`. Keep an aligned field-projection test that must not fail. Build paired programs differing only in borrow form or offset. A concrete validated pair: a 4-byte-aligned `[u32; 2]` stack array, `ptr = array.as_ptr().byte_add(1)` so `ptr % 4 == 1`; the corrected check takes the modeled assertion-failure path while the pre-fix no-borrow-check path returns stored 42.
Cases: 137940-7082fa27a792e34a9474db396ccf3958143211af
Source: https://github.com/rust-lang/rust/pull/137940
> The current alignment check does not include checks for creating misaligned references from raw pointers, which is now added in this patch.
> When inserting the check we need to be careful with references to field projections (e.g. `&(*ptr).a`), in which case the resulting reference must be aligned according to the field type and not the type of the pointer.
> // We have to exclude borrows here: in `&x.field`, the exact
> // Naturally, the field type is type of the initial place we look at.
> pointee_ty = place.ty(self.local_decls, self.tcx).ty;
> BorrowedFieldProjectionMode::FollowProjections
> BorrowedFieldProjectionMode::NoFollowProjections
> let _ptr: &u32 = unsafe { &(*ptr).a };
> let _ptr = &(*(ptr.byte_add(1)));
> let _ptr = &mut (*(ptr.byte_add(1)));
> //@ error-pattern: misaligned pointer dereference: address must be a multiple of 0x4 but is
> BorrowCheckMode::ExcludeBorrows
> IncludeBorrows

### Clamp CheckAlignment masks and codegen alignment to Target::max_reliable_alignment()
On 32-bit x86 Windows, MSVC does not reliably align `u64`/`i64` and similar types. Historically CheckAlignment was disabled by an early `return false` for i686-pc-windows-msvc (`FIXME(#112480) MSVC and rustc disagree on minimum stack alignment on x86 Windows`) and codegen asserted full requested alignment to LLVM. The corrected approach introduces `Target::max_reliable_alignment()` (4 bytes when `self.is_like_windows && self.arch == "x86"`, otherwise `Align::MAX`), keeps the pass enabled but ANDs the alignment mask with the reliable-alignment mask (`let max_mask = max_align.bytes() - 1;`), and clamps load/store and ABI pointee alignment with `.min(max_reliable_alignment())`. `Every target that returns less than `Align::MAX` here is still has a soundness bug.`
Preconditions: CheckAlignment is enabled via `sess.ub_checks()`; the old early return for i686-pc-windows-msvc is removed.; The target reports `max_reliable_alignment()` below `Align::MAX`; concrete rule `if self.is_like_windows && self.arch == "x86" {` then `Align::from_bytes(4).unwrap()`, covering both MSVC and GNU Windows x86 targets.; The requested/required alignment exceeds the reliable alignment (e.g. an 8-byte-aligned u64) for clamping to be observable.; For load/store codegen, `if flags.contains(MemFlags::UNALIGNED) { 1 } else { align.bytes() as c_uint };` still forces alignment 1 after the min operation.
Pitfalls: Do not describe the change as fixing MSVC; it suppresses detection of the platform's unsoundness. The source says `Every target that returns less than `Align::MAX` here is still has a soundness bug.` and the change `would detect this unsoundness.`; Do not reintroduce the early `return false` for i686-pc-windows-msvc; the pass should remain enabled with a weakened mask so that misalignment beyond the reliable alignment is still flagged.; Do not limit the mitigation to MSVC only: the condition is `is_like_windows && self.arch == "x86"`, and regression codegen tests ignore both i686-pc-windows-msvc and i686-pc-windows-gnu.; The mask must be `max_align.bytes() - 1`, not the alignment value itself.; Clamping applies to loads and stores and to ABI pointee alignment (`Some(pointee.align.min(cx.tcx().sess.target.max_reliable_alignment()));`); dropping any of these over-promises alignment.; Do not claim the compiled compiler was executed/reproduced unless actually built; the PR text describes the mitigation, and ignore annotations are regression-suite accommodations.
Test strategy: Add target-gated MIR/UB-check tests for i686 Windows x86 using a pointer with required alignment >4, verifying the emitted mask is clamped while the pass remains enabled. Add codegen tests showing load/store and function-argument alignment annotations are capped at 4 on i686 Windows, and that non-i686/non-Windows targets still receive `Align::MAX` and unchanged high-alignment annotations. Note existing `tests/codegen/align-struct.rs` and `tests/codegen/issues/issue-56927.rs` now carry `// 32bit MSVC does not align things properly so we suppress high alignment annotations (#112480)`, `//@ ignore-i686-pc-windows-msvc`, and `//@ ignore-i686-pc-windows-gnu`. A concrete validated pair: required_align=8 with addresses 4, 8, 2 and required_align=4 at address 4; the corrected mask rejects address 4 for 8-byte alignment, while the historical clamp (mask 3) accepts it. Treat these finite tests as focused examples, not proof of equivalence.
Cases: 139261-e702f960f58c2c03728dc6f5314f41beab88e47b
Source: https://github.com/rust-lang/rust/pull/139261
> FIXME(#112480) MSVC and rustc disagree on minimum stack alignment on x86 Windows
> This implements mitigation for https://github.com/rust-lang/rust/issues/112480 by stopping to emit `align` attributes on loads and function arguments when building for a win32 MSVC target.
> MSVC is known to not properly align `u64` and similar types, and claiming to LLVM that everything is properly aligned increases the chance that this will cause problems.
> // If this target does not have reliable alignment, further limit the mask by anding it with
> // the mask for the highest reliable alignment.
> let max_mask = max_align.bytes() - 1;
> if self.is_like_windows && self.arch == "x86" {
> Align::from_bytes(4).unwrap()
> Every target that returns less than `Align::MAX` here is still has a soundness bug.
> would detect this unsoundness.
> let align = align.min(self.cx().tcx.sess.target.max_reliable_alignment());
> Some(pointee.align.min(cx.tcx().sess.target.max_reliable_alignment()));
> if flags.contains(MemFlags::UNALIGNED) { 1 } else { align.bytes() as c_uint };
> // 32bit MSVC does not align things properly so we suppress high alignment annotations (#112480)
> //@ ignore-i686-pc-windows-msvc
> //@ ignore-i686-pc-windows-gnu
