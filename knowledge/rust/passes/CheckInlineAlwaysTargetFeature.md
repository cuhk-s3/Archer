# CheckInlineAlwaysTargetFeature
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- Do not remove the old error while continuing to emit alwaysinline on the callee definition; the supplied rationale warns that this "will always inline regardless of matching target features, which can result in errors from LLVM."
- Do not assume an absent warning means an indirect call is safe; the pass only checks statically known `FnDef` callees.
- Both the MIR lint and codegen invoke the safety check at separate sites with differently ordered operands, so test both the emitted warning and the actual callsite attribute rather than only one side.
- The inline-attribute helper must still preserve the invariant quoted as "`optnone` requires `noinline`"; `OptimizeAttr::DoNotOptimize` must map to `InlineAttr::Never` and `requires_inline` must still produce a hint.
- Omitting session-level features from the caller's effective set can produce false mismatch warnings even when the compilation target supplies the feature.
- Treating implied features as explicitly caller-declared can change diagnostic meaning or filtering behavior.
- The `callee_only` list must remain meaningful after implied callee features are filtered out; test the note and suggestion when filtering removes entries.
- A subset match is still a mismatch: a caller that supplies only some required features must warn about the remaining ones rather than being considered fully safe.
- Do not silently omit always-inline after a mismatch; the pass is expected to warn so users understand why inlining cannot occur.
- Do not replace the feature gate with silent acceptance; without the feature the combination remains `error[E0658]: cannot use `#[inline(always)]` with `#[target_feature]``.
- The warning must correspond to the actual callsite safety result, not merely to the presence of target features on the callee.
- Do not infer safety from the absence of a warning for indirect calls that the pass cannot inspect.

## Patterns Not Well Handled

### Defer always-inline from target-feature definitions to safe callsites
For CheckInlineAlwaysTargetFeature, enabling the feature must not merely delete the historical hard error. The pass moves the always-inline attribute away from an `#[inline(always)]` callee definition when that callee also has user-defined `#[target_feature]` entries. It examines direct calls represented as `TerminatorKind::Call` or `TerminatorKind::TailCall` whose callee is a statically known `FnDef`, and places the inline attribute at the callsite only when the call is safe with respect to effective target features. On a mismatch it omits the attribute. The supplied rationale is: "Rather than adding the inline always attribute to the function definition, we add it to the callsite."
Preconditions: The crate enables `#![feature(target_feature_inline_always)]`; otherwise the historical combination remains a feature-gate error.; The callee is a `FnDef` with codegen attributes, `inline == InlineAttr::Always`, and a non-empty target-feature list.; The call is a MIR `TerminatorKind::Call` or `TerminatorKind::TailCall`, not an indirect call.; The function has user-defined target features, so the inline attribute must be deferred from the definition to the callsite.
Pitfalls: Do not remove the old error while continuing to emit alwaysinline on the callee definition; the supplied rationale warns that this "will always inline regardless of matching target features, which can result in errors from LLVM."; Do not assume an absent warning means an indirect call is safe; the pass only checks statically known `FnDef` callees.; Both the MIR lint and codegen invoke the safety check at separate sites with differently ordered operands, so test both the emitted warning and the actual callsite attribute rather than only one side.; The inline-attribute helper must still preserve the invariant quoted as "`optnone` requires `noinline`"; `OptimizeAttr::DoNotOptimize` must map to `InlineAttr::Never` and `requires_inline` must still produce a hint.
Test strategy: Use paired direct-call UI cases on a target with a real feature set, following the supplied test shape with `//@[aarch64] compile-flags: --target aarch64-unknown-linux-gnu`, `//@[aarch64] needs-llvm-components: aarch64`, `//@ add-core-stubs`, `//@ build-pass`, and `--crate-type=lib`. Vary only the caller's `#[target_feature]` declaration: a caller without features calling an alwaysinline callee requiring features must warn and must not receive a misleading definition-level attribute; a caller with all required or session-implied features must not warn. Also inspect codegen behavior for the callsite attribute separately from the callee definition. The supplied material notes that no compiler was built, so these are test-design recommendations rather than executed results.
Cases: 145932-bcfc9b5073a92bbb4b1e4db2eab535357d8973ad
Source: https://github.com/rust-lang/rust/pull/145932
> Rather than adding the inline always attribute to the function definition, we add it to the callsite.
> will always inline regardless of matching target features, which can result in errors from LLVM.
> // Apply function attributes as per usual if there are no user defined
> // this and not add the attribute to prevent soundness issues.
> TerminatorKind::Call { func, .. } | TerminatorKind::TailCall { func, .. }
> `optnone` requires `noinline`

