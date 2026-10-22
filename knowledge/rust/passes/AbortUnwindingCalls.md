# AbortUnwindingCalls
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- Do not conflate fn_can_unwind (may-unwind classification) with the removed abi_can_unwind workaround (ABI unwind flag only); the old has_ffi_unwind_calls deliberately ANDed both.
- Do not drop the extra abi_can_unwind conjunct while fn_can_unwind still over-approximates plain C, or the ffi-unwind query behavior changes independently of the pass fix.
- Do not treat a retained test name or old comment as proof that an old abort/no-abort decision is still correct; the deleted nounwind-on-stable-panic-unwind.rs explicitly documented the old behavior.
- Do not assume extern "C" and extern "C-unwind" are interchangeable in may-unwind tests; panicking asm test helpers were changed from extern "C" to extern "C-unwind".
- Several assembly/codegen tests gained `-C panic=abort` because a plain C ABI can no longer unwind; absence of that flag changes test expectations.
- panic=abort cases are not a substitute for testing panic=unwind, where the old feature-gated fallback applied.
- Do not use the Coroutine arm for CoroutineClosure: coroutines are never ZST, but an empty-field coroutine-closure aggregate is handled as ZST in GVN.
- Do not omit CoroutineClosure from def-like aggregate handling; it is a closure-like aggregate, not a state-machine coroutine.
- Do not attempt const-prop writing of CoroutineClosure values; bail out as unsupported like closures.
- Body ABI for a coroutine-closure is Abi::RustCall, unlike a coroutine body's Abi::Rust.
- Coverage must recognize AggregateKind::CoroutineClosure when collecting closure/coroutine aggregate spans.
- Do not assume every non-Closure/Coroutine type is a compiler invariant violation: ty::Error is an expected recovery type and must be handled gracefully by MIR passes.
- Do not silence the ICE by suppressing diagnostics or skipping the entire pass pipeline for erroneous crates; the narrow fix is to return only for ty::Error bodies, keeping normal ABI classification for valid bodies.
- The accompanying #[track_caller] change on DiagCtxt::span_bug only improves ICE backtraces; it is not the correctness fix for #120779.
- The author notes a check-fail UI test cannot exercise this because the ICE requires build-fail mode; absence of a regression test in the patch does not mean the bug is unverified.
- Do not claim the ICE was reproduced locally: no compiler was built for this corpus entry; evidence comes from the issue report and patch.
- Do not clobber UnwindAction::Cleanup with Terminate; doing so skips destructor execution.
- Only replace UnwindAction::Continue directly; preserve cleanup paths and terminate after they run.
- UnwindResume inside cleanup blocks must be handled even though cleanup blocks are otherwise skipped.
- A direct terminate(abi) on the call differs semantically from routing through a cleanup block that finally terminates; the latter permits drops.
- Changing this behavior affects existing run-make tests that assumed destructors were skipped across non-unwinding FFI frames.
- Do not blanket-disable landing pads/cleanup for all wasm: the fix checks panic=unwind and the exception-handling target feature so experimentation and Emscripten/WASI differences remain expressible.
- Do not conflate body_can_unwind (function ABI) with target_supports_unwinding (target capability); the bug arose because only the former was consulted.
- UnwindResume on a non-unwinding target must become Unreachable, not UnwindTerminate; the corrected branch tests `!target_supports_unwinding` before `!body_can_unwind`.
- When `!call_can_unwind || !target_supports_unwinding`, the cleanup is replaced with UnwindAction::Unreachable; retaining the landing pad is the historically incorrect behavior.
- A retained test name or old comment does not prove the fixed output; compare the actual revision-specific CHECK/NOT lines. The wasm default now expects `call` rather than `invoke` and no EH instructions.

## Patterns Not Well Handled

