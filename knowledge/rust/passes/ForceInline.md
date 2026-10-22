# ForceInline
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- Recording only the top-level FnDef from a Call terminator loses callee edges represented as function arguments.
- Cycle avoidance must inspect the function operand in call_args[2] for const_eval_select; otherwise recursive calls can be missed and query evaluation can cycle.
- Do not assume the direct call target is the only relevant callee.
- The patch only follows the third argument (args[2]), matching the test's runtime-function position.
- Equating sanitizer compatibility with equality of the disabled-sanitizer set alone; realtime mode is a separate setting that changes instrumentation context.
- Assuming the default Caller mode is the same as an explicit realtime = "caller"; both are the semantic default for the attribute comparison, but a missing attribute must not be confused with a missing disabled set.
- Checking only the function on which the attribute is written and ignoring sanitizer-setting inheritance from enclosing defs.
- Treating the async-only rtsan_nonblocking_async lint as evidence about inlining legality; it is a separate diagnostic about executor behavior.
- Testing only whether no_sanitize is empty; this misses a setting where only rtsan_setting is non-default.
- Checking the disabled-sanitizer set instead of the complete SanitizerFnAttrs means the realtime mode alone does not trigger the force-inline warning.
- Ignoring sanitizer-setting inheritance from an enclosing item.
- Confusing malformed realtime values, which should produce E0539 with the allowed values nonblocking, blocking, and caller, with a valid non-default setting.

## Patterns Not Well Handled

