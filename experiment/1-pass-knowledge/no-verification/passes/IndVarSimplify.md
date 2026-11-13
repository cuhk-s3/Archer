# Issue 108618

## Bug Triggering Strategy

The bug is triggered by a flaw in the comparator used to sort the exiting blocks of a loop, which violates the mathematical properties of a strict weak ordering when block names are discarded.

To trigger this issue at the LLVM IR level, the following conditions must be met:

1. **Multiple Exiting Blocks**: Create a loop that contains at least three distinct exiting blocks (blocks that have branches leading outside the loop).
2. **Specific Dominance Pattern**: The control flow within the loop must be structured such that:
   - One exiting block (let's call it `B`) strictly dominates another exiting block (`C`).
   - A third exiting block (`A`) is in a separate control-flow branch, making it incomparable to both `B` and `C` (i.e., `A` neither dominates nor is dominated by `B` or `C`).
3. **Unnamed Blocks**: The blocks must be unnamed. This naturally happens in release builds or when optimization pipelines (like `-O1`) are run, as LLVM discards value names by default to save memory.
4. **Strict Weak Ordering Checks**: The compiler must be built with standard library debug checks enabled (e.g., libc++'s `-D_LIBCPP_DEBUG_STRICT_WEAK_ORDERING_CHECK`), which validates the properties of comparators passed to sorting algorithms.

### Why this triggers the bug:
The optimization pass attempts to sort the exiting blocks primarily using dominance (`properlyDominates`). If two blocks do not dominate each other, it falls back to using their names as a tie-breaker.

When the blocks are unnamed, their names are empty strings (`""`). Consequently, the tie-breaker evaluates `"" < ""` and returns `false` for any two incomparable blocks. In sorting algorithms, if `comp(X, Y)` is false and `comp(Y, X)` is false, `X` and `Y` are considered mathematically equivalent (`X == Y`).

In the specific dominance pattern described above:
- Because `B` dominates `C`, the comparator correctly establishes that **`B < C`**.
- Because `A` and `B` are incomparable and unnamed, the comparator evaluates them as equivalent (**`A == B`**).
- Because `A` and `C` are incomparable and unnamed, the comparator evaluates them as equivalent (**`A == C`**).

This creates a logical contradiction: `A == B` and `A == C` implies that `B` must be equivalent to `C` (transitivity of equivalence). However, we already established that `B < C`. This breaks the transitivity of equivalence, violating the fundamental rules of a strict weak ordering and causing the sorting algorithm's debug assertions to crash the compiler.

---

# Issue 116249

## Incorrect Preservation of `samesign` Flag when Narrowing Comparisons

**Description:**
The bug is triggered when an integer comparison (`icmp`) instruction annotated with the `samesign` flag is optimized by narrowing its operands to a smaller integer type. The `samesign` flag asserts that both operands of the comparison share the same sign (i.e., both are non-negative or both are negative) in their current type.

When the comparison is narrowed (e.g., from `i32` to `i8`), the position of the sign bit changes to the most significant bit of the new, narrower type. Two values that have the same sign in a wider type may not have the same sign in the narrower type after truncation. For example, `0` and `128` are both non-negative in `i32`, but when truncated to `i8`, `0` remains non-negative while `128` becomes negative.

The optimization incorrectly preserves the `samesign` flag on the newly narrowed comparison. Because the same-sign guarantee no longer holds for the truncated operands, the comparison evaluates to `poison`. This leads to undefined behavior when the `poison` value is subsequently used, such as in a conditional branch for a loop exit.

---

# Issue 166496

## Floating-Point Induction Variable Conversion with Out-of-Bounds Exact Integer Representation

**Description**:
To trigger this bug, construct a loop controlled by a floating-point induction variable. Set the initial value or the exit value (loop bound) of the induction variable to a constant whose magnitude exceeds the maximum integer value that can be exactly represented by the specific floating-point type without gaps (for example, greater than $2^{24}$ for single-precision or $2^{53}$ for double-precision).

When the optimization pass attempts to transform the floating-point induction variable into an integer induction variable, it incorrectly assumes the conversion is safe as long as the values can be cast to integers. Because the pass fails to verify whether the floating-point bounds fall within the exact integer representation limits of the floating-point semantics, it performs an unsafe transformation. This leads to a miscompilation where the transformed integer loop executes a different number of iterations compared to the original floating-point loop, as the original floating-point arithmetic would have experienced precision loss (gaps between representable integers) that the integer arithmetic does not replicate.

---

# Issue 66986

## Unsafe Speculation of Trapping Operations during Loop Exit Count Expansion

**Description:**
The bug is triggered when a loop optimization pass attempts to rewrite a loop's exit condition based on its computed exit count, but incorrectly speculates operations that can trap at runtime.

1. A loop contains an exit condition that depends on an expression involving a potentially trapping operation, such as an integer division or remainder.
2. In the original program, this trapping operation is safely guarded by control flow (e.g., an `if` statement checking if the divisor is zero) that prevents the operation from executing with invalid operands.
3. The compiler analyzes the loop using Scalar Evolution (SCEV) and computes an expression for the loop's exact exit count, which inherently incorporates the trapping operation.
4. During loop transformations like Linear Function Test Replace (LFTR), the pass attempts to replace the original induction variable-based exit test with a new test against the computed exit count.
5. To do this, the pass expands the SCEV expression for the exit count into actual LLVM IR instructions. However, it fails to verify whether the operations within the expression are safe to unconditionally expand (speculate).
6. Consequently, the potentially trapping operation is generated outside of its original protective control flow guard. When the program executes, the speculated instruction may evaluate with invalid operands (like a zero divisor), leading to a runtime fault such as a floating-point exception.
