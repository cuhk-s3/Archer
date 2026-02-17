# Issue 152824

## Incorrect Floating-Point Sign Inference from Fabs Comparisons

**Description**
The bug is triggered when the compiler analyzes floating-point comparisons where the left-hand side is an absolute value intrinsic (e.g., `fabs(x) > 0.0`). The optimization logic incorrectly deduces the floating-point class of the underlying operand `x` by assuming that if `fabs(x)` satisfies a positive condition, `x` itself must be positive. This logic fails to account for the fact that `x` could be negative, as the `fabs` operation discards sign information.

This incorrect inference—that `x` is strictly positive—is propagated through the intermediate representation. If `x` is used to update other variables (for example, a loop accumulator or a maximum value tracker), those variables are also marked as known-positive. Based on this false assumption, downstream optimizations may aggressively simplify code, such as removing subsequent `fabs` instructions (folding `fabs(y)` to `y`). When the value is actually negative at runtime, this simplification results in the use of a negative number where a positive magnitude is required, causing subsequent comparisons to evaluate incorrectly and altering the program's logic.

## Example

### Original IR
```llvm
define float @test_sign_inference(float %x) {
entry:
  %abs = call float @llvm.fabs.f32(float %x)
  %cmp = fcmp ogt float %abs, 0.000000e+00
  br i1 %cmp, label %if.then, label %if.end

if.then:
  ; The compiler analyzes this block knowing fabs(x) > 0.
  ; It should not assume x > 0, but the bug causes it to do so.
  %res = call float @llvm.fabs.f32(float %x)
  ret float %res

if.end:
  ret float 0.000000e+00
}/data/yunboni/projects/ReviewAgent/collect/log

declare float @llvm.fabs.f32(float)
```
### Optimized IR
```llvm
define float @test_sign_inference(float %x) {
entry:
  %abs = call float @llvm.fabs.f32(float %x)
  %cmp = fcmp ogt float %abs, 0.000000e+00
  br i1 %cmp, label %if.then, label %if.end

if.then:
  ; Incorrect optimization: fabs(x) folded to x.
  ; If x is -1.0, this returns -1.0 instead of 1.0.
  ret float %x

if.end:
  ret float 0.000000e+00
}

declare float @llvm.fabs.f32(float)
```


---

# Issue 53218

## Incorrect Handling of Poison-Generating Flags in Global Value Numbering

**Description**
The bug is triggered when the Global Value Numbering (GVN) optimization incorrectly identifies two instructions as equivalent (congruent) when they share the same opcode and operands but differ in their poison-generating flags (such as `nuw`, `nsw`, or `exact`).

The issue arises because the optimization pass ignores these flags during hashing or equality checks, potentially selecting an instruction with stricter constraints (e.g., "no unsigned wrap") as the representative leader for an instruction with looser constraints. When subsequent simplification logic processes uses of the value, it relies on the flags of the representative leader. This allows the compiler to perform algebraic simplifications—such as cancelling out inverse operations—that are only valid under the stricter constraints. Since the original instruction did not guarantee these constraints, the transformation alters the semantics of the program, leading to a miscompilation.

## Example

### Original IR
```llvm
define i32 @test_gvn_poison_flags(i32 %x) {
  ; Instruction with stricter constraints (nuw)
  %strict = add nuw i32 %x, 1
  call void @use(i32 %strict)

  ; Instruction with looser constraints (no flags)
  ; This is defined even if %x is UINT_MAX (wraps to 0)
  %loose = add i32 %x, 1

  ; Returns the wrapped value
  ret i32 %loose
}

declare void @use(i32)
```
### Optimized IR
```llvm
define i32 @test_gvn_poison_flags(i32 %x) {
  ; GVN incorrectly identifies %loose as congruent to %strict and replaces it.
  ; The 'nuw' flag is propagated to the use in the return.
  %strict = add nuw i32 %x, 1
  call void @use(i32 %strict)

  ; Returns poison if %x is UINT_MAX, introducing Undefined Behavior
  ret i32 %strict
}

declare void @use(i32)
```


---

# Issue 55291

## Unsound Expansion of Unsigned Remainder by All-Ones Constant

**Description**
The bug is triggered when the compiler optimizes an unsigned remainder operation (`urem`) where the divisor is the maximum representable value for the type (a constant with all bits set to one). The optimization attempts to replace the arithmetic instruction with a conditional selection: if the numerator equals the divisor, the result is zero; otherwise, the result is the numerator itself.

This transformation is unsound because it duplicates the numerator operand in the generated code—once for the equality check and once as the fallback return value. If the numerator is an undefined value (`undef`), the compiler is permitted to instantiate these two occurrences with different concrete values. This inconsistency allows the optimized code to return the divisor value itself (e.g., by treating the numerator as "not equal" in the condition but "equal" in the return value), which is mathematically impossible for a remainder operation, as the result must always be strictly less than the divisor. To be correct, the numerator must be frozen to ensure a consistent value across all uses in the expanded logic.

## Example

### Original IR
```llvm
define i8 @test_urem_undef() {
  %res = urem i8 undef, -1
  ret i8 %res
}
```
### Optimized IR
```llvm
define i8 @test_urem_undef() {
  %cmp = icmp eq i8 undef, -1
  %res = select i1 %cmp, i8 0, i8 undef
  ret i8 %res
}
```


---

# Issue 59888

## Summary Title
Incorrect Sinking of Freeze Instruction Through Range-Dependent Operations

## Description
The bug is triggered by an optimization transformation that moves a `freeze` instruction from the result of an operation (typically a unary intrinsic or function call) to its operand. Specifically, it transforms the pattern `freeze(op(x))` into `op(freeze(x))`.

This transformation is incorrect when the operation `op` exhibits different output ranges depending on the properties of its input. The optimizer may analyze the original operand `x` and, assuming it is not poison, infer that `op(x)` produces values within a restricted range (e.g., a small integer range based on the bit-width or known bits of `x`). It then attaches this inferred range as metadata to the transformed instruction.

However, if `x` is `poison`, the original expression `freeze(op(x))` evaluates to an arbitrary, fixed value of the result type. In the transformed expression, `freeze(x)` converts the poison into an arbitrary value of the *input* type. When `op` is executed on this arbitrary input, it may produce a result that falls outside the restricted range inferred from the original non-poison `x`. This violation of the attached range metadata causes the transformed code to exhibit undefined behavior or produce poison in scenarios where the original code was well-defined. The core flaw is the assumption that input constraints on `x` hold for `freeze(x)`, ignoring that `freeze` can introduce arbitrary values that violate those constraints.

## Example

### Original IR
```llvm
define i8 @test_freeze_sink_range(i8 %x) {
  %op = call i8 @llvm.ctpop.i8(i8 %x), !range !0
  %fr = freeze i8 %op
  ret i8 %fr
}

declare i8 @llvm.ctpop.i8(i8)

!0 = !{i8 0, i8 2}
```
### Optimized IR
```llvm
define i8 @test_freeze_sink_range(i8 %x) {
  %x.frozen = freeze i8 %x
  %op = call i8 @llvm.ctpop.i8(i8 %x.frozen), !range !0
  ret i8 %op
}

declare i8 @llvm.ctpop.i8(i8)

!0 = !{i8 0, i8 2}
```
