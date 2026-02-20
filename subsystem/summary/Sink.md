# Subsystem Knowledge for Sink

## Elements Frequently Missed

* **The `willreturn` Attribute**: The optimization pass frequently misses checking for the `willreturn` attribute on function calls. While it correctly checks for memory side effects (e.g., `readnone` or `readonly`), it fails to verify if the instruction is actually guaranteed to terminate and return control to the caller.
* **Termination Behavior and Guarantees**: Instructions that do not write to memory or throw exceptions, but may still fail to return (e.g., by entering an infinite loop or trapping), are incorrectly treated as completely safe to move. The pass misses the implicit side effect of non-termination.
* **Implicit Control Flow Dependencies**: The pass misses the implicit dependency between a potentially non-returning instruction and the subsequent instructions (like conditional branches). The execution of the branch is inherently dependent on the preceding instruction returning.

## Patterns Not Well Handled

### Pattern 1: Sinking Non-Returning Instructions Past Conditional Branches
The optimization pass identifies an instruction (such as a `readnone` function call) whose result is used exclusively in one target block of a subsequent conditional branch. Because the instruction lacks standard memory side effects, the pass assumes it is safe to sink it into the conditional block to save execution time on the other paths. However, this pattern is poorly handled because it ignores termination semantics. If the sunk instruction was capable of infinite looping or trapping, moving it past the branch fundamentally alters the program's control flow, allowing the branch (and potentially the other execution path) to execute when it originally would not have.

### Pattern 2: Exposing Undefined Behavior via Premature Branch Execution
When a non-returning instruction is sunk past a conditional branch, the branch instruction is forced to execute earlier relative to the non-returning instruction. This pattern is not well handled because the branch condition might rely on an `undef`, poison, or uninitialized value. In the original IR, the non-returning instruction would safely preempt the branch, preventing the undefined behavior from ever being triggered. By sinking the instruction, the compiler exposes the program to undefined behavior, leading to severe miscompilations.