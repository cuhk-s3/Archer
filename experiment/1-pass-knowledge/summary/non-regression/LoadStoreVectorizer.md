# Subsystem Knowledge for LoadStoreVectorizer
## Elements Frequently Missed

*   **Execution Transfer Guarantees (`willreturn` attribute)**: The optimization pass frequently misses checking whether intervening instructions are guaranteed to return or transfer execution to their successors. It relies too heavily on memory interference checks while ignoring control flow guarantees.
*   **Non-Memory Side Effects (Traps, Exits, Infinite Loops)**: Instructions that do not interfere with the specific memory state being vectorized (e.g., function calls marked `inaccessiblememonly` or `readnone`) but can halt, trap, or diverge execution are overlooked.
*   **Conditional Undefined Behavior**: The pass fails to recognize that subsequent memory accesses might be dynamically unreachable and inherently unsafe to execute unconditionally. It misses the implicit safety guard provided by preceding non-returning instructions.

## Patterns Not Well Handled

### Pattern 1: Hoisting/Sinking Across Instructions Lacking Execution Transfer Guarantees
The LoadStoreVectorizer aggressively groups contiguous memory accesses (loads or stores) into single, wider vectorized operations. However, it handles the reordering of these accesses poorly when they are separated by instructions that do not guarantee execution transfer (e.g., function calls without the `willreturn` attribute). The pass incorrectly assumes that as long as the intervening instruction does not alias or modify the target memory (such as an `inaccessiblememonly` call), it is safe to hoist or sink memory operations across it. This ignores the implicit control flow boundaries established by potentially non-returning instructions.

### Pattern 2: Unsafe Speculation of Memory Accesses Introducing Unconditional UB
By merging a later memory access with an earlier one (either by hoisting the later access up or sinking the earlier access down), the vectorizer effectively speculates the execution of the later access. This pattern is not well handled because the pass does not account for the possibility that the later access might trigger undefined behavior (such as an out-of-bounds pointer dereference) if executed unconditionally. In the original program, this undefined behavior is safely avoided if the intervening instruction halts or diverges execution. The vectorization transformation incorrectly bypasses this dynamic protection, transforming a valid program into one that executes undefined behavior unconditionally.
