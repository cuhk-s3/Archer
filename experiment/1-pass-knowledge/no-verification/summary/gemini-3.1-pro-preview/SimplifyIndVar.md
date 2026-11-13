# Subsystem Knowledge for SimplifyIndVar
## Elements Frequently Missed

* **Potentially Trapping Instructions**: Instructions that can trigger runtime exceptions, such as integer division (`sdiv`, `udiv`) and remainder (`srem`, `urem`). The optimization pass frequently misses identifying these instructions as hazardous when they are part of a loop-invariant expression.
* **Control Flow Guards and Dominance Conditions**: Conditional branches and checks (e.g., verifying a divisor is not zero) that exist within the loop body to protect the execution of trapping instructions. The pass misses the control-flow dependencies that make the instruction safe to execute.
* **Speculative Execution Safety Checks**: The pass misses querying safety mechanisms (like `isSafeToSpeculativelyExecute`) before moving instructions. It fails to verify whether an instruction is guaranteed to execute in the original program before hoisting it to a dominating block like the loop preheader.

## Patterns Not Well Handled

### Pattern 1: Unsafe Hoisting of Conditionally Executed Loop-Invariant Expressions
When `SimplifyIndVar` attempts to optimize induction variable comparisons, it often tries to hoist loop-invariant operands out of the loop and into the preheader. This pattern is not well handled when the loop-invariant expression contains a potentially trapping operation that is only conditionally executed inside the loop. Because the pass moves the expression to the preheader unconditionally, it bypasses the original protective control-flow guards (such as checking for a zero divisor). This causes the trapping operation to execute speculatively before the loop even begins, leading to runtime faults (e.g., division by zero) that would have been safely avoided in the unoptimized code.

### Pattern 2: Unchecked SCEV Expansion of Trapping Operations
The optimization pass relies on Scalar Evolution (SCEV) to analyze induction variables and loop-invariant expressions. SCEV models the mathematical values of expressions but abstracts away their control-flow dependencies. When `SimplifyIndVar` expands a SCEV expression into actual LLVM IR instructions at a new insertion point (like the loop preheader), it fails to validate whether the expanded operations are safe to execute at that specific location. This pattern is problematic because the pass blindly trusts the SCEV representation and expands trapping operations without ensuring they are guarded or inherently safe, resulting in illegal speculative execution.
