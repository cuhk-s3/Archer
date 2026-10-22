# RemoveNoopLandingPads
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- Do not treat `panic_strategy() == PanicStrategy::Abort` as the complete non-unwinding test, because a future non-unwinding variant is not necessarily `Abort`.
- Do not treat `panic_strategy() != PanicStrategy::Abort` as meaning “unwinds”; that mistakenly includes `ImmediateAbort`.
- Do not infer the exact strategy from `cfg(panic = "abort")`, because the supplied description says immediate-abort also sets `cfg(panic="abort")` for compatibility.
- Do not mix immediate-abort with abort/unwind crates in this setup; the supplied description notes diagnostics for incompatible dependency trees and a special core/sysroot diagnostic suggesting build-std.
- Do not describe the old code as a reproduced optimization bug under the old two-strategy world; the incorrect enablement is exposed by supplying the newly introduced `ImmediateAbort` variant.
- Do not equate “non-unwinding” with “is the `Abort` variant”; `ImmediateAbort` is a distinct non-unwinding variant.
- Do not use cfg observations to infer whether `RemoveNoopLandingPads` should be enabled, because immediate-abort sets abort-related cfg values while remaining a distinct strategy.
- Do not assume an immediate-abort panic runtime exists; the supplied description says `CStore` returns early for `PanicStrategy::ImmediateAbort`.
- Do not collapse codegen/runtime assertions about trap calls into proof about the MIR pass predicate; test the pass effect separately.

## Patterns Not Well Handled

### New non-unwinding panic strategies must not enable RemoveNoopLandingPads
RemoveNoopLandingPads decides whether it may run by asking whether the active panic strategy unwinds. The reusable invariant is that only an actually unwinding strategy should enable the pass. When a new strategy such as `ImmediateAbort` is introduced, it is non-unwinding despite being distinct from `Abort`; therefore the pass must use a semantic unwinds predicate rather than an identity comparison against `Abort`. The historical change replaced `sess.panic_strategy() != PanicStrategy::Abort` with `sess.panic_strategy().unwinds()`, whose implementation is `matches!(self, PanicStrategy::Unwind)`. This is feature-integration correctness for a new variant, not evidence that the prior two-variant code was already buggy.
Preconditions: The compiler has a distinct non-unwinding panic strategy, here `ImmediateAbort = "immediate-abort"`, in addition to `Unwind` and `Abort`.; The pass enablement predicate is expressed in terms of panic strategy and assumes every strategy other than `Abort` unwinds.; Compilation uses `-Cpanic=immediate-abort -Zunstable-options` on a nightly compiler when exercising the new strategy.; Immediate-abort is all-or-nothing for linking: the supplied description states every crate in the graph, including the sysroot, must use immediate-abort.
Pitfalls: Do not treat `panic_strategy() == PanicStrategy::Abort` as the complete non-unwinding test, because a future non-unwinding variant is not necessarily `Abort`.; Do not treat `panic_strategy() != PanicStrategy::Abort` as meaning “unwinds”; that mistakenly includes `ImmediateAbort`.; Do not infer the exact strategy from `cfg(panic = "abort")`, because the supplied description says immediate-abort also sets `cfg(panic="abort")` for compatibility.; Do not mix immediate-abort with abort/unwind crates in this setup; the supplied description notes diagnostics for incompatible dependency trees and a special core/sysroot diagnostic suggesting build-std.; Do not describe the old code as a reproduced optimization bug under the old two-strategy world; the incorrect enablement is exposed by supplying the newly introduced `ImmediateAbort` variant.
Test strategy: Use focused compile/codegen tests under `-Cpanic=immediate-abort -Zunstable-options`. For this pass, compile the same source under `panic=abort` and `panic=immediate-abort` and compare observable MIR/codegen effects for functions containing landing-pad or cleanup candidates: both non-unwinding strategies should leave `RemoveNoopLandingPads` disabled. Include the unwinding strategy as a control where the pass is enabled. Treat these concrete strategy comparisons as targeted historical evidence, not as universal proof of equivalence for all inputs.
Cases: 146317-4c1595a93b349fa755d84f8943860589c27b64f0
Source: https://github.com/rust-lang/rust/pull/146317
> In many parts of the compiler, `PanicStrategy::ImmediateAbort` behaves just like `PanicStrategy::Abort`
> so I've added a helper function so we can say `sess.panic_strategy().unwinds()`.
> pub fn unwinds(self) -> bool {
> matches!(self, PanicStrategy::Unwind)
> sess.panic_strategy() != PanicStrategy::Abort
> sess.panic_strategy().unwinds()
> ImmediateAbort = "immediate-abort",

### Distinguish panic-strategy enablement from runtime and cfg classification
For RemoveNoopLandingPads, the relevant decision is pass enablement based on whether the panic strategy unwinds. The historical evidence shows a separate helper, `unwinds()`, is the intended semantic classifier. This pattern records the qualification needed when testing the pass: the new strategy is non-unwinding, but it is not the `Abort` variant and may still advertise abort-related cfg values. Broad assumptions about panic runtime behavior or cfg values should not substitute for checking the pass's actual unwinds predicate.
Preconditions: The test or code path is concerned with whether `RemoveNoopLandingPads` runs, not with the exact panic runtime or cfg surface.; The active strategy is one of `Unwind`, `Abort`, or the newly introduced `ImmediateAbort`.; The supplied description’s codegen test checks `tail call void @llvm.trap()` and absence of calls into std panic formatting for panics, bounds checks, division, and RefCell borrow failure; these are runtime observations and should not be confused with pass enablement.
Pitfalls: Do not equate “non-unwinding” with “is the `Abort` variant”; `ImmediateAbort` is a distinct non-unwinding variant.; Do not use cfg observations to infer whether `RemoveNoopLandingPads` should be enabled, because immediate-abort sets abort-related cfg values while remaining a distinct strategy.; Do not assume an immediate-abort panic runtime exists; the supplied description says `CStore` returns early for `PanicStrategy::ImmediateAbort`.; Do not collapse codegen/runtime assertions about trap calls into proof about the MIR pass predicate; test the pass effect separately.
Test strategy: Keep tests for `RemoveNoopLandingPads` enablement focused on strategy semantics: include `Unwind` as the unwinding control and both `Abort` and `ImmediateAbort` as non-unwinding cases, checking that the pass is disabled for both non-unwinding strategies. Use codegen or runtime tests only as complementary evidence for the new strategy, not as a substitute for the pass-enablement check. Finite concrete cases provide focused historical evidence rather than universal equivalence proof.
Cases: 146317-4c1595a93b349fa755d84f8943860589c27b64f0
Source: https://github.com/rust-lang/rust/pull/146317
> In many parts of the compiler, `PanicStrategy::ImmediateAbort` behaves just like `PanicStrategy::Abort`
> so I've added a helper function so we can say `sess.panic_strategy().unwinds()`.
> pub fn unwinds(self) -> bool {
> matches!(self, PanicStrategy::Unwind)
> sess.panic_strategy() != PanicStrategy::Abort
> sess.panic_strategy().unwinds()
> // Since the ImmediateAbort strategy is new, it also sets cfg(panic="abort"), so that code
> // Immediate-aborting panics don't use a runtime.
