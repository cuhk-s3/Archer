# Issue 108698

## Narrowing of Logical Shift Right Without Shift Amount Validation

**Description**: 
The bug is triggered when the compiler attempts to narrow the type of a logical shift right (`lshr`) instruction that operates on a zero-extended value. The optimization shrinks the shift operation to use the smaller source type of the zero-extension and truncates the shift amount accordingly. 

However, the transformation fails to verify whether the shift amount is strictly less than the bitwidth of the smaller type. In the original wider type, a shift amount greater than or equal to the smaller type's bitwidth would safely shift out all the active bits, correctly producing a zero result. When the operation is narrowed, applying the same (or truncated) shift amount to the smaller type results in undefined behavior (a `poison` value) because the shift amount exceeds or equals the new, smaller bitwidth. This leads to a miscompilation where valid zero results are incorrectly replaced with `poison`.

## Example

### Original IR
```llvm
define i32 @test(i8 %x, i32 %shamt) {
entry:
  %ext = zext i8 %x to i32
  %shift = lshr i32 %ext, %shamt
  ret i32 %shift
}
```
### Optimized IR
```llvm
define i32 @test(i8 %x, i32 %shamt) {
entry:
  %shamt.trunc = trunc i32 %shamt to i8
  %shift.narrow = lshr i8 %x, %shamt.trunc
  %ext = zext i8 %shift.narrow to i32
  ret i32 %ext
}
```


---

# Issue 114901

## Vectorization of Non-Commutative Binary Operations on Extracted Comparisons

**Description:**
The bug is triggered by a specific pattern involving a scalar non-commutative binary operation (such as arithmetic or logical shifts) applied to two boolean values. These boolean values are the results of comparison operations performed on elements extracted from different indices of the same vector.

When the compiler attempts to optimize this pattern, it tries to vectorize the operations by:
1. Performing a single vector comparison against a combined constant vector.
2. Using a shuffle operation to align the comparison results into the same vector lane.
3. Applying the binary operation as a vector operation.
4. Extracting the final scalar result from the vector.

The flaw in this transformation is that it assumes the binary operation is commutative or otherwise fails to correctly track and preserve the original left-hand side and right-hand side operand ordering. Consequently, for non-commutative binary operations, the operands can end up swapped or incorrectly ordered in the newly generated vector binary operation. This leads to a miscompilation where the optimized code evaluates the binary operation with reversed arguments, producing incorrect values or poison.

## Example

### Original IR
```llvm
define i1 @test_shl_extracted_cmps(<2 x i32> %v) {
  %e0 = extractelement <2 x i32> %v, i32 0
  %e1 = extractelement <2 x i32> %v, i32 1
  %c0 = icmp eq i32 %e0, 42
  %c1 = icmp eq i32 %e1, 24
  %res = shl i1 %c0, %c1
  ret i1 %res
}

```
### Optimized IR
```llvm
define i1 @test_shl_extracted_cmps(<2 x i32> %v) {
  %1 = icmp eq <2 x i32> %v, <i32 42, i32 24>
  %2 = shufflevector <2 x i1> %1, <2 x i1> poison, <2 x i32> <i32 1, i32 poison>
  %3 = shl <2 x i1> %2, %1
  %res = extractelement <2 x i1> %3, i32 0
  ret i1 %res
}

```


---

# Issue 115575

## Scalarization of Vector Operations with Out-of-Bounds Insertion Indices

**Description**: 
The bug occurs when the compiler attempts to scalarize a vector binary operation or comparison where one of the operands is an `insertelement` instruction using an out-of-bounds index. 

When an insertion index is greater than or equal to the number of elements in the vector, the `insertelement` instruction evaluates to `poison`. In the original IR, the subsequent vector operation simply takes this `poison` vector and propagates it, resulting in a `poison` value without causing Undefined Behavior (UB). 

However, during the scalarization transformation, the compiler attempts to fold the operation by extracting the corresponding element from the other operand (such as a constant vector) using the same out-of-bounds index. This out-of-bounds extraction yields a `poison` value. The compiler then constructs a scalar version of the binary operation using the originally inserted scalar and the extracted `poison` value. 

For certain operations, such as integer division (`sdiv`, `udiv`) or remainder (`srem`, `urem`), having `poison` as an operand (e.g., as the divisor) triggers immediate Undefined Behavior. Consequently, the transformation incorrectly elevates a safe `poison` result into UB, leading to a miscompilation where the optimized code is less defined than the original code.

