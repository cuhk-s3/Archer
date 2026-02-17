# Issue 108698

## Unsafe Narrowing of Vector Logical Right Shifts

**Description**
The bug is triggered when the optimizer attempts to reduce the bit width of a vector logical right shift (`lshr`) instruction. This optimization occurs when the value being shifted is the result of a zero-extension (`zext`) from a narrower type (e.g., extending `i1` to `i32`). The compiler attempts to optimize this pattern by performing the shift directly on the narrower type and zero-extending the result, rather than extending the input first.

The issue arises because the optimizer fails to verify that the shift amount is valid for the narrower type. In LLVM IR, a shift instruction produces a poison value if the shift amount is greater than or equal to the bit width of the type being shifted. While the shift amount might be valid for the original wider type, it can exceed the capacity of the narrower type (e.g., shifting by 1 is valid for `i32` but undefined for `i1`). Consequently, the transformed instruction yields undefined behavior instead of the correct result (often 0), leading to miscompilation.

## Example

### Original IR
```llvm
define <2 x i32> @test_unsafe_narrowing(<2 x i1> %x) {
  %ext = zext <2 x i1> %x to <2 x i32>
  %res = lshr <2 x i32> %ext, <i32 1, i32 1>
  ret <2 x i32> %res
}
```
### Optimized IR
```llvm
define <2 x i32> @test_unsafe_narrowing(<2 x i1> %x) {
  %narrow = lshr <2 x i1> %x, <i1 true, i1 true>
  %res = zext <2 x i1> %narrow to <2 x i32>
  ret <2 x i32> %res
}
```


---

# Issue 114901

## Incorrect Vectorization of Non-Commutative Binary Operations on Extracted Comparisons

**Description**:
The bug is triggered when the compiler attempts to optimize a specific pattern of scalar instructions back into vector operations. The pattern involves:
1. Extracting two elements from a vector using `extractelement`.
2. Performing integer comparisons (`icmp`) on these extracted elements.
3. Combining the resulting boolean values using a **non-commutative** binary operator (e.g., `ashr`, `sub`, `shl`).

The optimization attempts to replace this sequence with a single vector comparison followed by a vector binary operation and an extraction. However, the transformation logic fails to correctly handle the operand ordering required for non-commutative operations. It blindly constructs the vector binary operation without ensuring that the Left-Hand Side (LHS) and Right-Hand Side (RHS) of the original scalar operation map correctly to the LHS and RHS of the generated vector operation. This leads to a miscompilation where the operands are effectively swapped or misaligned in the vector domain.

## Example

### Original IR
```llvm
define i1 @test(<2 x i32> %vec) {
  %e0 = extractelement <2 x i32> %vec, i32 0
  %e1 = extractelement <2 x i32> %vec, i32 1
  %c0 = icmp eq i32 %e0, 10
  %c1 = icmp eq i32 %e1, 20
  ; Non-commutative operation: shl. Order is c1 << c0.
  %res = shl i1 %c1, %c0
  ret i1 %res
}
```
### Optimized IR
```llvm
define i1 @test(<2 x i32> %vec) {
  ; The optimization vectorizes the comparison
  %1 = icmp eq <2 x i32> %vec, <i32 10, i32 20>
  ; %1 is <c0, c1>
  
  ; The optimization incorrectly maps the scalar operands to vector lanes for the non-commutative op.
  ; It assumes the first vector lane (c0) corresponds to the LHS and the second (c1) to the RHS,
  ; or simply aligns them incorrectly, resulting in c0 << c1 instead of c1 << c0.
  %2 = shufflevector <2 x i1> %1, <2 x i1> poison, <2 x i32> <i32 1, i32 0>
  %3 = shl <2 x i1> %1, %2
  
  ; Extracting index 0 yields (c0 << c1), which is the swapped operation.
  %res = extractelement <2 x i1> %3, i32 0
  ret i1 %res
}
```


---

# Issue 115575

## Incorrect Scalarization of Vector Operations with Out-of-Bounds Insertion Indices

**Description**:
The bug is triggered when the compiler attempts to scalarize a vector binary operation (such as integer division or remainder) where one of the operands is created by an `insertelement` instruction using an out-of-bounds index.

