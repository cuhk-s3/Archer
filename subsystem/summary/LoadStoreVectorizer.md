# Subsystem Knowledge for LoadStoreVectorizer

## Elements Frequently Missed

* **The `willreturn` Attribute**: The optimization pass frequently misses checking for the `willreturn` attribute on interleaved function calls. It fails to verify whether an instruction is guaranteed to transfer execution to its successor before reordering memory operations across it.
* **Instructions Not Guaranteed to Transfer Execution**: Function calls, traps, or potentially infinite loops that lack the `willreturn` property are overlooked. The pass treats them as safe to bypass as long as they do not interfere with memory state, ignoring their control-flow implications.
* **Implicit Control-Flow Dependencies for Undefined Behavior**: The pass misses the implicit dependency where a subsequent memory access's safety (e.g., avoiding out-of-bounds access) relies entirely on a preceding instruction halting or diverging execution. 

## Patterns Not Well Handled

### Pattern 1: Vectorization Across Non-Returning Instructions
This pattern occurs when contiguous memory accesses (such as consecutive loads or stores) are interleaved with an instruction that does not interfere with the memory state (e.g., a function call marked `inaccessiblememonly`) but is not guaranteed to return or transfer execution to its successor. 

**Issues Caused:**
The vectorizer incorrectly assumes it is safe to group the contiguous memory accesses together. It hoists or sinks the accesses across the non-returning instruction to form a single, wider vectorized memory operation. If the later memory access is out-of-bounds or invalid, moving it before the non-returning instruction transforms a dynamically unreachable undefined behavior into an unconditional undefined behavior.

**Why it is not well handled:**
The LoadStoreVectorizer relies too heavily on memory alias analysis while neglecting control-flow safety. Because the interleaved instruction (like an `inaccessiblememonly` call) does not read or write the target memory, the alias analysis correctly reports no memory interference. However, the pass fails to account for the fact that reordering a potentially faulting memory access across an instruction that might exit, trap, or loop infinitely is fundamentally unsafe. It lacks the necessary checks to ensure that the interleaved instructions are guaranteed to return (`willreturn`) before allowing the vectorization and reordering of memory accesses.