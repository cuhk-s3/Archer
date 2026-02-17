# Issue 112068

## Incorrect Promotion of Poison to Undefined Behavior in Intrinsic Simplification

**Description**
The bug is triggered when the optimizer simplifies `cttz` or `ctlz` intrinsics by changing the `is_zero_poison` argument from `false` to `true`. This transformation is applied when the result of the intrinsic is used exclusively as a shift amount, relying on the fact that shifting by the bit width (the value returned by the intrinsic for zero input when `is_zero_poison` is false) produces a poison value. However, the optimizer fails to strip attributes that imply immediate undefined behavior, such as `noundef`, from the intrinsic call. Consequently, when the input is zero, the modified intrinsic produces a poison value which the attribute immediately escalates to Undefined Behavior, whereas the original code simply propagated a poison value through the shift operation.

## Example

### Original IR
```llvm
define i32 @test_cttz_noundef_shift(i32 %x, i32 %y) {
  ; The intrinsic is called with is_zero_poison = false.
  ; The noundef attribute asserts the result is not poison.
  ; If %x is 0, cttz returns 32 (bit width).
  %cnt = call noundef i32 @llvm.cttz.i32(i32 %x, i1 false)
  ; Shifting by 32 results in poison, but not immediate UB.
  %res = shl i32 %y, %cnt
  ret i32 %res
}

declare i32 @llvm.cttz.i32(i32, i1)
```
### Optimized IR
```llvm
define i32 @test_cttz_noundef_shift(i32 %x, i32 %y) {
  ; The optimizer incorrectly changes is_zero_poison to true while keeping noundef.
  ; If %x is 0, cttz returns poison.
  ; The noundef attribute immediately escalates this poison to Undefined Behavior.
  %cnt = call noundef i32 @llvm.cttz.i32(i32 %x, i1 true)
  %res = shl i32 %y, %cnt
  ret i32 %res
}

declare i32 @llvm.cttz.i32(i32, i1)
```


---

# Issue 112076

## Summary Title
Unsafe Propagation of Poison-Generating Metadata When Linearizing Select Instructions

## Description
The bug is triggered when the optimizer transforms a `select` instruction, which implements a specific mathematical idiom (such as `bit_ceil`), into an unconditional sequence of arithmetic operations. The original code pattern involves an intrinsic call (e.g., `llvm.ctlz`) that is annotated with poison-generating metadata, such as a `!range` attribute. For certain input values, this metadata causes the intrinsic to produce `poison`. In the source IR, the `select` instruction effectively masks this poison by choosing a safe alternative value (e.g., a constant) whenever the input would cause the intrinsic to violate its metadata constraints.

The optimization replaces this conditional logic with a branchless calculation that always consumes the result of the intrinsic. However, the transformation fails to remove the poison-generating metadata from the intrinsic. Consequently, for inputs that violate the metadata constraints, the intrinsic generates `poison` which now unconditionally propagates through the optimized arithmetic sequence. This results in the transformed code returning `poison` for inputs that yielded a well-defined value in the original code.

## Example

### Original IR
```llvm
define i32 @trigger(i32 %x) {
  ; The ctlz intrinsic is annotated with range metadata [0, 32).
  ; For i32, ctlz(0) returns 32. The metadata implies the result is never 32,
  ; effectively asserting that %x is never 0. If %x is 0, this produces poison.
  %val = call i32 @llvm.ctlz.i32(i32 %x, i1 false), !range !0
  
  ; The select instruction masks the poison case. If %x is 0, it returns 32 (safe).
  ; If %x is not 0, it returns %val (safe, within range).
  %cond = icmp eq i32 %x, 0
  %res = select i1 %cond, i32 32, i32 %val
  ret i32 %res
}

declare i32 @llvm.ctlz.i32(i32, i1)

!0 = !{i32 0, i32 32}
```
### Optimized IR
```llvm
define i32 @trigger(i32 %x) {
  ; The optimizer recognizes that ctlz(0) == 32 and folds the select.
  ; However, it incorrectly preserves the !range metadata.
  ; Now, if %x is 0, the intrinsic returns 32, which violates the [0, 32) range,
  ; causing the function to return poison instead of 32.
  %val = call i32 @llvm.ctlz.i32(i32 %x, i1 false), !range !0
  ret i32 %val
}

declare i32 @llvm.ctlz.i32(i32, i1)

!0 = !{i32 0, i32 32}
```


---

# Issue 112467

## Incorrect Poison Propagation in Logical to Bitwise Conversion of `samesign` Comparisons

## Description
The bug is triggered when the compiler optimizes a logical AND/OR operation (typically represented as a `select` instruction) involving integer comparisons, where one of the comparisons carries the `samesign` optimization flag. The optimizer attempts to fold these comparisons into a more efficient bitwise expression (e.g., converting a logical OR into a bitwise OR).

The flaw lies in preserving the `samesign` flag during this conversion. The `samesign` flag specifies that the comparison yields `poison` if the operands do not share the same sign. In the original logical form, if the result is determined by the other operand (e.g., the first operand of a logical OR is true), the potential `poison` from the `samesign` comparison is suppressed. However, the transformed bitwise operation evaluates all operands eagerly and propagates `poison` if any operand is `poison`. Consequently, for inputs where the `samesign` constraint is violated but the logical operation would have short-circuited, the optimized code produces `poison` instead of a defined value, resulting in a miscompilation.

## Example

### Original IR
```llvm
define i1 @test_poison_propagation(i32 %a, i32 %b) {
  %cmp1 = icmp eq i32 %a, -1
  %cmp2 = icmp samesign ult i32 %a, %b
  %res = select i1 %cmp1, i1 true, i1 %cmp2
  ret i1 %res
}
```
### Optimized IR
```llvm
define i1 @test_poison_propagation(i32 %a, i32 %b) {
  %cmp1 = icmp eq i32 %a, -1
  %cmp2 = icmp samesign ult i32 %a, %b
  %res = or i1 %cmp1, %cmp2
  ret i1 %res
}
```


---

# Issue 112476

## Preservation of `samesign` Attribute During ICmp Operand Simplification

**Description**:
The bug is triggered when the optimizer simplifies an integer comparison (`icmp`) instruction that is annotated with the `samesign` attribute. The `samesign` attribute implies that the comparison yields a poison value if the operands do not share the same sign bit. The optimizer performs a transformation that simplifies the sequence of operations feeding into the comparison (such as combining shifts and bitwise AND/OR operations) into a more efficient form. 

While the transformed operands maintain the correct logical truth value for the comparison (e.g., equality or inequality against zero), the transformation may produce a value with a different sign bit than the original expression. Specifically, the new operand might be negative while the original was positive, or vice versa. Because the optimizer retains the `samesign` attribute on the transformed instruction, the new operands—which now have differing signs—violate the attribute's constraint. This causes the instruction to incorrectly evaluate to poison instead of the expected boolean result.

## Example

### Original IR
```llvm
define i1 @test(i32 %a) {
  %shr = lshr i32 %a, 31
  %cmp = icmp samesign ne i32 %shr, 0
  ret i1 %cmp
}
```
### Optimized IR
```llvm
define i1 @test(i32 %a) {
  %cmp = icmp samesign slt i32 %a, 0
  ret i1 %cmp
}
```


---

# Issue 113423

## Incorrect Fast Math Flag Propagation when Hoisting Floating-Point Operations over Select

**Description**
The bug is triggered when the compiler optimizes a `select` instruction where one operand is a floating-point binary operation and the other is a value that can be factored into that operation (e.g., transforming `select(cond, x, x * y)` into `x * select(cond, 1.0, y)`). This optimization effectively hoists the binary operation above the `select`.

The incorrect transformation occurs because the newly created binary operation blindly inherits the Fast Math Flags (FMF) from the original binary operation found in one of the branches. These flags (such as `ninf` for "no infinity" or `nnan` for "no NaN") assert that the operands and results do not violate specific constraints, producing `poison` if they do. In the original code, these constraints only applied to the branch containing the operation. However, the transformation applies the operation—and its restrictive flags—to the branch that originally bypassed the operation. If the value on that path violates the flags (e.g., it is infinity when `ninf` is set), the transformed code incorrectly evaluates to `poison`, whereas the original code would have returned a valid result.

## Example

### Original IR
```llvm
define float @test_fmul_select_hoist_ninf(i1 %cond, float %x, float %y) {
  %mul = fmul ninf float %x, %y
  %result = select i1 %cond, float %x, float %mul
  ret float %result
}
```
### Optimized IR
```llvm
define float @test_fmul_select_hoist_ninf(i1 %cond, float %x, float %y) {
  %operand = select i1 %cond, float 1.000000e+00, float %y
  %result = fmul ninf float %x, %operand
  ret float %result
}
```


---

# Issue 113869

## Incorrect Poison Handling in Saturated Add Folding

**Description**
The bug occurs when the compiler attempts to optimize a `select` instruction sequence that implements unsigned saturated addition (e.g., `(X < Y) ? -1 : (Y + ~X)`) by replacing it with a `uadd.sat` intrinsic.

The error arises from the pattern matching logic for the bitwise NOT operation (`~X`), which is typically implemented as an XOR with an all-ones constant. The compiler incorrectly matched cases where the all-ones constant contained poison elements (e.g., in a vector constant).

In the original code, if the saturation condition (`X < Y`) is met, the `select` instruction returns a defined constant (`-1`), ignoring the `Y + ~X` calculation. Consequently, even if `~X` evaluates to poison (due to the poisonous mask), the final result is well-defined. However, the optimized transformation generates `uadd.sat(~X, Y)`, which unconditionally uses `~X` as an operand. If `~X` is poison, the intrinsic propagates the poison to the result. This leads to a miscompilation where the target code produces undefined behavior (poison) for inputs where the source code produced a valid value.

## Example

### Original IR
```llvm
define <2 x i8> @src(<2 x i8> %x, <2 x i8> %y) {
  %not_x = xor <2 x i8> %x, <i8 -1, i8 poison>
  %sum = add <2 x i8> %y, %not_x
  %cond = icmp ult <2 x i8> %x, %y
  %res = select <2 x i1> %cond, <2 x i8> <i8 -1, i8 -1>, <2 x i8> %sum
  ret <2 x i8> %res
}
```
### Optimized IR
```llvm
define <2 x i8> @src(<2 x i8> %x, <2 x i8> %y) {
  %not_x = xor <2 x i8> %x, <i8 -1, i8 poison>
  %res = call <2 x i8> @llvm.uadd.sat.v2i8(<2 x i8> %not_x, <2 x i8> %y)
  ret <2 x i8> %res
}

declare <2 x i8> @llvm.uadd.sat.v2i8(<2 x i8>, <2 x i8>)
```


---

# Issue 115149

## Incorrect No-Wrap Flag Intersection in PHI-of-GEPs Optimization

**Description**:
The bug is triggered when the optimizer attempts to fold a PHI node, whose incoming values are `getelementptr` (GEP) instructions, into a single GEP instruction acting on a new PHI of the operands. During this transformation, the compiler calculates the no-wrap flags (such as `inbounds`) for the resulting GEP by intersecting the flags of the original GEPs. The flaw is that the logic initializes the flag set to an optimistic state (assuming all flags are present) and only intersects it with the flags of the incoming GEPs starting from the second operand, failing to account for the flags of the first operand.

