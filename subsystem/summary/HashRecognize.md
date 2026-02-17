# Subsystem Knowledge for HashRecognize

## Elements Frequently Missed

*   **Live-out users of Simple Recurrences**: The optimization pass frequently misses checking whether instructions classified as "simple recurrences" (used to evolve data, such as `lshr`) have users outside the loop structure.
*   **External dependencies on auxiliary instructions**: Instructions identified as auxiliary drivers for the main idiom (e.g., data shifting logic driving a CRC check) are often assumed to be dead code once the main idiom is optimized, ignoring their necessity for downstream computations in exit blocks.

## Patterns Not Well Handled

### Pattern 1: CRC Loops with Live-Out Data Evolution
This pattern involves a loop that performs two distinct tasks: calculating a CRC value (conditional recurrence) and evolving the input data (simple recurrence, often a shift), where the evolved data is required after the loop terminates.
*   **Issue**: The `HashRecognize` pass correctly identifies the CRC idiom and attempts to replace the loop with an optimized intrinsic. However, it incorrectly assumes the data evolution logic exists solely to support the CRC calculation. Consequently, it removes the instruction sequence responsible for evolving the data.
*   **Result**: When the loop is bypassed or replaced, the `phi` nodes in the exit block that depend on the evolved data (the simple recurrence) receive `undef` values instead of the computed result, breaking program correctness.