## Example

### Original IR
```llvm
define <2 x i32> @test(i32 %x) {
  %ins = insertelement <2 x i32> poison, i32 %x, i32 2
  %div = sdiv <2 x i32> %ins, <i32 42, i32 42>
  ret <2 x i32> %div
}

```
### Optimized IR
```llvm
define <2 x i32> @test(i32 %x) {
  %div.scalar = sdiv i32 %x, poison
  %div = insertelement <2 x i32> poison, i32 %div.scalar, i32 2
  ret <2 x i32> %div
}

```


---

# Issue 121110

## Incorrect Folding of Shuffled Compares with Conditionally Equivalent Predicates

**Description**:
The bug occurs in a compiler optimization that attempts to fold a `shufflevector` of two compare instructions into a single compare of shuffled operands. Specifically, it tries to transform a pattern like `shuffle (cmp P1 X, Y), (cmp P2 Z, W)` into `cmp P1 (shuffle X, Z), (shuffle Y, W)`. 

To perform this transformation, the optimization checks if the two source compare instructions have "equivalent" predicates. However, the matching logic used to compare these predicates is too permissive. It allows matching predicates that are only equivalent under specific conditions or flags. For example, it considers an unsigned compare with a `samesign` flag (which asserts that both operands have the same sign, making signed and unsigned comparisons logically identical) as equivalent to a regular signed compare.

When the transformation combines the two compares, it blindly applies the predicate and flags from the first compare (the LHS) to the newly created combined compare. If the LHS compare was an unsigned compare with a `samesign` assumption, but the RHS compare was a regular signed compare without that assumption, the new instruction will evaluate the RHS lanes using the unsigned predicate. 

This leads to a miscompilation because the operands from the RHS lanes are not guaranteed to have the same sign. Evaluating them with an unsigned predicate instead of their original signed predicate produces incorrect boolean results (e.g., when comparing negative numbers). This silently corrupts the logic of the program, altering control flow or output. The issue is resolved by strictly requiring the base predicates of both compares to match exactly before allowing the fold, rather than relying on conditional equivalence.

## Example

### Original IR
```llvm
define <2 x i1> @test_shuffle_cmp_samesign(<2 x i32> %x, <2 x i32> %y, <2 x i32> %z, <2 x i32> %w) {
  %cmp1 = icmp samesign ult <2 x i32> %x, %y
  %cmp2 = icmp slt <2 x i32> %z, %w
  %shuf = shufflevector <2 x i1> %cmp1, <2 x i1> %cmp2, <2 x i32> <i32 0, i32 2>
  ret <2 x i1> %shuf
}
```
### Optimized IR
```llvm
define <2 x i1> @test_shuffle_cmp_samesign(<2 x i32> %x, <2 x i32> %y, <2 x i32> %z, <2 x i32> %w) {
  %1 = shufflevector <2 x i32> %x, <2 x i32> %z, <2 x i32> <i32 0, i32 2>
  %2 = shufflevector <2 x i32> %y, <2 x i32> %w, <2 x i32> <i32 0, i32 2>
  %shuf = icmp samesign ult <2 x i32> %1, %2
  ret <2 x i1> %shuf
}
```


---

# Issue 158197

## Endian-Unaware Vector-to-Scalar Packing and Extraction

**Description**: 
The bug is triggered by a transformation that attempts to optimize vector element extractions by packing an entire vector into a single, large scalar integer. Once packed, the optimization replaces the original vector extraction instructions with scalar bitwise operations, specifically logical right shifts and bitwise AND masks, to isolate the desired vector lane. 

The vulnerability lies in the calculation of the shift amount used to locate the specific element within the packed integer. The transformation hardcodes a little-endian assumption, calculating the bit offset simply as the element index multiplied by the element size (i.e., assuming the element at index 0 resides in the least significant bits). 

On big-endian targets, the memory layout dictates that the first vector element occupies the most significant bits of the packed integer. Because the transformation fails to query the target's data layout to adjust the bit offset accordingly, it shifts by the wrong amount and extracts incorrect bits. To trigger this issue, the input LLVM IR must contain vector extraction operations that the compiler attempts to scalarize into bitwise arithmetic while compiling for a target with a big-endian data layout.

## Example

