# Issue 104422

## Incorrect Bit-Width Demotion for Intermediate Reduction Nodes

**Description:**
The bug is triggered in the SLP vectorizer when optimizing a reduction pattern (such as a loop accumulation) by demoting the bit width of the operations (e.g., reducing 64-bit arithmetic to 32-bit). To perform this optimization safely, the compiler verifies that all users of the vectorized instructions can accept the reduced bit width.

The issue arises because the validation logic is overly permissive for "external" users (users not included in the vectorization tree). The compiler uses a list of users to ignore during this check, which is intended to handle the final result of the reduction (e.g., the value feeding a loop PHI node). However, the bug incorrectly extends this exemption to intermediate nodes within the vectorization tree, rather than restricting it to the root node. Consequently, the compiler erroneously determines that it is safe to truncate intermediate operations, even if they involve values—such as large integer constants—that require the full bit width. This results in the loss of significant bits and incorrect program execution.

## Example

### Original IR
```llvm
define i64 @slp_reduction_bug(ptr %ptr) {
entry:
  %l0 = load i32, ptr %ptr, align 4
  %conv0 = zext i32 %l0 to i64
  %gep1 = getelementptr inbounds i32, ptr %ptr, i64 1
  %l1 = load i32, ptr %gep1, align 4
  %conv1 = zext i32 %l1 to i64
  %gep2 = getelementptr inbounds i32, ptr %ptr, i64 2
  %l2 = load i32, ptr %gep2, align 4
  %conv2 = zext i32 %l2 to i64
  %gep3 = getelementptr inbounds i32, ptr %ptr, i64 3
  %l3 = load i32, ptr %gep3, align 4
  %conv3 = zext i32 %l3 to i64
  ; Intermediate reduction node
  %add1 = add i64 %conv0, %conv1
  %add2 = add i64 %conv2, %conv3
  ; Root of reduction
  %red = add i64 %add1, %add2
  ; External user of intermediate node requiring full 64-bit width
  ; 4294967296 is 1 << 32. If add1 is demoted to 32-bit, this bit is lost.
  %check = and i64 %add1, 4294967296
  %res = add i64 %red, %check
  ret i64 %res
}
```
### Optimized IR
```llvm
define i64 @slp_reduction_bug(ptr %ptr) {
entry:
  ; The vectorizer loads 4 i32 values
  %0 = load <4 x i32>, ptr %ptr, align 4
  ; It performs the first stage of reduction using 32-bit arithmetic (demotion)
  %1 = shufflevector <4 x i32> %0, <4 x i32> poison, <2 x i32> <i32 0, i32 2>
  %2 = shufflevector <4 x i32> %0, <4 x i32> poison, <2 x i32> <i32 1, i32 3>
  %3 = add <2 x i32> %1, %2
  ; It extracts the intermediate value (add1) which is now truncated to 32 bits
  %4 = extractelement <2 x i32> %3, i32 0
  %5 = zext i32 %4 to i64
  ; It continues the reduction for the root
  %6 = extractelement <2 x i32> %3, i32 1
  %7 = add i32 %4, %6
  %red = zext i32 %7 to i64
  ; The bug: %5 is a zero-extended 32-bit value, so the 33rd bit is always 0.
  ; The original logic required the carry bit from the 64-bit add.
  %check = and i64 %5, 4294967296
  %res = add i64 %red, %check
  ret i64 %res
}
```


---

# Issue 105988

## Summary Title
Incorrect Bit Width Reduction for Integer Comparison Users in SLP Vectorizer

## Description
The bug is triggered when the SLP vectorizer attempts to optimize vector operations by reducing the bit width of elements (demanded bits analysis), specifically when those elements are used as operands in integer comparison instructions (`icmp`). 

The optimization logic determines the minimum required bit width for a vector node by examining the properties of its user instructions. A flaw exists where the analysis relies on the size of the user instruction's *return type* to decide if the operand's bit width can be reduced. The logic assumes that if a user instruction produces a result significantly smaller than the operand, the operation acts like a truncation, allowing the operand to be narrowed.

However, an integer comparison instruction always produces a 1-bit result (`i1`), regardless of the size of the integers being compared. The analyzer incorrectly interprets this small result size as a signal that the operands can be safely truncated to a smaller width. Since comparisons actually require the full width of their operands to produce the correct result, this incorrect inference leads the compiler to generate code where the inputs to the comparison are truncated, resulting in incorrect comparison outcomes at runtime.

## Example

### Original IR
```llvm
define void @test_slp_bug(ptr %a, ptr %b, ptr %res) {
entry:
  %a0 = load i32, ptr %a, align 4
  %b0 = load i32, ptr %b, align 4
  %v0 = or i32 %a0, %b0
  %c0 = icmp eq i32 %v0, 0
  %z0 = zext i1 %c0 to i8
  store i8 %z0, ptr %res, align 1

  %a1_ptr = getelementptr inbounds i32, ptr %a, i64 1
  %b1_ptr = getelementptr inbounds i32, ptr %b, i64 1
  %res1_ptr = getelementptr inbounds i8, ptr %res, i64 1
  %a1 = load i32, ptr %a1_ptr, align 4
  %b1 = load i32, ptr %b1_ptr, align 4
  %v1 = or i32 %a1, %b1
  %c1 = icmp eq i32 %v1, 0
  %z1 = zext i1 %c1 to i8
  store i8 %z1, ptr %res1_ptr, align 1

  %a2_ptr = getelementptr inbounds i32, ptr %a, i64 2
  %b2_ptr = getelementptr inbounds i32, ptr %b, i64 2
  %res2_ptr = getelementptr inbounds i8, ptr %res, i64 2
  %a2 = load i32, ptr %a2_ptr, align 4
  %b2 = load i32, ptr %b2_ptr, align 4
  %v2 = or i32 %a2, %b2
  %c2 = icmp eq i32 %v2, 0
  %z2 = zext i1 %c2 to i8
  store i8 %z2, ptr %res2_ptr, align 1

  %a3_ptr = getelementptr inbounds i32, ptr %a, i64 3
  %b3_ptr = getelementptr inbounds i32, ptr %b, i64 3
  %res3_ptr = getelementptr inbounds i8, ptr %res, i64 3
  %a3 = load i32, ptr %a3_ptr, align 4
  %b3 = load i32, ptr %b3_ptr, align 4
  %v3 = or i32 %a3, %b3
  %c3 = icmp eq i32 %v3, 0
  %z3 = zext i1 %c3 to i8
  store i8 %z3, ptr %res3_ptr, align 1

  ret void
}
```
### Optimized IR
```llvm
define void @test_slp_bug(ptr %a, ptr %b, ptr %res) {
entry:
  %0 = load <4 x i32>, ptr %a, align 4
  %1 = load <4 x i32>, ptr %b, align 4
  ; The bug: The vectorizer incorrectly truncates the operands to i8 (or i1)
  ; because the user instruction (icmp) returns i1, ignoring that icmp requires full width.
  %2 = trunc <4 x i32> %0 to <4 x i8>
  %3 = trunc <4 x i32> %1 to <4 x i8>
  %4 = or <4 x i8> %2, %3
  ; The comparison is now performed on truncated values, potentially yielding incorrect results.
  %5 = icmp eq <4 x i8> %4, zeroinitializer
  %6 = zext <4 x i1> %5 to <4 x i8>
  store <4 x i8> %6, ptr %res, align 1
  ret void
}
```


---

# Issue 108620

## Summary Title
Stale Reference to Transformed Values in Horizontal Reduction

## Description
The bug is triggered during the vectorization of horizontal reductions (e.g., summing a list of values) in the SLP Vectorizer. The compiler processes a list of candidate scalar values iteratively to build the vectorization tree and handle "external uses" (values computed in the reduction that are needed elsewhere).

The issue arises because the logic fails to check if a candidate scalar has already been vectorized or transformed in a previous iteration of the reduction process. Instead of using the new, transformed value (which represents the current state of the computation), the compiler continues to inspect the original, stale scalar value.

This stale reference causes the compiler to incorrectly assess the external uses of the instruction. It may fail to register that the value is used externally (because the uses have moved to the transformed value) or fail to generate the necessary fix-up code (like `extractelement` instructions) to satisfy those uses. Consequently, when the vectorizer attempts to clean up and delete the original scalar instructions—believing them to be fully redundant and unused—it crashes because those instructions still have active users that were not properly migrated to the new vector values.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define i32 @horizontal_reduction_with_external_use(i32* %ptr, i32* %external_use_ptr) #0 {
entry:
  %gep0 = getelementptr inbounds i32, i32* %ptr, i64 0
  %val0 = load i32, i32* %gep0, align 4
  %gep1 = getelementptr inbounds i32, i32* %ptr, i64 1
  %val1 = load i32, i32* %gep1, align 4
  %gep2 = getelementptr inbounds i32, i32* %ptr, i64 2
  %val2 = load i32, i32* %gep2, align 4
  %gep3 = getelementptr inbounds i32, i32* %ptr, i64 3
  %val3 = load i32, i32* %gep3, align 4

  ; Horizontal reduction tree
  %add0 = add i32 %val0, %val1
  %add1 = add i32 %val2, %val3
  %root = add i32 %add0, %add1

  ; External use of an intermediate reduction value (%add0)
  ; This triggers the bug if the vectorizer fails to track this use correctly
  ; during the iterative reduction process.
  store i32 %add0, i32* %external_use_ptr, align 4

  ret i32 %root
}