If the first GEP operand lacks specific flags (e.g., it is not `inbounds` and thus allows overflow) while the subsequent operands possess them, the resulting merged GEP incorrectly retains the restrictive flags. This causes the compiler to treat valid pointer arithmetic as undefined behavior, enabling subsequent optimizations to incorrectly alter the program logic, such as removing valid loops or checks.

## Example

### Original IR
```llvm
define i8* @test_phi_gep_flags(i8* %base, i1 %cond, i64 %idx1, i64 %idx2) {
entry:
  br i1 %cond, label %bb1, label %bb2

bb1:
  ; This GEP does NOT have inbounds. It is the first operand in the PHI below.
  %gep1 = getelementptr i8, i8* %base, i64 %idx1
  br label %exit

bb2:
  ; This GEP HAS inbounds.
  %gep2 = getelementptr inbounds i8, i8* %base, i64 %idx2
  br label %exit

exit:
  ; The optimizer merges these into a single GEP. 
  ; Due to the bug, it ignores the flags of the first operand (%gep1) and keeps inbounds from %gep2.
  %res = phi i8* [ %gep1, %bb1 ], [ %gep2, %bb2 ]
  ret i8* %res
}
```
### Optimized IR
```llvm
define i8* @test_phi_gep_flags(i8* %base, i1 %cond, i64 %idx1, i64 %idx2) {
entry:
  br i1 %cond, label %bb1, label %bb2

bb1:
  br label %exit

bb2:
  br label %exit

exit:
  %idx.phi = phi i64 [ %idx1, %bb1 ], [ %idx2, %bb2 ]
  ; BUG: The resulting GEP has 'inbounds' set, implying %gep1 was inbounds, which is false.
  %res = getelementptr inbounds i8, i8* %base, i64 %idx.phi
  ret i8* %res
}
```


---

# Issue 115465

## Summary Title
Unsafe Folding of Shufflevector into Select with Scalar Condition

## Description
The bug is triggered by an optimization that folds a `shufflevector` instruction into a preceding `select` instruction. This transformation targets patterns where a `select` instruction provides one of the input vectors to a `shufflevector`, specifically matching the form `shufflevector (select cond, v1, v2), v3, mask`. The compiler attempts to sink the shuffle operation into the operands of the select, rewriting the expression as `select cond, (shufflevector v1, v3, mask), (shufflevector v2, v3, mask)`.

This transformation is incorrect when the `select` uses a scalar condition (e.g., `i1`) that can be `poison`. In the original instruction sequence, if the scalar condition is `poison`, the `select` produces a fully poison vector. However, the subsequent `shufflevector` can still produce valid, non-poison elements if its mask selects values from the second operand (`v3`), assuming `v3` itself contains defined values. 

In the transformed sequence, the `select` becomes the outermost operation. If the scalar condition is `poison`, the `select` instruction forces the entire result to be `poison`, regardless of the operands. This effectively discards the valid values that would have been retrieved from `v3` in the original code. By turning defined values into poison, the transformation violates the rule that optimizations cannot make the target code more poisonous than the source.

## Example

### Original IR
```llvm
define <2 x i8> @test(i1 %cond, <2 x i8> %v1, <2 x i8> %v2, <2 x i8> %v3) {
  %sel = select i1 %cond, <2 x i8> %v1, <2 x i8> %v2
  %shuf = shufflevector <2 x i8> %sel, <2 x i8> %v3, <2 x i32> <i32 2, i32 3>
  ret <2 x i8> %shuf
}
```
### Optimized IR
```llvm
define <2 x i8> @test(i1 %cond, <2 x i8> %v1, <2 x i8> %v2, <2 x i8> %v3) {
  %shuf1 = shufflevector <2 x i8> %v1, <2 x i8> %v3, <2 x i32> <i32 2, i32 3>
  %shuf2 = shufflevector <2 x i8> %v2, <2 x i8> %v3, <2 x i32> <i32 2, i32 3>
  %sel = select i1 %cond, <2 x i8> %shuf1, <2 x i8> %shuf2
  ret <2 x i8> %sel
}
```


---

# Issue 118798

## Infinite Loop in Shift Reassociation with Non-Immediate Constants

**Description**
The bug is triggered by a sequence of nested shift instructions (e.g., `(X << A) << B`) where the shift amounts `A` and `B` are symbolic constants (such as pointers cast to integers or other constant expressions) rather than immediate integer literals. 

The optimization logic attempts to canonicalize such patterns by reassociating the operations to group constants together, intending to fold them (e.g., transforming `(X << A) << B` into `(X << B) << A` if `B` is a constant). However, the detection logic for "constants" was too broad and included non-immediate symbolic constants. When both shift amounts fell into this category, the optimizer treated them symmetrically and repeatedly swapped the operands back and forth in an infinite loop, preventing the compilation from terminating.

## Example

### Original IR
```llvm
@g1 = external global i32
@g2 = external global i32

define i64 @test_loop(i64 %x) {
  %shl1 = shl i64 %x, ptrtoint (i32* @g1 to i64)
  %shl2 = shl i64 %shl1, ptrtoint (i32* @g2 to i64)
  ret i64 %shl2
}
```
### Optimized IR
```llvm
@g1 = external global i32
@g2 = external global i32

define i64 @test_loop(i64 %x) {
  %1 = add i64 ptrtoint (i32* @g1 to i64), ptrtoint (i32* @g2 to i64)
  %shl2 = shl i64 %x, %1
  ret i64 %shl2
}
```


---

# Issue 120361

## Incorrect Preservation of `samesign` Flag During Simplification of Logical Conjunctions

**Description**:
The bug is triggered when the optimizer simplifies a logical conjunction (such as a bitwise `AND` of booleans or a `select` instruction) involving two integer comparisons, where one comparison implies the other. For example, checking if a value is equal to a specific non-zero constant implies that the value is not zero. When the optimizer folds the expression to retain only the "stronger" comparison (the one that implies the other), it fails to remove the `samesign` flag from that instruction.

This preservation is incorrect because the `samesign` flag asserts that the operands must have the same sign; otherwise, the result is `poison`. In the original conjunction, inputs that would violate the `samesign` constraint of the stronger comparison might be handled by the weaker comparison evaluating to `false`, resulting in a well-defined `false` for the whole expression. By reducing the expression to solely the stronger comparison with `samesign` intact, these inputs now produce `poison`, making the transformed code more undefined than the original.

## Example

### Original IR
```llvm
define i1 @test(i8 %x) {
  %strong = icmp samesign ult i8 %x, 10
  %weak = icmp ne i8 %x, -1
  %res = select i1 %weak, i1 %strong, i1 false
  ret i1 %res
}
```
### Optimized IR
```llvm
define i1 @test(i8 %x) {
  %strong = icmp samesign ult i8 %x, 10
  ret i1 %strong
}
```


---

# Issue 121432

## Incorrect Fast Math Flag Propagation in Nested Copysign Simplification

**Description**
The bug is triggered when the compiler optimizes a nested sequence of `llvm.copysign` intrinsics, specifically transforming the pattern `copysign(Magnitude, copysign(Intermediate, Sign))` into `copysign(Magnitude, Sign)`.

The incorrect transformation logic involves unconditionally propagating the Fast Math Flags (such as `nnan` for "no NaNs" or `ninf` for "no infinities") from the outer `copysign` call to the simplified instruction. In the original code, the outer flags apply to the result of the inner `copysign`. Since `copysign` derives its magnitude from the `Intermediate` operand, the result of the inner call can be a valid, finite number even if the `Sign` operand is NaN or Infinity.

By bypassing the intermediate step and applying the outer flags directly to the `Sign` operand, the optimizer incorrectly asserts that `Sign` itself must satisfy the constraints (e.g., not being NaN). If the `Sign` operand violates these flags, the transformed instruction yields a poison value (undefined behavior), whereas the original code was well-defined. This results in a miscompilation where the optimized code is more restrictive than the source.

## Example

### Original IR
```llvm
define double @test_copysign_nested_flags(double %mag, double %intermediate, double %sign) {
  %inner = call double @llvm.copysign.f64(double %intermediate, double %sign)
  %res = call nnan double @llvm.copysign.f64(double %mag, double %inner)
  ret double %res
}

declare double @llvm.copysign.f64(double, double)
```
### Optimized IR
```llvm
define double @test_copysign_nested_flags(double %mag, double %intermediate, double %sign) {
  %res = call nnan double @llvm.copysign.f64(double %mag, double %sign)
  ret double %res
}

declare double @llvm.copysign.f64(double, double)
```


---

# Issue 121459

## Incorrect Propagation of Inbounds Flag when Folding PHI of GEPs

**Description**
The bug is triggered when the optimizer attempts to fold a PHI node where the incoming values are `getelementptr` (GEP) instructions that share the same base pointer but differ in indices or offsets. When unifying these incoming GEPs into a single GEP instruction (typically by creating a new PHI node for the varying offsets), the optimizer incorrectly propagates the `inbounds` no-wrap flag from one of the source GEPs to the newly created GEP.

If the incoming GEPs have inconsistent flags—for example, one has `inbounds` and another does not—the optimizer fails to intersect these flags (i.e., it does not drop `inbounds` if any input lacks it). As a result, the transformed code asserts `inbounds` behavior for all paths. This causes miscompilation when the control flow takes a path corresponding to a GEP that originally allowed wrapping or out-of-bounds arithmetic; the new GEP evaluates to `poison` instead of a valid pointer value.

## Example

### Original IR
```llvm
define i8* @test_phi_gep_inbounds_propagation(i8* %base, i1 %cond) {
entry:
  br i1 %cond, label %if.true, label %if.false

if.true:
  ; This path has 'inbounds'
  %gep.inbounds = getelementptr inbounds i8, i8* %base, i64 10
  br label %merge

if.false:
  ; This path does NOT have 'inbounds'
  %gep.no.inbounds = getelementptr i8, i8* %base, i64 20
  br label %merge

merge:
  ; The PHI node combines both GEPs
  %res = phi i8* [ %gep.inbounds, %if.true ], [ %gep.no.inbounds, %if.false ]
  ret i8* %res
}
```
### Optimized IR
```llvm
define i8* @test_phi_gep_inbounds_propagation(i8* %base, i1 %cond) {
entry:
  br i1 %cond, label %if.true, label %if.false

if.true:
  br label %merge

if.false:
  br label %merge

merge:
  ; The optimizer sinks the GEP and creates a PHI for the indices.
  %gep.idx = phi i64 [ 10, %if.true ], [ 20, %if.false ]
  ; BUG: The 'inbounds' flag is incorrectly preserved on the merged GEP.
  ; It should be dropped because the 'if.false' path did not have it.
  %res = getelementptr inbounds i8, i8* %base, i64 %gep.idx
  ret i8* %res
}
```


---

# Issue 121581

## Unsafe Simplification of Pointer Comparisons with Identical Offsets

The bug is triggered when the optimizer simplifies an integer comparison (`icmp`) between two `getelementptr` (GEP) instructions that have different base pointers but identical indices. The compiler incorrectly folds the comparison `cmp (gep base1, idx), (gep base2, idx)` into `cmp base1, base2` without verifying that the pointer arithmetic is guaranteed not to wrap (overflow) the address space. For relational comparisons (such as `ult`), if the addition of the offset causes a wrap-around, the relative order of the resulting pointers may differ from the relative order of the base pointers, rendering the optimization invalid.

## Example

