# Subsystem Knowledge for LoopUnroll
## Elements
 Frequently Missed

*   **Exit Block PHI Node Dependencies**: Transformation passes
 often focus on the loop body, ignoring the fact that LCSSA PHI nodes in the immediate successor (exit) blocks are tied to the loop
's internal induction variables and values. When the loop body is unrolled, these PHIs must have their incoming values updated, but
 the dependency of external analyses (like ScalarEvolution) on these specific PHI nodes is frequently overlooked.
*   **Analysis
 Invalidation Triggers**: Transformations often perform manual IR mutation without explicitly signaling the analysis manager to invalidate specific handles. These nodes
 are missed because the pass assumes that structural IR changes are sufficient, forgetting that high-level analysis frameworks (SCEV, Dependence
Info) maintain their own internal maps that become stale upon IR transformation.

## Patterns Not Well Handled

### Pattern 1: Dis
connect between Structural IR Mutation and Analysis Cache Coherency
This pattern occurs when the LoopUnroll pass performs "surgical
" updates to the control flow—such as remapping incoming values for exit PHIs after duplicating loop blocks—without communicating these
 updates to the `ScalarEvolution` (SCEV) or other side-effect-tracking analyses. The issue arises because the LL
VM infrastructure distinguishes between the *mutability* of the IR and the *validity* of the analysis state. When Loop
Unroll creates new BasicBlocks and redirects PHI incoming edges, the transformation logic treats the IR as a local graph problem
 but fails to recognize it as a global semantic change. Consequently, the analysis cache continues to map exit PHI nodes to their pre
-unrolling expressions, leading to a state where the optimizer makes incorrect deductions based on "ghost" data that no longer matches
 the post-transform IR.

### Pattern 2: Multi-Exit Loop Transformation Complexity
This pattern is characterized by complex loop exits
 where multiple paths lead to the same exit block or where multiple PHI nodes must be updated to maintain LCSSA form during unrolling. Loop
Unroll often handles the simple case (a single latch to a single exit) correctly but fails when the unrolling process
 necessitates the creation of multiple new incoming edges for exit PHIs. Because the internal logic for updating these PHIs is often procedural
 and scattered across the transformation sequence, the pass fails to track every affected node. This results in an incomplete update where some PHI
 operands are correctly patched to reflect the unrolled iterations, while others remain pointed at the stale, pre-transformed IR, causing the analysis framework
 to return inconsistent or contradictory results for a single loop exit.