attributes #0 = { "target-cpu"="skylake" }
```
### Optimized IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define i32 @horizontal_reduction_with_external_use(i32* %ptr, i32* %external_use_ptr) #0 {
entry:
  %0 = bitcast i32* %ptr to <4 x i32>*
  %1 = load <4 x i32>, <4 x i32>* %0, align 4
  ; The vectorizer performs a pairwise addition (horizontal reduction step)
  %2 = shufflevector <4 x i32> %1, <4 x i32> poison, <4 x i32> <i32 0, i32 2, i32 poison, i32 poison>
  %3 = shufflevector <4 x i32> %1, <4 x i32> poison, <4 x i32> <i32 1, i32 3, i32 poison, i32 poison>
  %4 = add <4 x i32> %2, %3
  ; Correctly handling the external use by extracting the value from the vector
  %5 = extractelement <4 x i32> %4, i32 0
  store i32 %5, i32* %external_use_ptr, align 4
  ; Completing the reduction
  %6 = call i32 @llvm.vector.reduce.add.v4i32(<4 x i32> %4)
  ret i32 %6
}

declare i32 @llvm.vector.reduce.add.v4i32(<4 x i32>)

attributes #0 = { "target-cpu"="skylake" }
```


---

# Issue 112460

## Summary Title
Incorrect Sign Extension when Vectorizing Freeze Instructions with Bit Width Reduction

## Description
The bug is triggered when the SLP vectorizer optimizes a sequence of instructions involving a `freeze` instruction applied to a value that was zero-extended from a smaller bit width (e.g., extending an `i1` boolean to an `i8` integer). 

The vectorizer's minimum bit width analysis correctly identifies that the operations can be performed on the smaller, underlying type to improve performance. However, the optimization logic fails to correctly preserve the "unsigned" property of the original zero-extension when processing the `freeze` instruction. As a result, when the vectorizer generates code to promote the frozen value back to the target bit width, it incorrectly emits a sign-extension (`sext`) instead of a zero-extension (`zext`). This transformation corrupts the value (e.g., turning a positive `1` into a negative `-1`), which leads to miscompilation when the value is subsequently used in operations sensitive to sign, such as unsigned comparisons.

## Example

### Original IR
```llvm
define void @test(ptr %p, i1 %a, i1 %b) {
entry:
  %z1 = zext i1 %a to i8
  %f1 = freeze i8 %z1
  store i8 %f1, ptr %p, align 1
  %p2 = getelementptr inbounds i8, ptr %p, i64 1
  %z2 = zext i1 %b to i8
  %f2 = freeze i8 %z2
  store i8 %f2, ptr %p2, align 1
  ret void
}
```
### Optimized IR
```llvm
define void @test(ptr %p, i1 %a, i1 %b) {
entry:
  %0 = insertelement <2 x i1> poison, i1 %a, i32 0
  %1 = insertelement <2 x i1> %0, i1 %b, i32 1
  %2 = freeze <2 x i1> %1
  %3 = sext <2 x i1> %2 to <2 x i8>
  store <2 x i8> %3, ptr %p, align 1
  ret void
}
```


---

# Issue 112577

## Incorrect Bit Width Demotion of `llvm.abs` Intrinsic

## Description
The bug is triggered when the SLP vectorizer applies a "minimum bit width" optimization to code containing the `llvm.abs` (absolute value) intrinsic. This optimization attempts to replace operations performed on wide integers (e.g., 64-bit) with narrower vector operations (e.g., 32-bit) when the inputs and outputs originate from or are truncated to the narrower width.

The flaw lies in the vectorizer's failure to validate the sign interpretation of the `abs` operand during this demotion. In the original wider bit width, an intermediate value might be positive (for instance, due to zero-extension or unsigned multiplication). However, when this value is implicitly truncated to the narrower bit width for the vectorized operation, its most significant bit may become set. This causes the value to be interpreted as negative in the narrower signed context. Consequently, the demoted `abs` instruction negates the value, whereas the original wide `abs` instruction would have treated it as positive and left it unchanged. This discrepancy leads to incorrect results in the vectorized code.

## Example

### Original IR
```llvm
define void @test(ptr %src, ptr %dst) {
entry:
  %l0 = load i8, ptr %src, align 1
  %z0 = zext i8 %l0 to i32
  %abs0 = call i32 @llvm.abs.i32(i32 %z0, i1 false)
  %t0 = trunc i32 %abs0 to i8
  store i8 %t0, ptr %dst, align 1

  %src1 = getelementptr inbounds i8, ptr %src, i64 1
  %l1 = load i8, ptr %src1, align 1
  %z1 = zext i8 %l1 to i32
  %abs1 = call i32 @llvm.abs.i32(i32 %z1, i1 false)
  %t1 = trunc i32 %abs1 to i8
  %dst1 = getelementptr inbounds i8, ptr %dst, i64 1
  store i8 %t1, ptr %dst1, align 1
  ret void
}

declare i32 @llvm.abs.i32(i32, i1)
```
### Optimized IR
```llvm
define void @test(ptr %src, ptr %dst) {
entry:
  %0 = load <2 x i8>, ptr %src, align 1
  %1 = call <2 x i8> @llvm.abs.v2i8(<2 x i8> %0, i1 false)
  store <2 x i8> %1, ptr %dst, align 1
  ret void
}

declare <2 x i8> @llvm.abs.v2i8(<2 x i8>, i1)
```


---

# Issue 113520

## Incorrect Extension Logic for Externally Used Scalars in SLP Vectorization

**Description**:
The bug is triggered when the SLP vectorizer processes a group of instructions that includes mixed sign-extension and zero-extension operations (or operations with conflicting signedness requirements) and creates a vector node where some of the scalar values are used externally (outside the vectorized tree).

When the compiler generates code to extract these scalars for their external users, it must cast the values back to their original bit width. The incorrect transformation occurs because the compiler relies on precomputed, aggregated signedness information for the entire vector node to decide whether to perform a sign-extension (`sext`) or a zero-extension (`zext`). In scenarios where the vector node represents a mix of operations (e.g., alternate `sext` and `zext`), this aggregated property may incorrectly mandate a sign-extension for a lane that originally required a zero-extension. This results in the generation of `sext` instructions instead of `zext`, causing miscompilation by interpreting large unsigned values as negative signed numbers.

## Example

### Original IR
```llvm
define i32 @test(ptr %a, ptr %b) {
entry:
  %a0_ptr = getelementptr inbounds i16, ptr %a, i64 0
  %a0 = load i16, ptr %a0_ptr, align 2
  %a1_ptr = getelementptr inbounds i16, ptr %a, i64 1
  %a1 = load i16, ptr %a1_ptr, align 2
  %z = zext i16 %a0 to i32
  %s = sext i16 %a1 to i32
  %op0 = add i32 %z, 0
  %op1 = add i32 %s, 0
  %t0 = trunc i32 %op0 to i16
  %t1 = trunc i32 %op1 to i16
  store i16 %t0, ptr %b, align 2
  %b1_ptr = getelementptr inbounds i16, ptr %b, i64 1
  store i16 %t1, ptr %b1_ptr, align 2
  ret i32 %op0
}
```
### Optimized IR
```llvm
define i32 @test(ptr %a, ptr %b) {
entry:
  %0 = load <2 x i16>, ptr %a, align 2
  %1 = add <2 x i16> %0, zeroinitializer
  store <2 x i16> %1, ptr %b, align 2
  %2 = extractelement <2 x i16> %1, i32 0
  %3 = sext i16 %2 to i32
  ret i32 %3
}
```


---

# Issue 114738

## Incorrect Poison Handling in Vector Reductions of Boolean Logic

**Description:**
The bug is triggered when the vectorizer transforms a sequence of scalar boolean logic operations (such as logical ORs or ANDs, often implemented using `select` instructions or bitwise operators on boolean values) into a vector reduction. In the original scalar code, the structure of the operations allows for poison suppression; for example, a logical OR operation where one operand is `true` will evaluate to `true` even if the other operand is `poison`.

However, the vectorizer replaces this sequence with a vector reduction intrinsic (e.g., a reduction OR). Standard vector reduction intrinsics do not possess this poison-suppressing property; they propagate poison if any single element within the input vector is poison. As a result, if the inputs contain a poison value that was originally masked by the scalar logic (e.g., by a `true` value in an OR chain), the vectorized reduction yields a `poison` result instead of the correct defined value. This leads to a miscompilation where the target IR is more poisonous than the source IR.

## Example

