# Issue 112350

## Incorrect Inversion Analysis for Comparisons with Mismatched Poison-Generating Flags

**Description**:
The bug is triggered when the compiler evaluates whether two comparison instructions are exact logical inverses of each other. The strategy involves creating two comparisons with inverse predicates (e.g., `<` and `>=`) operating on the same operands, but applying a poison-generating flag (such as `samesign`) to only one of them.

Because the flag can cause the instruction to yield a poison value under certain conditions, the two comparisons are not strict inverses: one might produce a well-defined boolean result while the other produces poison. The compiler's analysis fails to check for matching poison-generating flags between the two instructions. As a result, it incorrectly assumes they are exact inverses and performs optimizations based on this assumption, such as replacing a conditional `select` instruction with a logical `xor`. This transformation is invalid because it can unconditionally propagate poison from the flagged comparison, whereas the original code might have safely selected the unflagged, well-defined comparison.

---

# Issue 137582

## Speculative Execution of Calls with UB-Implying Attributes

The bug occurs when the compiler attempts to speculatively evaluate a call instruction that possesses attributes implying undefined behavior (UB). The triggering pattern involves the following steps:

1. **Speculatable Call with UB-Implying Attributes**: The IR contains a call to a speculatable function or intrinsic (e.g., a math operation like `smin`). Crucially, this call is annotated with UB-implying attributes, such as `noundef`, `dereferenceable`, or `dereferenceable_or_null` on its return value or arguments.
2. **Speculative Evaluation with Replaced Operands**: A value analysis pass attempts to refine the value of this instruction on specific control-flow edges. To do this, it speculatively evaluates the call by replacing its original operands with edge-specific constraints (e.g., known constants or ranges).
3. **Flawed Safety Check**: Before evaluating, the pass checks if the instruction is safe to speculatively execute. The safety check incorrectly returns true because it only verifies that the callee is speculatable (i.e., has no side effects or memory dependencies), completely ignoring the presence of UB-implying attributes.
4. **Incorrect UB Deduction**: Because the safety check passes, the analysis evaluates the instruction with the substituted operands. If these new operands logically result in an `undef` or `poison` value, the attached UB-implying attributes (like `noundef`) escalate this to immediate undefined behavior within the analysis's internal reasoning.
5. **Invalid Optimizations**: The analysis incorrectly deduces that certain valid execution paths or value ranges trigger UB, leading it to infer overly aggressive and false constraints. These flawed constraints are then used to apply invalid optimizations—such as incorrectly attaching `nsw`/`nuw` flags to prior instructions or adding restrictive `!range` metadata—ultimately miscompiling the program by making the target more undefined than the source.

---

# Issue 141017

## Incorrect Fast-Math Flags Propagation in Select Patterns

**Description**:
The bug is triggered when a floating-point `select` instruction uses the result of a floating-point comparison to form a higher-level pattern, such as a minimum or maximum operation. In this scenario, the comparison instruction is decorated with certain fast-math flags (e.g., `nsz` for no-signed-zeros) that relax its semantics, while the `select` instruction lacks these flags and retains stricter semantics.

During pattern matching and analysis, the compiler incorrectly extracts and uses the fast-math flags from the comparison instruction to represent the properties of the entire select pattern. Because the analysis assumes the relaxed semantics of the comparison apply to the `select` as well, it permits optimizations and canonicalizations that are invalid under the stricter semantics of the original `select` instruction. This leads to miscompilations, such as incorrectly handling signed zeros or other floating-point edge cases, where the transformed code produces a different result than the original IR.

---

# Issue 161524

## Incorrect Poison Analysis for PHI Nodes with Poison-Generating Flags

**Description**:
The bug is triggered by exploiting a flaw in the compiler's analysis of whether a value is guaranteed not to be undefined or poison. Specifically, when evaluating a PHI node, the analysis only verifies that its incoming values are not undef or poison, but fails to account for poison-generating flags (such as fast-math flags like `ninf` or `nnan`) attached directly to the PHI node itself.

To trigger this bug:
1. Construct a PHI node and attach one or more poison-generating flags to it (e.g., floating-point fast-math flags).
2. Ensure that all incoming values to this PHI node are guaranteed not to be undef or poison.
3. Consume the result of the PHI node in an instruction that relies on poison analysis for optimization, such as a `freeze` instruction.
4. The compiler incorrectly assumes the PHI node's result is safe from being poison solely because its incoming values are safe, completely ignoring the potential for the PHI node's flags to generate poison. This leads to invalid optimizations, such as improperly eliminating the `freeze` instruction.
5. At runtime, if an incoming value violates the condition of the poison-generating flag (e.g., an infinity value passed to a PHI node with the `ninf` flag), the PHI node produces a poison value. Because the `freeze` instruction was incorrectly removed, the optimized program becomes more poisonous than the original, resulting in a miscompilation.

