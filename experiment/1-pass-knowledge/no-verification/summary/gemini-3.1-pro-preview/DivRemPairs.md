# Subsystem Knowledge for DivRemPairs
## Elements
 Frequently Missed

*   **Instruction Flags (NUSW/NUW/Exact)**
: The optimization pass frequently overlooks the semantic implications of metadata flags attached to division instructions. When an instruction result is repurposed for a secondary
 calculation (like a remainder), these flags act as assertions that restrict the valid input domain. Failing to strip these flags during transformation
 leads to "poison" propagation, where an operation that should produce a well-defined value instead yields poison because the flag'
s specific constraints were violated.
*   **Dependency/Side-Effect Integrity**: The pass often focuses on algebraic equivalence ($
X \% Y = X - (X / Y) * Y$) while ignoring the operational equivalence regarding definedness. It
 assumes that if the mathematical identity holds, the optimized sequence is safe, failing to account for the fact that the original division instruction might
 have been "more constrained" than the new expression, thereby altering the program's definedness.

## Patterns Not Well Handled

###
 Pattern 1: Propagation of Poison via Instruction Reuse
The primary high-level pattern not well handled is the reuse of
 a division result that carries "strong" flags (specifically `exact`) within a substituted expression for a remainder.


- **The Issue**: When `DivRemPairs` identifies an opportunity to combine a `sdiv` and `srem
` (or `udiv`/`urem`) into a single instruction sequence, it often creates a new instruction based
 on the existing division. If the original division was marked `exact`, it implies that the divisor must evenly divide the dividend. If
 this precondition is not met at runtime, the original `sdiv` evaluates to poison. By reusing this specific `sdiv` to
 calculate the remainder, the transformation forces the remainder computation to also evaluate to poison if the `exact` condition is failed.

- **Why it is not handled**: The optimizer treats the division as a black-box provider of the quotient value, failing
 to acknowledge that the *result* of the instruction is coupled with the *validity* of the instruction's flags. The
 transformation assumes the result of the division is always valid for use in the remainder calculation, ignoring the case where the division instruction itself
 was "poison-prone" due to the metadata attached to it.