### Original IR
```llvm
define i1 @test_poison_suppression(<4 x i1> %vec) {
  %v0 = extractelement <4 x i1> %vec, i32 0
  %v1 = extractelement <4 x i1> %vec, i32 1
  %v2 = extractelement <4 x i1> %vec, i32 2
  %v3 = extractelement <4 x i1> %vec, i32 3
  ; Logical OR implemented as select allows poison suppression (e.g., true || poison -> true)
  %or1 = select i1 %v0, i1 true, i1 %v1
  %or2 = select i1 %or1, i1 true, i1 %v2
  %or3 = select i1 %or2, i1 true, i1 %v3
  ret i1 %or3
}
```
### Optimized IR
```llvm
define i1 @test_poison_suppression(<4 x i1> %vec) {
  ; The vectorizer replaces the select chain with a reduction intrinsic.
  ; This intrinsic propagates poison if any element is poison, unlike the scalar code.
  %res = call i1 @llvm.vector.reduce.or.v4i1(<4 x i1> %vec)
  ret i1 %res
}

declare i1 @llvm.vector.reduce.or.v4i1(<4 x i1>)
```


---

# Issue 114905

## Reassociation of Logical Reductions Exposing Poison Values

**Description**
The bug is triggered when the SLP vectorizer optimizes a reduction sequence involving logical operations (such as chains of boolean AND/OR implemented via `select` instructions). In the original Intermediate Representation (IR), the specific nesting or order of these operations may ensure that a `poison` operand is effectively masked by a controlling value (e.g., `false` in a logical AND chain causes the result to be `false` regardless of a subsequent `poison` operand).

When the vectorizer processes this sequence, it may reassociate or reorder the operands to construct a balanced reduction tree. This transformation can change the pairing of operands such that the `poison` value is combined with a value that does not suppress it (e.g., pairing `poison` with `true` in a logical AND). Consequently, the `poison` value propagates to the final result, causing the transformed code to yield `poison` (undefined behavior) where the original code produced a well-defined value. The issue stems from the optimizer's failure to freeze potentially poisonous values before altering the operation order, which breaks the implicit poison-masking semantics of the original chain.

## Example

### Original IR
```llvm
define i1 @test_poison_masking(ptr %ptr) {
entry:
  %p0 = getelementptr inbounds i1, ptr %ptr, i64 0
  %v0 = load i1, ptr %p0, align 1
  %p1 = getelementptr inbounds i1, ptr %ptr, i64 1
  %v1 = load i1, ptr %p1, align 1
  %p2 = getelementptr inbounds i1, ptr %ptr, i64 2
  %v2 = load i1, ptr %p2, align 1
  %p3 = getelementptr inbounds i1, ptr %ptr, i64 3
  %v3 = load i1, ptr %p3, align 1
  ; Logical AND chain implemented via selects to ensure poison masking.
  ; If %v0 is false, the result is false regardless of %v3 being poison.
  %op1 = select i1 %v0, i1 %v1, i1 false
  %op2 = select i1 %op1, i1 %v2, i1 false
  %op3 = select i1 %op2, i1 %v3, i1 false
  ret i1 %op3
}
```
### Optimized IR
```llvm
define i1 @test_poison_masking(ptr %ptr) {
entry:
  ; The SLP vectorizer transforms the select chain into a vector reduction.
  ; This introduces a bug because the 'and' reduction propagates poison.
  ; If %v0 is false and %v3 is poison, the original code returns false,
  ; but this optimized code returns poison.
  %0 = load <4 x i1>, ptr %ptr, align 1
  %1 = call i1 @llvm.vector.reduce.and.v4i1(<4 x i1> %0)
  ret i1 %1
}

declare i1 @llvm.vector.reduce.and.v4i1(<4 x i1>)
```


---

# Issue 116691

## Out-of-Bounds Access in SLP Vectorizer for Gathered Loads

**Description**: 
The bug is triggered during the SLP vectorization of gathered load instructions. When the vectorizer identifies candidates for vectorization, it attempts to group consecutive load instructions into vectors of a specific width. The issue arises because the logic assumes that a full vector's worth of elements is always available starting from a selected index. If the number of remaining load instructions in the candidate list is less than the target vector width (for instance, when the total number of loads is not a multiple of the vector size), the compiler attempts to extract a slice of instructions that extends beyond the bounds of the container. This out-of-bounds access leads to a compiler crash.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @test_slp_gather_crash(ptr %src, ptr %dst) {
entry:
  ; Load 5 elements with stride 2 (non-consecutive, candidates for gathered loads)
  %s0 = getelementptr i32, ptr %src, i64 0
  %l0 = load i32, ptr %s0
  %s1 = getelementptr i32, ptr %src, i64 2
  %l1 = load i32, ptr %s1
  %s2 = getelementptr i32, ptr %src, i64 4
  %l2 = load i32, ptr %s2
  %s3 = getelementptr i32, ptr %src, i64 6
  %l3 = load i32, ptr %s3
  %s4 = getelementptr i32, ptr %src, i64 8
  %l4 = load i32, ptr %s4

  ; Store 5 elements to consecutive memory (seeds SLP vectorizer)
  ; The vectorizer will attempt to vectorize these stores and look up the definition tree.
  ; It will find the 5 loads. With VF=4, it processes the first 4.
  ; The bug triggers when it attempts to process the remaining 1 load using a slice of size 4.
  %d0 = getelementptr i32, ptr %dst, i64 0
  store i32 %l0, ptr %d0
  %d1 = getelementptr i32, ptr %dst, i64 1
  store i32 %l1, ptr %d1
  %d2 = getelementptr i32, ptr %dst, i64 2
  store i32 %l2, ptr %d2
  %d3 = getelementptr i32, ptr %dst, i64 3
  store i32 %l3, ptr %d3
  %d4 = getelementptr i32, ptr %dst, i64 4
  store i32 %l4, ptr %d4

  ret void
}
```
### Optimized IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @test_slp_gather_crash(ptr %src, ptr %dst) {
entry:
  ; The first 4 loads are gathered into a vector
  %s0 = getelementptr i32, ptr %src, i64 0
  %l0 = load i32, ptr %s0
  %s1 = getelementptr i32, ptr %src, i64 2
  %l1 = load i32, ptr %s1
  %s2 = getelementptr i32, ptr %src, i64 4
  %l2 = load i32, ptr %s2
  %s3 = getelementptr i32, ptr %src, i64 6
  %l3 = load i32, ptr %s3
  
  %vec0 = insertelement <4 x i32> poison, i32 %l0, i32 0
  %vec1 = insertelement <4 x i32> %vec0, i32 %l1, i32 1
  %vec2 = insertelement <4 x i32> %vec1, i32 %l2, i32 2
  %vec3 = insertelement <4 x i32> %vec2, i32 %l3, i32 3

  ; The first 4 stores are vectorized
  %d0 = getelementptr i32, ptr %dst, i64 0
  store <4 x i32> %vec3, ptr %d0, align 4

  ; The 5th element remains scalar (correct behavior after fix)
  %s4 = getelementptr i32, ptr %src, i64 8
  %l4 = load i32, ptr %s4
  %d4 = getelementptr i32, ptr %dst, i64 4
  store i32 %l4, ptr %d4, align 4

  ret void
}
```


---

# Issue 119393

## Incorrect Shuffle Mask Indexing for Multi-Part Vector Nodes with Poison Values

**Description**
The bug is triggered when the SLP vectorizer processes a vectorization tree node that spans multiple vector registers (parts) and contains undefined (`poison`) scalar values. This scenario typically arises during the analysis of gathered nodes or reductions where the resulting vector is large enough to be split into multiple hardware registers.

When the compiler constructs the shuffle mask to estimate the cost of these operations, it iterates through the scalar elements of each vector part to identify `poison` values and mark the corresponding mask indices as unused. However, the incorrect transformation logic failed to account for the offset of the current vector part. Instead of applying the mask updates to the indices corresponding to the specific register being processed (e.g., the second or third part), it erroneously updated the indices corresponding to the first vector part.

This resulted in a corrupted shuffle mask where `poison` elements in higher-order vector parts were not correctly marked, and valid elements in the first part might have been incorrectly marked as poison. This inconsistency leads to an assertion failure in the shuffle cost estimator, which validates that the mask correctly represents the expected subvector usage.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @test(ptr %p) {
entry:
  store i32 0, ptr %p, align 4
  %p1 = getelementptr inbounds i32, ptr %p, i64 1
  store i32 1, ptr %p1, align 4
  %p2 = getelementptr inbounds i32, ptr %p, i64 2
  store i32 2, ptr %p2, align 4
  %p3 = getelementptr inbounds i32, ptr %p, i64 3
  store i32 3, ptr %p3, align 4
  %p4 = getelementptr inbounds i32, ptr %p, i64 4
  store i32 4, ptr %p4, align 4
  %p5 = getelementptr inbounds i32, ptr %p, i64 5
  store i32 poison, ptr %p5, align 4
  %p6 = getelementptr inbounds i32, ptr %p, i64 6
  store i32 6, ptr %p6, align 4
  %p7 = getelementptr inbounds i32, ptr %p, i64 7
  store i32 7, ptr %p7, align 4
  ret void
}
```
### Optimized IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @test(ptr %p) {
entry:
  ; The bug causes the element at index 1 (corresponding to the offset of poison in the second part)
  ; to be incorrectly marked as poison/undef in the first part.
  store <8 x i32> <i32 0, i32 poison, i32 2, i32 3, i32 4, i32 poison, i32 6, i32 7>, ptr %p, align 4
  ret void
}
```


