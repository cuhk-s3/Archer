# Subsystem Knowledge for TailRecursionElimination
## Elements Frequently Missed

* **Parameter Memory Attributes (`readonly`, `readnone`)**: The optimization pass frequently misses the need to strip or update memory-related parameter attributes when transforming the function. Because the pass focuses on control flow and instruction replacement, it overlooks the fact that modifying parameter memory invalidates the original immutability guarantees provided by these attributes.
* **`byval` Argument Semantics**: The pass treats the memory allocated for `byval` arguments as a convenient, reusable scratchpad for setting up the next iteration's arguments. It misses the broader semantic implications of mutating this memory, especially when it is tied to other restrictive attributes.

## Patterns Not Well Handled

### Pattern 1: Memory Reuse Contradicting Parameter Attributes During Loop Conversion
When Tail Recursion Elimination transforms a tail-recursive call into a loop, it must update the function's arguments for the next iteration. To do this efficiently, the pass often reuses the existing memory of the parameters, inserting memory copy or store instructions to overwrite the old values with the new ones.

This pattern is not well handled when the parameter being overwritten is passed via memory (e.g., `byval`) and is explicitly marked with immutability attributes like `readonly`. The optimization pass successfully rewrites the control flow and updates the memory but fails to sanitize the function's signature by stripping the `readonly` attribute. This creates a semantic contradiction in the LLVM IR: a parameter guaranteed not to be written to is now being actively mutated by the newly inserted loop instructions. Because the pass leaves this invalid attribute intact, downstream optimization passes (such as Global Value Numbering or Loop Invariant Code Motion) rely on the false assumption of immutability, leading to severe miscompilations like incorrectly eliding necessary memory loads or optimizing loop-terminating conditions into infinite loops.
