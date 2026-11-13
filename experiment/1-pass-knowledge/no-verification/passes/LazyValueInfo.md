# Issue 137582

## Speculative Execution of Calls with UB-Implying Attributes

The bug occurs when the compiler attempts to speculatively evaluate a call instruction that possesses attributes implying undefined behavior (UB). The triggering pattern involves the following steps:

1. **Speculatable Call with UB-Implying Attributes**: The IR contains a call to a speculatable function or intrinsic (e.g., a math operation like `smin`). Crucially, this call is annotated with UB-implying attributes, such as `noundef`, `dereferenceable`, or `dereferenceable_or_null` on its return value or arguments.
2. **Speculative Evaluation with Replaced Operands**: A value analysis pass attempts to refine the value of this instruction on specific control-flow edges. To do this, it speculatively evaluates the call by replacing its original operands with edge-specific constraints (e.g., known constants or ranges).
3. **Flawed Safety Check**: Before evaluating, the pass checks if the instruction is safe to speculatively execute. The safety check incorrectly returns true because it only verifies that the callee is speculatable (i.e., has no side effects or memory dependencies), completely ignoring the presence of UB-implying attributes.
4. **Incorrect UB Deduction**: Because the safety check passes, the analysis evaluates the instruction with the substituted operands. If these new operands logically result in an `undef` or `poison` value, the attached UB-implying attributes (like `noundef`) escalate this to immediate undefined behavior within the analysis's internal reasoning.
5. **Invalid Optimizations**: The analysis incorrectly deduces that certain valid execution paths or value ranges trigger UB, leading it to infer overly aggressive and false constraints. These flawed constraints are then used to apply invalid optimizations—such as incorrectly attaching `nsw`/`nuw` flags to prior instructions or adding restrictive `!range` metadata—ultimately miscompiling the program by making the target more undefined than the source.

---

# Issue 62200

## Incorrect Constant Range Inference at Select Instruction Use with Undef/Poison Condition

**Description**:
The bug occurs when the compiler attempts to infer the properties (such as a constant range) of a value used as a data operand in a `select` instruction.

To optimize the data operand, the compiler assumes that the `select` condition must evaluate to a specific boolean value for that operand to be chosen (e.g., assuming the condition is `true` when evaluating the true operand, or `false` when evaluating the false operand). It then uses this assumption to deduce constraints on the data operand and applies optimizations based on these constraints (such as converting a signed operation to an unsigned one, or replacing operations with more efficient equivalents).

However, if the condition of the `select` instruction is potentially `undef` or `poison`, this assumption becomes invalid. An `undef` or `poison` condition can non-deterministically evaluate to either boolean state, meaning the `select` instruction might choose a data operand even if the operand does not actually satisfy the assumed constraints. Consequently, optimizing the operand based on an unreliable condition leads to miscompilations, as the optimized instruction may produce incorrect results when the condition evaluates differently or propagates undefined behavior.

---

# Issue 62901

## Incorrect Value Range Inference from Select Conditions with Undef

**Description:**
The bug occurs when the compiler infers value ranges or properties of a `select` instruction's result based on its condition. The optimization logic assumes that if the true (or false) branch of a `select` is chosen, the condition must hold true (or false), and thus the selected value strictly satisfies the constraints implied by the condition.

However, this assumption is unsound if the condition can evaluate to `undef`. When the condition is `undef`, it can non-deterministically evaluate to `true` or `false` at runtime, regardless of the actual values of the variables involved in the condition. Consequently, the `select` instruction might return a value from a branch even if the underlying variables do not actually satisfy the condition.

By intersecting the value range of the true/false values with the constraints derived from the potentially `undef` condition, the compiler deduces an overly restrictive and incorrect range for the `select` result. This flawed range analysis can then trigger invalid downstream optimizations, such as incorrectly replacing a sign-extension (`sext`) with a zero-extension (`zext`), or improperly eliminating bounds checks, leading to a miscompilation.

To trigger this bug, the following pattern can be used:
1. Construct a `select` instruction where the condition is a relational or logical expression involving certain variables (e.g., `x > c`).
2. Use those same variables in the true or false values of the `select` (e.g., returning `x` when the condition is true).
3. Allow the variables to be `undef`, making the condition potentially `undef`.
4. Use the result of the `select` in an operation that can be optimized based on value ranges (e.g., a sign-extension, zero-extension, or a comparison).
5. The compiler will incorrectly optimize the subsequent operation by assuming the `select` result strictly adheres to the condition's constraints, failing to account for the non-deterministic `undef` behavior.

---

# Issue 68381

## Incorrect Constant Range Inference for `undef` Values

**Description**:
The bug is triggered by exploiting how the compiler's value analysis handles `undef` values when computing constant ranges. The strategy involves the following steps:

1. **Introduce an `undef` Value**: Construct a control flow graph containing a PHI node (or a similar merging construct) where one incoming value is a bounded value (e.g., a variable zero-extended from a smaller integer type) and another incoming value is explicitly `undef`.
2. **Perform Range-Dependent Operations**: Use the result of this PHI node in subsequent operations that are typically targeted by range-based optimizations, such as bitwise masking (e.g., `and`), absolute value calculations, or bounds checks.
3. **Trigger Incorrect Range Analysis**: The compiler's value analysis evaluates the range of the PHI node. Instead of recognizing that `undef` can represent *any* possible value of that type (which should result in a full, unrestricted range), the analysis incorrectly ignores the `undef` or assumes it conforms to the restricted range of the other incoming bounded value.
4. **Erroneous Optimization**: Because the analysis infers an artificially narrow constant range for the PHI node, subsequent optimization passes (like correlated value propagation) operate under the false assumption that the value will never exceed this narrow range.
5. **Miscompilation**: Relying on this flawed assumption, the optimizer erroneously removes instructions that it deems redundant—such as a masking operation that clears upper bits or a conditional branch checking the value's bounds. Since the `undef` could actually take a value outside the inferred range at runtime, removing these necessary instructions leads to a miscompilation.