---

# Issue 120076

## Incorrect Bitwidth Demotion of Sign-Sensitive Operations in SLP Vectorizer

**Description**:
The bug is triggered when the SLP vectorizer attempts to reduce the bitwidth of a sequence of integer operations involving type promotions and comparisons. Specifically, the issue arises in patterns where a value is zero-extended from a narrow type to a wider type and subsequently used in a signed comparison (e.g., `zext` followed by `icmp slt`). In such cases, the wider bitwidth is essential to treat the value as a large positive number, whereas the narrow type might interpret the same bit pattern as a negative number.

The miscompilation occurs because the vectorizer's analysis of minimum bitwidths does not consistently persist "do not demote" decisions across the entire vectorization graph. If the vectorizer analyzes a set of nodes and determines they must keep their original bitwidth to preserve correctness, this constraint may be ignored if the nodes are re-analyzed as part of a different reduction chain or subgraph. Consequently, the compiler incorrectly decides to demote the operations to the narrower bitwidth, transforming a true comparison (unsigned/positive in wide type) into a false comparison (signed/negative in narrow type), resulting in incorrect program behavior.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define i1 @test_slp_demotion_bug(ptr %p) {
entry:
  %0 = load i8, ptr %p, align 1
  %arrayidx1 = getelementptr inbounds i8, ptr %p, i64 1
  %1 = load i8, ptr %arrayidx1, align 1
  %arrayidx2 = getelementptr inbounds i8, ptr %p, i64 2
  %2 = load i8, ptr %arrayidx2, align 1
  %arrayidx3 = getelementptr inbounds i8, ptr %p, i64 3
  %3 = load i8, ptr %arrayidx3, align 1
  
  ; Zero-extend i8 to i32. This makes all values positive in i32.
  %conv0 = zext i8 %0 to i32
  %conv1 = zext i8 %1 to i32
  %conv2 = zext i8 %2 to i32
  %conv3 = zext i8 %3 to i32
  
  ; Signed comparison on the wide type.
  ; If the input is 255 (0xFF), zext makes it 255.
  ; 255 < 10 is false.
  ; If demoted to i8, 0xFF is -1.
  ; -1 < 10 is true.
  %cmp0 = icmp slt i32 %conv0, 10
  %cmp1 = icmp slt i32 %conv1, 10
  %cmp2 = icmp slt i32 %conv2, 10
  %cmp3 = icmp slt i32 %conv3, 10
  
  ; Reduction tree to trigger SLP
  %or1 = or i1 %cmp0, %cmp1
  %or2 = or i1 %cmp2, %cmp3
  %res = or i1 %or1, %or2
  
  ret i1 %res
}
```
### Optimized IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define i1 @test_slp_demotion_bug(ptr %p) {
entry:
  %0 = load <4 x i8>, ptr %p, align 1
  ; BUG: The zext was removed, and the comparison was demoted to i8.
  ; This changes the semantics for inputs in range [128, 255] which are negative in i8 but positive in i32.
  %1 = icmp slt <4 x i8> %0, <i8 10, i8 10, i8 10, i8 10>
  %2 = call i1 @llvm.vector.reduce.or.v4i1(<4 x i1> %1)
  ret i1 %2
}

declare i1 @llvm.vector.reduce.or.v4i1(<4 x i1>)
```


---

# Issue 120823

## Incorrect Propagation of `samesign` Flag During Vectorization with Bitwidth Reduction

**Description**
The bug is triggered when the SLP vectorizer optimizes integer comparison instructions (`icmp`) that are annotated with the `samesign` flag. During the vectorization process, the compiler performs an analysis to determine if the operands can be represented using a smaller bitwidth (e.g., truncating 32-bit integers to 1-bit or 8-bit vectors) without losing significant data.

When this bitwidth reduction occurs, the vectorizer correctly generates the truncated vector operations but incorrectly propagates the `samesign` flag from the original instruction to the new, narrower comparison. The `samesign` flag asserts that both operands share the same sign bit. However, truncating a value can change its sign interpretation; for instance, a value that is positive in a wider type (e.g., `1` in `i32`) may be interpreted as negative in a narrower type (e.g., `1` in `i1`, where the single bit is the sign bit). If the truncation results in operands having different sign bits in the narrower type, the preserved `samesign` flag causes the instruction to produce a `poison` value (undefined behavior), leading to a miscompilation.

## Example

### Original IR
```llvm
define <2 x i1> @test_samesign_trunc_bug(i32 %a, i32 %b, i32 %c, i32 %d) {
entry:
  %mask.a = and i32 %a, 1
  %mask.b = and i32 %b, 1
  %mask.c = and i32 %c, 1
  %mask.d = and i32 %d, 1
  %cmp0 = icmp samesign ult i32 %mask.a, %mask.b
  %cmp1 = icmp samesign ult i32 %mask.c, %mask.d
  %ins0 = insertelement <2 x i1> poison, i1 %cmp0, i32 0
  %ins1 = insertelement <2 x i1> %ins0, i1 %cmp1, i32 1
  ret <2 x i1> %ins1
}
```
### Optimized IR
```llvm
define <2 x i1> @test_samesign_trunc_bug(i32 %a, i32 %b, i32 %c, i32 %d) {
entry:
  %0 = insertelement <2 x i32> poison, i32 %a, i32 0
  %1 = insertelement <2 x i32> %0, i32 %c, i32 1
  %2 = trunc <2 x i32> %1 to <2 x i1>
  %3 = insertelement <2 x i32> poison, i32 %b, i32 0
  %4 = insertelement <2 x i32> %3, i32 %d, i32 1
  %5 = trunc <2 x i32> %4 to <2 x i1>
  %6 = icmp samesign ult <2 x i1> %2, %5
  ret <2 x i1> %6
}
```


---

# Issue 122583

## Summary Title
Incorrect Operand Resolution for Poison Lanes in Extract Bundles Leads to Poison Propagation

## Description
The bug is triggered when the SLP vectorizer processes a bundle of instructions that contains both extract instructions (such as `extractelement` or `extractvalue`) and `poison` values, where the `poison` values typically represent unused lanes or padding in the vectorization factor. 

When the vectorizer analyzes the operands of this bundle to determine if it can be optimized into a single shuffle of a common source vector, it incorrectly identifies the source operand for the `poison` lanes as a `poison` value, rather than the source vector used by the valid extract instructions. This mismatch leads the vectorizer to conclude that the instructions do not share a common source, preventing the transformation into a `shufflevector` instruction. 

A `shufflevector` with undefined mask indices would produce `undef` values for the unused lanes, which are generally benign (e.g., can be resolved to 0). However, because the shuffle optimization is rejected, the vectorizer falls back to an alternative strategy, such as gathering scalar values, which explicitly inserts `poison` values into the resulting vector. When this vector is subsequently used in operations that propagate poison (such as a horizontal reduction), the `poison` value corrupts the final result, causing Undefined Behavior (UB) in cases where the optimized code should have been valid.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define i32 @test(<4 x i32> %v) {
entry:
  %e0 = extractelement <4 x i32> %v, i32 0
  %e1 = extractelement <4 x i32> %v, i32 1
  %add0 = add i32 %e0, 1
  %add1 = add i32 %e1, 2
  %vec0 = insertelement <4 x i32> undef, i32 %add0, i32 0
  %vec1 = insertelement <4 x i32> %vec0, i32 %add1, i32 1
  %res = call i32 @llvm.vector.reduce.add.v4i32(<4 x i32> %vec1)
  ret i32 %res
}

declare i32 @llvm.vector.reduce.add.v4i32(<4 x i32>)
```
### Optimized IR
```llvm
target datalayout = "e-m:e-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define i32 @test(<4 x i32> %v) {
entry:
  %e0 = extractelement <4 x i32> %v, i32 0
  %e1 = extractelement <4 x i32> %v, i32 1
  %0 = insertelement <4 x i32> poison, i32 %e0, i32 0
  %1 = insertelement <4 x i32> %0, i32 %e1, i32 1
  %2 = add <4 x i32> %1, <i32 1, i32 2, i32 poison, i32 poison>
  %res = call i32 @llvm.vector.reduce.add.v4i32(<4 x i32> %2)
  ret i32 %res
}

