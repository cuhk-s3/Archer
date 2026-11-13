# Issue 114947

## Incorrect Constant Folding of Denormal Floating-Point Values Due to Unhandled Contexts and Vector Types

**Description**:
The bug involves a miscompilation during the constant folding of floating-point operations (such as comparisons or binary operations) that operate on denormal floating-point constants.

When a function is configured with a non-IEEE denormal handling mode (e.g., `dynamic`, `preserve-sign`, or flush-to-zero), denormal values may be flushed to zero at runtime. However, the compiler's constant folding logic may fail to apply this flushing behavior and incorrectly evaluate the operation using the exact denormal values. This discrepancy leads to a mismatch between the compile-time folded result and the actual runtime execution.

This incorrect transformation is triggered in two primary scenarios:

1. **Missing Instruction Context**: When the constant folding logic is invoked without a specific instruction context (e.g., the instruction pointer is null or unknown during certain optimization passes), the compiler cannot determine the function's specific denormal mode. Instead of conservatively aborting the fold when the mode is unknown, the compiler incorrectly defaulted to assuming strict IEEE behavior (preserving denormals).
2. **Vector Constants**: The internal logic responsible for flushing denormal constants was previously limited to scalar floating-point types. If the operation involved vector constants containing denormals, the compiler bypassed the flushing logic entirely. It assumed strict IEEE behavior for all vector types, even when the instruction context was available and explicitly specified a non-IEEE denormal mode.

By assuming IEEE semantics in these cases, the compiler folds the operations based on non-zero denormal values (e.g., evaluating a comparison between a denormal and zero as "not equal"). Meanwhile, the target hardware might flush the denormal to zero, which would change the correct runtime result (e.g., making the comparison "equal").

---

# Issue 81793

## Constant Folding of Loads from Memory with Padded Types

**Description**:
The bug is triggered when the compiler attempts to constant-fold a load instruction that reads from a memory location initialized or stored with a uniform constant (e.g., all ones) of a type that requires padding in memory. This occurs when a type's bit size is not equal to its store size (for example, an `i9` type which occupies 16 bits in memory).

In such cases, the padding bits are technically undefined or zero-extended by the backend. However, the optimization logic incorrectly assumes that the entire memory representation, including the padding bits, shares the same uniform pattern as the valid bits of the constant. Consequently, when a value is loaded from this memory location—especially on big-endian targets where the load might directly read the padding bits—the compiler erroneously folds the load into a uniform constant.

The strategy to trigger this miscompilation involves storing a uniform constant of a non-byte-aligned (padded) type and subsequently loading a value from that same memory location, causing the compiler to incorrectly evaluate the load based on the uninitialized or zeroed padding bits.

---

# Issue 98665

## Incorrect Result Type During Constant Folding of Floating-Point Intrinsics

**Description**:
The bug is triggered when the compiler attempts to constant-fold a math intrinsic (such as a power function) that operates on a lower-precision floating-point type (e.g., `half` / `f16`).

During the evaluation of the constant expression, the folding logic computes the mathematical result using a higher-precision floating-point type (e.g., `float` or `double`). However, it fails to properly convert or truncate the computed value back to the original lower-precision type before constructing the resulting constant.

As a result, the intrinsic call is replaced with a constant of an incorrect, wider type. This type mismatch corrupts the LLVM IR, leading to severe downstream issues. For example, storing the incorrectly typed constant can cause out-of-bounds memory writes, and subsequent passes may incorrectly fold operations (like floating-point comparisons) due to the unexpected type or value representation. To trigger this issue, one simply needs to provide an IR containing a constant-foldable floating-point intrinsic call that uses a lower-precision type.
