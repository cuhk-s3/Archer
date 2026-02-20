# Issue 152824

## Incorrect Floating-Point Class Deduction for Absolute Value Operands in Comparisons Against Zero

**Description**: 
The bug is triggered when a floating-point comparison instruction evaluates the result of an absolute value operation (e.g., `fabs(x)`) against zero (e.g., `fabs(x) > 0.0`). 

During optimization, the compiler attempts to deduce the floating-point properties—such as the sign, or whether the value is zero, NaN, or infinity—of the original source operand (`x`) based on the comparison's predicate. However, the deduction logic fails to account for the effect of the absolute value operation when handling inequality predicates (such as greater-than or less-than). 

Instead of recognizing that the absolute value strips the sign and therefore the original operand could be either positive or negative, the compiler directly applies the comparison's implied sign to the source operand. For example, from the condition `fabs(x) > 0.0`, the compiler incorrectly deduces that `x` itself must be strictly positive, ignoring the fact that a negative `x` would also satisfy the condition. 

This flawed deduction pollutes the compiler's knowledge of the value, causing it to make incorrect assumptions about the sign of the source operand. Consequently, this leads to miscompilations where subsequent operations are improperly folded, simplified, or optimized based on the erroneous sign assumption.

## Example

### Original IR
```llvm
declare double @llvm.fabs.f64(double)
declare void @llvm.assume(i1)

define i1 @test(double %x) {
  %fabs = call double @llvm.fabs.f64(double %x)
  %cmp = fcmp ogt double %fabs, 0.000000e+00
  call void @llvm.assume(i1 %cmp)
  %res = fcmp olt double %x, 0.000000e+00
  ret i1 %res
}

```
### Optimized IR
```llvm
declare double @llvm.fabs.f64(double)
declare void @llvm.assume(i1)

define i1 @test(double %x) {
  %fabs = call double @llvm.fabs.f64(double %x)
  %cmp = fcmp ogt double %fabs, 0.000000e+00
  call void @llvm.assume(i1 %cmp)
  ret i1 false
}

```


---

# Issue 53218

## Incorrect Value Numbering of Instructions with Poison-Generating Flags

**Description**: 
The bug is triggered when two identical instructions—differing only in their poison-generating flags (such as `nuw`, `nsw`, or `exact`)—are present in the same function. The optimization pass (like Global Value Numbering) hashes and compares these instructions while ignoring their flags, incorrectly determining that they are equivalent. 

If the instruction with the poison-generating flags is selected as the leader and replaces the instruction without the flags, it effectively introduces these restrictive flags into a computation path where they did not originally exist. Subsequent optimization passes (such as instruction simplification) may then exploit these newly introduced flags to perform aggressive simplifications. This leads to a miscompilation because the simplifications are based on the false assumption that the operation will not trigger the poison condition (e.g., assuming no overflow occurs), altering the program's semantics for inputs that would violate those conditions.

## Example

### Original IR
```llvm
define i32 @test(i32 %x, i1 %c) {
entry:
  %b = add nsw i32 %x, 1
  %a = add i32 %x, 1
  %sel = select i1 %c, i32 %b, i32 0
  %res = add i32 %sel, %a
  ret i32 %res
}
```
### Optimized IR
```llvm
define i32 @test(i32 %x, i1 %c) {
entry:
  %b = add nsw i32 %x, 1
  %sel = select i1 %c, i32 %b, i32 0
  %res = add i32 %sel, %b
  ret i32 %res
}
```


---

# Issue 63019

## Incorrect Merging of Partial Alias Results with Different Offsets

**Description**: 
The bug is triggered when the compiler performs alias analysis on memory operations involving pointers that partially alias a memory location at different offsets. During the analysis, the compiler often needs to merge multiple alias results (for example, when analyzing pointers derived from control flow merges like PHI nodes or `select` instructions, or when aggregating alias information from different sources). 

When merging these results, the compiler incorrectly evaluates two partial alias results with different offsets as equivalent. This happens because the comparison logic only checks the alias kind (i.e., whether they are both partial aliases) and completely ignores the specific offset values associated with them. As a result, the merged alias result loses crucial offset information. 

Consequently, downstream memory optimization passes (such as Dead Store Elimination, Global Value Numbering, or Instruction Combining) rely on this inaccurate and overly broad alias information. This leads to invalid transformations, such as improper reordering of memory accesses, incorrect load/store forwarding, or the erroneous elimination of necessary memory operations.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define i8 @test_partial_alias_merge(i1 %c) {
entry:
  %alloc = alloca i32, align 4
  ; Store 0x01020304 to the allocated memory
  store i32 16909060, ptr %alloc, align 4
  
  ; Create two pointers with different offsets (1 and 2)
  %p1 = getelementptr inbounds i8, ptr %alloc, i64 1
  %p2 = getelementptr inbounds i8, ptr %alloc, i64 2
  
  ; Select between the two pointers
  %sel = select i1 %c, ptr %p1, ptr %p2
  
  ; Load from the selected pointer
  %v = load i8, ptr %sel, align 1
  ret i8 %v
}

```
### Optimized IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define i8 @test_partial_alias_merge(i1 %c) {
entry:
  %alloc = alloca i32, align 4
  store i32 16909060, ptr %alloc, align 4
  
  ; The compiler incorrectly merges the PartialAlias results of %p1 and %p2,
  ; treating them as equivalent and retaining only the offset of %p1 (offset 1).
  ; As a result, GVN incorrectly forwards the byte at offset 1 (0x03) for all paths,
  ; ignoring the possibility that %sel could be at offset 2 (0x02).
  ret i8 3
}

```