declare i32 @llvm.vector.reduce.add.v4i32(<4 x i32>)
```


---

# Issue 122691

Based on the provided bug report and patch, here is the summary of the bug triggering strategy.

## Crash due to PoisonValues in Division/Remainder Vectorization Analysis

**Description**
The bug is triggered when the SLP vectorizer processes a sequence of division or remainder instructions (such as `sdiv` or `urem`). In certain scenarios, such as when handling non-unique values or resizing the scalar list to match a specific vector width, the vectorizer pads the bundle of scalar values with `PoisonValue` elements.

The issue arises during a subsequent analysis phase known as "value demotion," which checks if the vectorized values can be truncated to a smaller bit width. This analysis iterates over the scalar elements of the vector node and expects each element to be a valid instruction. However, when the analysis encounters the `PoisonValue` elements (which are constants) mixed with the division/remainder instructions, it attempts to treat them as instructions (e.g., by casting them). This results in a type mismatch assertion failure, causing the compiler to crash.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @test(ptr %src, ptr %dst) {
entry:
  %src1 = getelementptr inbounds i32, ptr %src, i64 1
  %src2 = getelementptr inbounds i32, ptr %src, i64 2
  %l0 = load i32, ptr %src, align 4
  %l1 = load i32, ptr %src1, align 4
  %l2 = load i32, ptr %src2, align 4
  ; Masking to trigger value demotion analysis (checking if values fit in smaller bitwidth)
  %t0 = and i32 %l0, 65535
  %t1 = and i32 %l1, 65535
  %t2 = and i32 %l2, 65535
  ; Division instructions that will be vectorized with padding
  %d0 = sdiv i32 %t0, 10
  %d1 = sdiv i32 %t1, 10
  %d2 = sdiv i32 %t2, 10
  %dst1 = getelementptr inbounds i32, ptr %dst, i64 1
  %dst2 = getelementptr inbounds i32, ptr %dst, i64 2
  store i32 %d0, ptr %dst, align 4
  store i32 %d1, ptr %dst1, align 4
  store i32 %d2, ptr %dst2, align 4
  ret void
}
```
### Optimized IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @test(ptr %src, ptr %dst) {
entry:
  ; The vectorizer loads 4 elements (or masks) and pads the operations with poison
  %0 = load <4 x i32>, ptr %src, align 4
  %1 = and <4 x i32> %0, <i32 65535, i32 65535, i32 65535, i32 poison>
  ; The sdiv is vectorized with a poison element in the 4th lane
  %2 = sdiv <4 x i32> %1, <i32 10, i32 10, i32 10, i32 poison>
  %3 = shufflevector <4 x i32> %2, <4 x i32> poison, <3 x i32> <i32 0, i32 1, i32 2>
  store <3 x i32> %3, ptr %dst, align 4
  ret void
}
```


---

# Issue 123639

## Incorrect Shuffle Mask Offset for Reused Vector Nodes

**Description**: 
The bug is triggered when the SLP Vectorizer attempts to optimize a sequence of scalar operations into a `BuildVector` node by reusing elements from previously vectorized instructions. When generating the shuffle mask to combine these existing vector nodes, the compiler incorrectly calculates the index offsets for the subsequent vector operands. Specifically, the logic determines the offset based solely on the vector factor (size) of the first input vector. In scenarios where the `BuildVector` node combines multiple vectors or reuses nodes in a way that requires alignment to the maximum vector size among inputs, this assumption fails. This results in a shuffle instruction with incorrect indices that selects the wrong elements from the source vectors, leading to a miscompilation.

## Example

### Original IR
```llvm
define void @test(<2 x float> %a, <4 x float> %b, <4 x float>* %out) {
  %a0 = extractelement <2 x float> %a, i32 0
  %a1 = extractelement <2 x float> %a, i32 1
  %b0 = extractelement <4 x float> %b, i32 0
  %b1 = extractelement <4 x float> %b, i32 1
  %i0 = insertelement <4 x float> poison, float %a0, i32 0
  %i1 = insertelement <4 x float> %i0, float %b0, i32 1
  %i2 = insertelement <4 x float> %i1, float %a1, i32 2
  %i3 = insertelement <4 x float> %i2, float %b1, i32 3
  store <4 x float> %i3, <4 x float>* %out
  ret void
}
```
### Optimized IR
```llvm
define void @test(<2 x float> %a, <4 x float> %b, <4 x float>* %out) {
  %1 = shufflevector <2 x float> %a, <2 x float> poison, <4 x i32> <i32 0, i32 1, i32 poison, i32 poison>
  %2 = shufflevector <4 x float> %1, <4 x float> %b, <4 x i32> <i32 0, i32 2, i32 1, i32 3>
  store <4 x float> %2, <4 x float>* %out
  ret void
}
```


---

# Issue 125357

## Incorrect Reordering Reset for Reused Root Nodes in SLP Vectorization

**Description**
The bug is triggered when the SLP vectorizer constructs a vectorization graph—typically involving horizontal reductions—where the root node of the graph is also reused as an operand within the same tree structure. During the vectorization process, the compiler performs a reordering pass to optimize the arrangement of vector elements, aiming to minimize shuffle costs or align with memory access patterns.

The error occurs because the compiler unconditionally discards the calculated reordering for the root node, operating under the assumption that the specific lane order of the root is irrelevant to the rest of the tree. However, if the root node is reused as an input for another operation inside the graph, that internal operation relies on the root node maintaining the specific reordering determined during the optimization pass. Resetting the root node's order creates an inconsistency: the internal use expects the reordered state, while the node definition has been reverted to the original scalar order. This mismatch leads to an assertion failure when the compiler attempts to validate that the scalar values in the vectorization tree entry match the expected operands.

## Example

### Original IR
```llvm
define void @test(ptr %p) {
entry:
  %p0 = getelementptr inbounds i32, ptr %p, i64 0
  %l0 = load i32, ptr %p0, align 4
  %p1 = getelementptr inbounds i32, ptr %p, i64 1
  %l1 = load i32, ptr %p1, align 4
  %v0 = add i32 %l1, 10
  %v1 = add i32 %l0, %v0
  %out0 = getelementptr inbounds i32, ptr %p, i64 2
  store i32 %v0, ptr %out0, align 4
  %out1 = getelementptr inbounds i32, ptr %p, i64 3
  store i32 %v1, ptr %out1, align 4
  ret void
}
```
### Optimized IR
```llvm
define void @test(ptr %p) {
entry:
  %p0 = getelementptr inbounds i32, ptr %p, i64 0
  %0 = load <2 x i32>, ptr %p0, align 4
  %1 = insertelement <2 x i32> poison, i32 10, i32 1
  %2 = shufflevector <2 x i32> %0, <2 x i32> poison, <2 x i32> <i32 1, i32 0>
  %3 = add <2 x i32> %0, %1
  %out0 = getelementptr inbounds i32, ptr %p, i64 2
  store <2 x i32> %3, ptr %out0, align 4
  ret void
}
```


---

# Issue 129057

## Unsafe Bitwidth Demotion of Multi-Use Values in SLP Vectorizer

**Description**:
The bug occurs in the SLP vectorizer's bitwidth reduction (demotion) optimization. The compiler analyzes chains of instructions that ultimately feed into a truncation instruction (e.g., truncating a 32-bit value to 8 bits). To improve vectorization efficiency, the compiler attempts to perform the entire sequence of operations using the narrower bit width (e.g., 8-bit operations) instead of the original width.

The issue arises when an intermediate value within this chain has multiple uses:
1.  One use is part of the chain being demoted, where the high bits are eventually discarded by the final truncation.
2.  Another use is external to the demotion logic or requires the full bit width (e.g., an integer comparison against a large constant).

The compiler incorrectly assumes that because the value is part of a demotable chain, it can be safely truncated to the narrower width. It proceeds to narrow the value, stripping away significant high bits. However, the second user (such as the comparison) depends on these high bits. When the truncated value is used by this second instruction (even if zero- or sign-extended back to the original width), the necessary information is lost, leading to incorrect evaluation and miscompilation. The fix involves verifying that values with multiple uses are only demoted if they naturally fit within the narrower type, ensuring no significant bits are lost for other users.

## Example

### Original IR
```llvm
define i1 @test(ptr %A, ptr %B, ptr %C) {
entry:
  %l1 = load i32, ptr %A
  %gepA = getelementptr i32, ptr %A, i64 1
  %l2 = load i32, ptr %gepA
  %l3 = load i32, ptr %B
  %gepB = getelementptr i32, ptr %B, i64 1
  %l4 = load i32, ptr %gepB
  %add1 = add i32 %l1, %l3
  %add2 = add i32 %l2, %l4
  %t1 = trunc i32 %add1 to i8
  %t2 = trunc i32 %add2 to i8
  store i8 %t1, ptr %C
  %gepC = getelementptr i8, ptr %C, i64 1
  store i8 %t2, ptr %gepC
  %cmp = icmp ugt i32 %add1, 255
  ret i1 %cmp
}
```
### Optimized IR
```llvm
define i1 @test(ptr %A, ptr %B, ptr %C) {
entry:
  %0 = load <2 x i32>, ptr %A, align 4
  %1 = load <2 x i32>, ptr %B, align 4
  %2 = trunc <2 x i32> %0 to <2 x i8>
  %3 = trunc <2 x i32> %1 to <2 x i8>
  %4 = add <2 x i8> %2, %3
  store <2 x i8> %4, ptr %C, align 1
  %5 = extractelement <2 x i8> %4, i64 0
  %6 = zext i8 %5 to i32
  %cmp = icmp ugt i32 %6, 255
  ret i1 %cmp
}
```


---

# Issue 134013

## Incorrect Vector Size Calculation for Comparison Clusters

**Description**: 
The bug is triggered when the SLP vectorizer processes a bundle of scalar comparison instructions (such as `fcmp` or `icmp`). During the vector tree construction, the compiler attempts to determine the optimal number of elements required to form "full" vector registers, based on the underlying data type and the operands involved. 

The issue occurs because the logic fails to ensure that this calculated optimal vector size does not exceed the actual number of scalar instructions currently being vectorized. If the estimated size for a full vector register is larger than the number of available scalars in the bundle, the compiler proceeds with an invalid size assumption. This mismatch causes the vectorizer to access out-of-bounds elements or generate invalid shuffle masks, leading to a crash.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @test_slp_vector_size_mismatch(ptr %a, ptr %b, ptr %res) #0 {
entry:
  %a0 = load double, ptr %a, align 8
  %a1_gep = getelementptr inbounds double, ptr %a, i64 1
  %a1 = load double, ptr %a1_gep, align 8
  %a2_gep = getelementptr inbounds double, ptr %a, i64 2
  %a2 = load double, ptr %a2_gep, align 8

  %b0 = load double, ptr %b, align 8
  %b1_gep = getelementptr inbounds double, ptr %b, i64 1
  %b1 = load double, ptr %b1_gep, align 8
  %b2_gep = getelementptr inbounds double, ptr %b, i64 2
  %b2 = load double, ptr %b2_gep, align 8

  %c0 = fcmp ogt double %a0, %b0
  %c1 = fcmp ogt double %a1, %b1
  %c2 = fcmp ogt double %a2, %b2

  %z0 = zext i1 %c0 to i32
  %z1 = zext i1 %c1 to i32
  %z2 = zext i1 %c2 to i32

  store i32 %z0, ptr %res, align 4
  %res1_gep = getelementptr inbounds i32, ptr %res, i64 1
  store i32 %z1, ptr %res1_gep, align 4
  %res2_gep = getelementptr inbounds i32, ptr %res, i64 2
  store i32 %z2, ptr %res2_gep, align 4

  ret void
}

attributes #0 = { "min-legal-vector-width"="256" "target-cpu"="skylake" }
```
### Optimized IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @test_slp_vector_size_mismatch(ptr %a, ptr %b, ptr %res) #0 {
entry:
  %0 = load <2 x double>, ptr %a, align 8
  %1 = load <2 x double>, ptr %b, align 8
  %2 = fcmp ogt <2 x double> %0, %1
  %3 = zext <2 x i1> %2 to <2 x i32>
  store <2 x i32> %3, ptr %res, align 4
  %a2_gep = getelementptr inbounds double, ptr %a, i64 2
  %a2 = load double, ptr %a2_gep, align 8
  %b2_gep = getelementptr inbounds double, ptr %b, i64 2
  %b2 = load double, ptr %b2_gep, align 8
  %c2 = fcmp ogt double %a2, %b2
  %z2 = zext i1 %c2 to i32
  %res2_gep = getelementptr inbounds i32, ptr %res, i64 2
  store i32 %z2, ptr %res2_gep, align 4
  ret void
}

