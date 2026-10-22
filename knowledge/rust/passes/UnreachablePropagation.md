# UnreachablePropagation
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- Do not equate participation in codegen with needing a live coverage counter.
- Do not equate absent coverage statements with inlined coverage; non-inlined statements belong to the enclosing function.
- Do not mark a function unused when its coverage appears only through inlining into other functions.
- Do not mark never-instrumented functions unused; require function_coverage_info.
- This is a specific pass interaction, not a claim that modern rustc is generally defective.
- used_via_inlining is not equivalent to having an own counter.
- Classifying unused functions solely by all_mono_items misses functions that lost all own coverage statements.
- Functions with no coverage statements and no function_coverage_info were never instrumented and must be skipped.
- Keep the states distinct: reachable instrumented, instrumented with own statements removed, inlined-only coverage, and never instrumented.
- Checking only for a counter mapping is insufficient; inspect Code(Zero) versus Code(Counter(...)) and the (unused) marker.
- Do not overgeneralize the zero mapping to reachable instrumented functions.
- Finite fixed inputs demonstrate a concrete trigger and expected output; they do not prove general equivalence.
- Do not describe the wrong output as proof that modern rustc is generally buggy; it is a specific coverage-map regression condition.

## Patterns Not Well Handled

### UnreachablePropagation can remove all own coverage counters from an instrumented function
With coverage instrumentation enabled and MIR optimization level at least 2, UnreachablePropagation can delete every own StatementKind::Coverage counter increment from an instrumented function while that function still participates in codegen. The needed follow-on invariant is that coverage map generation must recognize this state. Source evidence states: "If a function is instrumented for coverage, but MIR opts remove *all* of its counter-increment statements (e.g. because bb0's ends with `TerminatorKind::Unreachable`), then we will codegen a function with no `llvm.instrprof.increment` intrinsics." Consequently "This causes LLVM to assume that the function wasn't instrumented, so it will disappear from the final coverage mappings," so the function must instead be emitted as unused with Code(Zero).
Preconditions: coverage instrumentation is enabled, e.g. -C instrument-coverage; UnreachablePropagation is enabled, i.e. mir_opt_level >= 2; the item is function-like and carries function_coverage_info; the body is fully unreachable, e.g. ends in TerminatorKind::Unreachable; all non-inlined coverage statements belonging to the function were removed; the function may still be in codegen mono items via a function pointer or unreachable stub
Pitfalls: Do not equate participation in codegen with needing a live coverage counter.; Do not equate absent coverage statements with inlined coverage; non-inlined statements belong to the enclosing function.; Do not mark a function unused when its coverage appears only through inlining into other functions.; Do not mark never-instrumented functions unused; require function_coverage_info.; This is a specific pass interaction, not a claim that modern rustc is generally defective.
Test strategy: Compile a coverage-instrumented test such as tests/coverage/unreachable.rs at MIR opt level 2 with two otherwise identical variants: a reachable instrumented function retaining its counter and a fully unreachable function whose own coverage statements are removed. Inspect the .cov-map: the reachable variant keeps Code(Counter(0)); the unreachable variant must become "unreachable::unreachable_intrinsic (unused)" with "Code(Zero) at (prev + 22, 1) to (start + 1, 44)".
Cases: 122860-1cca2529d1c90458080be6cf271a92eedc49d399
Source: https://github.com/rust-lang/rust/pull/122860
> If a function is instrumented for coverage, but MIR opts remove *all* of its counter-increment statements (e.g. because bb0's ends with `TerminatorKind::Unreachable`), then we will codegen a function with no `llvm.instrprof.increment` intrinsics.
> This causes LLVM to assume that the function wasn't instrumented, so it will disappear from the final coverage mappings
> removed by later MIR transforms (e.g. UnreachablePropagation).
> Coverage gets confused by MIR passes that can remove all

### Coverage unused-function classification needs own-coverage tracking separate from inlining and mono items
Coverage map generation must "Detect functions that were instrumented for coverage, but have had all their coverage statements removed by later MIR transforms (e.g. `UnreachablePropagation`)". The guarded rule is `if !saw_own_coverage && body.function_coverage_info.is_some()` followed by `missing_own_coverage.insert(def_id);`. A function is not unused merely due to all_mono_items membership; it is also unused when it does "Not participate directly in codegen (or have lost all its coverage statements)". Own coverage must be tracked separately: "Non-inlined coverage statements belong to the enclosing function."
Preconditions: the function is function-like and was instrumented, so function_coverage_info is Some; saw_own_coverage is false after MIR transforms; coverage received only through inlining is tracked separately from own coverage; the function may or may not appear in all_mono_items; never-instrumented functions are excluded from the unused classification
Pitfalls: used_via_inlining is not equivalent to having an own counter.; Classifying unused functions solely by all_mono_items misses functions that lost all own coverage statements.; Functions with no coverage statements and no function_coverage_info were never instrumented and must be skipped.; Keep the states distinct: reachable instrumented, instrumented with own statements removed, inlined-only coverage, and never instrumented.
Test strategy: Exercise four fixed CoverageUsage states: reachable instrumented with one own coverage statement; unreachable_intrinsic instrumented but with all own statements removed while still in all_mono_items; instrumented visible only through inlined coverage; and never instrumented. Assert the first uses Counter(0), the second is unused with Code(Zero), and the last two do not produce spurious unused or zero mappings.
Cases: 122860-1cca2529d1c90458080be6cf271a92eedc49d399
Source: https://github.com/rust-lang/rust/pull/122860
> Detect functions that were instrumented for coverage, but have had all their coverage statements removed by later MIR transforms (e.g. `UnreachablePropagation`)
> if !saw_own_coverage && body.function_coverage_info.is_some() {
> missing_own_coverage.insert(def_id);
> Not participate directly in codegen (or have lost all its coverage statements)
> Non-inlined coverage statements belong to the enclosing function.

### The observable invariant is Code(Zero) plus an (unused) marker versus live Code(Counter(0))
For an instrumented function whose own counter statements were removed by UnreachablePropagation, the coverage map must show an unused function with Code(Zero). The historical test evidence distinguishes exactly these outputs: "-Function name: unreachable::unreachable_intrinsic" versus "+Function name: unreachable::unreachable_intrinsic (unused)", and "-- Code(Counter(0)) at (prev + 22, 1) to (start + 1, 44)" versus "+- Code(Zero) at (prev + 22, 1) to (start + 1, 44)". A reachable instrumented function must remain Code(Counter(0)), so the zero mapping is conditional on loss of all own coverage statements rather than instrumentation alone.
Preconditions: the test is compiled with coverage instrumentation and MIR opt level 2; the observed artifact is the generated .cov-map; one variant has a reachable body retaining its own counter increment; another variant is fully unreachable so UnreachablePropagation deletes its own coverage statements; the function may still participate in codegen as a stub or function-pointer target
Pitfalls: Checking only for a counter mapping is insufficient; inspect Code(Zero) versus Code(Counter(...)) and the (unused) marker.; Do not overgeneralize the zero mapping to reachable instrumented functions.; Finite fixed inputs demonstrate a concrete trigger and expected output; they do not prove general equivalence.; Do not describe the wrong output as proof that modern rustc is generally buggy; it is a specific coverage-map regression condition.
Test strategy: Compare .cov-map output for the two reachable/unreachable variants, asserting "unreachable::unreachable_intrinsic (unused)" and "Code(Zero) at (prev + 22, 1) to (start + 1, 44)" for the unreachable variant while the reachable control keeps Code(Counter(0)). Use these as focused regression checks, not universal proof.
Cases: 122860-1cca2529d1c90458080be6cf271a92eedc49d399
Source: https://github.com/rust-lang/rust/pull/122860
> -Function name: unreachable::unreachable_intrinsic
> +Function name: unreachable::unreachable_intrinsic (unused)
> -- Code(Counter(0)) at (prev + 22, 1) to (start + 1, 44)
> +- Code(Zero) at (prev + 22, 1) to (start + 1, 44)
> This causes LLVM to assume that the function wasn't instrumented, so it will disappear from the final coverage mappings
