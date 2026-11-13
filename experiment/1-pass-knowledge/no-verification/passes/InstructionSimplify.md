# Issue 114191

## Eager Poison Folding of Vector Division/Remainder Threaded Over Select

The bug is triggered by a vector integer division or remainder instruction where the divisor is a `select` instruction. The `select` chooses between two constant vectors, and at least one of these constant vectors contains a zero or `undef` element.

When the compiler attempts to optimize this pattern by threading the division or remainder operation over the `select`, it evaluates the operation against each constant vector independently. During this process, if the simplification logic encounters a constant vector with a zero or `undef` element as the divisor, it eagerly folds the entire division or remainder operation for that vector into `poison` (due to division by zero being undefined behavior).

This transformation is incorrect because the zero or `undef` element might be masked out by the `select` condition at runtime. By unconditionally folding the operation to `poison`, the compiler introduces a miscompilation, as the `poison` value propagates to the final result even when the division by zero would not have dynamically occurred.

---

# Issue 115574

## Invalid Pointer Substitution Based on Equality Comparison

**Description**:
The bug is triggered when the compiler simplifies a `select` instruction whose condition is an equality comparison (`icmp eq`) between two pointers. The optimization logic assumes that if two pointers compare equal, they are strictly equivalent and can be freely substituted for one another. Consequently, it replaces one pointer with the other in the arms of the `select` (or within expressions evaluated in the arms).

However, in LLVM IR, pointers are not just addresses; they also carry provenance information (i.e., which memory allocation they belong to). Two pointers can have the exact same address (e.g., one pointing to the end of an allocation and another to the beginning of an adjacent one) but possess entirely different provenance. Substituting one pointer for another based solely on address equality can incorrectly change the provenance of the pointer returned by the `select`. This loss or alteration of provenance information violates the memory model and can lead to miscompilations in subsequent memory alias analyses or memory access optimizations.

---

# Issue 138819

## Incorrect Idempotency Assumption for Multi-Return Intrinsics

**Description**:
The bug is triggered when the compiler incorrectly assumes that an operation returning multiple values (such as a struct containing a normalized value and an associated scale or exponent) is fully idempotent.

When the operation is applied to the primary result of a previous identical operation, the compiler's simplification logic folds the second call entirely into the first one, returning the exact same multi-value result. However, this transformation is invalid. While the primary result (the normalized value) is indeed idempotent and remains unchanged, the secondary result (the scale or exponent) changes upon repeated application. Because the input to the second operation is already normalized, its secondary result should evaluate to a specific constant (e.g., zero), rather than the variable secondary result produced by the first operation. By replacing the second call with the first call's unmodified result, the compiler introduces a miscompilation where the secondary return value is incorrect.

---

# Issue 58977

## Incorrect Logic Fold with Partial Undef Vector in Bitwise NOT Matching

**Description**:
The bug is triggered by providing a vector logical expression that matches a specific simplification pattern involving a bitwise NOT operation (for example, the pattern `(B ^ ~A) | (A & B) --> B ^ ~A`).

In LLVM IR, a bitwise NOT is typically represented as an XOR instruction with an all-ones constant. To trigger the miscompilation, the all-ones vector constant used in the XOR must contain `undef` elements (a partial undef vector).

When the compiler's simplification logic matches this XOR instruction as a strict bitwise NOT, it proceeds to apply the logical fold. However, because of the `undef` lanes, the XOR does not strictly behave as a bitwise NOT for those specific lanes. This breaks the fundamental logical identity required for the transformation. As a result, the compiler replaces the original expression with a simplified version that is semantically inequivalent, potentially evaluating to a different value or becoming more undefined than the original source expression.

---

# Issue 61312

## Incorrect Context Instruction when Threading Binary Operations over PHI Nodes

**Description**:
The bug occurs during the simplification of binary operations that use a PHI node as one of their operands. The compiler attempts to optimize the binary operation by "threading" it over the PHI node, which involves evaluating the binary operation independently for each incoming value of the PHI node. If the operation simplifies to the exact same common result for all incoming values, the compiler replaces the original binary operation with that common result.

The flaw lies in the context instruction used during this simplification process. Instead of using the terminator instruction of the specific incoming basic block as the context for evaluating each incoming value, the compiler incorrectly uses the original context (typically the binary operation itself or the PHI node).

This leads to the following incorrect transformation logic:
1. **Mismatched Contextual Facts**: Context-sensitive analyses (such as computing known bits, value ranges, or dominating branch conditions) rely on the context instruction to determine what facts are true at a given point in the IR. By using the binary operation's context, the compiler applies facts that are true at the binary operation's location to incoming values that originate from different basic blocks where those facts do not necessarily hold.
2. **Conflicting Assumptions**: For instance, if the binary operation is located after a loop or a conditional branch, its context includes the conditions required to reach that location (e.g., a loop exit condition). When evaluating an incoming value that was computed *inside* the loop body or on a specific branch path, the compiler incorrectly applies the post-loop/post-branch conditions to it. This mixes the state of the merged execution path with the computation of a specific, isolated incoming path.
3. **Spurious Common Values**: Due to these incorrect assumptions, the binary operation might spuriously simplify to the same constant or value for all incoming paths (often due to coincidental mathematical equivalences under the wrong assumptions). The compiler then incorrectly concludes that the binary operation always yields this common value and replaces it, resulting in a miscompilation.

