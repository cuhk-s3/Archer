# Subsystem Knowledge for EntryExitInstrumenter

## Elements Frequently Missed

* **Function Linkage Types (`available_externally`)**: The optimization pass frequently misses checking the linkage type of the function being processed. Specifically, it fails to skip functions marked with `available_externally` linkage. These functions are provided to the compiler solely for inlining and optimization purposes and are intentionally discarded during the code generation phase.

## Patterns Not Well Handled

### Pattern 1: Instrumenting Non-Emitted Functions
The pass does not well handle the pattern of applying instrumentation to functions that are not guaranteed to be emitted into the final object file. When the pass inserts entry and exit hooks (e.g., `__cyg_profile_func_enter` and `__cyg_profile_func_exit`), it takes the address of the current function to pass as an argument to the callback. If the function has `available_externally` linkage, taking its address creates a hard reference to it. Because the compiler strictly adheres to the linkage semantics and discards the function's body during code generation, this newly introduced reference cannot be resolved, ultimately leading to undefined reference errors during the linking phase. The pass should proactively identify and skip instrumentation for functions whose definitions will be discarded.