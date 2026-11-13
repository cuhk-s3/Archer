# Subsystem Knowledge for IVUsers
## Elements Frequently Missed

*   **Non-Invertible and Non-Linear Operations in SCEV**: Operations such as bitwise instructions (AND, OR, XOR), min/max intrinsics, and complex conditional logic (selects) are frequently missed or mishandled. The optimization pass assumes standard arithmetic linearity when adjusting expressions, failing to account for the fact that these operations do not distribute or invert cleanly with addition or subtraction.
*   **Invertibility Validation Checks**: The pass frequently misses the crucial verification step to ensure that an expression is strictly invertible. It assumes that normalizing an expression (e.g., adjusting by the loop step) and subsequently denormalizing it will always yield the exact original expression, which is false for non-linear operations.
*   **Post-Increment Context Constraints**: The pass misses the need to restrict post-increment normalization exclusively to affine or strictly linear induction variable uses. It blindly applies step adjustments to post-increment users regardless of the underlying mathematical properties of the SCEV expression.

## Patterns Not Well Handled

### Pattern 1: Post-Increment Normalization of Non-Linear SCEV Expressions
During Loop Strength Reduction (LSR), the `IVUsers` analysis attempts to normalize induction variable expressions to account for post-increment loops by adjusting the expression by the loop step (e.g., subtracting the step). This pattern is not well handled when the SCEV expression contains non-invertible operations like bitwise logic or min/max. Because these operations break mathematical symmetry, the normalization process becomes lossy. The pass fails to verify if `denormalize(normalize(expr)) == expr` before proceeding, resulting in an incorrectly adjusted expression being passed down the optimization pipeline.

### Pattern 2: Corrupted Loop Exit Conditions via Lossy Rewriting
When an induction variable is used in a loop exit condition (such as an `icmp` instruction) and involves a post-increment non-invertible expression, the pass attempts to rewrite the use based on the flawed normalization described in Pattern 1. This pattern is poorly handled because the compiler blindly trusts the incorrectly adjusted SCEV expression to rewrite the induction variable uses. Consequently, the semantic equivalence of the loop exit condition is destroyed, which typically corrupts the loop's control flow and leads to severe miscompilations, such as infinite loops and runtime timeouts.