In LLVM IR, an `insertelement` instruction with an index greater than or equal to the vector size produces a `poison` vector. Consequently, any subsequent binary operation using this vector as an input should also result in `poison`, which is a safe and well-defined state that does not execute the operation.

The optimization logic, however, fails to verify that the insertion index is within the valid bounds of the vector type. It proceeds to transform the vector operation into a scalar operation by extracting the inserted scalar value and attempting to retrieve the corresponding element from the second vector operand using the same out-of-bounds index. Accessing the second operand at an invalid index typically yields an `undef` value. When this `undef` value is used as a divisor in instructions like `sdiv` or `urem`, it triggers immediate Undefined Behavior (UB). This transformation incorrectly replaces a safe code path (producing `poison`) with one that exhibits Undefined Behavior, resulting in a miscompilation.

## Example

### Original IR
```llvm
define i32 @test(i32 %a, <2 x i32> %b) {
  %ins = insertelement <2 x i32> poison, i32 %a, i32 2
  %op = sdiv <2 x i32> %ins, %b
  %res = extractelement <2 x i32> %op, i32 2
  ret i32 %res
}
```
### Optimized IR
```llvm
define i32 @test(i32 %a, <2 x i32> %b) {
  %ext = extractelement <2 x i32> %b, i32 2
  %res = sdiv i32 %a, %ext
  ret i32 %res
}
```


---

# Issue 121110

## Summary Title
Incorrect Folding of Shuffles with Swapped Comparison Predicates

## Description
The bug is triggered in the `VectorCombine` pass when the optimizer attempts to fold a shuffle instruction that merges the results of two comparison instructions into a single vector comparison. The optimization logic identifies two scalar or vector comparisons feeding into a shuffle and tries to combine them. The issue arises because the pattern matching logic permitted the two comparisons to have different predicates if they were logically equivalent via operand swapping (e.g., `less-than` vs. `greater-than`). 

When such a match occurred, the pass constructed a new vector comparison using the predicate of the first instruction for all lanes, relying on the matcher to swap the operands of the second instruction to compensate. However, this transformation strategy—unifying two different predicates into a single SIMD operation by swapping operands—was flawed or unsafe in this context, leading to miscompilation. The resulting vector instruction did not correctly preserve the semantics of the original code, causing incorrect values to be computed.

## Example

### Original IR
```llvm
define <2 x i1> @test(<2 x i32> %a, <2 x i32> %b, <2 x i32> %c, <2 x i32> %d) {
  %cmp1 = icmp slt <2 x i32> %a, %b
  %cmp2 = icmp sgt <2 x i32> %c, %d
  %shuf = shufflevector <2 x i1> %cmp1, <2 x i1> %cmp2, <2 x i32> <i32 0, i32 2>
  ret <2 x i1> %shuf
}
```
### Optimized IR
```llvm
define <2 x i1> @test(<2 x i32> %a, <2 x i32> %b, <2 x i32> %c, <2 x i32> %d) {
  %1 = shufflevector <2 x i32> %a, <2 x i32> %c, <2 x i32> <i32 0, i32 2>
  %2 = shufflevector <2 x i32> %b, <2 x i32> %d, <2 x i32> <i32 0, i32 2>
  %shuf = icmp slt <2 x i32> %1, %2
  ret <2 x i1> %shuf
}
```


---

# Issue 126085

## Incorrect Vector Type in Shuffle Cost Calculation for Size-Mismatched Vectors

**Description**
The bug is triggered when the vector combiner attempts to fold a sequence of vector operations—specifically involving the extraction of an element from a source vector and its insertion into a destination vector—into a sequence of shuffle operations. The issue arises when the source vector and the destination vector have different lengths, particularly when the source vector is larger than the destination vector.

When calculating the estimated cost of the transformation, the compiler constructs a shuffle mask to represent the permutation of the source vector. However, when querying the Target Transform Info (TTI) for the cost of this shuffle, the compiler incorrectly provides the *destination* vector type (the smaller vector) instead of the *source* vector type. If the index of the element being extracted from the larger source vector exceeds the bounds of the smaller destination vector, the cost model validates the mask indices against the incorrect, smaller type. This results in an assertion failure indicating an out-of-bounds shuffle mask element.

## Example