### Original IR
```llvm
define i1 @test_gep_icmp_no_inbounds(i8* %base1, i8* %base2, i64 %idx) {
  %gep1 = getelementptr i8, i8* %base1, i64 %idx
  %gep2 = getelementptr i8, i8* %base2, i64 %idx
  %cmp = icmp ult i8* %gep1, %gep2
  ret i1 %cmp
}
```
### Optimized IR
```llvm
define i1 @test_gep_icmp_no_inbounds(i8* %base1, i8* %base2, i64 %idx) {
  %cmp = icmp ult i8* %base1, %base2
  ret i1 %cmp
}
```


---

# Issue 121584

## Incorrect Preservation of NSW Flag When Converting Left Shift to Multiplication

## Description
The bug is triggered during the optimization of signed remainder (`srem`) instructions where the operands are defined by left-shift (`shl`) or multiplication (`mul`) operations sharing a common variable (e.g., `srem (shl X, C), (mul X, Y)`). To simplify these expressions, the compiler analyzes the left-shift operation as if it were a multiplication by a power of two.

The issue arises because the compiler incorrectly preserves the `nsw` (No Signed Wrap) flag when converting the `shl` instruction into its conceptual `mul` equivalent. While `shl nsw` and `mul nsw` are often compatible, they diverge when the shift amount is equal to the bit width minus one (creating `INT_MIN`). In this specific case, `shl nsw` is well-defined for certain inputs (like -1) where the equivalent `mul nsw` would result in a signed overflow (poison). By incorrectly attaching `nsw` to the synthesized multiplication, the optimizer infers overly aggressive constraints on the input values—assuming valid inputs are impossible—which leads to a miscompilation of the remainder operation.

## Example

### Original IR
```llvm
define i8 @test(i8 %x, i8 %y) {
  %shl = shl nsw i8 %x, 7
  %mul = mul nsw i8 %x, %y
  %rem = srem i8 %shl, %mul
  ret i8 %rem
}
```
### Optimized IR
```llvm
define i8 @test(i8 %x, i8 %y) {
  %1 = srem i8 -128, %y
  %rem = mul nsw i8 %1, %x
  ret i8 %rem
}
```


---

# Issue 121890

## Unsafe Folding of GEP Comparisons with Multi-Byte Strides

**Description**
The bug occurs in the `InstCombine` pass when optimizing equality comparisons (`icmp eq` or `icmp ne`) between two `getelementptr` (GEP) instructions. The issue arises when the two GEP instructions share the same base pointer and differ by exactly one index operand. The compiler incorrectly transforms the pointer comparison into a direct comparison of the differing indices.

This transformation relies on the assumption that different indices always produce different memory addresses (injectivity). However, this assumption is flawed for standard GEP instructions that lack "no-wrap" flags (such as `inbounds` or `nuw`). Pointer arithmetic in LLVM IR is modular; if the size of the element being indexed (the stride) is greater than one byte, the offset calculation (`index * stride`) can wrap around the address space. Consequently, two distinct indices can result in the same effective memory address if their difference multiplied by the stride is a multiple of the address space size. The compiler failed to verify that the GEP instructions had flags guaranteeing no overflow, leading to miscompilations where the optimized code reported indices as unequal while the original pointers were equal due to address wrapping.

## Example

### Original IR
```llvm
define i1 @test_unsafe_gep_fold(ptr %base, i64 %idx1, i64 %idx2) {
  %gep1 = getelementptr i32, ptr %base, i64 %idx1
  %gep2 = getelementptr i32, ptr %base, i64 %idx2
  %cmp = icmp eq ptr %gep1, %gep2
  ret i1 %cmp
}
```
### Optimized IR
```llvm
define i1 @test_unsafe_gep_fold(ptr %base, i64 %idx1, i64 %idx2) {
  %cmp = icmp eq i64 %idx1, %idx2
  ret i1 %cmp
}
```


---

# Issue 124387

## Invalid Range Metadata Retention after Operand Simplification in Funnel Shifts

**Description**
The bug is triggered during an optimization pass that simplifies the operands of a funnel shift intrinsic (e.g., `llvm.fshl`) based on demanded bits analysis. Specifically, if the funnel shift instruction carries a `range` metadata attribute that constrains its possible return values, simplifying the input operands can alter the computation such that the result no longer falls within the specified range. The compiler fails to drop or invalidate this `range` attribute after modifying the operands. Consequently, the instruction is treated as producing a `poison` value because the new result violates the stale range constraint, leading to undefined behavior and miscompilation.

## Example

### Original IR
```llvm
define i1 @test(i8 %x) {
  %b = or i8 %x, 127
  %res = call i8 @llvm.fshl.i8(i8 %b, i8 %b, i8 1), !range !0
  %t = trunc i8 %res to i1
  ret i1 %t
}

declare i8 @llvm.fshl.i8(i8, i8, i8)

!0 = !{i8 128, i8 0}
```
### Optimized IR
```llvm
define i1 @test(i8 %x) {
  %1 = and i8 %x, -128
  %res = call i8 @llvm.fshl.i8(i8 %1, i8 %1, i8 1), !range !0
  %t = trunc i8 %res to i1
  ret i1 %t
}

declare i8 @llvm.fshl.i8(i8, i8, i8)

!0 = !{i8 128, i8 0}
```


---

# Issue 126974

## Incorrect Propagation of `samesign` Flag During Min/Max Comparison Folding

**Description**
The bug is triggered when the optimizer attempts to simplify an integer comparison (`icmp`) that compares the result of a minimum or maximum operation (e.g., `umax(X, Y)`) against another value `Z`. Specifically, the issue arises when the original comparison instruction carries the `samesign` flag, which asserts that the operands of the comparison are known to share the same sign bit.

To optimize the code, the compiler attempts to decompose the comparison `icmp samesign Pred (MinMax X, Y), Z` into simpler comparisons involving the individual operands, such as `icmp samesign Pred X, Z` and `icmp samesign Pred Y, Z`. The flaw is that the optimizer incorrectly preserves the `samesign` flag on these decomposed instructions. While the *result* of the min/max operation is guaranteed to have the same sign as `Z` (validating the original `samesign` flag), the individual inputs `X` or `Y` are not guaranteed to share that sign. If one of the inputs has a different sign than `Z` (but was discarded by the min/max logic), asserting `samesign` on it creates a poison value (undefined behavior). This allows the compiler to make invalid assumptions—such as assuming a variable is non-negative when it is not—leading to miscompilation.

## Example

### Original IR
```llvm
define i1 @test_bug(i32 %x, i32 %y) {
  %min = call i32 @llvm.umin.i32(i32 %x, i32 %y)
  %cmp = icmp samesign ult i32 %min, 10
  ret i1 %cmp
}

declare i32 @llvm.umin.i32(i32, i32)
```
### Optimized IR
```llvm
define i1 @test_bug(i32 %x, i32 %y) {
  %cmp1 = icmp samesign ult i32 %x, 10
  %cmp2 = icmp samesign ult i32 %y, 10
  %cmp = or i1 %cmp1, %cmp2
  ret i1 %cmp
}
```


---

# Issue 136430

## Incorrect Fast-Math Flag Propagation in FCmp/Select to Min/Max Folding

**Description**
The bug occurs during an optimization that folds a floating-point comparison (`fcmp`) followed by a `select` instruction into a floating-point minimum or maximum intrinsic (e.g., `llvm.maxnum` or `llvm.minnum`). When generating the new intrinsic, the compiler incorrectly propagates the "no infinities" (`ninf`) fast-math flag solely from the `select` instruction.

In the original instruction sequence, a `select` instruction marked with `ninf` does not necessarily produce poison if an unselected operand is infinite. However, the replacement `min`/`max` intrinsic operates on both inputs. If the generated intrinsic inherits the `ninf` flag but receives an infinite input (which was validly handled in the source), the result becomes poison. The optimization failed to ensure that the `ninf` flag on the new intrinsic was consistent with the original comparison instruction, which determines whether the operation is safe to perform under the assumption of no infinities.

## Example

### Original IR
```llvm
define float @test_ninf_propagation(float %a, float %b) {
  %cond = fcmp olt float %a, %b
  %res = select ninf i1 %cond, float %a, float %b
  ret float %res
}
```
### Optimized IR
```llvm
define float @test_ninf_propagation(float %a, float %b) {
  %res = call ninf float @llvm.minnum.f32(float %a, float %b)
  ret float %res
}

declare float @llvm.minnum.f32(float, float)
```


---

# Issue 136646

## Incorrect Transformation of Select-Based Absolute Value to Fabs for Negative NaNs

The bug is triggered when the compiler optimizes a manual implementation of the floating-point absolute value operation into the `fabs` intrinsic. The original pattern involves a floating-point comparison (`fcmp`) of a value against zero, which controls a `select` instruction that chooses between the original value and its negation (typically represented as a subtraction from zero).

The flaw arises because the optimization fails to preserve the sign bit of NaN (Not-a-Number) inputs in specific scenarios. If the comparison predicate is "unordered" (e.g., `ugt`), the comparison evaluates to true for NaN inputs. In the original instruction sequence, this causes the `select` to return the input NaN unchanged, thereby preserving its sign bit. In contrast, the `fabs` intrinsic unconditionally clears the sign bit. Consequently, if the input is a negative NaN, the transformation incorrectly changes the result from a negative NaN to a positive NaN, altering the semantics of the program.

## Example

### Original IR
```llvm
define float @test_negative_nan_sign_preservation(float %x) {
  %neg = fsub float -0.000000e+00, %x
  %cond = fcmp uge float %x, -0.000000e+00
  %res = select i1 %cond, float %x, float %neg
  ret float %res
}
```
### Optimized IR
```llvm
define float @test_negative_nan_sign_preservation(float %x) {
  %res = call float @llvm.fabs.f32(float %x)
  ret float %res
}

declare float @llvm.fabs.f32(float)
```


---

# Issue 136650

## Unsafe Folding of Logical AND of Floating-Point Comparisons with Sign-Bit Operations

**Description**
The bug is triggered when the optimizer attempts to fold a logical conjunction (typically represented by a `select` instruction acting as a logical AND) of two floating-point comparisons into a single ordered comparison. The specific pattern involves:
1.  A primary check determining if a floating-point value is ordered (i.e., not NaN).
2.  A secondary check determining if a derived version of that value—modified by sign-bit manipulation operations like `copysign`—is infinite.

The optimization incorrectly merges these two conditions into a single ordered comparison against infinity. This transformation is unsound when the sign-bit manipulation operation depends on additional operands that may be poison (e.g., the second argument of `copysign`). In the original logical conjunction, if the primary check fails (the value is NaN), the result is a defined `false`, effectively masking any poison present in the secondary check. However, the transformed code performs a single comparison on the derived value. If that derived value is poison, the result becomes poison. Consequently, the optimization causes the target code to be "more poisonous" than the source code when the input is NaN and the sign source is poison.

## Example

### Original IR
```llvm
define i1 @test(double %x, double %y) {
  %z = call double @llvm.copysign.f64(double %x, double %y)
  %ord = fcmp ord double %x, 0.0
  %inf = fcmp oeq double %z, 0x7FF0000000000000
  %res = select i1 %ord, i1 %inf, i1 false
  ret i1 %res
}

declare double @llvm.copysign.f64(double, double)
```
### Optimized IR
```llvm
define i1 @test(double %x, double %y) {
  %z = call double @llvm.copysign.f64(double %x, double %y)
  %res = fcmp oeq double %z, 0x7FF0000000000000
  ret i1 %res
}

declare double @llvm.copysign.f64(double, double)
```


