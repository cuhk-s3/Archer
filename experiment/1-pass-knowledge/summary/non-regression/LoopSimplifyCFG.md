# Subsystem Knowledge for LoopSimplifyCFG
## Elements Frequently Missed

* **External Predecessors of Loop Exit Blocks**: The optimization pass frequently misses checking for incoming edges to loop exit blocks that originate from outside the loop (e.g., from the function entry block). It erroneously assumes that if all intra-loop edges to the exit block are dead, the block has no other predecessors.
* **Non-Canonical Loop Forms**: The pass implicitly relies on loops being in a canonical form (specifically, having dedicated exit blocks where exit blocks only have predecessors from inside the loop). It misses the possibility that prior optimization passes might have broken this canonical form by introducing external edges to the exit blocks.
* **Global vs. Local Reachability**: The pass evaluates reachability locally (relative to the loop's internal control flow) but applies a global transformation (replacing the block's contents with an `unreachable` instruction). It misses the global liveness of the block, failing to verify the block's complete predecessor list across the entire function.

## Patterns Not Well Handled

### Pattern 1: Shared Exit Blocks with External Control Flow
This pattern occurs when a loop exit block is shared, meaning it receives control flow from both inside the loop (e.g., a loop header or latch) and strictly outside the loop (e.g., the function's entry block).
When the optimization pass simplifies the control flow inside the loop—such as evaluating a conditional branch to a constant `false` and removing the intra-loop edge to the exit block—it incorrectly concludes that the entire exit block is dead. Consequently, it replaces the exit block's instructions with an `unreachable` instruction. This is not well handled because the dead block elimination logic is overly scoped to the loop's internal edges. It fails to query the complete predecessor list of the exit block to verify if external, live edges still exist before performing destructive updates, leading to miscompilations and broken control flow for the external paths.

### Pattern 2: Intra-Loop Dead Edge Elimination in Non-Canonical Loops
This pattern involves a specific sequence of transformations: first, a loop's canonical form is broken (e.g., by a pass that merges blocks or creates external edges to loop exit blocks), and subsequently, `LoopSimplifyCFG` performs constant folding or branch simplification inside the loop that removes the only intra-loop edge to that exit block.
When the intra-loop edge is removed, the pass triggers a cleanup routine that aggressively deletes or hollows out the target block. This pattern is not well handled because the pass lacks a robust safety check to differentiate between "removing a dead edge to a block" and "deleting the block entirely." It implicitly relies on the loop simplify form (like dedicated exits) being perfectly intact, which is not guaranteed if other passes have interleaved and modified the Control Flow Graph (CFG).
