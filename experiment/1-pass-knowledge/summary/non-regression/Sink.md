# Subsystem Knowledge for Sink
## Elements Frequently Missed

* **The `willreturn` Attribute**: The optimization pass frequently misses checking for the `willreturn` attribute on function calls. While it correctly checks for memory side effects (e.g., `readnone`), it fails to verify if the function is actually guaranteed to return control to the caller.
* **Instruction Termination Guarantees**: The pass overlooks the termination behavior of instructions. It assumes that instructions lacking traditional side effects (like memory writes or exceptions) are unconditionally safe to move, missing the fact that an instruction might trap, abort, or enter an infinite loop.
* **Implicit Control Flow Dependencies**: The pass misses the implicit dependency between a potentially non-returning instruction and subsequent instructions (like conditional branches). The execution of the branch is inherently dependent on the preceding instruction returning.

## Patterns Not Well Handled

### Pattern 1: Sinking Non-Returning Instructions Past Conditional Branches
The optimization pass incorrectly identifies pure instructions (e.g., function calls marked `readnone` but lacking `willreturn`) as safe to sink into conditionally executed blocks where their results are exclusively used. This pattern is not well handled because the pass equates "no memory side effects" with "safe to speculate or sink." This causes severe issues because it alters the program's fundamental control flow and termination semantics. If the original instruction was destined to hang or trap unconditionally, sinking it makes that termination behavior conditional, leading to miscompilations where a program might terminate normally instead of hanging.

### Pattern 2: Exposing Undefined Behavior via Altered Execution Order
When a non-returning instruction is sunk past a conditional branch, the pass fails to account for the safety of the branch condition itself. If the branch condition relies on an `undef`, poison, or uninitialized value, evaluating it triggers undefined behavior. In the original IR, the non-returning instruction acts as a shield, safely preempting the branch and preventing the undefined behavior from ever being reached. By sinking the instruction, the pass inadvertently exposes the program to undefined behavior, which is not well handled because the pass's legality checks do not consider the preemptive safety provided by non-returning instructions.