attributes #0 = { "min-legal-vector-width"="256" "target-cpu"="skylake" }
```


---

# Issue 139202

## Incorrect Vectorization of Distant Memory Accesses due to Offset Truncation

**Description**
The bug is triggered when the compiler's vectorization analysis attempts to determine if separate memory accesses (such as loads or stores) are consecutive in memory and thus eligible to be merged into a single vector instruction. To make this determination, the compiler calculates the byte offset or distance between the pointers of the candidate instructions.

The issue arises because the logic responsible for calculating this distance stores the result in a narrow integer type (typically 32-bit) instead of a type sufficient to hold the full pointer difference (typically 64-bit). When the actual distance between two pointers is very large (e.g., exceeding 4GB), the value is truncated to fit the narrow type. If the lower bits of this large, truncated offset happen to match the size of the elements being accessed, the compiler incorrectly perceives the widely separated pointers as being adjacent. Consequently, the vectorizer erroneously combines these non-consecutive accesses into a single vector operation, leading to incorrect memory accesses at runtime.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @test_offset_truncation(ptr %base, i32 %v1, i32 %v2) {
entry:
  ; Store the first value at the base address
  store i32 %v1, ptr %base, align 4

  ; Calculate a pointer at an offset of (2^30 + 1) elements.
  ; In bytes: (1073741825 * 4) = 4294967300 = 0x100000004 bytes.
  ; If the compiler truncates the offset difference to 32 bits, it sees 0x00000004.
  ; This matches sizeof(i32), causing the compiler to think this store is adjacent to the first.
  %p2 = getelementptr i32, ptr %base, i64 1073741825
  store i32 %v2, ptr %p2, align 4

  ret void
}
```
### Optimized IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @test_offset_truncation(ptr %base, i32 %v1, i32 %v2) {
entry:
  ; The compiler incorrectly merged the two distant stores into a single vector store
  ; at the base address, overwriting memory at base+4 instead of base+4GB+4.
  %0 = insertelement <2 x i32> poison, i32 %v1, i32 0
  %1 = insertelement <2 x i32> %0, i32 %v2, i32 1
  store <2 x i32> %1, ptr %base, align 4
  ret void
}
```


---

# Issue 151699

## Incorrect Opcode Validation for Alternate Instruction Sequences

**Description**
The bug is triggered when the SLP vectorizer attempts to vectorize a sequence of instructions containing mixed binary operations (e.g., a mix of shifts, additions, or multiplications). In such scenarios, the vectorizer designates a "main" opcode and an "alternate" opcode to handle the diversity of operations within a single vector lane.

The issue arises during the compatibility check for a candidate instruction. The compiler validates the instruction against the "main" operation but fails to handle the specific case where the instruction is structurally compatible with the bundle but does not support the "main" opcode itself. When this mismatch occurs, the compiler neglects to perform a fallback verification to check if the instruction is instead compatible with the "alternate" opcode. This oversight leads to an incorrect classification of the instruction (potentially treating an "alternate" operation as a "main" one or failing to identify the correct leader), which subsequently causes a crash during the vector tree construction or operand analysis phase.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @test_slp_bug(i32* %a, i32* %b, i32* %c) {
entry:
  ; Load 4 consecutive integers from %a
  %a0 = load i32, i32* %a, align 4
  %a1_ptr = getelementptr inbounds i32, i32* %a, i64 1
  %a1 = load i32, i32* %a1_ptr, align 4
  %a2_ptr = getelementptr inbounds i32, i32* %a, i64 2
  %a2 = load i32, i32* %a2_ptr, align 4
  %a3_ptr = getelementptr inbounds i32, i32* %a, i64 3
  %a3 = load i32, i32* %a3_ptr, align 4

  ; Load 4 consecutive integers from %b
  %b0 = load i32, i32* %b, align 4
  %b1_ptr = getelementptr inbounds i32, i32* %b, i64 1
  %b1 = load i32, i32* %b1_ptr, align 4
  %b2_ptr = getelementptr inbounds i32, i32* %b, i64 2
  %b2 = load i32, i32* %b2_ptr, align 4
  %b3_ptr = getelementptr inbounds i32, i32* %b, i64 3
  %b3 = load i32, i32* %b3_ptr, align 4

  ; Mixed operations sequence designed to trigger the bug
  ; Lane 0: shl (Main Opcode)
  ; Lane 1: lshr (Alternate Opcode)
  ; Lane 2: ashr (Third Opcode - should fail vectorization or be handled explicitly, but bug treats as Alternate)
  ; Lane 3: lshr (Alternate Opcode)
  %op0 = shl i32 %a0, %b0
  %op1 = lshr i32 %a1, %b1
  %op2 = ashr i32 %a2, %b2
  %op3 = lshr i32 %a3, %b3

  ; Store results to %c
  store i32 %op0, i32* %c, align 4
  %c1_ptr = getelementptr inbounds i32, i32* %c, i64 1
  store i32 %op1, i32* %c1_ptr, align 4
  %c2_ptr = getelementptr inbounds i32, i32* %c, i64 2
  store i32 %op2, i32* %c2_ptr, align 4
  %c3_ptr = getelementptr inbounds i32, i32* %c, i64 3
  store i32 %op3, i32* %c3_ptr, align 4

  ret void
}
```
### Optimized IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @test_slp_bug(i32* %a, i32* %b, i32* %c) {
entry:
  %0 = bitcast i32* %a to <4 x i32>*
  %1 = load <4 x i32>, <4 x i32>* %0, align 4
  %2 = bitcast i32* %b to <4 x i32>*
  %3 = load <4 x i32>, <4 x i32>* %2, align 4
  ; The vectorizer incorrectly identifies 'ashr' as compatible with the alternate opcode 'lshr'
  ; It generates vector 'shl' and 'lshr' instructions and shuffles them.
  %4 = shl <4 x i32> %1, %3
  %5 = lshr <4 x i32> %1, %3
  ; The shuffle mask <0, 5, 6, 7> selects:
  ; Lane 0: shl (index 0)
  ; Lane 1: lshr (index 5)
  ; Lane 2: lshr (index 6) -> INCORRECT: Original was ashr
  ; Lane 3: lshr (index 7)
  %6 = shufflevector <4 x i32> %4, <4 x i32> %5, <4 x i32> <i32 0, i32 5, i32 6, i32 7>
  %7 = bitcast i32* %c to <4 x i32>*
  store <4 x i32> %6, <4 x i32>* %7, align 4
  ret void
}
```


---

# Issue 158293

## Incorrect Commutativity Check When Vectorizing Mixed Commutative and Non-Commutative Operations

## Description
The bug is triggered when the SLP vectorizer attempts to vectorize a bundle of instructions that mixes commutative operations (such as `add`) with non-commutative operations (such as `sub`). This scenario typically occurs when a commutative instruction acts as an identity operation (e.g., `add x, 0`) and is assimilated into a vector node defined by a non-commutative opcode (e.g., treating it as `sub x, 0`).

The issue arises during the analysis phase when the compiler determines whether the operands of an instruction can be reordered (commutativity). The incorrect logic evaluates commutativity based solely on the properties of the representative vector operation (the non-commutative one) or its relationship to the instruction bundle, failing to check if the original scalar instruction itself is commutative. Consequently, the compiler incorrectly treats the operands of the commutative instruction as fixed. This misidentification leads to errors in handling operand dependencies and "copyable" values, resulting in a crash during the scheduling phase of the vectorization process.

## Example

### Original IR
```llvm
define void @test(ptr %p) {
entry:
  %p1 = getelementptr i32, ptr %p, i64 1
  %a = load i32, ptr %p
  %b = load i32, ptr %p1
  %sub = sub i32 %a, %b
  %add = add i32 0, %a
  store i32 %sub, ptr %p
  store i32 %add, ptr %p1
  ret void
}
```
### Optimized IR
```llvm
define void @test(ptr %p) {
entry:
  %p1 = getelementptr i32, ptr %p, i64 1
  %a = load i32, ptr %p
  %b = load i32, ptr %p1
  %0 = insertelement <2 x i32> poison, i32 %a, i32 0
  %1 = insertelement <2 x i32> %0, i32 0, i32 1
  %2 = insertelement <2 x i32> poison, i32 %b, i32 0
  %3 = insertelement <2 x i32> %2, i32 %a, i32 1
  %4 = sub <2 x i32> %1, %3
  store <2 x i32> %4, ptr %p, align 4
  ret void
}
```


---

# Issue 162663

## Crash due to Undef Values in Vectorized Division/Remainder Nodes

**Description:**
The bug is triggered when the SLP vectorizer attempts to vectorize a sequence of scalar values that includes a mix of division/remainder instructions (or function calls) and `undef` values. The vectorizer initially groups these values into a vector node. However, during a subsequent analysis phase intended to compute minimum value sizes for potential demotion, the compiler iterates over the scalar elements of this node. The logic incorrectly assumes that all scalar elements within a node representing a division or remainder operation are valid `Instruction` objects. When the compiler encounters an `undef` value (which is a `Constant` in LLVM IR, not an `Instruction`), it attempts to cast it to an `Instruction`, resulting in an assertion failure and a compiler crash.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @slp_crash_undef_div(ptr %p, i16 %a, i16 %b) {
entry:
  %ext.a = zext i16 %a to i32
  %ext.b = zext i16 %b to i32
  %div = sdiv i32 %ext.a, %ext.b
  store i32 %div, ptr %p, align 4
  %p.1 = getelementptr inbounds i32, ptr %p, i64 1
  store i32 undef, ptr %p.1, align 4
  ret void
}
```
### Optimized IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @slp_crash_undef_div(ptr %p, i16 %a, i16 %b) {
entry:
  %ext.a = zext i16 %a to i32
  %ext.b = zext i16 %b to i32
  %div = sdiv i32 %ext.a, %ext.b
  %0 = insertelement <2 x i32> poison, i32 %div, i32 0
  store <2 x i32> %0, ptr %p, align 4
  ret void
}
```


---

# Issue 165878

## Incorrect Bit-Width Demotion for Alternate Opcodes

**Description**
The bug is triggered when the SLP vectorizer attempts to optimize a sequence of instructions by reducing their bit width (demotion) while simultaneously handling nodes with different opcodes (alternate opcodes). When the vectorizer groups instructions with differing operations (e.g., mixing arithmetic operations with shifts) into a single vector node, it analyzes the values to determine if they can be computed using a narrower type (e.g., converting `i32` to `i16`).

The issue arises because the analysis for the minimum safe bit width may not strictly validate the constraints of the "alternate" opcode. Certain operations, such as shifts, divisions, and remainders, have strict validity requirements relative to the bit width (for example, a shift amount must be strictly less than the bit width). If the optimizer demotes the type based on the values of the primary operation but ignores that the alternate operation's operands (like a shift count) exceed the capacity of the new narrower type, the resulting vector instruction performs an undefined operation (poison), leading to a miscompilation.

## Example

### Original IR
```llvm
define void @test_slp_demotion_bug(ptr %src, ptr %dst) {
entry:
  %l0 = load i32, ptr %src, align 4
  %gep1 = getelementptr inbounds i32, ptr %src, i64 1
  %l1 = load i32, ptr %gep1, align 4
  ; Mask inputs to simulate values that fit in i8
  %v0 = and i32 %l0, 255
  %v1 = and i32 %l1, 255
  ; Lane 0: Arithmetic operation (add)
  %op0 = add i32 %v0, 10
  ; Lane 1: Shift operation (shl)
  ; The shift amount 20 is valid for i32 but invalid (poison) if demoted to i8
  %op1 = shl i32 %v1, 20
  store i32 %op0, ptr %dst, align 4
  %gep_dst1 = getelementptr inbounds i32, ptr %dst, i64 1
  store i32 %op1, ptr %gep_dst1, align 4
  ret void
}
```
### Optimized IR
```llvm
define void @test_slp_demotion_bug(ptr %src, ptr %dst) {
entry:
  %0 = load <2 x i32>, ptr %src, align 4
  ; The vectorizer incorrectly demotes the vector to <2 x i8>
  %1 = trunc <2 x i32> %0 to <2 x i8>
  ; It performs the operations on i8
  %2 = add <2 x i8> %1, <i8 10, i8 10>
  ; BUG: shl on i8 with shift amount 20 is poison (undefined behavior)
  %3 = shl <2 x i8> %1, <i8 20, i8 20>
  ; Shuffle to combine the alternate opcodes
  %4 = shufflevector <2 x i8> %2, <2 x i8> %3, <2 x i32> <i32 0, i32 3>
  ; Extend back to i32, propagating the poison
  %5 = zext <2 x i8> %4 to <2 x i32>
  store <2 x i32> %5, ptr %dst, align 4
  ret void
}
```


---

# Issue 173784

## Poison Propagation in Vectorized Boolean Logical Reductions

**Description**:
The bug is triggered when the SLP vectorizer transforms a chain of boolean logical operations (typically represented by `select` instructions implementing logical OR or AND) into a vector reduction. In the original scalar IR, these operations effectively support short-circuiting or masking semantics: if one operand determines the result (e.g., a `true` value in a logical OR), the other operand is not observed. This allows the unobserved operand to safely be `poison` without affecting the program's correctness.

The vectorizer lowers this pattern into a vector reduction intrinsic (such as `llvm.vector.reduce.or`) or a sequence of bitwise operations. Unlike the scalar `select` chain, vector reductions are eager and evaluate all lanes. If the constructed vector contains a lane with a determining value (e.g., `true`) and another lane with `poison`, the reduction operation combines them to produce a `poison` result. This transformation introduces undefined behavior in cases where the scalar code produced a well-defined result, as the compiler fails to `freeze` the potentially poisonous operands before performing the reduction.

## Example

### Original IR
```llvm
define i1 @test(ptr %p) {
  %v0 = load i1, ptr %p, align 1
  %p1 = getelementptr i1, ptr %p, i64 1
  %v1 = load i1, ptr %p1, align 1
  %p2 = getelementptr i1, ptr %p, i64 2
  %v2 = load i1, ptr %p2, align 1
  %p3 = getelementptr i1, ptr %p, i64 3
  %v3 = load i1, ptr %p3, align 1
  %op1 = select i1 %v0, i1 true, i1 %v1
  %op2 = select i1 %op1, i1 true, i1 %v2
  %op3 = select i1 %op2, i1 true, i1 %v3
  ret i1 %op3
}
```
### Optimized IR
```llvm
define i1 @test(ptr %p) {
  %1 = load <4 x i1>, ptr %p, align 1
  %2 = call i1 @llvm.vector.reduce.or.v4i1(<4 x i1> %1)
  ret i1 %2
}