### Use the caller's full effective feature set, including implied session features
Safety checking for an always-inline target-feature call must compare all features required by the callee with the caller's effective feature set. That set includes the caller's explicit `#[target_feature]` entries plus the compilation target's session-level target features, with the latter treated as `TargetFeatureKind::Implied`. For diagnostics, implied callee features are filtered out when constructing the `callee_only` list. The supplied source describes scanning "the users defined target features and ensure they" are covered by the caller's effective set.
Preconditions: The caller has an effective feature set assembled from explicit target features and `tcx.sess.target_features`.; Session-provided target features are marked as implied, not as explicit caller requirements.; The callee's required features are known and non-empty.; Diagnostic construction may need to filter implied callee features before listing missing features.
Pitfalls: Omitting session-level features from the caller's effective set can produce false mismatch warnings even when the compilation target supplies the feature.; Treating implied features as explicitly caller-declared can change diagnostic meaning or filtering behavior.; The `callee_only` list must remain meaningful after implied callee features are filtered out; test the note and suggestion when filtering removes entries.; A subset match is still a mismatch: a caller that supplies only some required features must warn about the remaining ones rather than being considered fully safe.
Test strategy: Construct callers that differ only in target-feature declarations. Include a caller with all callee-required features, a caller with a strict subset so that only the remaining features are reported, and a caller relying on target/session-implied features. Use a target such as aarch64 with features like `neon`, `fp16`, `sve`, `rdm`, and `fhm`, and check both the presence/absence of the warning and that the diagnostic's listed missing features remain correct after implied-feature filtering.
Cases: 145932-bcfc9b5073a92bbb4b1e4db2eab535357d8973ad
Source: https://github.com/rust-lang/rust/pull/145932
> // Scan the users defined target features and ensure they
> lacks the corresponding target feature can lead to unsound behavior.
> // Apply function attributes as per usual if there are no user defined
> `optnone` requires `noinline`

### Report mismatches and keep the feature gate explicit
When a direct call cannot be safely inlined because the caller lacks required target features, CheckInlineAlwaysTargetFeature emits the `INLINE_ALWAYS_MISMATCHING_TARGET_FEATURES` warning instead of silently dropping the attribute. The supplied text states: "If the function isn't inlined due to a mismatch, we emit a warning informing the user that the function can't be inlined due to the target feature mismatch." Separately, without the unstable feature the old combination must still be rejected with E0658; the supplied gate entry is `(unstable, target_feature_inline_always, "CURRENT_RUSTC_VERSION", Some(145574))`.
Preconditions: The crate either enables `target_feature_inline_always` or expects the legacy feature-gate rejection.; The callee is an `#[inline(always)]` function with non-empty `#[target_feature]`.; The caller's effective features do not cover all of the callee's required features.; The call is statically known enough for the MIR check to inspect it.
Pitfalls: Do not silently omit always-inline after a mismatch; the pass is expected to warn so users understand why inlining cannot occur.; Do not replace the feature gate with silent acceptance; without the feature the combination remains `error[E0658]: cannot use `#[inline(always)]` with `#[target_feature]``.; The warning must correspond to the actual callsite safety result, not merely to the presence of target features on the callee.; Do not infer safety from the absence of a warning for indirect calls that the pass cannot inspect.
Test strategy: Add a negative feature-gate UI test without the feature attribute and expect E0658. Add warning UI tests where a caller missing some or all callee features calls an always-inline target-feature callee and expect `inline_always_mismatching_target_features`, including a subset case where only the remaining feature is reported. Include a matching or target-implied caller that produces no such warning. These are test-design recommendations based on the supplied description, not executed proof of equivalence.
Cases: 145932-bcfc9b5073a92bbb4b1e4db2eab535357d8973ad
Source: https://github.com/rust-lang/rust/pull/145932
> If the function isn't inlined due to a mismatch, we emit a warning informing the user that the function can't be inlined due to the target feature mismatch.
> (unstable, target_feature_inline_always, "CURRENT_RUSTC_VERSION", Some(145574))
> //~^ WARNING call to `#[inline(always)]`-annotated `target_feature_identity` requires the same target features to be inlined [inline_always_mismatching_target_features]
> error[E0658]: cannot use `#[inline(always)]` with `#[target_feature]`
> cannot use `#[inline(always)]` with `#[target_feature]`
