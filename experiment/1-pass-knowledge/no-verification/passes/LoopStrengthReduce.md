# Issue 38847

## Incorrect Type Extension/Truncation of Normalized Post-Increment Loop Induction Variables

**Description**:
The bug is triggered when a loop induction variable (represented as an add recurrence) has a post-increment use outside of the loop, and the compiler attempts to perform a type conversion (such as a sign-extension, zero-extension, or truncation) on it.

During loop strength reduction, the compiler normalizes the induction variable expression to account for the post-increment use. If the type extension or truncation is applied directly to this already-normalized expression, the compiler naively extends or truncates the normalized components (such as the base and the step) instead of the actual underlying value.

This direct conversion of a normalized expression can result in an invalid extended or truncated add recurrence. For example, if the loop has a small backedge-taken count, extending the normalized base and step might not correctly preserve the wrapping or sign-changing behavior of the original type. Consequently, the post-increment value is evaluated incorrectly in the new type, leading to a miscompilation. A correct transformation requires the expression to be de-normalized back to its original form before applying the type conversion, and only then re-normalized for the post-increment use.

---

# Issue 58039

## Incorrect Type Conversion of Normalized Post-Increment Induction Variables

**Description**:
The bug is triggered during loop optimizations that attempt to simplify or reduce the strength of loop induction variables. It specifically involves induction variables that have "post-increment" uses, meaning the value of the variable is used after it has been stepped or updated (often occurring outside the loop or at the loop's exit).

To handle these post-increment uses, the compiler normalizes the underlying recurrence expression, which typically involves shifting its starting value to align with the post-increment state.

The bug manifests when these post-increment uses also require a type conversion, such as a sign-extension to a wider integer type or a truncation to a narrower one. The compiler's transformation logic incorrectly applies the type extension or truncation directly to the *already normalized* recurrence expression.

Because the normalized expression has a shifted base value, naively extending or truncating it can alter its wrapping semantics or sign-bit behavior in the new type. For example, an expression that correctly represents the post-increment value in the original type might yield an incorrect sequence of values when its normalized form is directly sign-extended to a wider type. This flawed transformation leads to miscompilations where the program computes and uses an incorrect value for the induction variable in the converted type.

---

# Issue 62660

## Loop Strength Reduction on Non-Invertible Post-Increment Expressions

**Description**:
The bug is triggered when a loop contains an induction variable whose value is used in a post-increment context, and the scalar evolution (SCEV) expression representing this use involves non-invertible or non-linear operations (such as bitwise operations, min/max, or complex conditional logic).

During the Loop Strength Reduction (LSR) pass, the compiler analyzes induction variable users and attempts to normalize their expressions to account for post-increment loops (e.g., by adjusting the expression by the loop step). For an expression to be safely normalized, the operation must be invertible—meaning that normalizing and subsequently denormalizing the expression should yield the exact original expression.

When the expression contains non-invertible operations, this mathematical symmetry is broken, and the normalization process becomes lossy or incorrect. The bug occurs because the compiler fails to verify the invertibility of the normalized expression before proceeding. It uses the incorrectly adjusted expression to rewrite the induction variable uses, which leads to a miscompilation. In practice, this often corrupts the loop's exit condition or induction variable updates, resulting in an infinite loop and a timeout at runtime.

---

# Issue 62852

## Incorrect Type Conversion on Normalized Expressions for Post-Increment Uses

**Description:**
The bug occurs during loop strength reduction when the compiler attempts to generate type conversions (extensions or truncations) for induction variables (IVs) that are used outside the loop.

The triggering strategy involves the following sequence:
1. **Induction Variable with Post-Increment Use**: A loop contains an induction variable that is updated (incremented or decremented) within the loop, and this updated (post-increment) value is used outside the loop after the loop exits.
2. **Type Conversion during Optimization**: During loop optimizations like loop strength reduction, the compiler decides to replace the original induction variable with a new one of a different type (e.g., widening it from a 32-bit integer to a 64-bit integer). To correctly rewrite the out-of-loop use, the compiler must generate a truncation or extension from the new IV type back to the original type.
3. **Normalization Flaw**: For post-increment uses, the compiler internally represents the IV using a "normalized" expression (which shifts the base of the recurrence by the step value to account for the post-increment). The bug is triggered when the compiler naively applies the type conversion (extend/truncate) directly to this normalized expression.
4. **Miscompilation**: Because type conversions (like sign-extension or zero-extension) are not strictly distributive over the addition of the step value, casting the normalized expression yields a different result than casting the actual de-normalized expression and then applying the step. This leads to an incorrectly calculated value for the IV outside the loop. This is particularly visible when the loop has a small backedge-taken count or uses negative steps, causing the out-of-loop value to be evaluated incorrectly.

By constructing a loop with a post-increment IV used outside the loop, and forcing the loop strength reducer to change the IV's type, the compiler will incorrectly cast the normalized recurrence, resulting in a miscompilation.
