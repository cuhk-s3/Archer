# Subsystem Knowledge for EntryExitInstrumenter
## Elements Frequently Missed

* **Function Linkage Types (`available_externally`)**: The optimization pass frequently misses checking the linkage type of the function being processed. Specifically, it fails to identify and skip functions with `available_externally` linkage. These functions are provided to the compiler solely for inlining and optimization purposes and are explicitly designed not to be emitted into the final object file.

## Patterns Not Well Handled

### Pattern 1: Instrumenting Non-Emitted Functions and Taking Their Addresses
When the pass applies entry and exit instrumentation to a function, it typically inserts callback functions (e.g., `__cyg_profile_func_enter` and `__cyg_profile_func_exit`) that take the address of the instrumented function as an argument. If this transformation is applied to a function with `available_externally` linkage, it creates an explicit pointer reference to the function itself. Because the function's address is taken, it cannot be completely optimized out or safely discarded by earlier passes. However, the compiler's code generation phase strictly adheres to the `available_externally` semantics and drops the function body anyway. This mismatch results in dangling references in the generated object file, ultimately causing undefined reference errors during the linking phase. The pass fails to recognize that functions not destined for code emission should be exempt from self-referencing instrumentation.
