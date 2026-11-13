# Issue 50742

## Instrumentation of Functions with `available_externally` Linkage

**Description**:
The bug is triggered when an instrumentation pass incorrectly processes functions that have `available_externally` linkage. In LLVM IR, the `available_externally` linkage type indicates that the function definition is provided for inlining and optimization purposes within the current module, but the compiler will not emit the function's body into the final object file.

When the transformation logic applies instrumentation (such as inserting entry and exit hooks) to these functions, it often introduces references to the function itself, such as taking the function's address to pass as an argument to the instrumentation callbacks. Because the function is instrumented and its address is taken, it may not be completely optimized out or inlined. However, adhering to the `available_externally` linkage semantics, the compiler still discards the function definition during code generation. Consequently, the generated object file contains unresolved references to the function, which ultimately leads to undefined reference errors during the linking phase. The core issue lies in the transformation pass failing to skip functions with `available_externally` linkage before applying modifications.