### Original IR
```llvm
target datalayout = "E-m:e-p:32:32-i64:64-v128:64:128-a:0:32-n32-S64"
target triple = "powerpc-unknown-linux-gnu"

define i8 @test_extract(<4 x i8> %v) {
entry:
  %ext = extractelement <4 x i8> %v, i32 1
  ret i8 %ext
}
```
### Optimized IR
```llvm
target datalayout = "E-m:e-p:32:32-i64:64-v128:64:128-a:0:32-n32-S64"
target triple = "powerpc-unknown-linux-gnu"

define i8 @test_extract(<4 x i8> %v) {
entry:
  %0 = bitcast <4 x i8> %v to i32
  %1 = lshr i32 %0, 8
  %2 = trunc i32 %1 to i8
  ret i8 %2
}
```


---

# Issue 67060

## Scalarization of Memory Operations on Vectors with Non-Byte-Sized Elements

**Description:**
The bug is triggered by a sequence of instructions that modify or extract a single element of a vector in memory (e.g., loading a vector, inserting or extracting an element, and then storing or using the result). 

Specifically, the issue occurs when the vector type has a total size that is a multiple of bytes (i.e., it is byte-sized), but its individual scalar elements are not byte-sized (such as a vector of `i1` elements, like `<32 x i1>`). 

The optimization pass attempts to simplify the operation by scalarizing it—replacing the full vector memory access with a direct scalar memory access (load or store) to the specific element. However, the transformation logic incorrectly verifies the byte-size property against the entire vector type rather than the scalar element type. Since the whole vector is byte-sized, the check passes, and the pass emits a scalar memory operation for the non-byte-sized element. 

When this scalar memory operation is later lowered by the backend, it is expanded to a full byte-sized memory access. For a store, this results in writing a full byte, which incorrectly clobbers adjacent bits belonging to other vector elements.

## Example

### Original IR
```llvm
define void @test(ptr %ptr, i1 %val) {
entry:
  %load = load <32 x i1>, ptr %ptr, align 4
  %insert = insertelement <32 x i1> %load, i1 %val, i32 2
  store <32 x i1> %insert, ptr %ptr, align 4
  ret void
}

```
### Optimized IR
```llvm
define void @test(ptr %ptr, i1 %val) {
entry:
  %0 = getelementptr inbounds i1, ptr %ptr, i64 2
  store i1 %val, ptr %0, align 1
  ret void
}

```


---

# Issue 89390

## Hoisting Shufflevector with Poison Mask Above Division/Remainder Operations

**Description**:
The bug is triggered by an incorrect optimization that folds a `shufflevector` of two binary operations into a binary operation of two `shufflevector`s. The specific pattern involves:

1. A `shufflevector` instruction that operates on the results of two identical integer division or remainder instructions (e.g., `sdiv`, `udiv`, `srem`, or `urem`).
2. The mask of the `shufflevector` instruction contains one or more `poison` (or `undef`) elements.
3. The compiler attempts to optimize this by hoisting the `shufflevector` above the binary operations. It creates new `shufflevector` instructions for the operands and then applies the division/remainder operation to the results of these new shuffles.
4. Because the original shuffle mask contained `poison`, the newly created `shufflevector` instructions produce `poison` in the corresponding lanes. 
5. When these `poison` values are fed into the new division or remainder instruction—specifically into the divisor operand—it triggers immediate Undefined Behavior (UB). 

In the original IR, the division/remainder operations were executed before the shuffle, meaning the divisors were valid, and the `poison` only safely appeared in the final shuffled result. The transformation incorrectly introduces full UB by forcing the division/remainder operation to evaluate with a `poison` divisor.

## Example

### Original IR
```llvm
define <2 x i32> @test(<2 x i32> %a, <2 x i32> %b, <2 x i32> %c, <2 x i32> %d) {
  %div1 = sdiv <2 x i32> %a, %b
  %div2 = sdiv <2 x i32> %c, %d
  %shuf = shufflevector <2 x i32> %div1, <2 x i32> %div2, <2 x i32> <i32 0, i32 poison>
  ret <2 x i32> %shuf
}
```
### Optimized IR
```llvm
define <2 x i32> @test(<2 x i32> %a, <2 x i32> %b, <2 x i32> %c, <2 x i32> %d) {
  %shuf.a = shufflevector <2 x i32> %a, <2 x i32> %c, <2 x i32> <i32 0, i32 poison>
  %shuf.b = shufflevector <2 x i32> %b, <2 x i32> %d, <2 x i32> <i32 0, i32 poison>
  %shuf = sdiv <2 x i32> %shuf.a, %shuf.b
  ret <2 x i32> %shuf
}
```
