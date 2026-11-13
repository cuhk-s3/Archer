# Issue 63962

## Incorrect Successor Ordering During Invariant Condition Injection in Loop Unswitching

**Description**:
The bug is triggered by a specific arrangement of successors in a conditional branch within a loop during loop unswitching optimizations.

1. A loop contains a conditional branch where the "true" path exits the loop (out-of-loop successor) and the "false" path remains within the loop (in-loop successor).
2. The loop unswitching optimization attempts to inject a pending invariant condition. To do this, it creates a new check block and reconstructs the original conditional branch inside it.
3. During the reconstruction of this branch, the transformation logic fails to preserve the original mapping of the condition's boolean result to its respective successors. Instead, it incorrectly assumes a fixed order, hardcoding the in-loop successor as the "true" branch and the out-of-loop successor as the "false" branch.
4. Because the original branch had the opposite successor order (exiting on "true" and staying on "false"), this hardcoded reconstruction swaps the successors. This effectively inverts the branch condition's logic, leading to incorrect control flow and a miscompilation.
