# Subsystem Knowledge for TailRecursionElimination
## Elements Frequently Missed

* **Parameter Memory Attributes (`readonly`, `readnone`)**: The optimization pass frequently misses stripping or updating memory access attributes on function parameters. When the pass transforms the function and introduces new memory writes to these parameters, leaving these attributes intact creates invalid IR semantics.
* **`byval` Argument Semantics**: While the pass correctly identifies that it can reuse the memory of `byval` arguments to pass values to the next loop iteration, it misses the broader implications this mutation has on the function's overall IR contract, specifically failing to reconcile the memory reuse with existing parameter attributes.

## Patterns Not Well Handled

### Pattern 1: Memory Mutation of Read-Only Arguments during Loop Conversion
When Tail Recursion Elimination transforms a tail-recursive call into a loop, it must update the function's arguments for the next iteration. For arguments passed via the `byval` attribute, the pass optimizes this by reusing the existing parameter's memory, inserting `memcpy` instructions to overwrite the old values with the new ones.

However, this pattern is not well handled because the pass fails to sanitize the function's signature after introducing these memory writes. If the original `byval` argument was also marked with the `readonly` attribute, the transformation introduces a direct semantic contradiction in the LLVM IR: a parameter explicitly guaranteed to be read-only is now being actively written to by a `memcpy`. Because downstream optimization passes heavily rely on the `readonly` attribute to make assumptions about memory immutability, this unhandled pattern leads to severe miscompilations, such as incorrectly eliding necessary memory loads or optimizing terminating conditions into infinite loops.
