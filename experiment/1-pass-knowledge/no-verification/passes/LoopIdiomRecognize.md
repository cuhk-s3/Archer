# Issue 62873

## Unfrozen Undef/Poison Value in Loop Idiom Transformation

**Description**:
The bug is triggered by a loop that matches a specific recognizable idiom, such as shifting a value until a certain bit is set or unset (the "shift-until-bit-test" pattern).

In the original IR, the bit position used for the loop's exit condition is evaluated, but it is not statically guaranteed to be free of `undef` or `poison` values (for example, it might be derived from a function argument or an operation that can produce poison).

When the compiler recognizes this idiom, it attempts to optimize the loop by analytically precomputing the loop's trip count and other related variables outside the loop. During this transformation, the compiler reuses the potentially `undef` or `poison` bit position value multiple times to generate new arithmetic instructions, but fails to apply a `freeze` operation to it.

Because `undef` or `poison` values can evaluate inconsistently across multiple uses or propagate to instructions that invoke undefined behavior (such as branch conditions or arithmetic operations with `nuw`/`nsw` flags), this duplication introduces undefined behavior or incorrect execution paths that were not present in the original code.

To trigger the bug, one must construct a loop matching the targeted idiom where the key variable (like the bit position) is derived from a source that can be `undef` or `poison`, forcing the compiler to duplicate the unfrozen value during the optimization pass.
