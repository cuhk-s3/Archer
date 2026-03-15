# Subsystem Knowledge for LoopUnrollRuntime
## Elements Frequently Missed

* **Integer Types Wider Than 64 Bits (e.g., `i128`)**: The optimization pass frequently misses the correct bit-width scaling when dealing with non-standard or wide integer types. It tends to implicitly rely on 64-bit limits (`uint64_t`) when generating constants, failing to account for types that require larger representations.
* **Sign-Extension of Negative Constants**: When generating negative constants (such as `-1` for subtraction operations) for wide integer types, the pass misses the requirement to sign-extend the value. Instead, it incorrectly zero-extends a 64-bit representation of `-1`, resulting in a large positive number (`UINT64_MAX`).
* **`undef` or `poison` Values in Trip Counts**: The pass misses seamless handling of trip counts that are not guaranteed to be free of `undef` or `poison`. The necessity to insert `freeze` instructions forces the pass into a manual backedge count calculation path, which exposes underlying bugs in constant generation.

## High-Level Patterns Not Well Handled

### Pattern 1: Manual Backedge Count Calculation for Wide, Poison-Susceptible Trip Counts
When a loop is subjected to runtime unrolling and its trip count is potentially `undef` or `poison`, the compiler must safely compute the backedge count to determine the number of extra iterations for the prologue or epilogue. The pattern involves inserting a `freeze` instruction on the trip count and manually subtracting 1 (represented as adding `-1`). This pattern is not well handled for wide integer types (like `i128`) because the compiler fails to correctly instantiate the `-1` constant for the addition. Instead of a proper wide all-ones value, it generates an incorrect constant, leading to a corrupted backedge count and ultimately causing the unrolled loop's prologue or epilogue to execute the wrong number of iterations.

### Pattern 2: Constant Generation and Extension for Wide Integer Arithmetic
The pass struggles with the high-level pattern of generating and extending constants for arithmetic operations on types wider than 64 bits. When the compiler needs to create a `-1` constant to decrement a wide induction variable or trip count, it uses a 64-bit representation of `-1` and incorrectly zero-extends it to the target bit width (e.g., `i128`). This transforms what should be a subtraction (adding `-1`) into the addition of a massive positive constant (e.g., `18446744073709551615`). This pattern of flawed constant extension breaks loop bound calculations and conditional checks (`icmp`) that rely on accurate arithmetic, leading to severe miscompilations in loop control flow.
