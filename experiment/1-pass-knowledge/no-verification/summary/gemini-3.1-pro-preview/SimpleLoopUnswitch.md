# Subsystem Knowledge for SimpleLoopUnswitch
## Elements Frequently Missed

* **Original Successor Mapping (True/False Targets)**: The exact mapping of the boolean condition (`true` or `false`) to its respective basic blocks (in-loop vs. out-of-loop successors) is frequently missed. The optimization logic fails to dynamically query and preserve which specific edge corresponds to the loop exit, leading to incorrect branch reconstruction.
* **Branch Condition Polarity**: The polarity of the branch condition relative to the loop exit is overlooked. The pass incorrectly assumes a fixed polarity (e.g., assuming the `true` branch always stays in the loop and the `false` branch always exits), missing the fact that developers or prior passes might structure the IR such that the `true` path is the exiting edge.

## Patterns Not Well Handled

### Pattern 1: Invariant Condition Injection with "True" Loop Exits
When a loop contains a conditional branch where the `true` path exits the loop and the `false` path remains within the loop, the unswitching logic fails to handle the injection of a pending invariant condition properly. During the creation of a new check block to evaluate the invariant condition, the pass attempts to reconstruct the original conditional branch. However, because it does not respect the original exit polarity, it hardcodes the in-loop successor as the `true` branch and the out-of-loop successor as the `false` branch. This effectively swaps the successors, inverts the control flow logic, and results in a miscompilation where the loop exits when it should continue, and vice versa.

### Pattern 2: Hardcoded Control Flow Reconstruction
The high-level pattern of rebuilding conditional branches using static, hardcoded assumptions about successor ordering is not well handled. Instead of cloning the original branch instruction or explicitly mapping the original `true`/`false` destinations to the newly constructed branch, the transformation logic relies on a rigid template. This rigid reconstruction pattern is fragile and breaks whenever the original IR deviates from the pass's internal assumptions about standard loop structures (e.g., assuming the fall-through or `false` branch is always the loop exit).
