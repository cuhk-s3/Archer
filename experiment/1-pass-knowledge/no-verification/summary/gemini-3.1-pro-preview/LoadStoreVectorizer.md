# Subsystem Knowledge for LoadStoreVectorizer
## Elements Frequently Missed

* **The `willreturn` Attribute**: The optimization pass frequently misses checking for the `willreturn` attribute on intervening function calls. It fails to recognize that without this attribute, a function call is not guaranteed to return or transfer execution to its successor.
* **Instructions That May Not Transfer Execution**: Instructions that can trap, exit the program, throw exceptions, or loop infinitely are overlooked if they do not directly read or write to the memory locations being vectorized (e.g., functions marked `inaccessiblememonly`).
* **Speculation Safety Checks**: The pass misses verifying whether a memory access is safe to speculatively execute (e.g., using `isSafeToSpeculativelyExecute` or checking for dereferenceability) before hoisting or sinking it across other instructions.
* **Implicit Control Flow Dependencies**: The pass focuses heavily on memory aliasing and data dependencies but misses the implicit control flow dependencies created by instructions that can halt sequential execution.

## Patterns Not Well Handled

### Pattern 1: Hoisting/Sinking Memory Accesses Across Non-Returning Instructions
The LoadStoreVectorizer aggressively looks for contiguous memory accesses (loads or stores) to combine into wider vector operations. When these accesses are interleaved with an instruction that does not clobber the relevant memory state (such as an `inaccessiblememonly` function call), the pass assumes it is safe to reorder the memory accesses across this instruction. However, it fails to handle cases where the intervening instruction lacks the `willreturn` guarantee. By ignoring the fact that the intervening instruction might terminate the program or loop infinitely, the pass illegally hoists or sinks memory operations across a boundary that is not guaranteed to transfer execution.

### Pattern 2: Speculating Potentially Faulting Memory Accesses
This pattern occurs when the vectorizer combines a safe memory access with a subsequent memory access that contains conditional Undefined Behavior (UB), such as an out-of-bounds read or write. In the original IR, the UB is dynamically unreachable because an intervening instruction halts execution (e.g., traps or exits) before the invalid access is reached. The vectorizer does not handle this well because it merges the accesses into a single vector instruction placed before the halting instruction. This transformation incorrectly speculates a faulting memory access, converting a valid program where UB is avoided into a miscompiled program that triggers unconditional UB.