---

# Issue 140994

## Summary Title
Incorrect Propagation of Fast Math Flags from Floating-Point Comparison to Select Instruction

## Description
The bug is triggered when the compiler optimizes a `select` instruction whose condition is a floating-point comparison (`fcmp`) annotated with Fast Math Flags (FMF), such as `nsz` (No Signed Zeros). 

When the optimizer transforms the `select` instruction—for instance, by inverting the comparison predicate and swapping the operands to canonicalize the instruction—it incorrectly propagates the Fast Math Flags from the `fcmp` condition to the newly created `select` instruction. 

Flags on an `fcmp` instruction control the semantics of the comparison itself (e.g., treating -0.0 and +0.0 as equal), whereas flags on a `select` instruction control the semantics of the resulting value. By transferring these flags, the compiler incorrectly grants the `select` instruction permission to ignore specific floating-point distinctions (like the sign of zero) in its output. This allows subsequent optimizations to aggressively fold the `select` or substitute operands (e.g., returning -0.0 instead of +0.0) when the original program semantics required the exact bit pattern to be preserved.

## Example

### Original IR
```llvm
define double @test(double %x, double %y, double %a, double %b) {
  %cmp = fcmp nsz uge double %x, %y
  %not = xor i1 %cmp, true
  %sel = select i1 %not, double %a, double %b
  ret double %sel
}
```
### Optimized IR
```llvm
define double @test(double %x, double %y, double %a, double %b) {
  %cmp = fcmp nsz olt double %x, %y
  %sel = select nsz i1 %cmp, double %b, double %a
  ret double %sel
}
```


---

# Issue 142518

## Unsafe Sinking of Bitwise NOT into Binary Operators with Dependent Operands

**Description**
The bug is triggered when the compiler attempts to optimize a logical expression by sinking a bitwise NOT operation into a binary operator (such as `AND` or `OR`) using De Morgan's laws. This transformation involves inverting the operands of the binary operator.