declare i1 @llvm.vector.reduce.or.v4i1(<4 x i1>)
```


---

# Issue 173796

## Incorrect Poison Handling in Boolean Reduction with Mixed Operand Usage

**Description**
The bug is triggered during the SLP vectorization of boolean reduction trees, where chains of `select` instructions (representing logical AND/OR) are converted into vector bitwise operations. The issue arises when a specific intermediate value is used in "mixed positions" within the reduction graph: it serves as a **condition operand** in one instruction and as a **value (data) operand** in another (or the instruction using it as a condition is itself used as a value operand).

When analyzing whether to insert `freeze` instructions to prevent poison propagation, the compiler incorrectly classifies the shared value. It observes the value's usage as a condition and assumes that this usage pattern allows it to skip freezing (likely assuming the condition determines control flow and poison safety). However, this logic fails to account for the value's simultaneous participation as a data operand in the reduction tree. 

In the scalar code, `select` instructions can suppress poison from unused operands (e.g., `select false, poison, ...` evaluates to a defined value). In the vectorized code, `select`s are replaced with bitwise operations (like `and`/`or`) which do not short-circuit and propagate poison if any operand is poison (e.g., `false & poison` evaluates to `poison`). By skipping the necessary `freeze` on the shared value, the vectorized code allows poison to propagate through the reduction tree in scenarios where the original scalar semantics would have safely masked it, leading to a miscompilation.

## Example

### Original IR
```llvm
define i1 @test(i1 %a, i1 %b) {
  ; Logical AND: a && b. If a is false, b (poison) is suppressed.
  %1 = select i1 %a, i1 %b, i1 false
  ; Logical AND: b && a. If b is poison, result is poison.
  %2 = select i1 %b, i1 %a, i1 false
  ; Reduction: (a && b) && (b && a)
  %3 = select i1 %1, i1 %2, i1 false
  ret i1 %3
}
```
### Optimized IR
```llvm
define i1 @test(i1 %a, i1 %b) {
  ; The optimizer incorrectly vectorizes the selects into bitwise ANDs without freezing inputs.
  ; Lane 0: a (cond) vs b (val). Lane 1: b (cond) vs a (val).
  %1 = insertelement <2 x i1> poison, i1 %a, i32 0
  %2 = insertelement <2 x i1> %1, i1 %b, i32 1
  %3 = insertelement <2 x i1> poison, i1 %b, i32 0
  %4 = insertelement <2 x i1> %3, i1 %a, i32 1
  ; Bitwise AND propagates poison even if one operand is false (unlike select).
  %5 = and <2 x i1> %2, %4
  %6 = call i1 @llvm.vector.reduce.and.v2i1(<2 x i1> %5)
  ret i1 %6
}

