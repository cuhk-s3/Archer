# Subsystem Knowledge for SimplifyLibCalls
## Elements Frequently Missed

* **Target-Specific Error States (`errno`)**: The optimization pass frequently misses the side effect of library calls modifying global error states (like `errno`) on the target platform. It often assumes that if a call succeeds or fails silently on the host, it will do the same on the target.
* **Edge-Case String Constants**: Inputs such as empty strings (`""`), standalone sign characters (`"+"`, `"-"`), or invalid base prefixes (e.g., `"0x"` without following digits) are frequently overlooked as potential triggers for implementation-defined behavior or error states.
* **Host-Target libc Discrepancies**: The pass misses the critical distinction between the host compiler's standard library behavior and the target execution environment's standard library behavior, especially during cross-compilation.
* **Side Effects in Seemingly Pure Functions**: String-to-integer conversion functions (like `atoi`, `strtol`, `strtoll`) are often mistakenly treated as purely read-only operations when constant-folded, missing their potential to write to memory (i.e., setting `errno` on failure).

## Patterns Not Well Handled

### Pattern 1: Host-Environment Evaluation of Target-Environment Library Calls
The compiler attempts to constant-fold library calls by executing the equivalent function using the host environment's standard library implementation. If the host implementation handles an edge-case input without setting an error state, the compiler assumes the operation is universally safe and replaces the library call with the resulting constant value.
This pattern causes miscompilations because the target environment's standard library might strictly enforce specific standards and set an error state for the exact same edge-case string. It is not well handled because the optimization pass relies too heavily on the host's native execution for constant folding and lacks a robust, target-independent model to accurately predict target-specific libc behaviors and edge-case compliance.

### Pattern 2: Unsafe Elimination of Side Effects in String-to-Integer Conversions
When the optimization pass successfully evaluates a string-to-integer library call at compile time, it completely removes the call and replaces it with the computed constant.
This causes issues because it inadvertently eliminates the secondary side effects of the library call, specifically the setting of `errno` when malformed or edge-case strings are parsed. It is not well handled because the pass fails to conservatively verify whether the constant input constitutes an edge case that *might* trigger an error state on any compliant libc implementation. Instead of preserving the call or modeling the `errno` side effect for questionable inputs, the pass aggressively optimizes the instruction away.
