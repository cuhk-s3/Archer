# Issue 112356

## Summary Title
Missing Poison-Generating Flag Check for `icmp samesign` Instructions

## Description
The bug is triggered when the optimizer transforms `icmp` instructions that utilize the `samesign` attribute. In LLVM IR, the `samesign` keyword specifies that the comparison yields a poison value if the operands do not have the same sign. The compiler's analysis logic, responsible for identifying instructions that can generate poison, failed to check for the presence of the `samesign` flag on integer comparisons.

As a result, optimization passes incorrectly treated these instructions as unconditionally safe and well-defined. This incorrect assumption allowed the compiler to perform transformations—such as simplifying `select` instructions or speculating execution—that are only valid for operations that do not generate poison. This led to miscompilations where the transformed code produced poison for specific inputs (due to sign mismatches) where the original code produced a defined value, effectively introducing undefined behavior.

## Example

### Original IR
```llvm
define i1 @test_samesign_poison_check(i32 %a, i32 %b, i1 %cond) {
  %cmp = icmp samesign ult i32 %a, %b
  %res = select i1 %cond, i1 %cmp, i1 false
  ret i1 %res
}
```
### Optimized IR
```llvm
define i1 @test_samesign_poison_check(i32 %a, i32 %b, i1 %cond) {
  %cmp = icmp samesign ult i32 %a, %b
  %res = and i1 %cond, %cmp
  ret i1 %res
}
```


---

# Issue 137582

## Speculative Execution Analysis Ignores UB-Implying Attributes on Call Instructions

## Description
The bug is triggered when the compiler's value tracking analysis attempts to reason about the value of a call instruction (such as an intrinsic) by walking up its definition chain. To perform this analysis safely, the compiler checks if the instruction is "safe to speculatively execute," meaning it can be evaluated or hoisted without introducing side effects or undefined behavior.

The flaw arises because the safety check for call instructions only verified that the function was generally `speculatable` (e.g., having properties like `readnone` or `nounwind`), but failed to account for attributes that imply immediate Undefined Behavior (UB), such as `noundef` on return values or parameters. An instruction with `noundef` attributes triggers UB if it processes or returns a `poison` value. By overlooking this, the analysis incorrectly classified these calls as safe to speculate. This allowed the compiler to infer constraints or apply optimizations (such as adding `nsw` or `nuw` flags to operands) based on the assumption that the instruction would execute safely. However, if the operands were `poison` (which is valid in the source if the instruction doesn't trigger UB), the speculated instruction in the target would trigger UB due to the `noundef` attribute, resulting in a miscompilation.

## Example

### Original IR
```llvm
define i32 @test_speculation_noundef(i1 %cond, i32 %x) {
entry:
  br i1 %cond, label %if.then, label %if.end

if.then:
  ; The 'noundef' attribute on the return value implies immediate UB if the result is poison.
  ; However, 'readnone' and 'nounwind' make the function appear safe to speculate.
  %call = call noundef i32 @func(i32 %x) #0
  br label %if.end

if.end:
  %res = phi i32 [ %call, %if.then ], [ 0, %entry ]
  ret i32 %res
}

declare i32 @func(i32) 
attributes #0 = { readnone nounwind }
```
### Optimized IR
```llvm
define i32 @test_speculation_noundef(i1 %cond, i32 %x) {
entry:
  ; The compiler incorrectly speculates (hoists) the call because it ignores the 'noundef' attribute.
  ; If %x is poison, this hoisted call triggers UB immediately, even if %cond is false.
  %call = call noundef i32 @func(i32 %x) #0
  %res = select i1 %cond, i32 %call, i32 0
  ret i32 %res
}

declare i32 @func(i32) 
attributes #0 = { readnone nounwind }
```


---

# Issue 59301

## Incorrect NSW Inference for 1-bit Integer Multiplication

**Description**
The bug is triggered when the compiler analyzes integer multiplication instructions (`mul`) operating on 1-bit integers (`i1`) to determine if the `nsw` (No Signed Wrap) flag can be added. The analysis logic incorrectly assumes that multiplying by the constant `1` is always safe from signed overflow, treating it as the multiplicative identity. However, for a 1-bit integer type, the bit pattern `1` represents the signed value `-1`. Multiplying `1` by `1` in this context is mathematically `(-1) * (-1) = +1`, which exceeds the range of a 1-bit signed integer (which can only represent `0` and `-1`). The compiler overlooks this corner case for 1-bit types and incorrectly annotates the multiplication with `nsw`, causing the instruction to yield a `poison` value instead of the correct wrapped result when executed.

## Example

### Original IR
```llvm
define i1 @test_mul_i1_nsw(i1 %a) {
  %res = mul i1 %a, 1
  ret i1 %res
}
```
### Optimized IR
```llvm
define i1 @test_mul_i1_nsw(i1 %a) {
  %res = mul nsw i1 %a, 1
  ret i1 %res
}
```


---

# Issue 59887

## Incorrect Range Analysis for 1-bit Absolute Value

**Description**
The bug is triggered during value range analysis of the absolute value operation (`llvm.abs`) when the operand is a 1-bit integer. When the input range to the `abs` function includes both zero and negative values (which represents the full range of a 1-bit integer), the compiler calculates the result's upper bound by incrementing the maximum absolute value of the input. Due to the 1-bit width, adding one to the maximum value (1) causes an overflow, wrapping the upper bound back to 0. This results in a range where the lower and upper bounds are identical (e.g., `[0, 0)`). The compiler incorrectly interprets this as an empty range—implying the result is impossible—rather than a full range containing all possible values. Optimization passes, such as Correlated Value Propagation (CVP), use this erroneous "empty" range information to incorrectly replace the function call with a constant zero or optimize away the code.

## Example

### Original IR
```llvm
define i1 @test_abs_i1(i1 %x) {
  %res = call i1 @llvm.abs.i1(i1 %x, i1 false)
  ret i1 %res
}

declare i1 @llvm.abs.i1(i1, i1)
```
### Optimized IR
```llvm
define i1 @test_abs_i1(i1 %x) {
  ret i1 false
}
```


---

# Issue 61984

## Incorrect Folding of Bitcast and Floating-Point Cast Sequences

**Description**
The bug is triggered when the optimizer encounters a sequence of two cast instructions involving floating-point types. Specifically, the sequence consists of a `bitcast` instruction converting between two different floating-point types of the same bit width (e.g., `bfloat` to `half` or vice versa), followed immediately by a floating-point conversion instruction (such as `fpext` or `fptrunc`).

The optimization logic incorrectly identifies this pair of casts as eliminable. It assumes that because the bit width is unchanged by the `bitcast`, the intermediate cast can be removed, and the operation can be reduced to a single floating-point cast from the initial source type to the final destination type.

This transformation is invalid because `bitcast` preserves the bit pattern but changes the semantic interpretation of those bits (e.g., how the exponent and mantissa are defined), whereas floating-point casts perform value-preserving conversions based on the input type's semantics. By eliminating the `bitcast`, the optimizer forces the subsequent cast to interpret the bits according to the original source format rather than the reinterpreted intermediate format. Since the two floating-point formats have different internal representations, this results in the computation of an incorrect numeric value.

## Example

### Original IR
```llvm
define float @test_incorrect_fold(bfloat %src) {
  %1 = bitcast bfloat %src to half
  %2 = fpext half %1 to float
  ret float %2
}
```
### Optimized IR
```llvm
define float @test_incorrect_fold(bfloat %src) {
  %1 = fpext bfloat %src to float
  ret float %1
}
```
