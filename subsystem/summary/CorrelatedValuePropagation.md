# Subsystem Knowledge for CorrelatedValuePropagation

## Elements Frequently Missed

*   **`undef` Operands in Constraint-Enforcing Operations**: The analysis frequently misinterprets `undef` values when they appear as operands to intrinsics that enforce specific properties (like `llvm.abs` enforcing non-negativity). The optimizer often assumes `undef` satisfies the necessary preconditions (e.g., being non-negative) to elide the operation, failing to account that `undef` can resolve to a value violating that property at runtime.
*   **Out-of-Range Switch Case Constants**: When analyzing `switch` instructions, the optimization pass misses the fact that explicit case values might lie strictly outside the inferred value range of the switch condition. These "impossible" cases are incorrectly counted as valid coverage for the range.
*   **PHI Nodes Merging Defined and Undefined Values**: The propagation logic struggles with PHI nodes that combine concrete constants with `undef`. The analysis tends to over-approximate the properties of the resulting value based on the concrete path, ignoring that the `undef` path introduces a wildcard that invalidates strict range or bitwise assumptions.

## Patterns Not Well Handled

### Pattern 1: Cardinality-Based Reachability Analysis in Switches
The optimization pass employs a flawed heuristic for eliminating the default case in `switch` instructions. It attempts to prove the default case is dead by comparing the *size* (cardinality) of the condition's inferred value range against the *count* of reachable explicit cases.
*   **The Issue**: This logic assumes that if the number of explicit cases equals or exceeds the number of possible values in the condition's range, the cases must cover the entire range.
*   **Why it fails**: It fails to verify set inclusion. If the explicit cases include values that are outside the condition's inferred range (which are technically unreachable but not pruned individually), the count becomes inflated. This leads the compiler to believe the range is fully covered when, in reality, valid values within the range are missing and should fall through to the default case.

### Pattern 2: Elision of Sanitizing Intrinsics on Indeterminate Inputs
The pass aggressively attempts to remove intrinsics that modify values to satisfy a constraint (e.g., `llvm.abs` ensuring a positive value) when it believes the input already satisfies that constraint.
*   **The Issue**: This pattern fails when the input is `undef` (or a PHI containing `undef`). The analysis incorrectly treats `undef` as "safe" or satisfying the non-negative predicate.
*   **Why it fails**: By removing the intrinsic, the compiler replaces a guaranteed non-negative result (computed by `abs`) with a raw `undef`. Since `undef` can resolve to any bit pattern, including negative numbers, the optimized code loses the guarantee provided by the original intrinsic, leading to miscompilation where a negative value propagates where a positive one was required.