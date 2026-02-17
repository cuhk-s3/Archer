## Elements Frequently Missed

*   **Branch Successor Operand Ordering**: The specific mapping of the `true` and `false` outcomes to their respective successor labels (successor index 0 vs. successor index 1) is frequently overlooked. The compiler often assumes a default ordering (True targets the loop, False targets the exit) rather than preserving the ordering defined in the original instruction.
*   **Semantic Association of Boolean Outcomes**: The logical relationship between a condition's evaluation (True/False) and the control flow intent (Stay in Loop/Exit Loop) is missed. The pass fails to verify whether the "True" path of the invariant condition was originally the path that kept execution inside the loop or the path that exited it.

## Patterns Not Well Handled

### Pattern 1: Inverted Invariant Condition Mapping (True-to-Exit)
This pattern involves loops containing an invariant condition where the `true` evaluation leads to a loop exit, and the `false` evaluation leads to the loop body (or vice versa, provided it deviates from the canonical `if (cond) { loop }` structure).

*   **Issue**: When `SimpleLoopUnswitch` hoists the invariant condition to the loop preheader, it must construct a new branch instruction to direct flow to either the unswitched loop version or the exit/alternative path.
*   **Why it is not well handled**: The optimization logic defaults to a rigid reconstruction strategy, creating a branch where the `true` outcome blindly points to the unswitched loop copy. It fails to detect that in the original IR, the `true` outcome was actually the exit condition. This results in a complete inversion of control flow, causing the loop to execute when it should terminate and terminate when it should execute.