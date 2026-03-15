# Issue 114947

## Incorrect Constant Folding of Denormal Floating-Point Values Due to Unhandled Contexts and Vector Types

**Description**:
The bug involves a miscompilation during the constant folding of floating-point operations (such as comparisons or binary operations) that operate on denormal floating-point constants.

When a function is configured with a non-IEEE denormal handling mode (e.g., `dynamic`, `preserve-sign`, or flush-to-zero), denormal values may be flushed to zero at runtime. However, the compiler's constant folding logic may fail to apply this flushing behavior and incorrectly evaluate the operation using the exact denormal values. This discrepancy leads to a mismatch between the compile-time folded result and the actual runtime execution.

This incorrect transformation is triggered in two primary scenarios:

1. **Missing Instruction Context**: When the constant folding logic is invoked without a specific instruction context (e.g., the instruction pointer is null or unknown during certain optimization passes), the compiler cannot determine the function's specific denormal mode. Instead of conservatively aborting the fold when the mode is unknown, the compiler incorrectly defaulted to assuming strict IEEE behavior (preserving denormals).
2. **Vector Constants**: The internal logic responsible for flushing denormal constants was previously limited to scalar floating-point types. If the operation involved vector constants containing denormals, the compiler bypassed the flushing logic entirely. It assumed strict IEEE behavior for all vector types, even when the instruction context was available and explicitly specified a non-IEEE denormal mode.

By assuming IEEE semantics in these cases, the compiler folds the operations based on non-zero denormal values (e.g., evaluating a comparison between a denormal and zero as "not equal"). Meanwhile, the target hardware might flush the denormal to zero, which would change the correct runtime result (e.g., making the comparison "equal").

## Example

### Original IR
```llvm
define <2 x i1> @test_vector_denormal_fold() #0 {
entry:
  ; 0x3800000000000000 is the double-precision hex representation of the single-precision denormal value 2^-127.
  ; With "denormal-fp-math"="preserve-sign", this denormal should be flushed to zero, making the comparison true.
  %cmp = fcmp oeq <2 x float> <float 0x3800000000000000, float 0x3800000000000000>, zeroinitializer
  ret <2 x i1> %cmp
}

attributes #0 = { "denormal-fp-math"="preserve-sign" }
```
### Optimized IR
```llvm
define <2 x i1> @test_vector_denormal_fold() #0 {
entry:
  ; The compiler incorrectly assumes strict IEEE behavior for vector types and folds the comparison to false,
  ; bypassing the denormal flushing logic that should have evaluated it to true (<i1 true, i1 true>).
  ret <2 x i1> zeroinitializer
}

attributes #0 = { "denormal-fp-math"="preserve-sign" }
```
