# Subsystem Knowledge for LoopStrengthReduce
## Elements Frequently Missed

*   **Post-Increment Uses of Induction Variables**: The optimization pass frequently mishandles induction variables when their updated (post-increment) values are used outside the loop or at the loop's exit. The logic fails to correctly map the internal normalized representation back to the exact out-of-loop state.
*   **Non-Distributive Properties of Type Conversions**: The pass misses the mathematical reality that type conversions (such as `sext`, `zext`, and `trunc`) are not strictly distributive over addition. It incorrectly assumes that casting a shifted base and step is equivalent to shifting a casted base.
*   **Wrapping and Sign-Bit Semantics**: When shifting the starting value of a recurrence to align with a post-increment state (normalization), the pass frequently misses how this shift alters the wrapping behavior or sign-bit boundaries of the original type, leading to invalid values when subsequently widened or narrowed.
*   **Invertibility of SCEV Expressions**: The pass misses checking whether a Scalar Evolution (SCEV) expression is mathematically invertible before attempting to normalize it. Operations like bitwise logic, `min`/`max`, and complex conditionals are treated as linear, which breaks the required symmetry for normalization and denormalization.

## Patterns Not Well Handled

### Pattern 1: Direct Type Conversion on Normalized Recurrences
This pattern occurs when a loop induction variable has a post-increment use outside the loop, and the Loop Strength Reduction (LSR) pass decides to change the variable's type (e.g., widening a 32-bit integer to a 64-bit integer). To handle the post-increment use, the compiler internally represents the induction variable as a "normalized" add recurrence, which involves shifting the base of the recurrence by the step value.

The issue arises because the compiler naively applies the required type extension (`sext`, `zext`) or truncation (`trunc`) directly to this already-normalized expression. Because type casts are not distributive over addition, casting the normalized expression `(Base + Step)` can yield a completely different result than the correct approach of casting the de-normalized expression and then applying the step `(Cast(Base) + Cast(Step))`. This pattern is not well handled because the compiler fails to de-normalize the expression back to its original form before applying the cast, resulting in miscompilations where the out-of-loop value evaluates incorrectly due to unexpected integer wrapping or sign changes.

### Pattern 2: Normalization of Non-Invertible Post-Increment Expressions
This pattern involves loops where the induction variable is used in a post-increment context, but the expression representing this use contains non-linear or non-invertible operations, such as bitwise operations (`AND`, `OR`, `XOR`), `min`/`max` functions, or complex conditional logic.

During LSR, the compiler attempts to normalize these expressions by adjusting them by the loop step. For this normalization to be safe and correct, the underlying mathematical operation must be invertible—meaning that normalizing the expression and subsequently denormalizing it must yield the exact original expression. This pattern is not well handled because the compiler blindly applies the normalization step without verifying the invertibility of the operations within the SCEV expression. When non-invertible operations are present, the mathematical symmetry is broken, making the normalization process lossy. Consequently, the compiler rewrites the induction variable uses using a corrupted expression, which frequently leads to infinite loops or incorrect loop exit conditions.