---

# Issue 54311

## Incorrect `smin`/`smax` Pattern Matching for `select` with `nsw` Subtraction

**Description**:
The bug is triggered by a sequence of transformations involving a conditional signed subtraction with the `nsw` (no signed wrap) flag.

1. Initially, the subtraction is guarded by a conditional branch based on a signed comparison of its operands (e.g., `X <s Y`), ensuring the subtraction only executes when it is guaranteed not to overflow.
2. Control flow simplification hoists the subtraction, making it unconditional, and replaces the branch with a `select` instruction. The `select` chooses `0` if the condition is met, and the subtraction result otherwise. If the unconditional subtraction overflows, it produces a `poison` value. However, the `select` safely ignores this by choosing `0` when the overflow would occur, keeping the program well-defined.
3. An optimization pass incorrectly identifies this `select` pattern as a signed minimum (`smin`) or maximum (`smax`) operation between the subtraction result and `0`.
4. The `select` is transformed into an `smin` or `smax` intrinsic. Unlike the `select` instruction, which conditionally shields the `poison` value, the intrinsic unconditionally evaluates its arguments. If the subtraction overflows, the `poison` value is propagated through the `smin`/`smax` intrinsic, replacing a well-defined `0` with `poison` and leading to a miscompilation.

---

# Issue 56293

## Constant Folding of String-to-Integer Library Calls Ignoring Target-Specific Error States

**Description**:
The bug is triggered by providing an edge-case constant string (such as an empty string, a standalone sign character, or an invalid base prefix) as an argument to a string-to-integer conversion library call (e.g., `atoi`, `strtol`, `strtoll`).

During optimization, the compiler attempts to constant-fold the call by evaluating it using the host environment's standard library implementation. If the host implementation handles the edge-case string without setting an error state (such as `errno`), the compiler assumes the operation is safe and replaces the library call with the resulting constant value.

However, the target environment's standard library implementation might have different behavior or strictly enforce specific standards, setting an error state for the same edge-case string. By folding the call and removing it, the compiler inadvertently eliminates the side effect of setting the error state on the target platform. This discrepancy between the host's compile-time evaluation and the target's runtime behavior leads to observable differences in program execution and results in a miscompilation.

---

# Issue 57357

## Incorrect Floating-Point Min/Max Matching with Mismatched Signed Zeros

**Description**

The bug is triggered by a specific sequence of floating-point comparison (`fcmp`) and `select` instructions involving zero values with different signs. The strategy to trigger this issue involves the following pattern:

1. **Strict Inequality Comparison**: A floating-point comparison instruction uses a strict inequality predicate (e.g., strictly less than `olt`, or strictly greater than `ogt`) to compare a variable against a zero value (e.g., `+0.0`).
2. **Select with Mismatched Zero**: A `select` instruction uses the boolean result of this comparison to choose between the original variable and a zero constant that has the opposite sign of the zero used in the comparison (e.g., `-0.0`).
3. **Absence of Fast-Math Flags**: The `select` instruction does not possess the `nsz` (no signed zeros) fast-math flag, meaning the sign of zero must be strictly preserved according to IEEE-754 semantics.

When this pattern occurs, the compiler's value tracking and pattern matching logic incorrectly identifies the sequence as a standard floating-point minimum or maximum operation. Because IEEE-754 comparisons ignore the sign of zero, the compiler attempts to canonicalize the operation by treating the mismatched zeros as identical. It then erroneously transforms the strict inequality predicate into a non-strict inequality (e.g., changing `<` to `<=`).

This transformation introduces a miscompilation when the input variable is zero. For example, in the original strict inequality (`+0.0 < +0.0`), the condition evaluates to `false`, and the `select` correctly returns the original `+0.0`. However, in the transformed non-strict inequality (`+0.0 <= +0.0`), the condition evaluates to `true`, causing the `select` to incorrectly return the `-0.0` branch. This unintended sign flip for zero can drastically alter the results of subsequent operations, such as causing a division by zero to yield negative infinity instead of positive infinity.

---

# Issue 58046

