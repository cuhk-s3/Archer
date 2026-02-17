# Issue 112350

## Incorrect Inversion Analysis for Comparisons with Mismatched `samesign` Flags

**Description**
The bug is triggered when the compiler analyzes two integer comparison instructions to determine if they are logical inverses of each other. The analysis correctly identifies that the comparison predicates are inverses (e.g., `ult` vs `uge`) but fails to check for consistency in the `samesign` optimization flag. If one comparison has the `samesign` flag enabled while the other does not, the flagged instruction yields `poison` for operands with differing signs, whereas the unflagged instruction yields a defined boolean result. By incorrectly classifying these as inverses, the compiler permits transformations (such as converting a `select` to arithmetic logic) that replace a valid, defined result with `poison`, resulting in undefined behavior.

## Example

### Original IR
```llvm
define i32 @test_inversion_bug(i8 %x, i8 %y) {
  %cmp_samesign = icmp samesign ult i8 %x, %y
  %cmp_normal = icmp uge i8 %x, %y
  %result = select i1 %cmp_normal, i32 1, i32 0
  call void @use(i1 %cmp_samesign)
  ret i32 %result
}

declare void @use(i1)
```
### Optimized IR
```llvm
define i32 @test_inversion_bug(i8 %x, i8 %y) {
  %cmp_samesign = icmp samesign ult i8 %x, %y
  %result = select i1 %cmp_samesign, i32 0, i32 1
  call void @use(i1 %cmp_samesign)
  ret i32 %result
}

declare void @use(i1)
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

# Issue 141017

## Incorrect Usage of Floating-Point Comparison Flags in Select Analysis

**Description**
The bug is triggered when the compiler analyzes a `select` instruction controlled by a floating-point comparison (`fcmp`). The analysis logic incorrectly applies the Fast Math Flags (FMF) present on the comparison instruction—such as `nsz` (No Signed Zeros)—to the `select` instruction itself. While these flags allow the comparison to ignore certain floating-point distinctions (like the sign of zero) when computing the condition, they do not grant permission to alter the values returned by the `select`. By conflating the comparison's relaxed semantics with the selection's semantics, the compiler may misidentify the code as a pattern (e.g., a min/max idiom) that is allowed to ignore signed zeros. This leads to invalid transformations where the optimized code produces a result with the wrong sign (e.g., returning `-0.0` instead of `+0.0`), violating the strict floating-point requirements of the original `select` instruction.

## Example

### Original IR
```llvm
define float @test_min_nsz(float %a, float %b) {
  %cmp = fcmp nsz olt float %a, %b
  %val = select i1 %cmp, float %a, float %b
  ret float %val
}
```
### Optimized IR
```llvm
define float @test_min_nsz(float %a, float %b) {
  %val = call float @llvm.minnum.f32(float %a, float %b)
  ret float %val
}

