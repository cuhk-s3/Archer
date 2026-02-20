# Subsystem Knowledge for LoopUnrollRuntime

## Elements Frequently Missed

* **Integer Types Wider Than 64 Bits (e.g., `i128`)**: The optimization pass frequently misses the proper handling of integer types that exceed standard 64-bit hardware register widths. Constants generated for these wide types are often incorrectly truncated or extended based on a 64-bit intermediate representation.
* **Sign-Extension of Negative Constants**: When generating negative constants (such as `-1`) for arithmetic operations, the pass misses the requirement to properly sign-extend the value to the target integer width. It incorrectly applies zero-extension, turning a small negative number into a massive positive number.
* **`undef` or `poison` Values in Loop Trip Counts**: The pass struggles with the downstream effects of handling potential `undef` or `poison` values. The necessity to insert `freeze` instructions forces the pass to abandon standard SCEV (Scalar Evolution) backedge calculations and manually construct arithmetic instructions, exposing flaws in constant generation.

## Patterns Not Well Handled

### Pattern 1: Manual Backedge Count Calculation for Wide Integer Types
When a loop's trip count is represented by an integer wider than 64 bits and is not guaranteed to be free of `undef` or `poison` values, the compiler must insert a `freeze` instruction. Consequently, it manually computes the backedge count by adding `-1` to the frozen trip count. However, the pass fails to handle the constant generation for `-1` correctly for wide types. Instead of creating an all-ones value (proper sign-extension), it uses a 64-bit `-1` and zero-extends it to the wider type (e.g., resulting in `18446744073709551615` for `i128`). This transforms a subtraction into the addition of a large positive constant, completely corrupting the backedge count calculation.

### Pattern 2: Prologue/Epilogue Control Flow Generation in Runtime Unrolling
During runtime loop unrolling, the compiler must generate a prologue or epilogue loop to handle the "extra" iterations that do not evenly divide by the unroll factor. The control flow for these extra iterations relies heavily on accurate trip count and backedge count comparisons. Because the pass assumes constants can be safely manipulated within 64-bit boundaries, the boundary checks (e.g., `icmp ult`) for the unrolled loop's preheader branch are evaluated against corrupted, incorrectly extended constants. This pattern is not well handled because the runtime unroller's IR builder logic lacks robust type-width awareness during the synthesis of these control-flow arithmetic instructions, leading to miscompilations where the prologue or epilogue executes the wrong number of times.