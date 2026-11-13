# Subsystem Knowledge for LoopSimplifyCFG
## Elements Frequently Missed

* **External Predecessors to Loop Exit Blocks**: The optimization pass frequently misses checking for incoming control flow edges that originate from outside the loop. When evaluating whether an exit block is dead, it only considers edges coming from within the loop.
* **Non-Canonical Loop States**: The pass overlooks the fact that prior optimization passes might have broken the canonical loop form. It fails to verify if an exit block is dedicated solely to the loop or shared with external execution paths.
* **Global Block Reachability**: The pass misses the broader Control Flow Graph (CFG) context. By relying strictly on intra-loop edge liveness to determine block reachability, it ignores the global reachability of the block from the function's entry point.

## Patterns Not Well Handled

### Pattern 1: Dead Block Elimination on Shared Exit Blocks
When a loop exit block acts as a merge point for both intra-loop execution paths and extra-loop execution paths, the pass struggles to handle its elimination correctly. If the optimization determines that all paths from inside the loop to this exit block are dead, it erroneously marks the entire exit block as dead and removes it. This causes severe miscompilations, such as infinite loops or invalid CFGs, because execution paths originating outside the loop that still rely on reaching that exit block are abruptly broken. This pattern is poorly handled because the reachability analysis in `LoopSimplifyCFG` is overly localized to the loop's internal structure and fails to query the global CFG for external incoming edges before performing block deletion.

### Pattern 2: CFG Simplification on Non-Canonical Loops
The pass applies aggressive control flow simplifications under the implicit assumption that the loop is in canonical form (specifically, that loop exit blocks are dedicated and have no predecessors from outside the loop). However, when a sequence of prior passes alters the CFG—such as creating an external edge that jumps directly to a loop exit block—the loop loses its canonical form. `LoopSimplifyCFG` does not well handle this transition. It proceeds with transformations based on invalid assumptions about the loop's boundaries and exit conditions. This is poorly handled because the pass lacks sufficient validation checks to ensure the loop's exit blocks are still canonical (i.e., checking `Loop::hasDedicatedExits()`) before applying intra-loop reachability logic to delete them.
