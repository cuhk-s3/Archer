# Issue 64289

## Tail Recursion Elimination Modifying `readonly byval` Arguments

**Description**:
The bug is triggered when a function takes a parameter with both `byval` (pass-by-value) and `readonly` attributes, and contains a tail-recursive call. During tail recursion elimination, the compiler transforms the recursive call into a loop. To update the arguments for the next loop iteration, the optimization reuses the existing parameter's memory by inserting memory copy instructions that overwrite the original `byval` argument.

However, the transformation fails to strip the `readonly` attribute from the function parameter. This creates a semantic contradiction in the IR where a parameter explicitly marked as read-only is being written to. Subsequent optimization passes rely on the `readonly` attribute and incorrectly assume the parameter's memory is never modified throughout the function execution. This false assumption leads to severe downstream miscompilations, such as incorrectly eliding memory loads or optimizing terminating conditions into infinite loops.
