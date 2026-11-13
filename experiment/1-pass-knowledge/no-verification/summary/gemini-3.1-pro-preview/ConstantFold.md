# Subsystem Knowledge for ConstantFold
## Elements Frequently Missed

*   **Instruction Contexts and Function Attributes**: The specific instruction context (e.g., the instruction pointer) is frequently missed or unavailable during constant folding. Without it, the compiler cannot query function-level attributes (such as non-IEEE denormal handling modes like flush-to-zero) and incorrectly defaults to strict IEEE assumptions.
*   **Vector Type Equivalents of Scalar Logic**: Optimization logic is often implemented for scalar types but completely missed for vector types. For example, internal logic to flush denormal floating-point constants was applied to scalars but bypassed for vectors, causing inconsistent and incorrect folding for vector operations.
*   **Padding Bits in Memory Layouts**: The distinction between a type's bit size and its actual store size in memory (e.g., an `i9` type occupying 16 bits) is frequently missed. The compiler fails to account for the fact that padding bits are undefined or zero-extended, incorrectly assuming they share the same uniform pattern as the valid data bits.
*   **Original Type Precision in Intermediate Calculations**: When evaluating math intrinsics, the compiler frequently misses the final step of truncating or converting the computed result back to the original lower-precision type (e.g., `half` or `f16`) after performing intermediate calculations in a higher-precision host type (e.g., `float` or `double`).

## Patterns Not Well Handled

### Pattern 1: Context-Dependent Floating-Point Evaluation
The optimization pass struggles to correctly fold floating-point operations when the runtime behavior deviates from standard IEEE semantics due to specific function attributes or hardware modes (e.g., dynamic or preserve-sign denormal handling). When the instruction context is missing, or when the operation involves vector constants, the compiler falls back to strict IEEE semantics. This causes a critical mismatch between the compile-time folded result (which evaluates using exact denormal values) and the actual runtime execution (which may flush denormals to zero), leading to miscompiled comparisons and binary operations.

### Pattern 2: Memory-Level Constant Folding of Padded Types
The pass does not well handle the constant folding of load instructions that read from memory initialized with uniform constants of non-byte-aligned types (types where the bit size does not equal the store size). The folding logic erroneously assumes that the entire memory representation, including the padding bits, matches the uniform pattern of the valid bits. When a value is subsequently loaded from this memory—especially on big-endian targets where the load might directly read the padding bits—the compiler evaluates the load based on uninitialized or zeroed padding bits, resulting in an incorrect constant fold.

### Pattern 3: Type-Preservation in Mathematical Intrinsic Folding
The pass fails to maintain strict type consistency when evaluating mathematical intrinsics (such as power functions) on lower-precision floating-point types. To maintain accuracy, the folding logic computes the mathematical result using a higher-precision type. However, it fails to properly convert the result back to the original lower-precision type before constructing the resulting constant in the IR. This pattern of precision-changing evaluation corrupts the LLVM IR with type mismatches, which causes severe downstream issues such as out-of-bounds memory writes and incorrect subsequent optimizations.