declare i1 @llvm.vector.reduce.and.v2i1(<2 x i1>)
```


---

# Issue 174041

## Incorrect Vectorization of Incompatible Identity Operations

**Description**
The bug is triggered when the vectorizer attempts to combine different scalar bitwise instructions that act as identity operations (no-ops) into a single vector instruction. Specifically, this occurs when mixing a `xor` instruction with a constant zero (which preserves the value) and an `and` instruction with a constant -1 (which also preserves the value). The compiler incorrectly assumes these operations are compatible and selects the `and` opcode for the resulting vector instruction. Consequently, the constant `0` from the `xor` operation is used in the vector constant mask. Since `0` is not an identity element for `and` but rather a zeroing element, the lane corresponding to the original `xor` operation computes `value & 0` instead of preserving the value, leading to data corruption.

## Example

### Original IR
```llvm
define void @test(ptr %p, i32 %a, i32 %b) {
entry:
  ; Operation 1: xor with 0 (identity operation, result is %a)
  %op1 = xor i32 %a, 0
  
  ; Operation 2: and with -1 (identity operation, result is %b)
  %op2 = and i32 %b, -1
  
  ; Store to adjacent memory locations to trigger SLP vectorization
  store i32 %op1, ptr %p, align 4
  %p.1 = getelementptr inbounds i32, ptr %p, i64 1
  store i32 %op2, ptr %p.1, align 4
  ret void
}
```
### Optimized IR
```llvm
define void @test(ptr %p, i32 %a, i32 %b) {
entry:
  ; The vectorizer packs the inputs %a and %b
  %0 = insertelement <2 x i32> poison, i32 %a, i32 0
  %1 = insertelement <2 x i32> %0, i32 %b, i32 1
  
  ; BUG: The compiler incorrectly combines 'xor %a, 0' and 'and %b, -1' into a vector 'and'.
  ; It uses the constants from the original instructions: 0 and -1.
  ; Lane 0 computes: %a & 0 = 0 (Incorrect, should be %a)
  ; Lane 1 computes: %b & -1 = %b (Correct)
  %2 = and <2 x i32> %1, <i32 0, i32 -1>
  
  store <2 x i32> %2, ptr %p, align 4
  ret void
}
```


---

# Issue 75437

## Misinterpretation of Dynamic Vector Insertions as Undef in SLP Vectorization

**Description**: 
The bug is triggered when the SLP vectorizer analyzes the construction of a vector to identify which of its elements are `poison` or `undef`. This analysis traverses the chain of `insertelement` instructions used to build the vector. The flaw occurs when the analysis encounters an `insertelement` instruction where the insertion index is a runtime variable (non-constant) rather than a compile-time constant.

Instead of conservatively assuming that the dynamic insertion defines an element (making the vector state partially or fully defined), the logic ignores the instruction. If the base vector was `poison`, the optimizer incorrectly concludes that the vector elements remain `poison` effectively acting as if the dynamic insertion never happened. This leads to the incorrect removal of the `insertelement` instruction and the loss of the inserted value in the generated code.

## Example

### Original IR
```llvm
define <2 x float> @test_slp_dynamic_insert_bug(float %val, i32 %idx) {
  %vec = insertelement <2 x float> poison, float %val, i32 %idx
  %e0 = extractelement <2 x float> %vec, i32 0
  %e1 = extractelement <2 x float> %vec, i32 1
  %r0 = insertelement <2 x float> poison, float %e0, i32 0
  %r1 = insertelement <2 x float> %r0, float %e1, i32 1
  ret <2 x float> %r1
}
```
### Optimized IR
```llvm
define <2 x float> @test_slp_dynamic_insert_bug(float %val, i32 %idx) {
  ret <2 x float> poison
}
```


---

# Issue 98838

## Incorrect Poison Replacement in Logical Select Reductions

**Description**
The bug is triggered during the cleanup phase of the SLP vectorizer, where the compiler removes original scalar instructions that have been vectorized. To facilitate this removal and break dependency chains within the scalar code, the compiler replaces the uses of these instructions with `poison` values.

The issue arises when the scalar instruction being replaced is used as the **condition operand** of a `select` instruction that implements a logical operation (such as a logical AND or OR). In LLVM IR, a `select` instruction with a `poison` condition evaluates to `poison` regardless of its other operands. Consequently, replacing the condition with `poison` causes the entire logical operation to produce a `poison` value. This `poison` value can then propagate to subsequent instructions in the reduction chain or to other users that are not immediately eliminated. If the logic relies on the operation yielding a defined value (e.g., `false` or the value of the other operand), the unexpected `poison` leads to undefined behavior and miscompilation. The correct strategy requires replacing the condition with a non-poison constant (such as `false`) to ensure the `select` instruction resolves to a valid, defined value, thereby preventing the propagation of poison.

## Example

### Original IR
```llvm
define i1 @bug_trigger(ptr %p) {
entry:
  %p0 = getelementptr inbounds i8, ptr %p, i64 0
  %l0 = load i8, ptr %p0, align 1
  %p1 = getelementptr inbounds i8, ptr %p, i64 1
  %l1 = load i8, ptr %p1, align 1
  %p2 = getelementptr inbounds i8, ptr %p, i64 2
  %l2 = load i8, ptr %p2, align 1
  %p3 = getelementptr inbounds i8, ptr %p, i64 3
  %l3 = load i8, ptr %p3, align 1
  %c0 = icmp ne i8 %l0, 0
  %c1 = icmp ne i8 %l1, 0
  %c2 = icmp ne i8 %l2, 0
  %c3 = icmp ne i8 %l3, 0
  %or1 = select i1 %c0, i1 true, i1 %c1
  call void @use(i1 %or1)
  %or2 = select i1 %or1, i1 true, i1 %c2
  %or3 = select i1 %or2, i1 true, i1 %c3
  ret i1 %or3
}

declare void @use(i1)
```
### Optimized IR
```llvm
define i1 @bug_trigger(ptr %p) {
entry:
  %0 = load <4 x i8>, ptr %p, align 1
  %1 = icmp ne <4 x i8> %0, zeroinitializer
  %2 = call i1 @llvm.vector.reduce.or.v4i1(<4 x i1> %1)
  ; The bug: %or1 uses poison operands because scalar %c0 was replaced by poison
  ; resulting in %or1 being poison, which propagates to the external use.
  %or1 = select i1 poison, i1 true, i1 poison
  call void @use(i1 %or1)
  ret i1 %2
}

declare void @use(i1)
declare i1 @llvm.vector.reduce.or.v4i1(<4 x i1>)
```
