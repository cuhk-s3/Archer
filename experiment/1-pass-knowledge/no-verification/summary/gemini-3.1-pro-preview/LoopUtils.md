# Subsystem Knowledge for LoopUtils
## Elements Frequently Missed

* **`undef` and `poison` Initial Values**: The optimization pass frequently misses the special semantics of `undef` and `poison` when they are used as the initial start values for loop reductions. It fails to account for the fact that these values can evaluate to different results each time they are used.
* **Duplication of Value Uses**: The pass misses the safety implications of introducing multiple new uses of a single value (the reduction start value) across the loop body and epilogue. It incorrectly assumes that evaluating the same `undef` or `poison` value in multiple independent instructions will yield a consistent result.
* **Implicit Consistency Assumptions in Comparisons**: The pass relies on the missed assumption that comparing a current reduction state against an initial start value will consistently return the same boolean result across different lanes and stages of the loop, which is violated when the start value is undefined.

## Patterns Not Well Handled

### Pattern 1: "AnyOf" Reductions with Undef/Poison Start Values
This pattern occurs when a loop conditionally selects a new loop-invariant value or otherwise retains its initial reduction value (start value), and the loop vectorizer attempts to vectorize this "AnyOf" reduction. To track the reduction state, the vectorizer's transformation logic generates code that repeatedly compares the current reduction vector against the initial start value.

**Issues Caused**:
When the initial start value is `undef` or `poison`, the transformation introduces multiple independent uses of this undefined value in the vectorized loop body and the reduction epilogue. Subsequent optimization passes evaluate each of these `undef` or `poison` uses independently and inconsistently. Because the generated vector code's control flow and selection logic rely entirely on these comparisons yielding consistent results, the independent evaluations cause conflicting selections between the initial value and the new value, ultimately resulting in a miscompilation.

**Why it is not well handled**:
The transformation logic in LoopUtils is not well equipped to handle the propagation of `undef` or `poison` values when generating reduction epilogues and vectorized loop bodies. It blindly duplicates the use of the start value without inserting a `freeze` instruction or otherwise ensuring that the value is stabilized. The pass assumes that a value, once loaded or passed as an initial state, behaves as a strict constant across all its duplicated uses, failing to respect the non-deterministic evaluation rules of LLVM's `undef` and `poison` semantics.
