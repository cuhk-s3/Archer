# Subsystem Knowledge for LoopUnrollRuntime
## Elements Frequently Missed

* **Integer Types Wider Than 64 Bits**: The optimization pass often assumes or defaults to 64-bit limits when generating and manipulating constants. It misses the proper handling of wider integer types (e.g., `i128`), leading to incorrect bitwise representations when adapting constants to these wider types.
* **Sign-Extension of Negative Constants**: When constructing negative constants (such as `-1`) for arithmetic operations, the pass frequently misses the requirement to sign-extend the value to the target type's bit width. Instead, it incorrectly applies zero-extension, which changes the mathematical value of the constant in wider types.
* **`undef` and `poison` Values in Loop Bounds**: The potential presence of `undef` or `poison` values in loop trip counts is an edge case that forces the compiler to abandon standard loop bound logic. It requires the insertion of `freeze` instructions and manual backedge count calculations, which exposes underlying flaws in constant generation.

## Patterns Not Well Handled

### Pattern 1: Manual Backedge Count Calculation for Wide Trip Counts
When a loop is subjected to runtime unrolling and its trip count is represented by an integer type wider than 64 bits (e.g., `i128`), the presence of potential `undef` or `poison` values forces the compiler to manually compute the backedge count. This is typically done by inserting a `freeze` instruction on the trip count and adding `-1` to the frozen value.

This pattern is not well handled because the compiler constructs the `-1` constant using a 64-bit representation and incorrectly zero-extends it to the wider integer type. Instead of properly sign-extending the constant to an all-ones value (which would correctly represent `-1` in `i128`), the zero-extension creates a large positive constant (e.g., `UINT64_MAX`). As a result, the compiler adds a massive positive number instead of subtracting one from the trip count. This leads to an incorrect backedge count calculation, causing the unrolled loop's prologue or epilogue to execute the wrong number of iterations and resulting in a severe miscompilation.