## Incorrect Non-Negative Assumption for Floating-Point Division with Negative Zero Divisor

**Description**:
The bug is triggered by a floating-point division (`fdiv`) where the divisor can evaluate to negative zero (`-0.0`) but cannot be ordered less than zero (i.e., it is never strictly negative). The numerator is typically a positive value.

The compiler's value tracking analysis incorrectly assumes that if both operands of a floating-point division cannot be ordered less than zero, the result of the division also cannot be ordered less than zero. However, in IEEE 754 floating-point arithmetic, dividing a positive number by negative zero results in negative infinity (`-Inf`), which is strictly less than zero.

By constructing a scenario where the divisor evaluates to `-0.0` (for example, by multiplying `-0.0` with a guaranteed non-negative value) and then comparing the division result against a negative value (such as `-Inf`), the compiler erroneously concludes that the division result can never be negative. This flawed assumption causes the compiler to incorrectly fold or simplify subsequent instructions, such as evaluating a valid equality comparison to `false`, ultimately leading to a miscompilation.

---

# Issue 62760

## Incorrect Constant Range Calculation for 1-bit Intrinsics

**Description**:
The bug is triggered when the compiler attempts to determine the constant range of the result for certain integer intrinsics (such as absolute value or count leading/trailing zeros) applied to 1-bit (`i1`) values.

When calculating the upper and lower bounds of the result for these intrinsics, the logic typically adds 1 to the maximum possible value to represent the exclusive upper bound. However, for a 1-bit integer, adding 1 to the maximum value causes an overflow, wrapping the upper bound back to the lower bound. Consequently, the calculated lower bound and upper bound become equal.

In the compiler's range representation, a range with equal lower and upper bounds is treated as an empty range (indicating no possible valid values) rather than a full range (indicating all possible values). This incorrect empty range propagates through the optimization pipeline, leading the compiler to erroneously assume that the result is poison or that the code path is unreachable, ultimately causing a miscompilation.

---

# Issue 63316

## Incorrect NaN Deduction for Floating-Point Multiplication of Zero and Infinity

**Description**

The bug is triggered by a floating-point multiplication where one operand can evaluate to zero (but is known not to be infinity) and the other operand can evaluate to infinity (but is known not to be zero).

In IEEE-754 arithmetic, multiplying zero by infinity results in a NaN (Not-a-Number). However, the compiler's value tracking analysis contained flawed logic for deducing whether a multiplication could produce a NaN. Specifically, it incorrectly concluded that the result could never be NaN if both operands individually satisfied the condition of being either "never infinity" or "never zero". This logic failed to account for the cross-operand scenario where one operand is zero and the other is infinity.

As a result, when an instruction sequence involves such a multiplication followed by a check for NaN (e.g., an unordered floating-point comparison like `fcmp uno` or `fcmp ord`), the compiler erroneously assumes the multiplication can never yield NaN. This leads to an invalid optimization where the NaN check is folded to a constant boolean value (e.g., `false`), causing a miscompilation.

To trigger this issue, one can construct an IR pattern with:
1. A floating-point multiplication where one operand is potentially zero (e.g., the result of an integer-to-float conversion of a value that can be zero) and the other is infinity (e.g., a constant infinity).
2. A subsequent operation that checks if the result of the multiplication is NaN (e.g., an unordered comparison against zero).

Because of the flawed deduction, the compiler will incorrectly optimize away the NaN check, altering the program's intended behavior when the zero-times-infinity case occurs.

---

# Issue 89669

## Invalid Swapping of Select Operands with Poisonous Negation Zero

**Description**:
The bug occurs in the compiler's instruction combining pass, specifically within the logic that attempts to sink negations through expression trees.

1. **Pattern Recognition**: The optimizer encounters a negation of a `select` instruction, such as `sub 0, (select cond, -X, X)`. To optimize this, it checks if one operand of the `select` is the known negation of the other.
2. **Poisonous Negation**: The analysis identifies `-X` as a negation of `X`. In vector types, this negation is often represented as a subtraction from a zero vector. Crucially, the analysis allowed this zero vector to contain `poison` elements (e.g., `sub <0, poison>, X`). These `poison` elements are often introduced by prior optimization steps (like demanded-element simplification) that replace unused constant elements with `poison`.
3. **Invalid Transformation**: When the optimizer confirms the operands are negations of each other, it attempts to negate the entire `select` instruction by simply swapping its true and false operands, transforming the expression into `select cond, X, -X`.
4. **Miscompilation**: While mathematically correct, this transformation is invalid in the presence of `poison`. If the condition evaluates such that it selects the non-negated operand in the original code, the original expression evaluates to `sub 0, X`, which is well-defined and free of poison. However, the optimized expression evaluates directly to the negated operand `-X` (i.e., `sub <0, poison>, X`), which contains `poison` elements.
5. **Result**: The optimized code becomes "more poisonous" than the original code. It introduces `poison` values into execution paths that were previously well-defined. This violates compiler optimization rules and allows subsequent passes to incorrectly fold or eliminate the code, ultimately leading to a miscompilation (e.g., folding the entire expression to the original value `X` incorrectly).