### Original IR
```llvm
define <2 x float> @test_vector_combine_mismatch(<4 x float> %src, <2 x float> %dest) {
  %ext = extractelement <4 x float> %src, i32 3
  %ins = insertelement <2 x float> %dest, float %ext, i32 0
  ret <2 x float> %ins
}
```
### Optimized IR
```llvm
define <2 x float> @test_vector_combine_mismatch(<4 x float> %src, <2 x float> %dest) {
  ; The optimization incorrectly attempts to form a shuffle using the destination type (<2 x float>)
  ; but with an index (3) derived from the larger source type (<4 x float>).
  ; This results in an out-of-bounds mask index for the smaller vector type.
  %1 = shufflevector <2 x float> %dest, <2 x float> poison, <2 x i32> <i32 3, i32 1>
  ret <2 x float> %1
}
```


---

# Issue 67060

## Incorrect Scalarization of Packed Vector Elements Leading to Adjacent Data Corruption

**Description**
The bug is triggered when the compiler attempts to optimize a sequence of vector operations—specifically a vector load, an element modification (e.g., `insertelement`), and a vector store—into a single scalar store of the modified element. The optimization logic validates that the total bit width of the vector matches its storage size in memory, assuming this ensures the memory layout allows for scalar access.

However, this check is insufficient for vectors with sub-byte element types (such as `<N x i1>`), where elements are bit-packed. While the whole vector may be byte-aligned, individual elements are not. When the compiler converts the operation into a scalar store, it generates an instruction that writes the architecture's minimum addressable unit (typically a byte). Because the target element occupies fewer bits than a byte, the scalar store inadvertently overwrites adjacent bits belonging to other elements in the vector, leading to data corruption.

## Example

### Original IR
```llvm
define void @test_vector_corruption(<8 x i1>* %ptr, i1 %val) {
  %vec = load <8 x i1>, <8 x i1>* %ptr
  %ins = insertelement <8 x i1> %vec, i1 %val, i32 0
  store <8 x i1> %ins, <8 x i1>* %ptr
  ret void
}
```
### Optimized IR
```llvm
define void @test_vector_corruption(<8 x i1>* %ptr, i1 %val) {
  %1 = bitcast <8 x i1>* %ptr to i1*
  store i1 %val, i1* %1
  ret void
}
```


---

# Issue 89390

## Unsafe Hoisting of Shuffle over Division/Remainder with Poison Masks

## Description
The bug is triggered when the compiler optimizes a vector shuffle instruction that combines the results of two integer division or remainder operations. The optimization attempts to reduce instruction count by "hoisting" the shuffle before the operations, transforming a pattern like `shuffle(div(A, B), div(C, D))` into `div(shuffle(A, C), shuffle(B, D))`.

The issue arises when the shuffle mask contains `poison` or undefined elements, which indicate that the values in specific lanes of the result are not needed. When the compiler transforms the code, it propagates these `poison` elements into the generated shuffle instructions for the operands. Specifically, this creates a new divisor vector that contains `poison` or undefined values in the lanes corresponding to the mask's `poison` elements.

While the original code performed the division or remainder on valid operands and simply discarded the result for those lanes, the transformed code executes the division or remainder with a `poison` or undefined value in the divisor. For division and remainder operations, having an undefined or poison value in the divisor can trigger immediate Undefined Behavior (e.g., if treated as zero), rendering the transformation unsafe.

## Example

### Original IR
```llvm
define <2 x i32> @test_unsafe_hoist_sdiv(<2 x i32> %a, <2 x i32> %b, <2 x i32> %c, <2 x i32> %d) {
  %div1 = sdiv <2 x i32> %a, %b
  %div2 = sdiv <2 x i32> %c, %d
  %res = shufflevector <2 x i32> %div1, <2 x i32> %div2, <2 x i32> <i32 0, i32 poison>
  ret <2 x i32> %res
}
```
### Optimized IR
```llvm
define <2 x i32> @test_unsafe_hoist_sdiv(<2 x i32> %a, <2 x i32> %b, <2 x i32> %c, <2 x i32> %d) {
  %1 = shufflevector <2 x i32> %a, <2 x i32> %c, <2 x i32> <i32 0, i32 poison>
  %2 = shufflevector <2 x i32> %b, <2 x i32> %d, <2 x i32> <i32 0, i32 poison>
  %res = sdiv <2 x i32> %1, %2
  ret <2 x i32> %res
}
```
