## Elements Frequently Missed

*   **Live-Out Values of Inner Induction Variables**: The optimization pass frequently misses the correct handling of values defined within the inner loop that are used after the loop nest terminates (live-out values). Specifically, it fails to distinguish between the value of the induction variable during the loop body execution and its value upon loop exit.
*   **Global Variable Updates Tracking Loop Counters**: When a global variable is used to track the progress of an inner loop (effectively making the induction variable live-out), the pass often fails to generate the necessary code to update this global variable to its final exit value after the flattened loop completes.
*   **Distinction Between Loop Bound and Modulo Result**: The optimization misses the edge case where the reconstructed induction variable (derived via modulo arithmetic) wraps around to zero (or the start value) at the exact moment the original inner loop would have reached its upper bound.

## Patterns Not Well Handled

### Pattern 1: Reconstruction of Inner Induction Variables via Modulo Arithmetic
The Loop Flattening pass attempts to eliminate the inner loop structure by reconstructing the inner induction variable (IV) from the flattened loop counter using unsigned remainder instructions (`urem`). This pattern is not well handled when the inner IV is needed after the loop.
*   **Issue**: The formula `inner_IV = flattened_IV % inner_trip_count` correctly calculates the IV for valid iterations within the loop body. However, in the original code, when the inner loop exits, the IV equals the `inner_trip_count`. In the optimized code, the modulo operation results in `0` (assuming a 0-indexed loop) for the corresponding iteration count.
*   **Consequence**: Any code relying on the IV value after the loop (such as a global variable store or a subsequent use) receives the wrapped-around value (e.g., 0) instead of the loop bound, leading to logic errors.

### Pattern 2: Missing Post-Loop State Fix-ups for Flattened Loops
When flattening nested loops, the optimizer transforms the control flow from a multi-block structure with distinct exits to a single loop block. This pattern is poorly handled regarding the "fix-up" of state that persists beyond the loop.
*   **Issue**: The optimization assumes that updating the state within the flattened loop body is sufficient. It fails to recognize that the original control flow guaranteed the inner IV reached a specific exit value *before* passing control to the outer latch or exit block.
*   **Consequence**: The transformed IR lacks a specific instruction sequence after the flattened loop to manually set the live-out variables (or globals) to their expected exit values, leaving them in an intermediate state corresponding to the modulo calculation of the last flattened iteration.