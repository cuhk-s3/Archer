# Subsystem Knowledge for AggressiveInstCombine

## Elements Frequently Missed

*   **Target Pointer Index Width**: The optimization pass frequently overlooks the actual bit-width of the pointer index type (e.g., 64-bit) defined in the DataLayout, defaulting to or implicitly truncating to 32-bit representations during internal calculations.
*   **Large Constant Offsets**: The pass misses the handling of constant offsets that exceed the range of a 32-bit signed integer (specifically values where the 31st bit is set, such as `0x80000000`), treating them as negative values in narrower contexts.
*   **Sign-Extension vs. Zero-Extension Context**: The logic fails to distinguish between the need for zero-extension (for large positive offsets) and sign-extension when promoting internally calculated offsets back to the native pointer width.

## Patterns Not Well Handled

### Pattern 1: Load Folding with Large, Boundary-Crossing Offsets
This pattern involves a sequence of consecutive narrow loads (e.g., `i16`) from a base pointer with constant offsets, which are then combined (via `zext`, `shl`, `or`) into a wider value (e.g., `i32`). The specific variation that is not well handled occurs when the constant offsets are large positive values that exceed `INT32_MAX` (e.g., `2147483648`).

*   **Issue**: When `AggressiveInstCombine` attempts to coalesce these loads into a single wide load, it must calculate a new base address. The logic incorrectly truncates the accumulated offset to 32 bits.
*   **Why it is not well handled**: The optimizer treats the truncated 32-bit value as a signed integer. When generating the new `getelementptr` instruction for the 64-bit architecture, this value is sign-extended. Consequently, a large positive offset (e.g., `0x80000000`) is interpreted as a negative number (e.g., `-2147483648`), causing the optimized code to read from a completely incorrect memory location.