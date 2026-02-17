## Elements Frequently Missed

*   **Trapping Status of Instructions**: The optimization frequently misses checks for instructions that can trap or fault at runtime, specifically integer division (`sdiv`, `udiv`) and remainder (`srem`, `urem`) operations. It assumes that if an instruction's operands are loop-invariant, the instruction itself is safe to move, ignoring the potential for runtime exceptions (like division by zero).
*   **Control Flow Guards and Execution Context**: The pass often overlooks the specific control flow context (guards) that protects an instruction in the original code. It misses the fact that an instruction inside a loop body is implicitly guarded by the loop's entry condition (e.g., `i < n`). When moving code to the preheader, this guard is lost, leading to unconditional execution of code that was originally conditional.

## Patterns Not Well Handled

### Pattern 1: Speculative Hoisting of Loop-Invariant Comparisons
This pattern occurs when `SimplifyIndVar` attempts to simplify a comparison instruction inside a loop, where one operand is the induction variable and the other is a loop-invariant expression containing potentially trapping arithmetic (like division).
*   **The Transformation**: To canonicalize the loop or reduce overhead, the compiler identifies the invariant expression and "expands" or hoists it to the loop preheader.
*   **The Issue**: The optimization treats "loop invariance" (the value does not change) as synonymous with "speculative safety" (the instruction can run anywhere). By hoisting the expression to the preheader, the instruction executes before the loop condition is checked. If the loop was not supposed to execute (e.g., iteration count is zero) and the invariant expression involves a trapping condition (e.g., divisor is zero), the optimized code crashes where the original code would have safely skipped the loop.