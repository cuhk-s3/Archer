# RemoveZsts
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- Do not use the `Coroutine` arm for `CoroutineClosure`: coroutines are never ZST, but an empty-field coroutine-closure aggregate follows the closure ZST path.
- Do not omit `CoroutineClosure` from `AggregateTy::Def`-style def-like aggregate key handling; it is a closure aggregate, not a state-machine coroutine.
- Do not assume the zero-field case generalizes to captured-upvar async closures; the precondition is specifically zero fields, and captured upvars are separate inputs to test.
- Do not attempt const-prop writing of `CoroutineClosure` values; bail out as unsupported like closures.
- Do not assign `Abi::Rust` to a coroutine-closure body; it is callable and uses `Abi::RustCall`.
- Do not conflate the unsupported-type bailout with a claim about user-visible codegen; this is a MIR policy split.
- Do not recognize only `AggregateKind::Closure` and `AggregateKind::Coroutine`; the coroutine-closure aggregate variant is a distinct kind.
- Do not describe this as ordinary closure coverage behavior without noting the distinct `CoroutineClosure` aggregate input.

## Patterns Not Well Handled

### CoroutineClosure is closure-like, not coroutine-like, for MIR ZST and aggregate classification
When a closure-like `TyKind::CoroutineClosure` / `AggregateKind::CoroutineClosure` is introduced, every MIR pass that branches between `Closure` and `Coroutine` must place the new variant on the `Closure` side. GVN treats `Array`, `Tuple`, and `Closure` aggregates with no fields as ZST and maps `Closure`/`Coroutine` to `AggregateTy::Def`; RemoveZsts classifies `Adt`, `Array`, `Closure`, `Tuple` and opaque aliases as possibly ZST. The supplied description states the counterfactual (not claimed as reproduced): routing the new type through the adjacent `Coroutine` policy would make GVN refuse to treat an empty-field coroutine-closure aggregate as ZST and omit it from the def-like aggregate key, and RemoveZsts would not consider it possibly ZST. The rationale is captured by the comment `// Coroutines are never ZST, as they at least contain the implicit states.`, whereas a zero-field coroutine-closure aggregate is closure-like.
Preconditions: The input program uses an async closure (`async || ...`), producing `TyKind::CoroutineClosure` and `AggregateKind::CoroutineClosure` under nightly `async_closure` lowering.; MIR passes such as GVN or RemoveZsts run over the coroutine-closure body or aggregate.; The case distinguishes zero-upvar coroutine closures (zero fields) from coroutines; the other controls are `Closure` and `Coroutine` with zero fields.
Pitfalls: Do not use the `Coroutine` arm for `CoroutineClosure`: coroutines are never ZST, but an empty-field coroutine-closure aggregate follows the closure ZST path.; Do not omit `CoroutineClosure` from `AggregateTy::Def`-style def-like aggregate key handling; it is a closure aggregate, not a state-machine coroutine.; Do not assume the zero-field case generalizes to captured-upvar async closures; the precondition is specifically zero fields, and captured upvars are separate inputs to test.
Test strategy: Build MIR-focused checks for async closures with and without captures. After GVN/RemoveZsts, verify the empty-field `AggregateKind::CoroutineClosure` follows the closure ZST path and is keyed as a def-like aggregate. Keep a zero-field `Closure` and a zero-field `Coroutine` as controls that must remain identical across variants. Inspect emitted MIR and diagnostics rather than asserting execution equivalence.
Cases: 120361-ed7fca1f8805b4348b801f23f444e0dda42f7aed
Source: https://github.com/rust-lang/rust/pull/120361
> | AggregateKind::CoroutineClosure(did, substs)
> // Coroutines are never ZST, as they at least contain the implicit states.
> | ty::CoroutineClosure(..)

### CoroutineClosure follows closure policy for const-prop bailout and callable ABI
Const-prop and ABI decisions also split `Closure` from `Coroutine`, and a coroutine-closure must inherit the closure policy. DataflowConstProp rejects `Closure`/`Coroutine` writes with `throw_machine_stop_str!("unsupported type")`; the corrected behavior bails out on `CoroutineClosure` values rather than attempting to write their constants. AbortUnwindingCalls uses `Abi::RustCall` for `Closure` and `Abi::Rust` for `Coroutine`; the coroutine-closure body ABI is `Abi::RustCall`, as shown by `ty::CoroutineClosure(..) => Abi::RustCall,`. The supplied counterfactual (not claimed as reproduced) is that routing `CoroutineClosure` through `Coroutine` would use `Abi::Rust` and would not bail out as unsupported.
Preconditions: A `CoroutineClosure` value or body is encountered by DataflowConstProp or AbortUnwindingCalls.; The async-closure lowering produces compiler-internal `TyKind::CoroutineClosure`, not an ordinary user-named type.; `Closure` and `Coroutine` cases are retained as controls for the same decisions.
Pitfalls: Do not attempt const-prop writing of `CoroutineClosure` values; bail out as unsupported like closures.; Do not assign `Abi::Rust` to a coroutine-closure body; it is callable and uses `Abi::RustCall`.; Do not conflate the unsupported-type bailout with a claim about user-visible codegen; this is a MIR policy split.
Test strategy: Add compile or MIR checks that exercise the const-prop bailout and abort-unwinding ABI path with an async closure, so the `CoroutineClosure` variant is reached rather than only `Closure`/`Coroutine`. Compare the `CoroutineClosure` arm against `Closure` (bailout, `RustCall`) and `Coroutine` (differing arm) controls. Do not require execution claims.
Cases: 120361-ed7fca1f8805b4348b801f23f444e0dda42f7aed
Source: https://github.com/rust-lang/rust/pull/120361
> | ty::Dynamic(..) => throw_machine_stop_str!("unsupported type"),
> ty::CoroutineClosure(..) => Abi::RustCall,
> | ty::CoroutineClosure(..)

### Coverage aggregation must recognize CoroutineClosure aggregates
InstrumentCoverage's `is_closure_or_coroutine` originally recognized only `AggregateKind::Closure` and `AggregateKind::Coroutine`. The corrected policy includes `AggregateKind::CoroutineClosure`, as in `| AggregateKind::CoroutineClosure(..) => true,`, so coverage collects spans for coroutine-closure aggregates as closure/coroutine aggregates. The supplied counterfactual (not claimed as reproduced) is that omitting the variant from this recognition would fail to mark its aggregate as a closure/coroutine during coverage aggregation.
Preconditions: Coverage instrumentation runs over MIR containing `AggregateKind::CoroutineClosure`, typically from an async closure.; The recognition predicate is used for collecting closure/coroutine aggregate spans.
Pitfalls: Do not recognize only `AggregateKind::Closure` and `AggregateKind::Coroutine`; the coroutine-closure aggregate variant is a distinct kind.; Do not describe this as ordinary closure coverage behavior without noting the distinct `CoroutineClosure` aggregate input.
Test strategy: Run coverage instrumentation on an async closure and inspect whether the `AggregateKind::CoroutineClosure` aggregate is recognized as closure/coroutine for span collection. Retain `Closure` and `Coroutine` aggregate cases as controls. Treat the result as MIR/coverage inspection, not a proof of general equivalence.
Cases: 120361-ed7fca1f8805b4348b801f23f444e0dda42f7aed
Source: https://github.com/rust-lang/rust/pull/120361
> | AggregateKind::CoroutineClosure(..) => true,
> | AggregateKind::CoroutineClosure(did, substs)
> | ty::CoroutineClosure(..)
