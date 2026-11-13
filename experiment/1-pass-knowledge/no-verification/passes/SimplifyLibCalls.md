# Issue 56293

## Constant Folding of String-to-Integer Library Calls Ignoring Target-Specific Error States

**Description**:
The bug is triggered by providing an edge-case constant string (such as an empty string, a standalone sign character, or an invalid base prefix) as an argument to a string-to-integer conversion library call (e.g., `atoi`, `strtol`, `strtoll`).

During optimization, the compiler attempts to constant-fold the call by evaluating it using the host environment's standard library implementation. If the host implementation handles the edge-case string without setting an error state (such as `errno`), the compiler assumes the operation is safe and replaces the library call with the resulting constant value.

However, the target environment's standard library implementation might have different behavior or strictly enforce specific standards, setting an error state for the same edge-case string. By folding the call and removing it, the compiler inadvertently eliminates the side effect of setting the error state on the target platform. This discrepancy between the host's compile-time evaluation and the target's runtime behavior leads to observable differences in program execution and results in a miscompilation.
