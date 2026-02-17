## Elements Frequently Missed

*   **Dominator Tree Validity**: The optimization pass frequently misses the fact that the Dominator Tree (DT) has become stale due to recent Control Flow Graph (CFG) modifications (such as edge splitting or block duplication) before using it for subsequent analysis.
*   **Intervening Memory Clobbers**: Store instructions located within the blocks being threaded (the "mid" blocks) are often missed or incorrectly classified as non-aliasing. This occurs because the Alias Analysis relies on the stale DT to determine object lifetimes and pointer validity.
*   **Alias Analysis Preconditions**: The pass overlooks the strict dependency Alias Analysis has on an up-to-date Dominator Tree, leading to the acceptance of false `NoAlias` results when checking if a threaded path is safe for load elimination.

## Patterns Not Well Handled

### Pattern 1: Load Elimination with Intervening Stores on Threaded Paths
This pattern involves a specific sequence: a memory definition (Store A), a jump to an intermediate block containing another memory write (Store B), and a final jump to a destination block containing a memory read (Load A). Jump Threading attempts to thread the execution path from the first block to the destination to eliminate the final load.
*   **Issue**: The optimizer attempts to replace the final load with the value from Store A. To do this safely, it must prove Store B does not clobber the location. However, due to the CFG mutation occurring during threading, the Alias Analysis uses stale dominance information. It incorrectly concludes that Store B does not alias the memory location, causing the optimizer to replace the load with the stale value from Store A, effectively ignoring the write in Store B.

### Pattern 2: Concurrent CFG Mutation and Analysis Querying
This high-level pattern consists of performing structural changes to the Control Flow Graph (such as duplicating blocks to thread jumps) while simultaneously querying complex analysis subsystems (like Alias Analysis) that depend on the graph's structure.
*   **Issue**: The optimization logic assumes that analysis results remain valid or degrade gracefully during the transformation. However, because the Dominator Tree is updated lazily or left stale, the analysis subsystems operate on an obsolete view of the program structure. This leads to a synchronization gap where safety checks (such as memory dependency verification) pass based on the old graph topology, validating transformations that are invalid in the new, modified CFG.