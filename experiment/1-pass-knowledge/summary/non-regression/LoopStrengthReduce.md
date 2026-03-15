# Subsystem Knowledge for LoopStrengthReduce
## Elements Frequently Missed

*   **Wrapping and Overflow Semantics in Narrow Types**: The optimization pass frequently misses the distinct wrapping behavior (e.g., signed overflow changing the sign bit) of narrow integer types (like `i8`) when promoting induction variables to wider types (like `i32`).
*   **Non-Commutativity of Normalization and Type Conversion**: The pass fails to recognize that shifting the base value of a recurrence expression (normalization) does not safely commute with type conversions like sign-extension (`sext`) or truncation (`trunc`).
*   **Sign-Bit State in Post-Increment Uses**: The exact sign-bit state of a post-incremented value before it is extended is often overlooked. An addition in a narrow type might flip the sign bit, which a subsequent `sext` relies on, but a widened addition will not.
*   **LCSSA Phi Nodes with Implicit Cast Dependencies**: Loop-Closed SSA (LCSSA) Phi nodes that capture post-increment values and immediately feed into cast instructions are mishandled when the underlying induction variable is replaced or promoted.

## Patterns Not Well Handled

### Pattern 1: Type Promotion of Post-Increment Induction Variables Crossing Sign Boundaries
When an induction variable of a narrow type (e.g., `i8`) is used outside the loop after a post-increment operation, and that use is subsequently sign-extended (`sext`) to a wider type (e.g., `i32`), the optimization pass often attempts to promote the entire induction variable to the wider type to eliminate the cast. This pattern is poorly handled because the pass assumes the arithmetic in the wider type will yield the same result as the narrow type. However, if the post-increment addition in the narrow type crosses a signed boundary (e.g., `127 + 1` in `i8` becomes `-128`), the original code would sign-extend this wrapped value (yielding `-128` in `i32`). The optimized code, performing the addition in the wider type, simply computes `128`, completely losing the wrapping semantics and resulting in a miscompilation.

### Pattern 2: Applying Type Conversions Directly to Normalized Recurrence Expressions
To handle post-increment uses of induction variables, the compiler normalizes the underlying recurrence expression by shifting its starting value to align with the post-increment state. A critical pattern that is not well handled occurs when these post-increment uses also require a type conversion (`sext` or `trunc`). The optimization logic incorrectly applies the type extension or truncation directly to the *already normalized* recurrence expression. Because the normalized expression has a shifted base value, naively extending or truncating it alters its wrapping semantics. The pass essentially makes the flawed assumption that `cast(step(IV))` is equivalent to `step(cast(IV))` even when the step operation causes an overflow or sign change in the original uncast type.
