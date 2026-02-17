# Subsystem Knowledge for AliasAnalysis

## Elements Frequently Missed

*   **Integer Wrapping in Pointer Arithmetic**: The analysis frequently misses the implications of modular arithmetic in `GetElementPtr` (GEP) instructions, specifically those lacking the `inbounds` keyword. It often assumes that if a variable index is non-zero, the scaled offset derived from it must also be non-zero, ignoring cases where `index * scale` wraps to zero due to integer overflow.
*   **Stale Dominator Tree Information**: The analysis frequently misses that the Dominator Tree—a critical data structure used to reason about instruction dominance and reachability—may be outdated during passes that actively mutate the Control Flow Graph (CFG). This leads to Alias Analysis making decisions based on incorrect control flow relationships.
*   **Variable Index Contributions to Offsets**: The analysis frequently misinterprets the contribution of variable indices in GEP decomposition, assuming linear arithmetic properties rather than the actual bit-width constrained behavior of the target architecture.

## Patterns Not Well Handled

### Pattern 1: Assumption of Non-Zero Offsets from Non-Zero Indices
This pattern occurs when the optimizer attempts to prove NoAlias between a base pointer and a derived pointer (GEP) by analyzing the indices.
*   **The Issue**: The optimization logic identifies that a variable index used in the GEP is guaranteed to be non-zero (e.g., via `icmp` or `llvm.assume`). It then incorrectly deduces that the resulting memory address must be distinct from the base address.
*   **Why it is not well handled**: The logic fails to account for the scaling factor applied to the index. In modular arithmetic, a non-zero index multiplied by a scale (e.g., structure size) can wrap around to exactly zero (or a value that mimics another valid offset). By ignoring the possibility of overflow, the compiler incorrectly eliminates valid memory dependencies.

### Pattern 2: Alias Analysis Queries During Active CFG Mutation
This pattern involves optimization passes, such as Jump Threading, that simultaneously modify the Control Flow Graph and query Alias Analysis to perform redundancy elimination (e.g., replacing loads).
*   **The Issue**: To determine if a load can be safely replaced by a previous value, the pass queries Alias Analysis to check for clobbering stores. However, Alias Analysis relies on the Dominator Tree to determine if a store dominates or reaches the load.
*   **Why it is not well handled**: The optimization pass updates the CFG but may leave the Dominator Tree in a stale state (lazy update) while performing the query. Consequently, Alias Analysis uses obsolete dominance information, failing to see that a store on a newly threaded path clobbers the load, leading to the incorrect preservation of a stale value.