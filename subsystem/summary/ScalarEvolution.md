## Elements Frequently Missed

*   **Sign-Extension Logic for Large Integer Widths**: The optimization pass frequently misses the correct handling of type promotion for integer types larger than 64 bits (e.g., `i128`). Specifically, when internal arithmetic factors (such as -1 used for subtraction) are promoted to the wider type, the system incorrectly defaults to zero-extension instead of sign-extension, corrupting the arithmetic value.
*   **Speculative Safety of Faulting Instructions**: The pass fails to identify that certain arithmetic instructions, particularly division (`udiv`, `sdiv`) and remainder operations, are unsafe to execute speculatively. It misses the check that these instructions can trap (e.g., division by zero) and therefore cannot be moved from a guarded context within a loop to an unconditional context in the preheader.
*   **Control Dependencies in SCEV Expressions**: The system frequently overlooks the implicit control dependencies embedded in Scalar Evolution expressions. When an expression represents a value that is only valid or safe under specific loop conditions (guards), the pass misses preserving these dependencies during expansion.

## Patterns Not Well Handled

### Pattern 1: Algebraic Simplification of Large Integer Expressions
This pattern involves the decomposition and simplification of arithmetic expressions involving bit widths larger than the standard machine word (e.g., `i128`). When ScalarEvolution attempts to calculate the difference between two such expressions (e.g., `A - B`), it often converts the operation into an addition with a negated coefficient (e.g., `A + (-1 * B)`).
*   **Issue**: The compiler fails to correctly sign-extend the immediate coefficient (like -1) when promoting it to the large integer width. Instead, it zero-extends the value, treating a small negative number as a massive positive number.
*   **Consequence**: This results in erroneous constant differences. Downstream passes rely on these incorrect constants to prove conditions or simplify induction variables, leading to the removal of valid code or the introduction of incorrect logic.

### Pattern 2: Unconditional Expansion of Multi-Exit Loop Bounds
This pattern occurs when a loop has multiple exit conditions, leading to a trip count modeled as a `min` or `max` of several sub-expressions (e.g., `min(ExitCountA, ExitCountB)`). Often, one of these sub-expressions involves an unsafe operation (like division) that is guarded by a conditional check in the original loop body.
*   **Issue**: To facilitate optimizations like vectorization, the compiler expands this composite SCEV expression into the loop preheader. In doing so, it generates code to evaluate all operands of the `min`/`max` function unconditionally, effectively hoisting the unsafe operation out of its protective guard.
*   **Consequence**: If the unsafe operation (e.g., `udiv`) has a trigger condition (e.g., divisor is 0), the optimized code will trap at runtime before entering the loop, even if the original code would have safely bypassed the operation or exited the loop via a different condition.