### Plain C-family ABI is nounwind; only *-unwind ABIs may propagate unwinding
AbortUnwindingCalls consumes layout::fn_can_unwind for both the function body ABI and call-site ABIs. Historically, while c_unwind was feature-gated, the helper used an over-approximating fallback equivalent to `unwind || (!tcx.features().c_unwind && tcx.sess.panic_strategy() == PanicStrategy::Unwind)`, so on stable panic=unwind a plain extern "C" boundary was classified may-unwind and its unwind edge was left intact. The corrected invariant is that plain C-family ABIs (C, System, Cdecl, Stdcall, Fastcall, Vectorcall, Thiscall, Aapcs, Win64, SysV64) are nounwind and unwinds crossing them must terminate/abort, while extern "C-unwind" and other *-unwind ABIs remain may-unwind and must not be forcibly aborted. The historical workaround `abi_can_unwind` in has_ffi_unwind_calls was removed once the helper stopped over-approximating.
Preconditions: The callee or body ABI is a C-family ABI; only the ABI `unwind` flag distinguishes plain from *-unwind.; The observable historical behavior requires `panic=unwind`; `panic=abort` does not exercise the removed feature-gated fallback.; The historical incorrect behavior required the `c_unwind` feature to be disabled (stable mode).; The function body or call can actually unwind, for example by panicking or resuming an unwind.; AbortUnwindingCalls uses fn_can_unwind for both body ABI and call-site ABI decisions.
Pitfalls: Do not conflate fn_can_unwind (may-unwind classification) with the removed abi_can_unwind workaround (ABI unwind flag only); the old has_ffi_unwind_calls deliberately ANDed both.; Do not drop the extra abi_can_unwind conjunct while fn_can_unwind still over-approximates plain C, or the ffi-unwind query behavior changes independently of the pass fix.; Do not treat a retained test name or old comment as proof that an old abort/no-abort decision is still correct; the deleted nounwind-on-stable-panic-unwind.rs explicitly documented the old behavior.; Do not assume extern "C" and extern "C-unwind" are interchangeable in may-unwind tests; panicking asm test helpers were changed from extern "C" to extern "C-unwind".; Several assembly/codegen tests gained `-C panic=abort` because a plain C ABI can no longer unwind; absence of that flag changes test expectations.; panic=abort cases are not a substitute for testing panic=unwind, where the old feature-gated fallback applied.
Test strategy: Construct otherwise identical programs differing only in the ABI suffix on a panicking Rust function and/or imported panicking callee, compiled with `-C panic=unwind`. For plain C, verify the unwind is terminated/aborted at the boundary by inspecting MIR unwind actions and/or generated LLVM `nounwind` attributes; for C-unwind, verify the panic can propagate. Compile the plain-C case with `-C panic=abort` as a control. Use codegen tests under tests/codegen/unwind-abis checking LLVM attributes plus run/UI tests such as tests/ui/panics/panic-in-ffi.rs, and update may-unwind tests to use extern "C-unwind" for functions that must unwind.
Cases: 116088-bb2716effde9713efad15c269b35779a79c90271
Source: https://github.com/rust-lang/rust/pull/116088
> (accepted, c_unwind, "CURRENT_RUSTC_VERSION", Some(74990)),
> /// Allows `extern "C-unwind" fn` to enable unwinding across ABI boundaries and treat `extern "C" fn` as nounwind.
> -    /// Treat `extern "C"` function as nounwind.
> -    (unstable, c_unwind, "1.52.0", Some(74990)),
> Historically functions declared with `extern "C"` were marked at the
> | SysV64 { unwind } => unwind,
> | SysV64 { unwind } => unwind,
> -            unwind
> -                || (!tcx.features().c_unwind && tcx.sess.panic_strategy() == PanicStrategy::Unwind)
> -/// Some of the functions declared as "may unwind" by `fn_can_unwind` can't actually unwind. In
> -        if layout::fn_can_unwind(tcx, fn_def_id, sig.abi()) && abi_can_unwind(sig.abi()) {
> +        if layout::fn_can_unwind(tcx, fn_def_id, sig.abi()) {
> -extern "C" fn panicky() {
> +extern "C-unwind" fn panicky() {
> +extern "C-unwind" {
> -// Note that this test will get removed when `C-unwind` is fully stabilized

### CoroutineClosure bodies and aggregates use closure policy: Abi::RustCall, ZST handling, and const-prop bailout
A newly introduced coroutine-closure is closure-like, not coroutine-like. For AbortUnwindingCalls the body ABI must be `ty::CoroutineClosure(..) => Abi::RustCall`, matching closures, not `Abi::Rust` as for coroutines. The same audit applies across MIR policies: GVN treats an empty-field CoroutineClosure aggregate as ZST and as a def-like aggregate, RemoveZsts considers it possibly ZST, DataflowConstProp bails out as unsupported, and InstrumentCoverage recognizes its aggregate. Routing CoroutineClosure through the adjacent Coroutine policy is the incorrect counterfactual: it would flip all of those decisions, including using Abi::Rust for the body.
Preconditions: The program uses an async closure, producing TyKind::CoroutineClosure and AggregateKind::CoroutineClosure.; MIR optimization, coverage, or abort-unwinding analysis runs over that coroutine-closure body or aggregate.; Tests should distinguish zero-upvar coroutine closures from coroutines, since coroutines are never ZST but a zero-field coroutine-closure aggregate is handled as ZST by GVN.
Pitfalls: Do not use the Coroutine arm for CoroutineClosure: coroutines are never ZST, but an empty-field coroutine-closure aggregate is handled as ZST in GVN.; Do not omit CoroutineClosure from def-like aggregate handling; it is a closure-like aggregate, not a state-machine coroutine.; Do not attempt const-prop writing of CoroutineClosure values; bail out as unsupported like closures.; Body ABI for a coroutine-closure is Abi::RustCall, unlike a coroutine body's Abi::Rust.; Coverage must recognize AggregateKind::CoroutineClosure when collecting closure/coroutine aggregate spans.
Test strategy: Build MIR-focused tests for async closures with and without captures, then compare MIR after GVN/RemoveZsts: the empty-field AggregateKind::CoroutineClosure should follow the closure ZST path and be keyed as a def-like aggregate. Add compile/MIR checks for const-prop, abort-unwinding, and coverage paths with an async closure so the CoroutineClosure variant is exercised rather than only Closure/Coroutine. Inspect emitted MIR and diagnostics rather than requiring execution claims.
Cases: 120361-ed7fca1f8805b4348b801f23f444e0dda42f7aed
Source: https://github.com/rust-lang/rust/pull/120361
> | AggregateKind::CoroutineClosure(did, substs)
> | AggregateKind::CoroutineClosure(..) => true,
> // Coroutines are never ZST, as they at least contain the implicit states.
> | ty::CoroutineClosure(..)
> | ty::Dynamic(..) => throw_machine_stop_str!("unsupported type"),
> ty::CoroutineClosure(..) => Abi::RustCall,
> AggregateKind::CoroutineClosure(..)

### ty::Error body types must make AbortUnwindingCalls return early instead of ICE
AbortUnwindingCalls classifies the body type to choose the body ABI: Closure and CoroutineClosure use Abi::RustCall, Coroutine uses Abi::Rust, and a catch-all previously executed `span_bug!(body.span, "unexpected body ty: {:?}", body_ty)`. When earlier compilation errors produced `ty::Error(_)`, that catch-all caused an internal compiler error. The fix adds `ty::Error(_) => return,` so the pass no-ops on the erroneous body and lets the already-emitted diagnostics be reported. Valid closure, coroutine-closure, and coroutine bodies must still map to their Abi variants and continue through fn_can_unwind.
Preconditions: The crate already has earlier errors so a body's type is ty::Error(_); the issue reproduction uses the malformed guard `1..=2 if false =|value_ref, item| 1,`.; Compilation proceeds in build-fail/default mode so MIR transformation passes still run despite the errors; the ICE only reproduces in build-fail.; The erroneous body reaches AbortUnwindingCalls::run_pass, whose ABI classification match does not explicitly handle ty::Error.; After the fix, the pass must return without running any unwinding-abort rewrite on that error-typed body.
Pitfalls: Do not assume every non-Closure/Coroutine type is a compiler invariant violation: ty::Error is an expected recovery type and must be handled gracefully by MIR passes.; Do not silence the ICE by suppressing diagnostics or skipping the entire pass pipeline for erroneous crates; the narrow fix is to return only for ty::Error bodies, keeping normal ABI classification for valid bodies.; The accompanying #[track_caller] change on DiagCtxt::span_bug only improves ICE backtraces; it is not the correctness fix for #120779.; The author notes a check-fail UI test cannot exercise this because the ICE requires build-fail mode; absence of a regression test in the patch does not mean the bug is unverified.; Do not claim the ICE was reproduced locally: no compiler was built for this corpus entry; evidence comes from the issue report and patch.
Test strategy: Construct a build-fail/default compiletest case containing ordinary errors plus a malformed closure/guard that makes a closure body's type ty::Error; assert the compiler emits only the expected user-facing diagnostics and does not emit `unexpected body ty` or an internal compiler error. Because check-fail UI tests cannot reproduce this build-fail-only path, use a run-make or equivalent build-fail test. Additionally retain coverage that valid closure/coroutine-closure/coroutine bodies still select the expected Abi variants and still pass through fn_can_unwind.
Cases: 120782-7dc182d5d405a08ecdb4d652e10c6b6f183d61e7
Source: https://github.com/rust-lang/rust/pull/120782
> Fix mir pass ICE in the presence of other errors
> fixes #120779
> it is impossible to add a ui test for this, because it only reproduces in build-fail, but a test that also has errors in check-fail mode can't be made build-fail
> ty::Error(_) => return,
> _ => span_bug!(body.span, "unexpected body ty: {:?}", body_ty),
> ice: `unexpected body ty: {type error}`
> unexpected body ty: {type error}
> #0 [mir_drops_elaborated_and_const_checked] elaborating drops for `range_shadow_lit::{closure#0}`
> 1..=2 if false =|value_ref, item| 1,

### Preserve UnwindAction::Cleanup on non-unwinding frames and terminate only after cleanup runs
For a non-unwinding body such as extern "C", AbortUnwindingCalls must not replace a call's UnwindAction::Cleanup with Terminate, because that bypasses the landing pad and skips destructors on the frame. The corrected pass only directly replaces UnwindAction::Continue; it preserves Cleanup so destructors run, and separately replaces an UnwindResume terminator inside all blocks, including cleanup blocks, with UnwindTerminate(Abi) so termination happens after cleanup. Historically, an `else if !body_can_unwind` rewrite turned every unwinding call's action into Terminate, clobbering Cleanup, while cleanup blocks were skipped by `if block.is_cleanup { continue; }`, leaving UnwindResume unconverted.
Preconditions: The enclosing function ABI cannot unwind, such as extern "C" rather than extern "C-unwind".; A call inside that function may unwind and has a cleanup action because a live local requires Drop.; The cleanup path ends in UnwindResume, which must become UnwindTerminate(Abi) after cleanup.; Cleanup blocks must be inspected before the `if block.is_cleanup { continue; }` guard.
Pitfalls: Do not clobber UnwindAction::Cleanup with Terminate; doing so skips destructor execution.; Only replace UnwindAction::Continue directly; preserve cleanup paths and terminate after they run.; UnwindResume inside cleanup blocks must be handled even though cleanup blocks are otherwise skipped.; A direct terminate(abi) on the call differs semantically from routing through a cleanup block that finally terminates; the latter permits drops.; Changing this behavior affects existing run-make tests that assumed destructors were skipped across non-unwinding FFI frames.
Test strategy: Use a mir-opt test with `// EMIT_MIR ... AbortUnwindingCalls.after.mir` and CHECK patterns asserting that a drop call has `unwind: [[unwind:bb.*]]`, that the target block is `(cleanup)`, and that it ends with `terminate(abi)`. Add an extern "C" function holding a Drop value that panics, and a UI run test with `//@ needs-unwind` plus `//@ error-pattern: Noisy Drop` to verify destructor output is emitted before abort. Also update asm MAY_UNWIND expectations to route through a cleanup block ending in terminate(abi). No compiler was built and no execution/reproduction is claimed.
Cases: 129582-bb531083cc0301d2152dc59746eb30472564948d
Source: https://github.com/rust-lang/rust/pull/129582
> Make destructors on `extern "C"` frames to be executed
> // If we see an `UnwindResume` terminator inside a function that cannot unwind, we need
> // to replace it with `UnwindTerminate`.
> } else if !body_can_unwind
> && matches!(terminator.unwind(), Some(UnwindAction::Continue))
> // is replaced with terminate. For those with `UnwindAction::Cleanup`,
> // cleanup will still happen, and terminate will happen afterwards handled by
> // the `UnwindResume` -> `UnwindTerminate` terminator replacement.
> *cleanup = UnwindAction::Terminate(UnwindTerminateReason::Abi);
> terminator.kind = TerminatorKind::UnwindTerminate(UnwindTerminateReason::Abi);
> // CHECK: drop
> // CHECK-SAME: unwind: [[unwind:bb.*]]]
> // CHECK: [[unwind]] (cleanup)
> // CHECK-NEXT: terminate(abi)
> //@ error-pattern: Noisy Drop
> let _val = Noise;

### Suppress unwind landing pads and UnwindResume on targets that cannot unwind (wasm panic=abort without exception-handling)
AbortUnwindingCalls must consider target capability in addition to function and callee ABI. When `target_supports_unwinding` is false, defined as wasm-like target with PanicStrategy::Abort and no `exception-handling` target feature, the pass rewrites UnwindResume to TerminatorKind::Unreachable and forces a call's unwind action to UnwindAction::Unreachable using `if !call_can_unwind || !target_supports_unwinding`. Historically the pass only consulted body_can_unwind and call_can_unwind, so on wasm panic=abort without EH it kept cleanup landing pads for C-unwind calls and rewrote UnwindResume to UnwindTerminate rather than Unreachable, causing LLVM to emit unsupported EH instructions such as `catch_call`. Non-wasm targets and wasm with exception-handling must retain normal unwind machinery.
Preconditions: Target is_like_wasm.; panic_strategy() == PanicStrategy::Abort.; asm_target_features(def_id) does NOT contain sym::exception_handling (the exception-handling target feature is disabled).; The function body contains a call whose call_can_unwind is true, e.g. through a C-unwind ABI, or an UnwindResume terminator.; The pass must not have already returned early, e.g. due to panic strategy/AHB handling in the surrounding pass.
Pitfalls: Do not blanket-disable landing pads/cleanup for all wasm: the fix checks panic=unwind and the exception-handling target feature so experimentation and Emscripten/WASI differences remain expressible.; Do not conflate body_can_unwind (function ABI) with target_supports_unwinding (target capability); the bug arose because only the former was consulted.; UnwindResume on a non-unwinding target must become Unreachable, not UnwindTerminate; the corrected branch tests `!target_supports_unwinding` before `!body_can_unwind`.; When `!call_can_unwind || !target_supports_unwinding`, the cleanup is replaced with UnwindAction::Unreachable; retaining the landing pad is the historically incorrect behavior.; A retained test name or old comment does not prove the fixed output; compare the actual revision-specific CHECK/NOT lines. The wasm default now expects `call` rather than `invoke` and no EH instructions.
Test strategy: Use codegen-llvm tests with explicit revisions: NONWASM with ignore-wasm32, WASM with only-wasm32 (default, no EH feature), and WASMEXN with only-wasm32 plus `-Ctarget-feature=+exception-handling`. For default wasm assert absence of EH constructs: `WASM-NOT: call void @{{.*core9panicking19panic_cannot_unwind}}`, `WASM-NOT: invoke void @may_panic()`, `WASM-NOT: catchswitch`, `WASM-NOT: catchpad`, `WASM-NOT: catchret`, and presence of `WASM: call void @may_panic()`. For WASMEXN assert invoke, cleanuppad/catchswitch/catchpad/catchret, and the __gxx_wasm_personality_v0 attribute, matching native behavior. Keep non-wasm checks for the panic_cannot_unwind call. The WASMEXN intrinsic test uses the raw llvm.wasm.throw intrinsic via link_llvm_intrinsics because libstd's builtin was compiled with `-Cpanic=abort`, and is gated `#[cfg(wasmexn)]`.
Cases: 146457-88d7d20122e45f4167e262e6eda03fbf5383fb18
Source: https://github.com/rust-lang/rust/pull/146457
> and if that's `false` then terminators are all adjusted to be unreachable/not present.
> Currently this is only true for wasm targets on panic=abort when the
> `exception-handling` target feature is disabled. In such a
> if !target_supports_unwinding {
> terminator.kind = TerminatorKind::Unreachable;
> if !call_can_unwind || !target_supports_unwinding {
> If this function call can't unwind, or if the target doesn't
> This is causing failure to run on Wasmtime in some cases
> `catch_call` is emitted for `gzgetc_fn()` when opt-level < 2.
> // WASM-NOT: catchswitch
> // WASM-NOT: catchpad
> // WASM-NOT: catchret
> // WASM: call void @may_panic()
> // WASMEXN: invoke void @may_panic()
> If `+exception-handling` is enabled, however, then Rust codegen will look like native platforms where exceptions are caught and the program aborts.
