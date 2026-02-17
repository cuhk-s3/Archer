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

# Issue 62200

## Summary Title
Unsafe Value Range Inference from Select Instructions with Undef Conditions

## Description
The bug is triggered by an incorrect assumption in the compiler's value range analysis when handling `select` instructions. The analysis attempts to refine the possible range of a value used in a `select` branch (e.g., the "true" operand) by assuming that the `select` condition must hold (e.g., be true) for that branch to be chosen.

However, this logic fails when the condition of the `select` instruction is `undef` or `poison`. In such cases, the `select` instruction does not act as a strict guard; it may return the operand from the "true" branch even if the logical condition is not met (or is undefined). By ignoring this possibility, the compiler incorrectly infers a restricted range for the operand—such as assuming a value is strictly non-negative because the condition checks for positivity. Subsequent optimization passes, relying on this flawed range information, may incorrectly simplify instructions (e.g., replacing a signed division with an unsigned division or logical shift), leading to a miscompilation where the program's behavior changes for `undef` inputs.

## Example

### Original IR
```llvm
define i32 @test_unsafe_range_inference(i32 %x) {
  ; The select condition is undef. The instruction can return %x or 0.
  ; If %x is negative, the result can be negative.
  %val = select i1 undef, i32 %x, i32 0

  ; Signed division by 2. If %val is negative (e.g., -2), result is -1.
  ; If the compiler incorrectly assumes %val >= 0, it may optimize this to lshr.
  %res = sdiv i32 %val, 2
  ret i32 %res
}
```
### Optimized IR
```llvm
define i32 @test_unsafe_range_inference(i32 %x) {
  ; The compiler incorrectly inferred that %val is non-negative.
  %val = select i1 undef, i32 %x, i32 0

  ; sdiv was replaced by lshr. If %val was -2, result is now a large positive number (INT_MAX).
  %res = lshr i32 %val, 1
  ret i32 %res
}
```


---

# Issue 62901

## Summary Title
Incorrect Range Refinement for Select Instructions with Undef Conditions

## Description
The bug is triggered by an incorrect assumption in the value range analysis of `select` instructions. When determining the possible values of a `select` instruction, the analyzer attempts to refine the ranges of the true and false operands based on the condition. It assumes that if the true operand is selected, the condition must be true (and conversely, if the false operand is selected, the condition must be false). This allows the analyzer to propagate constraints from the condition to the selected value (e.g., inferring that a value is positive because the condition checked for it).

However, this logic fails when the condition of the `select` instruction is `undef`. According to IR semantics, if the condition is `undef`, the `select` instruction may return either operand. Crucially, the selection of the "true" operand in this case does not imply that the condition actually holds true. By ignoring this possibility, the analyzer infers an overly restricted range for the `select` result (e.g., guaranteeing it is non-negative). This incorrect range information causes subsequent optimization passes to perform invalid transformations, such as replacing a sign-extension (`sext`) with a zero-extension (`zext`), which alters the program's behavior for undefined inputs.

## Example

### Original IR
```llvm
define i64 @trigger_bug(i32 %x) {
  %val = select i1 undef, i32 %x, i32 0
  %res = sext i32 %val to i64
  ret i64 %res
}
```
### Optimized IR
```llvm
define i64 @trigger_bug(i32 %x) {
  %res = zext i32 %x to i64
  ret i64 %res
}
```


---

# Issue 68381

## Incorrect Range Deduction for PHI Nodes with Undef Operands

**Description**:
The bug is triggered by a PHI node that merges a value with a known, limited constant range (such as a zero-extended integer) and an `undef` value. The compiler's value analysis incorrectly infers that the result of the PHI node is bounded strictly by the limited range of the defined input. It fails to account for the fact that `undef` in LLVM IR represents an indeterminate value that can take any bit pattern, effectively implying a full range for the union.

Based on this overly restrictive range inference, optimization passes (such as Correlated Value Propagation) erroneously conclude that subsequent instructions—typically bitwise AND operations used for masking or range enforcement—are redundant. Consequently, these instructions are optimized away. This results in a miscompilation where, if the control flow follows the path with the `undef` value, the result is not properly masked or constrained, allowing arbitrary values to propagate where bounded values were expected.

## Example

### Original IR
```llvm
define i32 @test(i1 %cond, i1 %val) {
entry:
  br i1 %cond, label %taken, label %untaken

taken:
  %ext = zext i1 %val to i32
  br label %merge

untaken:
  br label %merge

merge:
  %phi = phi i32 [ %ext, %taken ], [ undef, %untaken ]
  %res = and i32 %phi, 1
  ret i32 %res
}
```
### Optimized IR
```llvm
define i32 @test(i1 %cond, i1 %val) {
entry:
  br i1 %cond, label %taken, label %untaken

taken:
  %ext = zext i1 %val to i32
  br label %merge

untaken:
  br label %merge

merge:
  %phi = phi i32 [ %ext, %taken ], [ undef, %untaken ]
  ret i32 %phi
}
```
