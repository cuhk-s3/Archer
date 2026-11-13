# Subsystem Knowledge for MustExecute
## Elements Frequently Missed

* **Loop Backedges**: These are frequently missed or mishandled because the analysis treats them as standard forward control flow edges. By viewing a backedge simply as a branch to a known predecessor (the loop header), the analysis ignores the semantic reality that a backedge initiates a completely new loop iteration.
* **Inter-iteration Control Flow Divergence**: The analysis frequently misses the possibility that control flow can diverge in subsequent loop iterations. It assumes that reaching the loop header guarantees the target block will be reached, failing to account for conditional early exits that might be taken in the next iteration.
* **Complex Loop Latches (Inner Cycles or Multiple Successors)**: Latches that do not unconditionally branch to the header (e.g., those with one path to the header and another to the target block) are missed. The analysis fails to properly isolate the backedge path from the forward execution path when computing transitive predecessors.

## Patterns Not Well Handled

### Pattern 1: Loop Latches as Transitive Predecessors of Target Blocks
This pattern occurs when a target block being analyzed for the "must-execute" property has the loop latch as a transitive predecessor. The latch contains multiple outgoing paths: one is the backedge to the loop header, and another is a forward path leading to the target block.
* **The Issue**: The MustExecute analysis collects all transitive predecessors of the target block, which inherently includes the loop header. When the analysis evaluates the loop latch, it observes the backedge pointing to the header. Because the header is already in the approved predecessor set, the analysis incorrectly validates the backedge as a safe path to the target block. This results in a false positive where the compiler believes the target block is guaranteed to execute, leading to illegal optimizations like unsafe instruction hoisting or memory promotion in passes like LICM.
* **Why it is not well handled**: The underlying graph traversal logic fails to distinguish between intra-iteration paths (forward progress within the same iteration) and inter-iteration paths (backedges). It blindly relies on set membership (whether the destination is in the predecessor set) without applying loop-specific boundary constraints to the backedge.

### Pattern 2: Conflating Loop Header Reachability with Target Block Execution
This pattern involves control flow where taking a backedge guarantees reaching the loop header, but the loop body contains conditional branches that can exit the loop entirely before ever reaching the target block in the new iteration.
* **The Issue**: The compiler erroneously equates "reaching the loop header" with "eventually reaching the target block." It assumes that if the header precedes the target block in the control flow graph, looping back to the header satisfies the must-execute requirement for the target block. However, in the subsequent iteration, the loop's exit condition might evaluate to true, causing the loop to terminate without executing the target block.
* **Why it is not well handled**: The MustExecute property is evaluated statically based on simple reachability sets without bounding the execution analysis to a single loop iteration. Because the analysis does not terminate or invalidate its reachability checks at loop backedges, it incorrectly extends "must-execute" guarantees across iteration boundaries, failing to respect the dynamic nature of loop exit conditions.