To correctly perform this transformation, the context instruction must be adjusted to the terminator of the incoming block, ensuring that only the facts and conditions valid for that specific incoming path are used during simplification.

---

# Issue 64339

## Incorrect Simplification of `AND` with Power-of-Two Constant and Decremented Value

**Description**:
The bug is triggered by a bitwise `and` instruction where one operand is a constant power of two, and the other operand is an expression of the form `X - 1` (represented in IR as `X + (-1)`).

The compiler attempts to optimize this pattern by checking if `X` is a power of two. If `X` is a strictly positive power of two, `X - 1` forms a contiguous bitmask of lower bits (e.g., `8 - 1 = 7`, which is `0b111` in binary). The compiler can then determine the result of the `and` operation based on the relative bit positions of `X` and the constant power of two, often folding it to zero if the constant's set bit falls outside the mask.

However, the compiler's analysis incorrectly allowed `X` to be zero (i.e., checking if `X` is "a power of two *or zero*"). If `X` is zero, `X - 1` evaluates to `-1` (where all bits are set to 1). In this scenario, `-1 & Constant` should simply evaluate to the `Constant`. Because the optimization logic assumed `X - 1` behaved strictly as a lower-bit mask, it incorrectly evaluated the bitwise intersection and erroneously folded the entire `and` expression to zero.

To trigger this bug, a program must construct an `and` operation matching this pattern where `X` is known by the compiler's analysis to be either a power of two or zero, and `X` actually evaluates to zero at runtime. The compiler will incorrectly optimize the expression to zero instead of the expected constant, leading to a miscompilation.

---

# Issue 68683

## Incorrect Simplification of PHI Nodes with Undef and Potentially Poisonous Inputs

**Description**:
The bug is triggered by a PHI node that receives a mix of `undef` and a common value `X` from its incoming edges. The compiler's simplification logic attempts to fold the PHI node directly to the common value `X` by ignoring the `undef` inputs.

However, this transformation is invalid if `X` is not statically guaranteed to be free of `poison`. In LLVM IR, replacing an `undef` value with `poison` is not a valid refinement, because `poison` is a stronger, more restrictive state that can propagate and lead to undefined behavior. By folding the PHI node to `X`, the compiler inadvertently makes the result more poisonous on the control flow paths that originally provided `undef`.

To trigger this miscompilation, one can construct a control flow graph containing a PHI node where at least one incoming edge provides `undef`, and the other edges provide a common value that could potentially evaluate to `poison` at runtime. The optimization pass will incorrectly delete the PHI node and replace its uses with the potentially poisonous value.

---

# Issue 77320

## Incorrect Simplification of Vector Select Involving Cross-Lane Bitcasts

**Description**:
The bug is triggered when the compiler attempts to simplify a vector `select` instruction by exploiting the equivalence implied by its vector condition (e.g., an element-wise equality comparison). The optimization logic tries to replace occurrences of one compared operand with the other within the computation of the selected values, assuming that the equivalence holds on a strictly per-lane basis.

However, if the def-use chain of the selected value includes a `bitcast` instruction that changes the number of vector lanes (e.g., casting between vectors with different element sizes but the same total bit width), the operation is no longer strictly per-lane. A `bitcast` that alters the lane count effectively mixes data across the original lanes, making it a cross-lane operation.

The compiler fails to recognize such `bitcast` instructions as cross-lane operations. Consequently, it incorrectly propagates the per-lane equivalence through the `bitcast`, replacing operands and simplifying the computation (e.g., incorrectly folding a subtraction to zero) even when the condition might only be true for a subset of the original lanes. This invalid assumption breaks the per-lane semantics of the vector `select`, leading to an incorrect fold and miscompilation of the selected value.

---

# Issue 81793

## Constant Folding of Loads from Memory with Padded Types

**Description**:
The bug is triggered when the compiler attempts to constant-fold a load instruction that reads from a memory location initialized or stored with a uniform constant (e.g., all ones) of a type that requires padding in memory. This occurs when a type's bit size is not equal to its store size (for example, an `i9` type which occupies 16 bits in memory).

In such cases, the padding bits are technically undefined or zero-extended by the backend. However, the optimization logic incorrectly assumes that the entire memory representation, including the padding bits, shares the same uniform pattern as the valid bits of the constant. Consequently, when a value is loaded from this memory location—especially on big-endian targets where the load might directly read the padding bits—the compiler erroneously folds the load into a uniform constant.

The strategy to trigger this miscompilation involves storing a uniform constant of a non-byte-aligned (padded) type and subsequently loading a value from that same memory location, causing the compiler to incorrectly evaluate the load based on the uninitialized or zeroed padding bits.
