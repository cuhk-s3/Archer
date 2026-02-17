# Subsystem Knowledge for Sink

## Elements Frequently Missed

*   **`willreturn` Function Attribute**: The optimization pass frequently overlooks the `willreturn` attribute on function calls. It correctly identifies that a call is `readonly` (does not modify memory) and `nounwind` (does not throw exceptions), but fails to verify that the call is guaranteed to return control to the caller.
*   **Termination Guarantees**: The analysis misses the check for whether an instruction is guaranteed to terminate. While an instruction may be safe regarding memory and exceptions, it may still introduce divergence (e.g., infinite loops) that must be preserved if the instruction originally executed unconditionally.

## Patterns Not Well Handled

### Pattern 1: Sinking Potentially Non-Terminating Calls Past Control Flow Splits
The optimization pass struggles when handling function calls that are side-effect free (e.g., `readonly`) but lack termination guarantees.
*   **Description**: The optimizer identifies a function call in a source block that is only used in a specific successor block. It attempts to sink the call into that successor block to reduce register pressure or execution cost on other paths.
*   **The Issue**: If the source block executes unconditionally (or dominates the exit) and the destination block is conditional, moving the instruction changes the program's termination behavior. In the original code, if the function loops infinitely, the program hangs. In the optimized code, if the control flow bypasses the destination block, the program terminates successfully.
*   **Why it is not well handled**: The safety checks for sinking likely prioritize memory dependence and exception handling (`nounwind`) but fail to treat non-termination as a side effect that prevents code motion across control flow boundaries.