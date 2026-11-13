# Issue 62660

## Loop Strength Reduction on Non-Invertible Post-Increment Expressions

**Description**:
The bug is triggered when a loop contains an induction variable whose value is used in a post-increment context, and the scalar evolution (SCEV) expression representing this use involves non-invertible or non-linear operations (such as bitwise operations, min/max, or complex conditional logic).

During the Loop Strength Reduction (LSR) pass, the compiler analyzes induction variable users and attempts to normalize their expressions to account for post-increment loops (e.g., by adjusting the expression by the loop step). For an expression to be safely normalized, the operation must be invertible—meaning that normalizing and subsequently denormalizing the expression should yield the exact original expression.

When the expression contains non-invertible operations, this mathematical symmetry is broken, and the normalization process becomes lossy or incorrect. The bug occurs because the compiler fails to verify the invertibility of the normalized expression before proceeding. It uses the incorrectly adjusted expression to rewrite the induction variable uses, which leads to a miscompilation. In practice, this often corrupts the loop's exit condition or induction variable updates, resulting in an infinite loop and a timeout at runtime.
