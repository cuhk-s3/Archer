# Subsystem Knowledge for FlattenCFG

## Elements Frequently Missed

*   **PHI Nodes at Control Flow Merge Points**: The optimization pass frequently overlooks PHI nodes located in blocks that serve as the merge point for one conditional region and the entry point for a subsequent region. It fails to recognize that these nodes represent state changes dependent on the path taken through the first region.
*   **Path-Dependent Data Values**: The pass often misses the correlation between specific control flow edges and the values they carry. When edges are removed or consolidated during flattening, the logic required to select the correct value (based on the predecessor block) is not preserved.
*   **Implicit Control Dependencies**: The optimizer focuses on simplifying explicit branch conditions (boolean logic) but misses implicit dependencies where data validity is tied to the execution of specific predecessor blocks.

## Patterns Not Well Handled

### Pattern 1: Merging Adjacent If-Regions with Inter-Region Data Dependencies
This pattern occurs when `FlattenCFG` attempts to merge two sequential conditional regions (e.g., `If A -> Merge/Start B -> If B`) where the connecting block contains a PHI node.
*   **The Issue**: The PHI node in the connecting block indicates that the program state differs based on whether the "Then" or "Else" path of the first region was taken. When the optimizer flattens the control flow to combine the conditions (e.g., checking `A` and `B` logic simultaneously or skipping checks), it destroys the specific edges that the PHI node relies on to select the correct incoming value.
*   **Why it is not well handled**: The transformation logic incorrectly assumes that because the control flow can be simplified (e.g., the target blocks are the same), the data flow is also uniform. It fails to convert the control-flow dependent PHI logic into data-flow dependent logic (such as inserting a `select` instruction) before removing the branching structure. Consequently, the optimized code often hardcodes one of the PHI's incoming values, leading to incorrect behavior when the alternative path should have been taken.