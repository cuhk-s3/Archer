# Issue 80289

## Incorrect Constant Extension for Loop Trip Counts Larger Than 64 Bits During Runtime Unrolling

**Description**:
The bug is triggered during runtime loop unrolling when the compiler needs to compute the backedge count to determine the number of extra iterations for a prologue or epilogue loop.

Specifically, the issue occurs under the following conditions:
1. A loop is subjected to runtime unrolling.
2. The loop's trip count is represented by an integer type wider than 64 bits (e.g., `i128`).
3. The trip count is not guaranteed to be free of `undef` or `poison` values.

Because of the potential for `undef` or `poison` values, the compiler inserts a `freeze` instruction on the trip count and manually computes the backedge count by adding `-1` to the frozen value. However, when constructing the `-1` constant for the addition, the compiler uses a 64-bit representation of `-1` and incorrectly zero-extends it to the wider integer type (e.g., resulting in `UINT64_MAX` for an `i128` type) instead of properly sign-extending it to an all-ones value.

As a result, instead of subtracting one from the trip count, the compiler adds a large positive constant. This leads to an incorrect backedge count calculation, causing the unrolled loop's prologue or epilogue to execute the wrong number of iterations and resulting in a miscompilation.