declare float @llvm.minnum.f32(float, float)
```


---

# Issue 143123

## Incorrect Handling of Ordered Comparisons in Select Patterns with Fast Math Flags

**Description:**
The bug occurs in the compiler's value tracking analysis when identifying floating-point minimum or maximum patterns formed by a `select` instruction and a comparison (`fcmp`). The issue arises when the `select` instruction carries the `nnan` (No NaN) Fast Math Flag, but the controlling `fcmp` instruction does not.

The analysis logic uses the `nnan` flag on the `select` to assume that the operands are "safe" (i.e., not NaN). Based on this assumption, it neglects to capture the "ordered" property of the comparison predicate (which dictates that the comparison is false if an operand is NaN). However, the `nnan` flag on the `select` only implies that the result is poison if an operand is NaN; it does not guarantee that the input to the `fcmp` is non-NaN. By dropping the ordered constraint, the compiler treats the pattern as if NaN behavior is irrelevant. This allows invalid transformations, such as inverting the condition and swapping operands, which fail to preserve the original behavior (where an ordered comparison returns false for NaN), leading to a value mismatch when a NaN input is encountered.

## Example

### Original IR
```llvm
define float @min_select_nnan(float %a, float %b) {
  %cmp = fcmp olt float %a, %b
  %sel = select nnan i1 %cmp, float %a, float %b
  ret float %sel
}
```
### Optimized IR
```llvm
define float @min_select_nnan(float %a, float %b) {
  %cmp = fcmp ogt float %a, %b
  %sel = select nnan i1 %cmp, float %b, float %a
  ret float %sel
}
```


---

# Issue 157238

## Incorrect Sign Inference for Min/Max Intrinsics with Negative NaN Operands

**Description**
The bug is triggered when the compiler analyzes floating-point `minnum` or `maxnum` intrinsics where one of the operands is a NaN (Not-a-Number) with its sign bit set (effectively a "negative" NaN). 

The value tracking analysis attempts to predict the sign bit of the result based on the operands. It incorrectly applies standard comparison logic to the sign bits, assuming that a value with the sign bit set is smaller than a positive value. Consequently, the analysis infers that the result of a `minnum` operation involving a negative NaN and a positive number must be negative. However, the semantics of `minnum` and `maxnum` dictate that if one operand is NaN, the other non-NaN operand is returned, regardless of the NaN's sign. This leads the compiler to incorrectly deduce that the result is negative (or has the sign bit set), causing it to erroneously optimize away subsequent checks, such as those verifying if the result is positive zero.

## Example

### Original IR
```llvm
define double @test_bug() {
  ; 0xFFF8000000000000 is a negative NaN
  %neg_nan = bitcast i64 -2251799813685248 to double
  ; minnum(-NaN, 0.0) should return 0.0 (positive)
  %m = call double @llvm.minnum.f64(double %neg_nan, double 0.000000e+00)
  ; copysign(1.0, 0.0) should return 1.0
  ; If the bug triggers, the compiler infers %m is negative and returns -1.0
  %r = call double @llvm.copysign.f64(double 1.000000e+00, double %m)
  ret double %r
}

declare double @llvm.minnum.f64(double, double)
declare double @llvm.copysign.f64(double, double)
```
### Optimized IR
```llvm
define double @test_bug() {
  ret double -1.000000e+00
}
```


---

# Issue 54311

## Unsafe Folding of Select-Guarded Subtraction to Min/Max Intrinsics

**Description**
The bug is triggered by an optimization pattern that attempts to replace a specific sequence of instructions involving a `select`, a comparison, and a subtraction with a signed minimum or maximum intrinsic. The logic targets patterns where a `select` instruction chooses between zero and the result of a subtraction `X - Y` (marked with the `nsw` or "No Signed Wrap" flag) based on a signed comparison between `X` and `Y`. For example, the pattern `(X < Y) ? 0 : (X -nsw Y)` is identified and transformed into `smax(X -nsw Y, 0)`.

The strategy is flawed because it fails to account for cases where the subtraction overflows. The `nsw` flag causes the subtraction to produce a "poison" value upon overflow. In the original code, the comparison condition (e.g., `X < Y`) ensures that if the subtraction would overflow in a way that contradicts the logic (e.g., `INT_MIN - 1`), the `select` instruction chooses the constant zero, effectively discarding the poison value from the unselected subtraction path. By converting this to a min/max intrinsic, the subtraction is passed as an unconditional argument. If the subtraction overflows, the intrinsic receives the poison value and propagates it, resulting in undefined behavior where the original code was well-defined.

## Example

### Original IR
```llvm
define i32 @test_unsafe_select_sub_nsw(i32 %x, i32 %y) {
  %sub = sub nsw i32 %x, %y
  %cmp = icmp slt i32 %x, %y
  %res = select i1 %cmp, i32 0, i32 %sub
  ret i32 %res
}
```
### Optimized IR
```llvm
define i32 @test_unsafe_select_sub_nsw(i32 %x, i32 %y) {
  %sub = sub nsw i32 %x, %y
  %res = call i32 @llvm.smax.i32(i32 %sub, i32 0)
  ret i32 %res
}

