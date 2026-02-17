# Subsystem Knowledge for VectorUtils

Based on the provided bug-triggering strategy and example, here is the subsystem knowledge base for the VectorUtils optimization pass.

## Elements Frequently Missed

*   **Operand Value Constraints Relative to Reduced Bit-Width**: The optimization pass frequently fails to verify if constant operands (specifically shift amounts) are valid within the new, narrower bit-width. For example, a shift amount valid for 32 bits (e.g., 16) is undefined or poison for 8 bits.
*   **Data Dependency on High-Order Bits**: The analysis misses the fact that right-shift operations (`lshr`, `ashr`) depend on the high-order bits of the input operand. Truncating the input operand *before* the shift discards the data that was intended to be shifted into the lower bits.

## Patterns Not Well Handled

### Pattern 1: Aggressive Demotion of Shift Instructions Followed by Truncation
This pattern involves a shift instruction (e.g., `lshr i32`) whose result is immediately truncated to a smaller type (e.g., `trunc to i8`). The optimization pass attempts to optimize this by performing the shift in the narrower type (converting `trunc(shift(x, c))` to `shift(trunc(x), c)`).

*   **Issue**: This transformation is mathematically incorrect for right shifts. The original operation shifts high bits down into the low bits which are then preserved by the truncate. The optimized version discards those high bits immediately via the input truncation, resulting in data loss.
*   **Why it is not well handled**: The optimizer likely treats shift instructions similarly to arithmetic operations like `add` or `mul`, where modular arithmetic allows the operation to be performed in the narrower width without affecting the lower bits. It fails to account for the positional nature of shifts where the result depends on bits that are outside the "demanded" low-bit range.