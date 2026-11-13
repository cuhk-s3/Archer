# Subsystem Knowledge for EntryExitInstrumenter
## Elements Frequently Missed

* **Function Linkage Types (Specifically `available_externally`)**: The optimization pass frequently misses checking the linkage type of the function being processed. Functions with `available_externally` linkage are provided solely for inlining and optimization purposes and are not emitted into the final object file. Failing to check and skip these linkage types leads to invalid modifications on functions that will ultimately be discarded.
* **Address-Taken Semantics Introduced by Instrumentation**: The pass misses accounting for the side effects of its own transformations, specifically how passing a function's address to an instrumentation callback changes the function's usage profile. Taking the address of a function can prevent it from being safely optimized out or inlined, conflicting with the semantics of certain linkage types.

## Patterns Not Well Handled

### Pattern 1: Instrumenting Non-Emitted Function Definitions
The pass does not well handle the pattern of applying structural modifications (like inserting entry and exit hooks) to functions that the compiler is explicitly instructed not to emit (e.g., functions with `available_externally` linkage). When the instrumenter inserts callbacks into these functions, it often passes the function's own address as an argument to the hook. Because the function's address is now taken, it cannot be trivially eliminated by standard optimization passes. However, the code generator still honors the `available_externally` linkage and discards the function body. This creates a paradox where the generated object file contains a call to the instrumentation hook referencing a function symbol that does not exist, inevitably causing undefined reference errors during the linking phase. The pass should identify and skip instrumentation for any function whose definition is not guaranteed to be emitted.
