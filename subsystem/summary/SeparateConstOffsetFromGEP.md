## Elements Frequently Missed

*   **Poison-Generating Flags (`nuw`/`nsw`) Context Sensitivity**: The optimization pass frequently misses that flags asserting "no wrap" behavior are dependent on the specific bit-width of the operation. It fails to recognize that a guarantee holding for a wide integer type (e.g., `i32`) does not automatically transfer to a narrower type (e.g., `i8`) after truncation.
*   **Impact of Discarded Bits on Validity**: The analysis often overlooks the state of high-order bits that are discarded during truncation. It assumes that if the final result is valid, the intermediate truncated operands preserve the same semantic properties as the original wide operands, ignoring that discarded bits could cause the new narrower instruction to generate poison.

## Patterns Not Well Handled

### Pattern 1: Distribution of Truncation over Integer Arithmetic
The optimization pass struggles when distributing a `trunc` instruction over binary arithmetic operations, specifically addition, to separate constant offsets (transforming `trunc(Var + Const)` into `trunc(Var) + trunc(Const)`).
*   **Issue**: When performing this transformation, the optimizer incorrectly copies poison-generating flags (such as `nuw`) from the original wide arithmetic instruction to the new, narrower instructions.
*   **Why it is not well handled**: The logic assumes algebraic equivalence is sufficient for transformation, failing to account for undefined behavior semantics. While `(A + B) mod 2^N` is algebraically equivalent to `(A mod 2^N) + (B mod 2^N)`, the `nuw` flag imposes a stricter constraint that the addition must not overflow. Narrowing the width increases the likelihood of overflow; therefore, blindly propagating the flag makes the optimized code stricter than the original, potentially turning well-defined values into poison.