declare i32 @llvm.smax.i32(i32, i32)
```


---

# Issue 57357

## Incorrect Handling of Signed Zeros in Floating-Point Min/Max Pattern Matching

**Description**
The bug is triggered when the compiler analyzes a `select` instruction controlled by a floating-point comparison to identify minimum or maximum patterns. The issue specifically arises when the comparison involves a zero constant (e.g., `+0.0`) and the `select` instruction returns a zero constant with the opposite sign (e.g., `-0.0`).

The compiler's analysis logic incorrectly assumes that because `+0.0` and `-0.0` compare equal, the zero in the comparison can be treated as identical to the zero in the select output for the purpose of pattern matching. This causes the compiler to misidentify the sequence as a standard floating-point min/max pattern (e.g., treating `x < +0.0 ? -0.0 : x` as equivalent to a canonical minimum operation).

Based on this misidentification, the compiler performs a transformation that relaxes the comparison predicate, such as changing a strict inequality (`<`) to a non-strict inequality (`<=`). This transformation is unsound when signed zeros are significant. For an input of `+0.0`, the original strict comparison `+0.0 < +0.0` evaluates to false, preserving the input value `+0.0`. However, the transformed non-strict comparison `+0.0 <= +0.0` evaluates to true, causing the `select` to return the explicit `-0.0` constant. This results in an incorrect sign for the return value.

## Example

### Original IR
```llvm
define float @test_signed_zero_mismatch(float %x) {
  %cmp = fcmp olt float %x, 0.000000e+00
  %res = select i1 %cmp, float -0.000000e+00, float %x
  ret float %res
}
```
### Optimized IR
```llvm
define float @test_signed_zero_mismatch(float %x) {
  %cmp = fcmp ole float %x, 0.000000e+00
  %res = select i1 %cmp, float -0.000000e+00, float %x
  ret float %res
}
```


---

# Issue 63316

## Incorrect Exclusion of NaN Result in Floating-Point Multiplication Analysis

**Description**
The bug occurs during the static analysis of floating-point multiplication instructions (`fmul`) when the compiler attempts to determine if the result can be Not-a-Number (NaN). In floating-point arithmetic, a multiplication produces NaN if either operand is NaN, or if the operation involves multiplying Zero by Infinity (`0 * Inf`).

The compiler attempts to prove that the result is never NaN by analyzing the properties of the operands. The flaw exists in the logic intended to rule out the `0 * Inf` case. The compiler incorrectly concludes that the result cannot be NaN if both operands independently satisfy a condition where they are either "known to never be Infinity" or "known to never be Zero". 

This logic is insufficient because it permits a combination where one operand contributes the Zero (satisfying the condition because it is not Infinity) and the other operand contributes the Infinity (satisfying the condition because it is not Zero). As a result, the compiler fails to recognize that `0 * Inf` is possible, leading it to incorrectly optimize away checks for NaN (such as `fcmp uno`) by assuming the result is always a valid number.

## Example

### Original IR
```llvm
define i1 @trigger_fmul_nan_exclusion() {
  ; Operand A is 0.0 (satisfies 'known to never be Infinity')
  ; Operand B is Infinity (satisfies 'known to never be Zero')
  ; The multiplication 0.0 * Infinity results in NaN.
  %mul = fmul double 0.000000e+00, 0x7FF0000000000000
  
  ; Check if the result is NaN (Unordered). Correct result should be true.
  %is_nan = fcmp uno double %mul, 0.000000e+00
  ret i1 %is_nan
}
```
### Optimized IR
```llvm
define i1 @trigger_fmul_nan_exclusion() {
  ; The compiler incorrectly concludes %mul cannot be NaN based on the flawed logic,
  ; optimizing the NaN check to false.
  ret i1 false
}
```
