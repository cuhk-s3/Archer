# Issue 112356

## Unrecognized Poison-Generating Flags on Compare Instructions

**Description**:
The bug is triggered by utilizing a compare instruction with a poison-generating flag (such as `samesign`) within a conditionally executed context, like a `select` instruction or a conditional branch.

When optimizations attempt to simplify the control flow or conditional operations, they may bypass the condition and unconditionally evaluate or return the result of the compare instruction. Because the compiler's analysis fails to recognize that this specific flag can generate poison when its semantic conditions are violated (e.g., operands having different signs), it incorrectly assumes the instruction is safe to hoist or evaluate unconditionally. This leads to a miscompilation where the optimized program yields a poison value instead of a well-defined result under circumstances where the original condition would have prevented the poison from being observed.

---

# Issue 114191

## Eager Poison Folding of Vector Division/Remainder Threaded Over Select

The bug is triggered by a vector integer division or remainder instruction where the divisor is a `select` instruction. The `select` chooses between two constant vectors, and at least one of these constant vectors contains a zero or `undef` element.

When the compiler attempts to optimize this pattern by threading the division or remainder operation over the `select`, it evaluates the operation against each constant vector independently. During this process, if the simplification logic encounters a constant vector with a zero or `undef` element as the divisor, it eagerly folds the entire division or remainder operation for that vector into `poison` (due to division by zero being undefined behavior).

This transformation is incorrect because the zero or `undef` element might be masked out by the `select` condition at runtime. By unconditionally folding the operation to `poison`, the compiler introduces a miscompilation, as the `poison` value propagates to the final result even when the division by zero would not have dynamically occurred.

---

# Issue 120932

## Incorrect Memory Effect Inference for Volatile Memory Intrinsics

**Description**:
The bug is triggered by the following sequence of conditions and transformations:
1. A function is defined containing a volatile memory intrinsic (such as a volatile `memcpy`, `memset`, or `memmove`).
2. The explicit pointer arguments of this volatile intrinsic are constrained to memory locations that typically do not produce observable side effects from the caller's perspective. For example, the pointers might reference strictly local allocations (`alloca`) or constant global variables.
3. When the compiler's interprocedural analysis evaluates the function to infer its memory effects, it examines these explicit memory accesses. Because the accessed memory is purely local or constant, the analysis deduces that the operations do not affect any globally observable state.
4. However, the analysis fails to account for the inherent semantics of `volatile` operations. According to the language reference, volatile operations can implicitly read or modify state that is not accessible via regular memory operations (often modeled as "inaccessible memory").
5. As a result of ignoring the volatile qualifier, the compiler erroneously annotates the function with an attribute indicating it has no memory effects whatsoever (e.g., `memory(none)`).
6. This incorrect attribute allows subsequent optimization passes to treat calls to this function as having no side effects, potentially leading to the calls being incorrectly eliminated as dead code, reordered, or hoisted, which results in a miscompilation.

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

# Issue 59301

## Incorrect `nsw` (No Signed Wrap) Inference for 1-bit Integer Multiplication

**Description**:
The bug is triggered when the compiler attempts to deduce and attach the `nsw` (no signed wrap) flag to a 1-bit integer multiplication (`mul i1`).

The optimization logic incorrectly assumes that multiplying a value by `1` will never result in a signed overflow, which is a valid assumption for wider integer types. However, for 1-bit integers, the representable signed value range is `[-1, 0]`, and the bit pattern for `1` actually represents `-1`. When multiplying `-1` by `-1` (i.e., `1 * 1` in 1-bit arithmetic), the true mathematical result is `1`. Because `1` falls outside the representable 1-bit signed range of `[-1, 0]`, the operation inherently experiences a signed overflow.

By erroneously assuming no overflow can occur and adding the `nsw` flag, the compiler introduces poison values when the operands evaluate to `1`. To trigger this miscompilation, one needs to construct an LLVM IR containing a 1-bit multiplication where the operands can be `1`, and then run an optimization pass (such as correlated value propagation) that infers overflow flags based on constant ranges.

---

# Issue 59887

## Incorrect Constant Range Calculation for 1-Bit Absolute Value

The bug is triggered when the compiler attempts to compute the constant range for an absolute value operation on a 1-bit integer.

When the input range of the operation contains both negative and non-negative values (i.e., it crosses zero, which is the case for a full 1-bit range), the compiler calculates the upper bound of the resulting absolute value range by finding the maximum possible absolute value and adding one. However, for a 1-bit integer, adding one to the maximum absolute value causes an overflow, wrapping the upper bound back to zero.

This wrap-around causes the compiler's range analysis to incorrectly construct an empty constant range instead of a full range. Consequently, optimization passes that rely on these ranges (such as Correlated Value Propagation) misinterpret the empty range and incorrectly fold the operation or subsequent dependent instructions into a constant (e.g., `false` or `0`), leading to a miscompilation.

---

# Issue 61984

## Incorrect Elimination of Bitcast Between Same-Width Floating-Point Types

**Description:**
The bug is triggered by a sequence of cast instructions involving floating-point types that share the same bit width but have different internal representations (such as `bfloat` and `half`). Specifically, the pattern consists of a `bitcast` instruction converting a value from one floating-point type to another of the same width, immediately followed by a floating-point cast instruction (such as a floating-point extension or truncation).

The compiler's optimization logic incorrectly assumes that a `bitcast` between any two floating-point types of the same size is a semantic no-op. Based on this flawed assumption, it attempts to optimize the cast pair by eliminating the `bitcast` entirely and applying the second floating-point cast directly to the original source type.

However, because the source and destination types of the `bitcast` have different binary representations (e.g., different allocations for exponent and mantissa bits), the `bitcast` fundamentally alters the interpreted numerical value. Bypassing the `bitcast` and directly casting the original type leads to an incorrect conversion. This causes subsequent operations, such as constant folding or comparisons, to operate on the wrong numerical value, ultimately resulting in a miscompilation.

---

# Issue 97600

## Incorrect Handling of Non-Pointer to Pointer Casts in Pointer Stripping Logic

**Description**

The bug is triggered when a pointer cast instruction (such as a `bitcast`) converts a non-scalar-pointer type—like a vector of pointers (e.g., `<1 x ptr>`)—into a scalar pointer type.

When compiler analysis passes attempt to find the underlying object of a memory location or strip away pointer casts, they iteratively look through cast instructions. If the source operand of a cast is not a scalar pointer type, the stripping logic is supposed to halt and return the current scalar pointer. However, due to a flaw in the logic, the analysis incorrectly returns the non-pointer source operand (e.g., the vector of pointers) instead of the scalar pointer.

Because downstream analyses, such as Alias Analysis, strictly expect the underlying object of a memory operation to be a scalar pointer, receiving a non-pointer type causes them to behave unpredictably. In this scenario, the analysis fails to properly evaluate the memory locations and defaults to incorrect assumptions, such as concluding that two memory accesses do not alias (`NoAlias`).

This flawed aliasing information is subsequently consumed by optimization passes like Loop Invariant Code Motion (LICM). Believing that there are no memory dependencies, the optimizer may illegally hoist or sink memory operations (like `store` instructions) out of loops. This results in a miscompilation where memory is not updated correctly during program execution.
