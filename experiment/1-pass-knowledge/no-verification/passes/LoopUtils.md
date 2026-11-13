# Issue 62565

## Miscompilation of "AnyOf" Reductions with Undef/Poison Initial Values

**Description**:
The bug is triggered when the loop vectorizer processes an "AnyOf" reduction pattern. In this pattern, a loop conditionally selects a new loop-invariant value if a specific condition is met; otherwise, it retains the initial reduction value (start value).

During vectorization, the compiler's transformation logic tracks the reduction state by repeatedly comparing the current reduction vector against the initial start value to determine if the new value has been selected in any lane. This approach introduces multiple new uses of the initial start value across the vectorized loop body and the reduction epilogue.

If the initial start value is `undef`, `poison`, or an input that causes the comparison to yield `poison`, these multiple uses become problematic. Subsequent optimization passes can evaluate each use of `undef` or `poison` independently and inconsistently. Because the generated vector code relies on the assumption that all comparisons against the start value will yield consistent results, the independent evaluation of these undefined values breaks the reduction logic. This leads to conflicting selections between the initial value and the new value, ultimately resulting in a miscompilation.