The issue arises specifically when the operands of the binary operator are dependent on each other, such as when one operand is explicitly defined as the bitwise NOT of the other (e.g., `A | ~A`). In this scenario, the second operand is a user of the first operand. When the optimizer processes the first operand to invert it, it may aggressively update its users to reflect the inversion. This update inadvertently modifies the second operand (or the instruction's reference to it) while the transformation is still in progress. The optimizer fails to account for this mutation, leading it to use stale or incorrect information when processing the second operand, resulting in a miscompilation of the logic.

## Example

### Original IR
```llvm
define i32 @test_unsafe_sink(i32 %a) {
  %not_a = xor i32 %a, -1
  %or = or i32 %a, %not_a
  %res = xor i32 %or, -1
  ret i32 %res
}
```
### Optimized IR
```llvm
define i32 @test_unsafe_sink(i32 %a) {
  %not_a = xor i32 %a, -1
  ret i32 %not_a
}
```


---

# Issue 161492

## Incorrect Self-Replacement of Freeze Instructions

**Description**
The bug occurs during the optimization of `freeze` instructions that operate on a `poison` (or `undef`) operand. The optimizer attempts to eliminate these instructions by finding a suitable concrete replacement value derived from the instruction's uses. A specific issue arises when the `freeze` instruction is used in a `select` instruction in a way that makes the optimizer identify the `freeze` instruction itself as the best replacement candidate (for example, if the `freeze` value is used in both arms of the `select`, or if the other arm is equivalent to the `freeze`).

In the optimization framework, instructing the system to replace an instruction with itself is interpreted as a signal to replace all its uses with `poison`. While this mechanism is valid for some dead code scenarios, it is semantically incorrect for `freeze`. A `freeze` instruction is explicitly designed to return a fixed, non-poison value. By replacing it with `poison`, the optimizer incorrectly re-introduces undefined behavior, causing a miscompilation where a valid arbitrary value becomes `poison`.

## Example

### Original IR
```llvm
define i32 @test_freeze_bug(i1 %cond) {
  %f = freeze i32 poison
  %sel = select i1 %cond, i32 %f, i32 %f
  ret i32 %sel
}
```
### Optimized IR
```llvm
define i32 @test_freeze_bug(i1 %cond) {
  ret i32 poison
}
```


---

# Issue 161493

## Incorrect Reuse of Poison-Generating Instructions in Funnel Shift Transformation

**Description**
The bug is triggered when the compiler optimizes a sequence of bitwise operations (typically `OR`s of shifted values) into a funnel shift (rotate) intrinsic. The optimization identifies that a value being computed is equivalent to rotating another existing value found elsewhere in the code. To optimize, it replaces the computation of the target value with a funnel shift applied to that existing source value.

However, the instructions computing the existing source value (such as shift instructions) may possess poison-generating flags (like `nsw` or `nuw`). If specific inputs violate these flags, the source value becomes poison. By reusing this source value to compute the target value via a funnel shift, the optimization propagates the poison to the target. This is incorrect if the original instruction sequence for the target value was computed independently without those specific flags, meaning the original code would have produced a well-defined result while the optimized code produces poison.

## Example

### Original IR
```llvm
define i32 @test(i32 %x) {
  ; This instruction generates poison if %x << 1 overflows (e.g. x = 0x40000000)
  %poison_source = shl nsw i32 %x, 1
  call void @use(i32 %poison_source)

  ; This instruction is safe and equivalent in bits to %poison_source
  %safe_source = shl i32 %x, 1

  ; Funnel shift pattern (rotate left by 1) using the safe source
  %part1 = shl i32 %safe_source, 1
  %part2 = lshr i32 %safe_source, 31
  %res = or i32 %part1, %part2

  ret i32 %res
}

declare void @use(i32)
```
### Optimized IR
```llvm
define i32 @test(i32 %x) {
  ; The poison-generating instruction is preserved
  %poison_source = shl nsw i32 %x, 1
  call void @use(i32 %poison_source)

  ; The optimization incorrectly reuses %poison_source for the funnel shift
  ; If %poison_source is poison, the result %res becomes poison, whereas originally it was well-defined
  %res = call i32 @llvm.fshl.i32(i32 %poison_source, i32 %poison_source, i32 1)

  ret i32 %res
}

declare void @use(i32)
declare i32 @llvm.fshl.i32(i32, i32, i32)
```


---

# Issue 161525

## Incorrect Fast Math Flag Propagation when Folding Floating-Point Subtraction Comparisons

## Description
The bug is triggered when the optimizer simplifies a floating-point comparison between the result of a subtraction and zero (e.g., `fcmp (fsub x, y), 0.0`) into a direct comparison of the subtraction operands (e.g., `fcmp x, y`).

During this transformation, the optimizer incorrectly retains the `ninf` (No Infs) Fast Math Flag from the original comparison instruction on the new comparison instruction. The `ninf` flag asserts that the operands of the instruction are not infinite. In the original sequence, this assertion applied to the result of the subtraction (`x - y`). In the transformed sequence, it applies directly to the inputs `x` and `y`.

This creates a correctness issue because it is possible for the inputs `x` or `y` to be infinite while the result of the subtraction is not (e.g., if the operation results in `NaN`). In such cases, the original instruction was well-defined (as the operand was not infinite), but the new instruction yields `poison` because its operands violate the `ninf` constraint. The optimizer should instead derive the Fast Math Flags for the new comparison from the underlying subtraction instruction, rather than preserving them from the original comparison.

## Example

### Original IR
```llvm
define i1 @test_ninf_propagation(float %x, float %y) {
  %sub = fsub float %x, %y
  %cmp = fcmp ninf oeq float %sub, 0.0
  ret i1 %cmp
}
```
### Optimized IR
```llvm
define i1 @test_ninf_propagation(float %x, float %y) {
  %cmp = fcmp ninf oeq float %x, %y
  ret i1 %cmp
}
```


---

# Issue 161636

## Incorrect Pointer Substitution in Select Simplification

**Description**
The bug is triggered by an optimization strategy that simplifies `select` instructions controlled by an equality comparison (e.g., `icmp eq ptr %a, %b`). The optimizer assumes that because the condition guarantees the two operands are equal in the "true" branch, it is safe to substitute one operand for the other in the selected value. For example, it might transform the pattern `select (%a == %b), %a, %b` directly into `%b`.

This assumption is incorrect for pointers in LLVM IR. Pointer equality implies only that the memory addresses are the same, not that the pointers possess the same provenance (i.e., they may refer to different underlying memory objects or have different validity states). A valid pointer can compare equal to an invalid pointer (such as a pointer to a freed object or a past-the-end pointer of a different allocation). Substituting a valid pointer with one that has different provenance based solely on address equality can produce a result that is illegal to dereference, leading to undefined behavior or value mismatches.

## Example

### Original IR
```llvm
define i32 @test_provenance_substitution(ptr %a, ptr %b) {
  %cmp = icmp eq ptr %a, %b
  %sel = select i1 %cmp, ptr %a, ptr %b
  %val = load i32, ptr %sel, align 4
  ret i32 %val
}
```
### Optimized IR
```llvm
define i32 @test_provenance_substitution(ptr %a, ptr %b) {
  %val = load i32, ptr %b, align 4
  ret i32 %val
}
```


---

# Issue 173793

## Stale Range Metadata Preservation on Funnel Shift Simplification

**Description**
The bug is triggered when the optimizer simplifies the operands of a funnel shift intrinsic (such as `fshl` or `fshr`) based on demanded bits analysis. This simplification rewrites the operands (e.g., by replacing bits that are not demanded with constants), which effectively changes the result value of the operation. However, the optimizer fails to drop or invalidate the `!range` metadata attached to the instruction. Consequently, the new result value may violate the constraints specified by the stale `!range` metadata, causing the instruction to be incorrectly treated as producing a `poison` value.

## Example

### Original IR
```llvm
define i8 @test(i8 %a, i8 %b) {
  ; The fshl result is constrained to [4, 8) (i.e., 4, 5, 6, 7).
  ; This implies bit 2 is always 1, which comes from %a.
  %res = call i8 @llvm.fshl.i8(i8 %a, i8 %b, i8 1), !range !0
  ; We only demand bit 0 of the result, which comes from %b.
  %out = and i8 %res, 1
  ret i8 %out
}

declare i8 @llvm.fshl.i8(i8, i8, i8)

!0 = !{i8 4, i8 8}
```
### Optimized IR
```llvm
define i8 @test(i8 %a, i8 %b) {
  ; The optimizer sees that %a is not demanded for the final result (bit 0).
  ; It simplifies %a to 0.
  ; However, fshl(0, %b, 1) produces 0 or 1 (since 0 << 1 is 0).
  ; This violates the preserved !range !0 which requires values in [4, 8).
  ; The instruction is now poison.
  %res = call i8 @llvm.fshl.i8(i8 0, i8 %b, i8 1), !range !0
  %out = and i8 %res, 1
  ret i8 %out
}

declare i8 @llvm.fshl.i8(i8, i8, i8)

!0 = !{i8 4, i8 8}
```


---

# Issue 37809

## Unsafe Expansion of Unsigned Remainder with Undef Operand

**Description**
The bug is triggered when the compiler optimizes an unsigned remainder (`urem`) instruction where the divisor is a constant with its sign bit set (i.e., it would be negative if treated as a signed integer). To avoid the performance cost of a hardware remainder operation, the optimizer expands this single instruction into a sequence of simpler operations, typically involving a comparison, a subtraction, and a conditional select (or equivalent arithmetic logic).

This expansion logic is flawed because it duplicates the dividend operand (the first argument of the remainder), increasing its number of uses from one in the original code to multiple uses in the generated sequence. If the dividend is an undefined value (`undef`), LLVM semantics allow each individual use to resolve to a different arbitrary value. Consequently, the transformed code may execute with inconsistent views of the operand—for example, treating it as one value to satisfy the comparison condition and a different value when performing the subtraction—resulting in a computed value that contradicts the semantics of the original instruction.

## Example

### Original IR
```llvm
define i32 @test_urem_undef() {
  %res = urem i32 undef, 2147483648
  ret i32 %res
}
```
### Optimized IR
```llvm
define i32 @test_urem_undef() {
  %cmp = icmp ult i32 undef, 2147483648
  %sub = sub i32 undef, 2147483648
  %res = select i1 %cmp, i32 undef, i32 %sub
  ret i32 %res
}
```


---

# Issue 44206

## Incorrect Inbounds Preservation When Swapping Nested GEP Offsets

**Description**
The bug is triggered when the optimizer reorders nested `getelementptr` (GEP) instructions, effectively swapping the order in which two offsets are applied to a base pointer. This transformation is often performed to move loop-invariant offsets to the inner GEP, allowing them to be hoisted out of loops.

The issue arises because the optimizer unconditionally preserves the `inbounds` keyword on the new GEP instructions without verifying that the new intermediate pointer calculation remains within the bounds of the allocated object. If the two offsets have opposite signs (e.g., one is positive and one is negative), the original order might produce a valid intermediate pointer, whereas the swapped order might cause the intermediate pointer to go out of bounds (e.g., stepping before the start of an array). By marking this invalid intermediate calculation as `inbounds`, the optimizer causes the result to become a poison value, leading to a miscompilation where valid code becomes undefined.

## Example

### Original IR
```llvm
define i8* @test_gep_inbounds_preservation(i8* %ptr, i64 %idx) {
  ; Original order: Apply positive variable offset first, then negative constant offset.
  ; If %idx is large enough, the intermediate pointer is inbounds.
  %gep1 = getelementptr inbounds i8, i8* %ptr, i64 %idx
  %gep2 = getelementptr inbounds i8, i8* %gep1, i64 -10
  ret i8* %gep2
}
```
### Optimized IR
```llvm
define i8* @test_gep_inbounds_preservation(i8* %ptr, i64 %idx) {
  ; Optimized order (Buggy): Offsets swapped to hoist constant.
  ; The inner GEP applies the negative offset first.
  ; If %ptr is the start of an object, %gep1 is out-of-bounds.
  ; Because 'inbounds' is preserved, %gep1 becomes poison, causing the result to be poison.
  %gep1 = getelementptr inbounds i8, i8* %ptr, i64 -10
  %gep2 = getelementptr inbounds i8, i8* %gep1, i64 %idx
  ret i8* %gep2
}
```


---

# Issue 47012

## Unsafe Folding of Select with Variable Shift into Bitwise Mask

**Description**
The bug is triggered when the optimizer attempts to fold a `select` instruction that chooses between a bit-test result (derived from a shift instruction) and a constant. The optimization strategy converts this pattern into a sequence of bitwise operations (typically creating a mask via `shl` and combining it with `or`) to test the relevant bits in a single step.

The issue arises because the transformation unconditionally uses the shift amount from the original shift instruction to generate the mask. In the original IR, the `select` instruction acts as a filter: if the condition directs execution to the constant arm, the result of the shift is ignored. This means that if the shift amount is `poison` (or otherwise invalid), the `poison` value is suppressed and does not affect the return value. In the transformed IR, however, the shift amount is used to compute the mask regardless of the condition. If the shift amount is `poison`, the resulting mask and the subsequent computation become `poison`. This results in the target code evaluating to `poison` in cases where the source code would have returned a valid, non-poison constant.

## Example

### Original IR
```llvm
define i32 @test_unsafe_select_fold(i1 %cond, i32 %y) {
  %mask = shl i32 1, %y
  %res = select i1 %cond, i32 %mask, i32 0
  ret i32 %res
}
```
### Optimized IR
```llvm
define i32 @test_unsafe_select_fold(i1 %cond, i32 %y) {
  %zext = zext i1 %cond to i32
  %res = shl i32 %zext, %y
  ret i32 %res
}
```


---

# Issue 53252

## Stale Predicate Variable in Clamp Canonicalization

**Description**
The bug is triggered when the optimizer attempts to simplify a sequence of `select` instructions that resemble a "clamp" operation (limiting a value within a specific range). Specifically, the issue arises when the comparison predicate in the `select` condition uses a strict inequality (such as unsigned greater-than `ugt` or unsigned less-than-or-equal `ule`) that the optimizer tries to canonicalize into a non-strict form (such as `uge` or `ult`) by adjusting the comparison constant.

During this canonicalization process, the optimizer correctly updates the constant operand (e.g., incrementing it) but fails to update the internal variable tracking the predicate type. Subsequent logic relies on this predicate variable to determine the orientation of the range bounds—specifically, whether to swap the lower and upper thresholds of the clamp. Because the variable retains the old, non-canonical predicate, the check fails, and the necessary swap is skipped. This results in the optimized code using incorrect bounds for the clamp, leading to a miscompilation where the wrong value is selected.

## Example

### Original IR
```llvm
define i8 @test(i8 %a) {
  %cmp1 = icmp ugt i8 %a, 4
  %sel1 = select i1 %cmp1, i8 %a, i8 5
  %cmp2 = icmp ult i8 %sel1, 2
  %sel2 = select i1 %cmp2, i8 %sel1, i8 2
  ret i8 %sel2
}
```
### Optimized IR
```llvm
define i8 @test(i8 %a) {
  %1 = call i8 @llvm.umax.i8(i8 %a, i8 2)
  %2 = call i8 @llvm.umin.i8(i8 %1, i8 5)
  ret i8 %2
}

declare i8 @llvm.umax.i8(i8, i8)
declare i8 @llvm.umin.i8(i8, i8)
```


---

# Issue 54077

## Incorrect Propagation of Fast Math Flags in Select to Copysign Transformation

**Description**
The bug is triggered when the compiler optimizes a code pattern that manually selects between floating-point constants based on the sign of a value (often implemented via bitcasts and integer comparisons) by replacing it with a `copysign` intrinsic. During this transformation, the optimizer incorrectly propagates Fast Math Flags (specifically "no signed zeros" or `nsz`) from the original `select` instruction to the newly generated instructions, such as the `copysign` call or an intermediate `fneg` instruction used to invert the sign argument.

The issue arises because the `copysign` logic relies on the precise preservation of the sign bit to replicate the behavior of the original explicit sign check. However, the `nsz` flag permits the compiler to treat positive and negative zero as interchangeable. When this flag is applied to the generated instructions, the compiler may canonicalize the sign argument (e.g., converting `-0.0` to `+0.0`), causing `copysign` to produce a result with the wrong sign. This leads to a value mismatch between the original strict bitwise logic and the optimized floating-point logic when processing zero values.

## Example

### Original IR
```llvm
define float @test_nsz_propagation(float %x) {
  %i = bitcast float %x to i32
  %cond = icmp slt i32 %i, 0
  %r = select nsz i1 %cond, float -1.0, float 1.0
  ret float %r
}
```
### Optimized IR
```llvm
define float @test_nsz_propagation(float %x) {
  %r = call nsz float @llvm.copysign.f32(float 1.0, float %x)
  ret float %r
}

declare float @llvm.copysign.f32(float, float)
```


---

# Issue 55721

## Incorrect Replacement of PHI Node with Switch Condition by Ignoring Default Case

## Description
The bug occurs in an optimization that attempts to replace a PHI node with the condition operand of a dominating `switch` instruction. This transformation is valid only if, for every control flow path from the `switch` to the PHI node, the value incoming to the PHI is equal to the value the `switch` condition must hold to take that path.

The issue arises because the analysis logic verifies this relationship by iterating over the explicit cases of the `switch` instruction but fails to account for the `default` case. If the `default` case leads to the PHI node (either directly or via a shared successor), the `switch` condition can hold any value not covered by the explicit cases, while the PHI node typically receives a specific, fixed value for that path. Since the optimizer neglects to check the constraints of the `default` path, it incorrectly concludes that the PHI value is always equivalent to the `switch` condition. This leads to a miscompilation where the PHI node is replaced by the raw condition value, causing incorrect results when the execution falls through the `default` case.

## Example

### Original IR
```llvm
define i32 @bug_trigger(i32 %cond) {
entry:
  switch i32 %cond, label %sw.default [
    i32 0, label %sw.bb
  ]

sw.bb:
  br label %exit

sw.default:
  br label %exit

exit:
  ; The PHI node returns 0 if %cond is 0 (via sw.bb).
  ; It returns 42 if %cond is not 0 (via sw.default).
  ; The bug is that the optimizer sees the explicit case (0 -> 0) matches %cond,
  ; but ignores the default case where %cond != 42.
  %result = phi i32 [ 0, %sw.bb ], [ 42, %sw.default ]
  ret i32 %result
}
```
### Optimized IR
```llvm
define i32 @bug_trigger(i32 %cond) {
entry:
  switch i32 %cond, label %sw.default [
    i32 0, label %sw.bb
  ]

sw.bb:
  br label %exit

sw.default:
  br label %exit

exit:
  ; The optimizer incorrectly replaced the PHI node with %cond.
  ; If %cond is 5, this returns 5, whereas the original code returned 42.
  ret i32 %cond
}
```


---

# Issue 55722

## Invalid `inbounds` Preservation when Merging GetElementPtr Instructions with Opposing Offset Signs

## Description
The bug is triggered when the optimizer merges two consecutive `getelementptr` (GEP) instructions into a single GEP instruction. When both original instructions are marked with the `inbounds` keyword, the optimizer attempts to preserve this property on the resulting merged instruction.

The issue arises from how the merged GEP represents the combined offset. The optimization may restructure the address calculation by combining a positive offset from one GEP and a negative offset from the other into a sequence of indices on the new GEP. For instance, a net small negative offset might be represented in the merged GEP as a large negative step (e.g., decrementing a base array index) followed by a positive step (e.g., accessing a field within a struct).

According to LLVM IR semantics, the `inbounds` keyword implies that not only the final address but also every intermediate address formed by the successive addition of indices must remain within the bounds of the allocated object. While the original sequence of instructions may have kept all intermediate values within bounds, the restructured calculation in the merged GEP can introduce an intermediate address that steps out of bounds (for example, stepping before the start of the allocation). By incorrectly retaining the `inbounds` keyword on this new calculation sequence, the optimizer transforms a valid pointer calculation into a poison value.

## Example

### Original IR
```llvm
%struct.S = type { [100 x i8] }

define i8* @test(%struct.S* %ptr) {
  ; Step 1: Move forward 99 bytes (within the first struct)
  %gep1 = getelementptr inbounds %struct.S, %struct.S* %ptr, i64 0, i32 0, i64 99
  ; Step 2: Move backward 100 bytes (net offset -1 byte)
  %gep2 = getelementptr inbounds i8, i8* %gep1, i64 -100
  ret i8* %gep2
}
```
### Optimized IR
```llvm
%struct.S = type { [100 x i8] }

define i8* @test(%struct.S* %ptr) {
  ; Merged GEP: Decomposed into -1 struct index (-100 bytes) and +99 array index (+99 bytes)
  ; This creates an intermediate address (%ptr - 100 bytes) which may be out of bounds
  ; even if the final address (%ptr - 1 byte) is valid.
  %gep2 = getelementptr inbounds %struct.S, %struct.S* %ptr, i64 -1, i32 0, i64 99
  ret i8* %gep2
}
```


---

# Issue 57899

## Incorrect Optimization of ZExt on Equality Comparison

**Description**
The bug is triggered when the compiler optimizes a zero-extension (`zext`) instruction applied to an equality comparison (`icmp eq` or `icmp ne`). The issue arises specifically when comparing a value `X` against a constant `C` that is a power of two, under the condition that `X` is statically analyzed to have at most one specific bit potentially set (i.e., `X` is known to be either zero or a specific power of two).

The optimizer attempts to simplify the expression `zext(X == C)` by directly extracting the potentially set bit from `X` (e.g., by shifting `X` so that the bit moves to the least significant position). This transformation assumes that checking `X == C` is equivalent to checking if `X` is non-zero. However, this assumption is only valid if the bit position set in the constant `C` matches the bit position that can be set in `X`. The compiler fails to verify that these bit positions align. Consequently, if `X` has a potential bit at position $N$ and `C` has a bit at position $M$ (where $N \neq M$), the optimizer incorrectly transforms the comparison—which should be false—into a value that evaluates to true when `X` is non-zero.

## Example

### Original IR
```llvm
define i32 @test_bug(i8 %x) {
  %masked = and i8 %x, 4
  %cmp = icmp eq i8 %masked, 8
  %res = zext i1 %cmp to i32
  ret i32 %res
}
```
### Optimized IR
```llvm
define i32 @test_bug(i8 %x) {
  %masked = and i8 %x, 4
  %shifted = lshr i8 %masked, 2
  %res = zext i8 %shifted to i32
  ret i32 %res
}
```


---

# Issue 59836

## Summary Title
**Unsafe Optimization of Comparison Involving Wrapping Multiplication of Zero-Extended Operands**

## Description
The bug is triggered when the compiler optimizes an integer comparison (`icmp`) where one operand is a multiplication of two zero-extended values (e.g., `mul (zext A), (zext B)`). The optimization logic attempts to recognize this pattern as an overflow check or a range check on the product of `A` and `B`, transforming it into a canonical form that checks the properties of the full, non-overflowing product (often utilizing overflow intrinsics).

The flaw in this strategy is the assumption that the multiplication instruction always computes the exact, full-precision product of the extended operands. However, if the bit width of the multiplication's result type is insufficient to hold the maximum possible product of `A` and `B` (i.e., the width is less than the sum of the widths of `A` and `B`), the multiplication wraps (performs modulo arithmetic). In such scenarios, the original code compares the wrapped result, whereas the optimized code behaves as if comparing the unwrapped, infinite-precision product. This discrepancy leads to incorrect execution when the multiplication actually overflows in the original program. The transformation is only valid if the multiplication is guaranteed not to wrap (e.g., it has the `nuw` flag).

## Example

### Original IR
```llvm
define i1 @test_unsafe_mul_opt(i8 %a, i8 %b) {
  %ext_a = zext i8 %a to i12
  %ext_b = zext i8 %b to i12
  %mul = mul i12 %ext_a, %ext_b
  %cmp = icmp ugt i12 %mul, 4000
  ret i1 %cmp
}
```
### Optimized IR
```llvm
define i1 @test_unsafe_mul_opt(i8 %a, i8 %b) {
  %ext_a = zext i8 %a to i16
  %ext_b = zext i8 %b to i16
  %mul = mul i16 %ext_a, %ext_b
  %cmp = icmp ugt i16 %mul, 4000
  ret i1 %cmp
}
```


---

# Issue 60906

## Unsafe Sinking of Integer Division/Remainder Past Select Instruction

## Description
The bug is triggered when the optimizer attempts to reduce code size by sinking an integer division or remainder operation (such as `sdiv`, `udiv`, `srem`, or `urem`) through a `select` instruction. This optimization targets patterns where a `select` chooses between two division/remainder operations that share a common operand (e.g., `select(cond, X / Y, X / Z)`). The optimizer transforms this into a single operation where the differing operand is selected first (e.g., `X / select(cond, Y, Z)`).

This transformation is incorrect when the condition of the `select` instruction is poison. In the original code, if the divisors (`Y` and `Z`) are safe (non-zero) values, the operations are well-defined, and a poison condition merely results in a poison output without side effects. However, in the transformed code, a poison condition causes the `select` to produce a poison value as the new operand for the division/remainder. Since integer division or remainder with a poison divisor (or a poison dividend in signed cases susceptible to overflow) is treated as Undefined Behavior (because poison can be refined to values like zero), the transformation introduces immediate Undefined Behavior in scenarios where the original code was safe.

## Example

### Original IR
```llvm
define i32 @test_unsafe_sink(i1 %cond, i32 %x) {
  %div1 = sdiv i32 %x, 42
  %div2 = sdiv i32 %x, 24
  %res = select i1 %cond, i32 %div1, i32 %div2
  ret i32 %res
}
```
### Optimized IR
```llvm
define i32 @test_unsafe_sink(i1 %cond, i32 %x) {
  %1 = select i1 %cond, i32 42, i32 24
  %res = sdiv i32 %x, %1
  ret i32 %res
}
```


---

# Issue 62401

## Unsafe expansion of urem to select with duplicated undef operands

**Description**: 
The bug is triggered when the compiler optimizes an unsigned remainder (`urem`) instruction where the divisor is a sign-extended boolean value (which results in either 0 or -1). The optimization attempts to replace the arithmetic operation `urem %y, -1` with a logically equivalent `select` sequence: `(%y == -1) ? 0 : %y`.

The issue arises because the transformation duplicates the dividend operand (`%y`), using it once in the comparison condition and again as the "false" value of the `select` instruction. In LLVM IR, multiple uses of an `undef` value can independently resolve to different concrete values. This allows a scenario where the comparison `(%y == -1)` resolves to false (implying `%y` is not -1), but the `%y` returned by the `select` resolves to -1. Consequently, the transformed code can return -1. However, in the original `urem` operation, if the input is -1, the result is 0; if the input is not -1, the result is the input itself (which is not -1). Therefore, the original instruction can never produce -1. The transformation introduces a value that was impossible in the original program, leading to a miscompilation.

## Example

### Original IR
```llvm
define i8 @test(i1 %c) {
  %ext = sext i1 %c to i8
  %rem = urem i8 undef, %ext
  ret i8 %rem
}
```
### Optimized IR
```llvm
define i8 @test(i1 %c) {
  %cmp = icmp eq i8 undef, -1
  %rem = select i1 %cmp, i8 0, i8 undef
  ret i8 %rem
}
```


---

# Issue 70509

## Incorrect Fallback Transformation for Multi-Use Arithmetic Shifts in Comparisons

## Description
The bug is triggered at the LLVM IR level when the optimizer processes an integer comparison (`icmp`) instruction that uses the result of an arithmetic shift right (`ashr`) instruction with a constant shift amount. The specific condition required to trigger the issue is that the `ashr` instruction must have **multiple uses** (i.e., its result is consumed by the comparison and at least one other instruction).

In the faulty optimization logic, a specialized handler designed to correctly transform `ashr` comparisons is guarded by a check that restricts its application to instructions with a single use. When the `ashr` instruction has multiple uses, this correct handler is skipped. Consequently, the execution flow falls through to a subsequent, more generic transformation logic. This generic logic fails to properly account for the sign-extension behavior of arithmetic shifts, effectively treating the `ashr` as a logical shift (`lshr`) or a generic binary operation. This results in an invalid simplification of the comparison—such as incorrect constant folding or predicate modification—leading to runtime miscompilations, particularly when the shifted value is negative.

## Example

### Original IR
```llvm
define i1 @test(i8 %x) {
  %y = ashr i8 %x, 4
  %z = icmp ugt i8 %y, 15
  call void @use(i8 %y)
  ret i1 %z
}

declare void @use(i8)
```
### Optimized IR
```llvm
define i1 @test(i8 %x) {
  %y = ashr i8 %x, 4
  call void @use(i8 %y)
  ret i1 false
}

declare void @use(i8)
```


---

# Issue 72927

## Incorrect Non-Negative Inference for Zero-Extension Used as Shift Amount

**Description**:
The bug is triggered when the optimizer incorrectly infers the `nneg` (non-negative) flag for a zero-extension (`zext`) instruction that is used as the shift amount operand in a shift instruction. 

The optimization relies on the constraint that a shift amount must be strictly less than the bit width of the type being shifted to be well-defined. The compiler assumes that this upper bound on the value implies the value is always "small" and therefore non-negative within the smaller source type of the `zext`. However, this assumption fails when the bit width of the shifted type is large enough to allow shift amounts that, while valid for the shift, correspond to negative values (values with the sign bit set) in the `zext`'s source type. By adding the `nneg` flag in these cases, the compiler incorrectly asserts that the source value must be positive, turning valid shift operations into undefined behavior.

## Example

### Original IR
```llvm
define i256 @trigger(i8 %x, i256 %y) {
  %z = zext i8 %x to i256
  %s = shl i256 %y, %z
  ret i256 %s
}
```
### Optimized IR
```llvm
define i256 @trigger(i8 %x, i256 %y) {
  %z = zext nneg i8 %x to i256
  %s = shl i256 %y, %z
  ret i256 %s
}
```


---

# Issue 74739

## Incorrect Retention of Poison-Generating Flags During Associative Constant Folding

**Description**:
The bug is triggered during an optimization pass that simplifies chains of associative binary operations (such as bitwise OR or integer addition) interrupted by a cast instruction. The transformation identifies a pattern where an inner binary operation with a constant operand is followed by a cast, which is then followed by an outer binary operation with another constant operand (e.g., `(Cast (Op X, C1)) Op C2`).

The optimization attempts to fold the two constants (`C1` and `C2`) together and reassociate the expression to reduce instruction count. The flaw in the logic is that it correctly updates the operands of the outer binary operation but fails to remove its poison-generating flags (such as `disjoint`, `nsw`, or `nuw`). These flags assert strict constraints on the operands, such as the absence of overlapping bits or signed overflow. Because the operands have been modified by the reassociation, the original constraints may no longer hold. Consequently, the transformed instruction incorrectly evaluates to a `poison` value when these conditions are violated, leading to miscompilation.

## Example

### Original IR
```llvm
define i16 @test(i8 %x) {
  %inner = or i8 %x, 1
  %cast = zext i8 %inner to i16
  %outer = or disjoint i16 %cast, 2
  ret i16 %outer
}
```
### Optimized IR
```llvm
define i16 @test(i8 %x) {
  %cast = zext i8 %x to i16
  %outer = or disjoint i16 %cast, 3
  ret i16 %outer
}
```


---

# Issue 76441

## Incorrect Constant Extension in Inverted Addition Optimization

**Description**
The bug is triggered when the compiler optimizes an addition instruction where both operands are identified as bitwise-inverted values (e.g., `~A + ~B`). The optimizer attempts to simplify this pattern into an equivalent subtraction form: `-2 - (A + B)`.

The issue arises from how the constant `-2` is generated for this transformation. The compiler uses a method that interprets the immediate value `-2` as a 64-bit integer and zero-extends it to the bit width of the operation's type. When the target type is wider than 64 bits (such as `i128`), this results in a large positive constant (representing `2^64 - 2`) rather than the intended sign-extended negative value. Consequently, the transformed expression computes an incorrect result for wide integer types.

## Example

### Original IR
```llvm
define i128 @test_incorrect_const_ext(i128 %a, i128 %b) {
  %not_a = xor i128 %a, -1
  %not_b = xor i128 %b, -1
  %res = add i128 %not_a, %not_b
  ret i128 %res
}
```
### Optimized IR
```llvm
define i128 @test_incorrect_const_ext(i128 %a, i128 %b) {
  %1 = add i128 %a, %b
  %res = sub i128 18446744073709551614, %1
  ret i128 %res
}
```


---

# Issue 85536

## Summary Title
Speculation of Instructions with UB-Implying Attributes into Select Operands

## Description
The bug is triggered when the optimizer attempts to fold an instruction that operates on the result of a `select` instruction into the operands of that `select`. This transformation involves cloning the instruction and applying it speculatively to both the true and false input values of the `select`, effectively hoisting the operation before the selection logic.

The issue arises because the cloned instructions retain attributes and metadata (such as `noundef`, `nonnull`, or range constraints) that imply Undefined Behavior (UB) if their inputs do not satisfy specific conditions. In the original program, the instruction is only executed on the selected value, which is implicitly guaranteed to be valid for that operation. However, the transformation speculates the instruction on the unselected value as well. If the unselected value violates the strict attributes of the instruction (e.g., it is `poison` or out of range), the transformed code introduces UB on a valid execution path where the operation would not have originally occurred on that value. This incorrect introduction of UB allows the compiler to erroneously optimize away valid code, leading to miscompilation.

## Example

### Original IR
```llvm
define i32 @test_bug(i1 %cond, i32 %a) {
  %sel = select i1 %cond, i32 %a, i32 poison
  %res = call i32 @speculatable_fn(i32 noundef %sel)
  ret i32 %res
}

declare i32 @speculatable_fn(i32 noundef) #0
attributes #0 = { speculatable willreturn memory(none) }
```
### Optimized IR
```llvm
define i32 @test_bug(i1 %cond, i32 %a) {
  %1 = call i32 @speculatable_fn(i32 noundef %a)
  %2 = call i32 @speculatable_fn(i32 noundef poison)
  %res = select i1 %cond, i32 %1, i32 %2
  ret i32 %res
}

declare i32 @speculatable_fn(i32 noundef) #0
attributes #0 = { speculatable willreturn memory(none) }
```


---

# Issue 89338

## Incorrect Canonicalization of Funnel Shift Right to Funnel Shift Left

**Description**
The bug is triggered when the optimizer attempts to canonicalize a funnel shift right (`fshr`) intrinsic into a funnel shift left (`fshl`) intrinsic. The transformation logic relies on the mathematical relationship that shifting right by `N` is often equivalent to shifting left by `BitWidth - N`. Consequently, the optimizer rewrites `fshr(Op0, Op1, ShiftAmt)` as `fshl(Op0, Op1, BitWidth - ShiftAmt)`.

However, this transformation is invalid when the `ShiftAmt` is zero (or a multiple of the bit width). In the case of a zero shift:
*   `fshr(Op0, Op1, 0)` returns the second operand (`Op1`), as it extracts the lower bits of the concatenated value.
*   `fshl(Op0, Op1, 0)` returns the first operand (`Op0`), as it extracts the upper bits of the concatenated value (note that `BitWidth - 0` modulo `BitWidth` is `0`).

The optimizer failed to verify that the shift amount was non-zero before applying this transformation. As a result, when the shift amount is effectively zero, the transformed code returns the wrong operand (`Op0` instead of `Op1`), leading to a miscompilation.

## Example

### Original IR
```llvm
define i32 @test_canonicalize_fshr(i32 %op0, i32 %op1, i32 %amt) {
  %res = call i32 @llvm.fshr.i32(i32 %op0, i32 %op1, i32 %amt)
  ret i32 %res
}

declare i32 @llvm.fshr.i32(i32, i32, i32)
```
### Optimized IR
```llvm
define i32 @test_canonicalize_fshr(i32 %op0, i32 %op1, i32 %amt) {
  %sub = sub i32 32, %amt
  %res = call i32 @llvm.fshl.i32(i32 %op0, i32 %op1, i32 %sub)
  ret i32 %res
}

declare i32 @llvm.fshl.i32(i32, i32, i32)
```


---

# Issue 89500

## Incorrect Poison Propagation in Select Folding with Bitwise Not

**Description**
The bug is triggered when the compiler optimizes a `select` instruction by replacing it with its "false" operand, relying on a logical equivalence between the "true" and "false" branches when the condition (an equality comparison) is met. This optimization specifically targets patterns involving bitwise operations, where the "false" operand is constructed using a bitwise NOT operation (represented in LLVM IR as an XOR with an all-ones constant).

The vulnerability lies in the pattern matching logic for the bitwise NOT operation, which incorrectly treats vector constants containing `poison` elements as valid all-ones masks. If the constant mask used for the NOT operation contains `poison`, the resulting value becomes `poison` in the corresponding vector lanes. When the optimizer unconditionally replaces the `select` with this "false" operand, it introduces `poison` into lanes that would have otherwise yielded a well-defined value from the "true" branch. This causes the transformed code to be more poisonous than the original source, resulting in a miscompilation.

## Example

### Original IR
```llvm
define <2 x i8> @test(<2 x i8> %a) {
  %not = xor <2 x i8> %a, <i8 -1, i8 poison>
  %cmp = icmp eq <2 x i8> %a, zeroinitializer
  %sel = select <2 x i1> %cmp, <2 x i8> <i8 -1, i8 -1>, <2 x i8> %not
  ret <2 x i8> %sel
}
```
### Optimized IR
```llvm
define <2 x i8> @test(<2 x i8> %a) {
  %not = xor <2 x i8> %a, <i8 -1, i8 poison>
  ret <2 x i8> %not
}
```


---

# Issue 89516

## Incorrect Pattern Matching Overwrites Variable Binding in Select Optimization

**Description**
The bug occurs in an optimization that attempts to simplify a `select` instruction based on a specific pattern involving signed remainder (`srem`) and addition operations. The intended pattern is `select (X < 0), (X + M), X`, where `X` is the result of `srem(..., M)`. This pattern canonicalizes modulo arithmetic for negative results.

The issue arises because the pattern matching logic fails to enforce that the value checked in the condition (`X`) is the same as the value used in the arithmetic operations. The optimizer first identifies the value `X` from the `select`'s condition (e.g., `icmp slt X, 0`). It then attempts to match the addition instruction in the `true` branch. However, instead of checking that one of the addition's operands is specifically `X`, the matcher uses a binding mechanism that captures the operand into the variable holding `X`.

This action overwrites the original value of `X` (from the condition) with the operand found in the addition (let's call it `Y`). The subsequent logic validates `Y` (checking if it is an `srem` and matches the `false` branch), but the constraint that `X` must equal `Y` is lost. Consequently, the optimization incorrectly triggers for code like `select (X < 0), (Y + M), Y` where `X` and `Y` are different values. The optimizer then transforms the code assuming the condition applies to `Y`, leading to a miscompilation.

## Example

### Original IR
```llvm
define i8 @test(i8 %a, i8 %x) {
  %y = srem i8 %a, 16
  %cond = icmp slt i8 %x, 0
  %add = add i8 %y, 16
  %res = select i1 %cond, i8 %add, i8 %y
  ret i8 %res
}
```
### Optimized IR
```llvm
define i8 @test(i8 %a, i8 %x) {
  %res = and i8 %a, 15
  ret i8 %res
}
```


---

# Issue 91127

## Incorrect Extension Logic when Swapping Operands in Truncated Comparison Folding

**Description**
The bug occurs in the instruction combination pass when optimizing an integer comparison between two truncated values (e.g., `icmp (trunc X), (trunc Y)`). The optimizer attempts to eliminate the truncations by widening the comparison to the original source types (e.g., comparing `X` and `Y` directly, potentially with extensions).

During this process, the optimizer may canonicalize the comparison by swapping the operands. The issue is that the logic fails to correctly update the extension mode (sign-extension vs. zero-extension) for the operand that is moved to the right-hand side after the swap. The decision to sign-extend or zero-extend is based on the flags of the truncation instruction (such as `nsw` or `nuw`). When the operands are swapped, the optimizer incorrectly retains the extension decision derived from the previous operand or fails to re-evaluate it for the new right-hand operand.

This leads to the generation of an incorrect extension instruction (e.g., `zext` instead of `sext`) for the widened comparison. Consequently, if the value requires sign-extension (e.g., it is negative), the zero-extended value will differ, causing the optimized comparison to yield an incorrect result compared to the original code.

## Example

### Original IR
```llvm
define i1 @test_trunc_cmp_swap_bug(i32 %a, i32 %b) {
  ; %a_zext is effectively zero-extended from i8 (0..255)
  %a_zext = and i32 %a, 255
  ; %b_sext is effectively sign-extended from i8 (-128..127)
  %b_shl = shl i32 %b, 24
  %b_sext = ashr i32 %b_shl, 24
  
  %t1 = trunc i32 %a_zext to i8
  %t2 = trunc i32 %b_sext to i8
  
  ; Signed comparison of truncated values.
  ; If %a_zext is 255 (0xFF), %t1 is -1.
  ; If %b_sext is 0, %t2 is 0.
  ; -1 < 0 is true.
  %cmp = icmp slt i8 %t1, %t2
  ret i1 %cmp
}
```
### Optimized IR
```llvm
define i1 @test_trunc_cmp_swap_bug(i32 %a, i32 %b) {
  %a_zext = and i32 %a, 255
  %b_shl = shl i32 %b, 24
  %b_sext = ashr i32 %b_shl, 24
  
  ; BUG: The comparison is widened to i32, but the extension logic is incorrect.
  ; %a_zext is treated as the value itself (zero-extended), but for a signed comparison
  ; corresponding to 'slt i8', it should have been sign-extended.
  ; If %a_zext is 255, it is positive in i32.
  ; If %b_sext is 0, it is 0.
  ; 255 < 0 is false. The result differs from the original.
  %cmp = icmp slt i32 %a_zext, %b_sext
  ret i1 %cmp
}
```


---

# Issue 92887

## Incorrect Refinement of Undef to Poison in Shuffle Vector Optimization

## Description
The bug is triggered when the optimizer attempts to simplify a `shufflevector` instruction where the first operand is a vector instruction (such as a binary operation or cast) and the second operand is an `undef` constant.

The optimization strategy involves "sinking" the shuffle into the operands of the first instruction, effectively rewriting the code to evaluate the operation in the shuffled element order directly. This transformation treats the shuffle as a single-source operation, assuming that the second operand serves merely as a placeholder for unused or "don't care" lanes, effectively treating it as `poison`.

However, in LLVM IR, `undef` and `poison` have distinct semantics: `undef` represents an unspecified bit pattern, while `poison` represents a deferred undefined behavior that propagates through operations. When the second operand is `undef`, the transformation incorrectly upgrades it to `poison`. If the shuffle mask selects elements from this `undef` operand, the optimized code produces `poison` instead of `undef`. This is an invalid refinement because it makes the target code more undefined than the source, potentially causing valid computations to result in `poison`.

## Example

### Original IR
```llvm
define <2 x i8> @test(<2 x i8> %a, <2 x i8> %b) {
  %op = add <2 x i8> %a, %b
  %res = shufflevector <2 x i8> %op, <2 x i8> undef, <2 x i32> <i32 0, i32 2>
  ret <2 x i8> %res
}
```
### Optimized IR
```llvm
define <2 x i8> @test(<2 x i8> %a, <2 x i8> %b) {
  %1 = shufflevector <2 x i8> %a, <2 x i8> poison, <2 x i32> <i32 0, i32 2>
  %2 = shufflevector <2 x i8> %b, <2 x i8> poison, <2 x i32> <i32 0, i32 2>
  %res = add <2 x i8> %1, %2
  ret <2 x i8> %res
}
```


---

# Issue 93769

## Incorrect Propagation of No-Infinities Flag During Constant Folding of Floating-Point Negation

**Description**
The bug is triggered when the optimizer folds a floating-point negation (`fneg`) instruction into a preceding floating-point binary operation (such as multiplication or division) by negating a constant operand. The issue arises because the transformation incorrectly propagates the `ninf` (No Infinities) FastMathFlag from the `fneg` instruction to the newly created binary operation.

Semantically, the `ninf` flag on an `fneg` instruction only asserts that the value being negated (the result of the preceding operation) is not infinity. It does not impose constraints on the operands of that preceding operation. For instance, a multiplication involving an infinite operand can validly produce a `NaN` result (e.g., `0 * Inf`), which satisfies the `ninf` constraint of the subsequent negation.

However, applying `ninf` to a binary operation asserts that both its operands and its result are not infinity. By transferring this flag from the negation to the binary operation, the optimizer incorrectly assumes the operands must be finite. This causes valid program states—where infinite operands produce non-infinite results—to be treated as undefined behavior (poison) in the transformed code, leading to a miscompilation.

## Example

### Original IR
```llvm
define float @test_ninf_propagation(float %x) {
  %mul = fmul float %x, 0.000000e+00
  %neg = fneg ninf float %mul
  ret float %neg
}
```
### Optimized IR
```llvm
define float @test_ninf_propagation(float %x) {
  %neg = fmul ninf float %x, -0.000000e+00
  ret float %neg
}
```


---

# Issue 95547

## Unsafe Narrowing of Trapping Instructions Based on Future Context

**Description:**
The bug is triggered when the compiler attempts to optimize integer division or remainder instructions by reducing their bit-width (e.g., demoting a 16-bit division to an 8-bit division) to match a subsequent truncation of the result. To perform this transformation safely, the compiler verifies that the high bits of the operands are zero, ensuring that the values fit within the narrower type without data loss.

The flaw occurs because the compiler uses the context of the *user* instruction (the subsequent truncation) to prove that the operands are within range. If the user instruction is protected by control flow conditions (such as a loop guard or branch) that do not apply to the division instruction itself, the operands may be guaranteed to be small at the use site but can be large at the definition site.

When the division instruction executes with a large value that is valid in the original bit-width, narrowing it based on the restricted range of the future context effectively truncates the value. If a non-zero divisor is truncated to zero (e.g., 256 becoming 0 in 8-bit), the transformation introduces a division-by-zero trap that did not exist in the original program.

## Example

### Original IR
```llvm
define i8 @test(i16 %a, i16 %b) {
entry:
  %div = udiv i16 %a, %b
  %cmp1 = icmp ult i16 %a, 256
  %cmp2 = icmp ult i16 %b, 256
  %cond = and i1 %cmp1, %cmp2
  br i1 %cond, label %use, label %exit

use:
  %res = trunc i16 %div to i8
  ret i8 %res

exit:
  ret i8 0
}
```
### Optimized IR
```llvm
define i8 @test(i16 %a, i16 %b) {
entry:
  %0 = trunc i16 %a to i8
  %1 = trunc i16 %b to i8
  %div = udiv i8 %0, %1
  %cmp1 = icmp ult i16 %a, 256
  %cmp2 = icmp ult i16 %b, 256
  %cond = and i1 %cmp1, %cmp2
  br i1 %cond, label %use, label %exit

use:
  ret i8 %div

exit:
  ret i8 0
}
```


---

# Issue 97053

## Unsafe Scalarization of Non-Speculatable Vector Binary Operations

The bug is triggered when the compiler attempts to scalarize a vector binary operation followed by an `extractelement` instruction using a potentially out-of-bounds index. Specifically, the optimization transforms a sequence like `extractelement (binop vector_x, vector_y), index` into `binop (extractelement vector_x, index), (extractelement vector_y, index)`.

This transformation is incorrect when the binary operation is not safe to speculate (e.g., integer division or remainder, which can trigger Undefined Behavior) and the extraction index is not guaranteed to be within the vector's bounds. In the original code, if the index is out-of-bounds, the `extractelement` instruction yields a `poison` value, but the preceding vector operation executes safely (assuming valid vector operands). In the transformed code, the extraction occurs first. If the index is out-of-bounds, it produces a `poison` scalar. When this `poison` value is subsequently used as an operand (specifically the divisor) in a non-speculatable operation, it triggers immediate Undefined Behavior. Thus, the optimization incorrectly promotes a safe `poison` result to Undefined Behavior.

## Example

### Original IR
```llvm
define i32 @test_unsafe_scalarization(<2 x i32> %x, <2 x i32> %y, i64 %idx) {
  %binop = sdiv <2 x i32> %x, %y
  %res = extractelement <2 x i32> %binop, i64 %idx
  ret i32 %res
}
```
### Optimized IR
```llvm
define i32 @test_unsafe_scalarization(<2 x i32> %x, <2 x i32> %y, i64 %idx) {
  %1 = extractelement <2 x i32> %x, i64 %idx
  %2 = extractelement <2 x i32> %y, i64 %idx
  %res = sdiv i32 %1, %2
  ret i32 %res
}
```


---

# Issue 97330

## **Summary Title**
Incorrect Context Propagation in Multi-Use Demanded Bits Simplification

## **Description**
The bug is triggered when the optimizer attempts to simplify an instruction (the "root") that has multiple users, based on an analysis of demanded bits initiated by one specific user. When a value has multiple uses, the optimizer typically defaults to demanding all bits to ensure the value remains correct for all consumers. However, the issue arises because the analysis of the root instruction is performed using the **context of the specific user** that triggered the optimization, rather than the context of the root instruction's definition.

This use-site context allows the analysis (e.g., `computeKnownBits`) to incorporate control-flow sensitive information—such as `llvm.assume` directives, branch conditions, or dominating constraints—that is valid only at that specific user's location. If the root instruction is defined in a block that is not dominated by these constraints (e.g., a predecessor block), the optimizer may incorrectly deduce properties that do not hold globally. Consequently, the root instruction is simplified based on these local facts (e.g., replaced by a constant), causing a miscompilation for other users located on execution paths where those facts are not true.

## Example

### Original IR
```llvm
define i32 @test_incorrect_context_propagation(i32 %x) {
entry:
  ; Root instruction with multiple uses
  %root = add i32 %x, 10

  ; Condition that implies %x == 20, and thus %root == 30
  %cond = icmp eq i32 %x, 20
  br i1 %cond, label %taken, label %untaken

taken:
  ; User 1: Located in a context where %x is known to be 20.
  ; The optimizer analyzes %root using this context.
  %use_in_context = add i32 %root, 0
  ret i32 %use_in_context

untaken:
  ; User 2: Located in a context where %x is NOT necessarily 20.
  ; If %root is simplified to 30 globally based on the 'taken' context, this returns incorrect results.
  ret i32 %root
}
```
### Optimized IR
```llvm
define i32 @test_incorrect_context_propagation(i32 %x) {
entry:
  ; The root instruction has been incorrectly replaced by a constant derived from the 'taken' context.
  %cond = icmp eq i32 %x, 20
  br i1 %cond, label %taken, label %untaken

taken:
  ; Correct for this path
  ret i32 30

untaken:
  ; Incorrect for this path (e.g., if %x was 0, should return 10, but returns 30)
  ret i32 30
}
```


---

# Issue 97475

## Incorrect Simplification of Vector Selects with Lane-Crossing Operands

**Description**
The bug is triggered when the optimizer attempts to simplify the operands of a vector `select` instruction based on "known bits" or value constraints implied by the `select` condition. For example, if the condition is a vector comparison `icmp eq %x, 0`, the optimizer infers that `%x` must be zero in the lanes where the condition is true, and attempts to simplify the "true" value of the `select` accordingly.

The flaw occurs because the optimizer fails to account for lane-crossing operations (such as `shufflevector`) within the computation of the selected values. In a vector context, the condition in lane *i* only implies information about the input `%x` in lane *i*. However, if the value being selected in lane *i* is derived from a different lane *j* of `%x` (due to a shuffle), the constraint derived from lane *i* does not apply. The optimizer incorrectly propagates the constraint from the condition lane to the data source lane, leading to an invalid simplification (e.g., folding the result to zero) when the source lane actually contains a different value.

## Example

### Original IR
```llvm
define <2 x i32> @test_vector_select_lane_crossing(<2 x i32> %x) {
  %cond = icmp eq <2 x i32> %x, zeroinitializer
  %shuf = shufflevector <2 x i32> %x, <2 x i32> poison, <2 x i32> <i32 1, i32 0>
  %res = select <2 x i1> %cond, <2 x i32> %shuf, <2 x i32> %x
  ret <2 x i32> %res
}
```
### Optimized IR
```llvm
define <2 x i32> @test_vector_select_lane_crossing(<2 x i32> %x) {
  %cond = icmp eq <2 x i32> %x, zeroinitializer
  %res = select <2 x i1> %cond, <2 x i32> zeroinitializer, <2 x i32> %x
  ret <2 x i32> %res
}
```


---

# Issue 98139

## Incorrect Known Bits Refinement for Select Instructions

**Description**:
The bug is triggered during the analysis of `select` instructions in the `InstCombine` pass, specifically when the compiler attempts to compute the "known bits" (bits guaranteed to be zero or one) for the instruction's result. The optimization strategy involves refining the known bits for the "true" and "false" operands independently, using the condition to infer additional constraints (for example, analyzing the "false" operand under the assumption that the condition is false).

The issue arises because the analysis logic for the "false" operand incorrectly updates the data structure designated for the "true" operand's known bits. Instead of storing the "false" arm's analysis in its own container, the compiler overwrites or corrupts the "true" arm's analysis with information derived from the "false" arm. Consequently, the specific properties of the "true" operand are discarded. When the compiler subsequently intersects the known bits of both arms to determine the properties valid for the entire `select` instruction, the result is incorrectly biased towards the "false" operand. This leads the compiler to erroneously assume that the `select` instruction always satisfies the bitwise constraints of the "false" operand, resulting in miscompilation when the "true" path is taken and produces a value incompatible with those constraints.

## Example

### Original IR
```llvm
define i32 @test_bug(i1 %cond, i32 %x) {
  %true_op = or i32 %x, 5
  %false_op = and i32 %x, 3
  %sel = select i1 %cond, i32 %true_op, i32 %false_op
  %res = and i32 %sel, 4
  ret i32 %res
}
```
### Optimized IR
```llvm
define i32 @test_bug(i1 %cond, i32 %x) {
  ret i32 0
}
```