### Follow function operands hidden in intrinsic arguments when collecting inliner callees
For inliner cycle-avoidance callee collection, a Call terminator may directly target the const_eval_select intrinsic while the actual user function is supplied as a function argument. The callee set must expose the FnDef operand at call_args[2]; otherwise recursive edges hidden inside const_eval_select((), g, g) are omitted, mutual recursion can be missed, and query evaluation can cycle. This is a callee-discovery invariant for force-inline/inliner processing: do not assume the direct call target is the only relevant callee.
Preconditions: The MIR body contains a TerminatorKind::Call terminator.; The direct callee operand has type ty::FnDef.; tcx.is_intrinsic(*def_id, sym::const_eval_select) is true for the direct callee.; Index call_args[2] is a function operand whose type is also a ty::FnDef.; Recursion may be hidden across the function arguments of const_eval_select rather than being visible as the direct call target.
Pitfalls: Recording only the top-level FnDef from a Call terminator loses callee edges represented as function arguments.; Cycle avoidance must inspect the function operand in call_args[2] for const_eval_select; otherwise recursive calls can be missed and query evaluation can cycle.; Do not assume the direct call target is the only relevant callee.; The patch only follows the third argument (args[2]), matching the test's runtime-function position.
Test strategy: Add a compile-only build-pass UI regression test compiled with -O --crate-type=lib, enabling the core_intrinsics and const_eval_select features, and defining mutually recursive #[inline] pub const fn f() and g() that call const_eval_select((), g, g) and const_eval_select((), f, f) respectively. Compare callee-query behavior when call_args[2] is followed versus when only the direct intrinsic target is recorded; the check is compile-time and does not require executing the compiled code.
Cases: 123444-b0b7c860e13858cbc344dcf2baf860752e3a2dd3
Source: https://github.com/rust-lang/rust/pull/123444
> Teach MIR inliner query cycle avoidance about const_eval_select
> Fixes https://github.com/rust-lang/rust/issues/122659
> if let TerminatorKind::Call { func, args: call_args, .. } = &terminator.kind {
> let call = if tcx.is_intrinsic(*def_id, sym::const_eval_select) {
> let func = &call_args[2].node;
> const_eval_select((), g, g)
> const_eval_select((), f, f)
> //@ build-pass
> //@ compile-flags: -O --crate-type=lib

### Compare complete sanitizer function attributes when deciding inline compatibility
The inline compatibility gate must compare the caller's and callee's full SanitizerFnAttrs, including both the disabled-sanitizer set and the realtime setting, rather than only the disabled-sanitizer subset. A caller and callee may have identical disabled bits but different rtsan_setting values (Nonblocking, Blocking, or default Caller); treating those as compatible permits inlining across a runtime sanitizer context boundary and loses that boundary. The corrected check is the full-attributes comparison, with an inlining rejection such as the existing incompatible-sanitizer error when they differ.
Preconditions: Sanitizer instrumentation decisions are function-granular, as stated in the sanitizer documentation.; The callee and caller are otherwise eligible for MIR inlining.; The realtime setting can be Nonblocking, Blocking, or the default Caller.; The inliner's attribute check is reached before the call is inlined.; The caller and callee have equal disabled-sanitizer bit sets but differ in rtsan_setting, or otherwise differ in complete SanitizerFnAttrs.
Pitfalls: Equating sanitizer compatibility with equality of the disabled-sanitizer set alone; realtime mode is a separate setting that changes instrumentation context.; Assuming the default Caller mode is the same as an explicit realtime = "caller"; both are the semantic default for the attribute comparison, but a missing attribute must not be confused with a missing disabled set.; Checking only the function on which the attribute is written and ignoring sanitizer-setting inheritance from enclosing defs.; Treating the async-only rtsan_nonblocking_async lint as evidence about inlining legality; it is a separate diagnostic about executor behavior.
Test strategy: Use compile-time UI tests rather than claiming sanitizer execution. Construct two programs differing only in the callee's #[sanitize(realtime = ...)] value with the same disabled set, place the caller in another realtime mode, and verify the inliner refuses the cross-setting inline (for example by inspecting optimized MIR or resulting codegen/symbol structure) while allowing the equal-setting case. Include cases with non-empty disabled sets and matching or differing realtime modes. Runtime rtsan tests require //@ needs-sanitizer-realtime, -Z sanitizer=realtime, and RTSAN_OPTIONS=abort_on_error=0, but they are integration checks, not evidence that this patch was executed here.
Cases: 147935-9d671a89295af277886b8e3717883c5184452141
Source: https://github.com/rust-lang/rust/pull/147935
> if callee_attrs.no_sanitize != codegen_fn_attrs.no_sanitize {
> +    if callee_attrs.sanitizers != codegen_fn_attrs.sanitizers {
> return Err("incompatible sanitizer set");
> +pub struct SanitizerFnAttrs {
> +    pub rtsan_setting: RtsanSetting,
> +pub enum RtsanSetting {
> function granularity.
> function again the program will get sanitized.

### Warn for force-inlined functions with any non-default sanitize setting
For an #[inline(always)] function, the force-inline effectiveness warning must fire whenever the complete sanitizer attributes differ from the default, not merely when the disabled-sanitizer set is non-empty. In particular, a non-default realtime mode such as realtime = "nonblocking" is sufficient to make the sanitize setting ineffective after inlining, producing the widened warning text about a non-default sanitize having no effect after inlining.
Preconditions: The function requests #[inline(always)].; The function has a non-default sanitize setting, potentially only a non-default realtime mode.; The inline(always) diagnostic path is reached.
Pitfalls: Testing only whether no_sanitize is empty; this misses a setting where only rtsan_setting is non-default.; Checking the disabled-sanitizer set instead of the complete SanitizerFnAttrs means the realtime mode alone does not trigger the force-inline warning.; Ignoring sanitizer-setting inheritance from an enclosing item.; Confusing malformed realtime values, which should produce E0539 with the allowed values nonblocking, blocking, and caller, with a valid non-default setting.
Test strategy: Add a focused inline(always) UI test where the only non-default attribute is realtime = "nonblocking" and assert the widened warning text "non-default `sanitize` will have no effect after inlining". Also test malformed realtime values (on, off) produce E0539 listing nonblocking, blocking, and caller, and test attribute inheritance; these are compile-time checks rather than runtime sanitizer execution.
Cases: 147935-9d671a89295af277886b8e3717883c5184452141
Source: https://github.com/rust-lang/rust/pull/147935
> -    if !codegen_fn_attrs.no_sanitize.is_empty()
> +    if codegen_fn_attrs.sanitizers != SanitizerFnAttrs::default()
> lint.primary_message("non-default `sanitize` will have no effect after inlining");
> //~^ WARN non-default `sanitize` will have no effect after inlining
> +pub struct SanitizerFnAttrs {
> +    pub rtsan_setting: RtsanSetting,
> +pub enum RtsanSetting {