---

# Issue 92217

## Incorrect Sign Bit Inference for Floating-Point Square Root

**Description:**
The bug occurs when the compiler's value tracking analysis attempts to infer the sign bit of a floating-point square root (`sqrt`) operation. The analysis incorrectly assumes that if the input to the `sqrt` is known not to be NaN, and the result is known not to be negative zero (e.g., due to fast-math flags or input properties), then the sign bit of the result must always be zero (i.e., the result is strictly positive).

However, this logic fails to account for negative inputs. According to IEEE 754 standards, the square root of a strictly negative number evaluates to NaN. Crucially, the sign bit of a generated NaN value is not guaranteed to be zero and can be set (resulting in a negative NaN). By incorrectly assuming the sign bit is always zero under these conditions, the compiler miscompiles subsequent instructions that depend on the sign bit of the `sqrt` result, such as sign bit extraction (e.g., `movemask` intrinsics) or conditional branches.

To trigger this issue, a `sqrt` operation must be fed a negative input (which is not NaN and not `-0`), and the program must subsequently observe or use the sign bit of the resulting NaN in a way that relies on the compiler's flawed known-bits analysis.

---

# Issue 97600

## Incorrect Handling of Non-Pointer to Pointer Casts in Pointer Stripping Logic

**Description**

The bug is triggered when a pointer cast instruction (such as a `bitcast`) converts a non-scalar-pointer type—like a vector of pointers (e.g., `<1 x ptr>`)—into a scalar pointer type.

When compiler analysis passes attempt to find the underlying object of a memory location or strip away pointer casts, they iteratively look through cast instructions. If the source operand of a cast is not a scalar pointer type, the stripping logic is supposed to halt and return the current scalar pointer. However, due to a flaw in the logic, the analysis incorrectly returns the non-pointer source operand (e.g., the vector of pointers) instead of the scalar pointer.

Because downstream analyses, such as Alias Analysis, strictly expect the underlying object of a memory operation to be a scalar pointer, receiving a non-pointer type causes them to behave unpredictably. In this scenario, the analysis fails to properly evaluate the memory locations and defaults to incorrect assumptions, such as concluding that two memory accesses do not alias (`NoAlias`).

This flawed aliasing information is subsequently consumed by optimization passes like Loop Invariant Code Motion (LICM). Believing that there are no memory dependencies, the optimizer may illegally hoist or sink memory operations (like `store` instructions) out of loops. This results in a miscompilation where memory is not updated correctly during program execution.

---

# Issue 99436

## Unsafe Operand Substitution in Speculatively Executed Instructions

**Description**:
The bug is triggered when the compiler performs operand substitution on an instruction that is executed unconditionally (speculatively), but whose safety relies heavily on the properties of its original operands.

The strategy involves the following pattern:
1. **Speculatively Safe Instruction**: An instruction (such as a memory load or a division) is safe to execute unconditionally because its variable operands possess certain guaranteed properties (e.g., a known valid, dereferenceable pointer, or a non-zero divisor).
2. **Conditional Equivalence**: The result of this instruction is used in a conditional operation (like a `select` instruction). The condition checks if the variable operand is equal to a specific constant (e.g., checking if the pointer is `null`, or if the divisor is `0`).
3. **Flawed Transformation**: The compiler attempts to optimize the instruction by replacing the variable operand with the constant, assuming the equivalence holds for that specific conditional path.
4. **Introduction of Undefined Behavior**: The compiler incorrectly verifies if the instruction is safe to speculatively execute *before* performing the substitution. Replacing the variable operand with the constant (e.g., substituting a valid pointer with `null`) invalidates the very properties that made the instruction safe in the first place. Because the instruction remains unconditionally executed outside the conditional construct, the newly substituted constant operand causes immediate undefined behavior (e.g., a null pointer dereference or division by zero) at runtime.
