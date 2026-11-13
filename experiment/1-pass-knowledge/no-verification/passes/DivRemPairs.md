# Issue 60748

## Reusing Division with Poison-Generating Flags for Remainder Computation

**Description**:
The bug is triggered when a remainder operation is optimized by decomposing it into a sequence of arithmetic operations (e.g., `X - (X / Y) * Y`) that reuses the result of a corresponding division operation with the same operands.

If the original division instruction possesses poison-generating flags (such as `exact`), reusing it directly to compute the remainder introduces a miscompilation. Specifically, if the condition for the poison-generating flag is not satisfied at runtime (e.g., the division is not actually exact), the division instruction evaluates to poison. Because the newly transformed remainder computation now depends on this division result, the poison propagates. This causes the remainder to incorrectly evaluate to poison instead of its original, well-defined value.

The core issue stems from the transformation failing to strip the poison-generating flags from the division instruction when its result is repurposed to calculate the remainder, thereby improperly restricting the domain of valid inputs for the remainder operation.
