# Issue 105988

## Incorrect Minimum Bitwidth Analysis for Nodes Used by Comparison Instructions

**Description**:
The bug is triggered when the vectorizer performs minimum bitwidth analysis on a vectorized node (such as a gather node) whose results are used by comparison instructions. During this analysis, the vectorizer attempts to determine the minimum required bitwidth for the node's elements by examining the type sizes of its user instructions.

However, comparison instructions inherently produce a boolean result, meaning their output type size is always 1 bit, regardless of the size of the operands being compared. The vectorizer incorrectly considers this 1-bit result size as a valid constraint for the operands' bitwidth. This flaw causes the analysis to erroneously conclude that the operands can be truncated or evaluated at a much smaller bitwidth (e.g., 1 bit). Consequently, this leads to an invalid type reduction and a miscompilation where the comparison operations are performed on incorrectly truncated values.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @test_gather_cmp(ptr %a, ptr %b, ptr %res) {
entry:
  %a0 = load i32, ptr %a, align 4
  %a1_ptr = getelementptr inbounds i32, ptr %a, i64 2
  %a1 = load i32, ptr %a1_ptr, align 4

  %b0 = load i32, ptr %b, align 4
  %b1_ptr = getelementptr inbounds i32, ptr %b, i64 2
  %b1 = load i32, ptr %b1_ptr, align 4

  %cmp0 = icmp eq i32 %a0, %b0
  %cmp1 = icmp eq i32 %a1, %b1

  %res0 = zext i1 %cmp0 to i8
  %res1 = zext i1 %cmp1 to i8

  store i8 %res0, ptr %res, align 1
  %res1_ptr = getelementptr inbounds i8, ptr %res, i64 1
  store i8 %res1, ptr %res1_ptr, align 1

  ret void
}

```
### Optimized IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @test_gather_cmp(ptr %a, ptr %b, ptr %res) {
entry:
  %0 = load i32, ptr %a, align 4
  %a1_ptr = getelementptr inbounds i32, ptr %a, i64 2
  %1 = load i32, ptr %a1_ptr, align 4
  %2 = insertelement <2 x i32> poison, i32 %0, i32 0
  %3 = insertelement <2 x i32> %2, i32 %1, i32 1
  %4 = trunc <2 x i32> %3 to <2 x i1>

  %5 = load i32, ptr %b, align 4
  %b1_ptr = getelementptr inbounds i32, ptr %b, i64 2
  %6 = load i32, ptr %b1_ptr, align 4
  %7 = insertelement <2 x i32> poison, i32 %5, i32 0
  %8 = insertelement <2 x i32> %7, i32 %6, i32 1
  %9 = trunc <2 x i32> %8 to <2 x i1>

  %10 = icmp eq <2 x i1> %4, %9
  %11 = zext <2 x i1> %10 to <2 x i8>

  store <2 x i8> %11, ptr %res, align 1

  ret void
}

```

---

# Issue 113425

## Incorrect Replacement of `undef` with Potentially `poison` Values During Vectorization

**Description:**
The bug is triggered when the SLP vectorizer attempts to vectorize a sequence of scalar instructions (such as binary operations) where one or more operands are `undef`. To construct the vector operands efficiently and avoid additional shuffle or `insertelement` instructions, the vectorizer may choose to reuse an existing vector that perfectly matches the non-`undef` operands in their respective lanes.

For the lanes corresponding to the `undef` operands, the vectorizer implicitly substitutes them with the values present in the reused vector at those same lanes. The miscompilation occurs because the vectorizer fails to verify whether the substituted elements from the reused vector are guaranteed not to be `poison`.

If the reused vector contains `poison` (or can evaluate to `poison` at runtime) in those lanes, the transformation effectively replaces an `undef` value with a `poison` value. In LLVM IR semantics, `poison` is a stronger, more restrictive state than `undef`. For example, multiplying `undef` by zero can be optimized to yield zero, whereas multiplying `poison` by zero strictly yields `poison`. Consequently, this invalid substitution makes the resulting vectorized program more poisonous than the original scalar code, violating IR semantics and leading to incorrect execution results.

## Example

### Original IR
```llvm
define <2 x i32> @test(i32 %x) {
entry:
  %v = insertelement <2 x i32> poison, i32 %x, i32 0
  %v0 = extractelement <2 x i32> %v, i32 0
  %m0 = mul i32 %v0, 0
  %m1 = mul i32 undef, 0
  %r0 = insertelement <2 x i32> poison, i32 %m0, i32 0
  %r1 = insertelement <2 x i32> %r0, i32 %m1, i32 1
  ret <2 x i32> %r1
}
```
### Optimized IR
```llvm
define <2 x i32> @test(i32 %x) {
entry:
  %v = insertelement <2 x i32> poison, i32 %x, i32 0
  %0 = mul <2 x i32> %v, zeroinitializer
  ret <2 x i32> %0
}
```

---

# Issue 117170

## Incorrect Shuffle Mask Generation for Vectors of Different Sizes in SLP Vectorization

**Description**:
The bug is triggered when the SLP vectorizer attempts to vectorize a sequence of scalar operations (such as load-math-store chains) that require shuffling elements from multiple source vectors to form the vectorized operands. The issue arises when the source vectors being shuffled have sizes (vector factors) that differ from the size of the resulting shuffle mask.

During the generation of the shuffle mask, the vectorizer must adjust the indices for elements originating from the second source vector by adding an offset. However, the vectorizer incorrectly uses the size of the resulting mask as this offset, rather than the actual vector factor of the input vectors. Consequently, the generated `shufflevector` instruction contains incorrect mask indices. This causes the shuffle operation to extract the wrong elements—such as erroneously referencing elements from the first vector instead of the second, or picking elements from incorrect positions—ultimately leading to a miscompilation of the vectorized code.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @test(<4 x i32> %v1, <4 x i32> %v2, ptr %out) {
entry:
  %e1 = extractelement <4 x i32> %v1, i32 0
  %e2 = extractelement <4 x i32> %v2, i32 0
  %add1 = add i32 %e1, 1
  %add2 = add i32 %e2, 1
  store i32 %add1, ptr %out, align 4
  %out1 = getelementptr inbounds i32, ptr %out, i64 1
  store i32 %add2, ptr %out1, align 4
  ret void
}
```
### Optimized IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @test(<4 x i32> %v1, <4 x i32> %v2, ptr %out) {
entry:
  %0 = shufflevector <4 x i32> %v1, <4 x i32> %v2, <2 x i32> <i32 0, i32 2>
  %1 = add <2 x i32> %0, <i32 1, i32 1>
  store <2 x i32> %1, ptr %out, align 4
  ret void
}
```

---

# Issue 120823

## Incorrect Preservation of `samesign` Flag on `icmp` Instructions with Reduced Operand Bitwidths

**Description:**
The bug occurs when the compiler vectorizes integer comparison (`icmp`) instructions that possess the `samesign` flag, while simultaneously reducing the bitwidth of their operands.

1. **Initial State**: The original IR contains scalar `icmp` instructions with the `samesign` flag. This flag indicates an optimization assumption that both operands are known to have the same sign (either both non-negative or both negative) in their original bitwidth.
2. **Bitwidth Reduction**: During vectorization, the compiler's minimum bitwidth analysis determines that the operands of the comparisons can be safely represented using a narrower integer type (e.g., truncating from `i32` to `i1`).
3. **Incorrect Transformation**: The vectorizer generates the vectorized `icmp` instruction with the truncated operands but incorrectly propagates the `samesign` flag from the original scalar instructions.
4. **Consequence**: Truncating the operands can alter their sign bits in the context of the narrower type. For example, a positive value like `1` in `i32` becomes `-1` (negative) when truncated to `i1`, while `0` remains `0` (positive). This violates the `samesign` condition in the reduced bitwidth, causing the comparison to evaluate to `poison` and leading to a miscompilation.

To maintain correctness, the compiler must drop the `samesign` flag from the vectorized `icmp` instruction whenever the bitwidth of its operands is reduced.

## Example

### Original IR
```llvm
define void @test_samesign_bitwidth_reduction(ptr %a, ptr %b, ptr %dst) {
entry:
  %a0 = getelementptr i32, ptr %a, i64 0
  %l.a0 = load i32, ptr %a0, align 4
  %and.a0 = and i32 %l.a0, 1
  %b0 = getelementptr i32, ptr %b, i64 0
  %l.b0 = load i32, ptr %b0, align 4
  %and.b0 = and i32 %l.b0, 1
  %cmp0 = icmp samesign ult i32 %and.a0, %and.b0
  %dst0 = getelementptr i8, ptr %dst, i64 0
  %z0 = zext i1 %cmp0 to i8
  store i8 %z0, ptr %dst0, align 1

  %a1 = getelementptr i32, ptr %a, i64 1
  %l.a1 = load i32, ptr %a1, align 4
  %and.a1 = and i32 %l.a1, 1
  %b1 = getelementptr i32, ptr %b, i64 1
  %l.b1 = load i32, ptr %b1, align 4
  %and.b1 = and i32 %l.b1, 1
  %cmp1 = icmp samesign ult i32 %and.a1, %and.b1
  %dst1 = getelementptr i8, ptr %dst, i64 1
  %z1 = zext i1 %cmp1 to i8
  store i8 %z1, ptr %dst1, align 1

  %a2 = getelementptr i32, ptr %a, i64 2
  %l.a2 = load i32, ptr %a2, align 4
  %and.a2 = and i32 %l.a2, 1
  %b2 = getelementptr i32, ptr %b, i64 2
  %l.b2 = load i32, ptr %b2, align 4
  %and.b2 = and i32 %l.b2, 1
  %cmp2 = icmp samesign ult i32 %and.a2, %and.b2
  %dst2 = getelementptr i8, ptr %dst, i64 2
  %z2 = zext i1 %cmp2 to i8
  store i8 %z2, ptr %dst2, align 1

  %a3 = getelementptr i32, ptr %a, i64 3
  %l.a3 = load i32, ptr %a3, align 4
  %and.a3 = and i32 %l.a3, 1
  %b3 = getelementptr i32, ptr %b, i64 3
  %l.b3 = load i32, ptr %b3, align 4
  %and.b3 = and i32 %l.b3, 1
  %cmp3 = icmp samesign ult i32 %and.a3, %and.b3
  %dst3 = getelementptr i8, ptr %dst, i64 3
  %z3 = zext i1 %cmp3 to i8
  store i8 %z3, ptr %dst3, align 1

  ret void
}

```
### Optimized IR
```llvm
define void @test_samesign_bitwidth_reduction(ptr %a, ptr %b, ptr %dst) {
entry:
  %0 = load <4 x i32>, ptr %a, align 4
  %1 = trunc <4 x i32> %0 to <4 x i1>
  %2 = load <4 x i32>, ptr %b, align 4
  %3 = trunc <4 x i32> %2 to <4 x i1>
  %4 = icmp samesign ult <4 x i1> %1, %3
  %5 = zext <4 x i1> %4 to <4 x i8>
  store <4 x i8> %5, ptr %dst, align 1
  ret void
}

```

---

# Issue 122324

## Incorrect Shuffle Mask Composition for Reused Gathered Scalars in SLP Vectorization

**Description**:
The bug is triggered during the vectorization of scalar operations when the vectorizer gathers scalar values into a vector, and some of these scalar values are reused (i.e., the same scalar appears in multiple lanes of the gathered vector).

To correctly position these reused scalars, the vectorizer generates shuffle masks. When these masks are subsequently combined with other masks (for example, when extending or further rearranging the vector elements), the logic responsible for composing the masks fails to correctly map the indices of the reused scalars.

This incorrect mask composition results in the emission of a `shufflevector` instruction with a flawed mask. Consequently, incorrect values are placed into the vector lanes, leading to a miscompilation where the vectorized code produces different results compared to the original scalar code.

## Example

### Original IR
```llvm
define void @test(ptr %src, ptr %dst) {
entry:
  %a = load i16, ptr %src, align 2
  %src1 = getelementptr inbounds i16, ptr %src, i64 1
  %b = load i16, ptr %src1, align 2
  %src2 = getelementptr inbounds i16, ptr %src, i64 2
  %c = load i16, ptr %src2, align 2
  %src3 = getelementptr inbounds i16, ptr %src, i64 3
  %d = load i16, ptr %src3, align 2

  %e0 = zext i16 %a to i32
  %e1 = zext i16 %b to i32
  %e2 = zext i16 %c to i32
  %e3 = zext i16 %a to i32

  store i32 %e0, ptr %dst, align 4
  %dst1 = getelementptr inbounds i32, ptr %dst, i64 1
  store i32 %e1, ptr %dst1, align 4
  %dst2 = getelementptr inbounds i32, ptr %dst, i64 2
  store i32 %e2, ptr %dst2, align 4
  %dst3 = getelementptr inbounds i32, ptr %dst, i64 3
  store i32 %e3, ptr %dst3, align 4

  ret void
}
```
### Optimized IR
```llvm
define void @test(ptr %src, ptr %dst) {
entry:
  %0 = load <4 x i16>, ptr %src, align 2
  ; Flawed mask composition: should be <0, 1, 2, 0> to reuse '%a', but the bug emits <0, 1, 2, 3>
  %1 = shufflevector <4 x i16> %0, <4 x i16> poison, <4 x i32> <i32 0, i32 1, i32 2, i32 3>
  %2 = zext <4 x i16> %1 to <4 x i32>
  store <4 x i32> %2, ptr %dst, align 4
  ret void
}
```

---

# Issue 122430

## Incorrect Shuffle Mask Generation for Gather/BuildVector with Subregisters in SLP Vectorizer

**Description**:
The miscompilation is triggered when the SLP vectorizer attempts to optimize a gather or buildvector sequence where the scalar elements can be sourced from existing vector registers.

1. **Gather to Shuffle Optimization**: When building a vector from scalar elements, the vectorizer checks if these elements originate from already vectorized registers. If so, it tries to replace the costly gather operation with a more efficient `shufflevector` instruction.
2. **Subregister Cost Estimation**: If the source vector registers are larger than the vector being built (i.e., the operation involves extracting subregisters), the vectorizer generates a temporary submask. This submask adjusts the element indices (e.g., using modulo arithmetic) to accurately estimate the cost of extracting from the smaller subregister.
3. **Corrupted Mask Application**: The bug occurs because the vectorizer incorrectly takes this temporary, adjusted submask—which was strictly intended for cost estimation—and applies it as the actual mask for the final `shufflevector` instruction.
4. **Resulting Miscompilation**: Because the submask's indices were mathematically altered for the cost model, copying them directly into the IR produces a `shufflevector` instruction with corrupted indices. This causes the compiled code to extract and operate on the wrong vector elements, leading to a runtime value mismatch.

## Example

### Original IR
```llvm
define <2 x i32> @test(<4 x i32> %v1, <4 x i32> %v2) {
entry:
  %e1_0 = extractelement <4 x i32> %v1, i32 2
  %e1_1 = extractelement <4 x i32> %v1, i32 3
  %e2_0 = extractelement <4 x i32> %v2, i32 2
  %e2_1 = extractelement <4 x i32> %v2, i32 3
  %add0 = add i32 %e1_0, %e2_0
  %add1 = add i32 %e1_1, %e2_1
  %i0 = insertelement <2 x i32> poison, i32 %add0, i32 0
  %i1 = insertelement <2 x i32> %i0, i32 %add1, i32 1
  ret <2 x i32> %i1
}
```
### Optimized IR
```llvm
define <2 x i32> @test(<4 x i32> %v1, <4 x i32> %v2) {
entry:
  %0 = shufflevector <4 x i32> %v1, <4 x i32> poison, <2 x i32> <i32 0, i32 1>
  %1 = shufflevector <4 x i32> %v2, <4 x i32> poison, <2 x i32> <i32 0, i32 1>
  %2 = add <2 x i32> %0, %1
  ret <2 x i32> %2
}
```

---

# Issue 122583

## Incorrect Handling of Poison Lanes in Vectorized Extract Instructions

**Description**:
When the SLP vectorizer processes a bundle of extract instructions (such as `extractelement` or `extractvalue`), it may encounter lanes within the vectorization list that are represented as `poison` values (e.g., due to unused lanes or padding). During the operand gathering phase, if a lane is identified as `poison`, the vectorizer incorrectly assigned a `poison` value as the source operand (i.e., the underlying vector or aggregate being extracted from) for that specific lane.

Because the vectorization of extract instructions heavily relies on analyzing their source operands to generate correct shuffle masks or vector combinations, replacing the source operand with `poison` disrupts this logic. It prevents the vectorizer from correctly identifying and matching the common source vector or aggregate across all lanes. Consequently, this leads to malformed vector transformations, such as generating incorrect shuffle masks or improperly propagating `poison` values into the final vectorized instructions. This ultimately causes miscompilations where the compiled program evaluates to a `poison` or undefined result.

To ensure correct vectorization, the source operand for these `poison` lanes should be set to match the source operand of the primary extract instruction in the bundle, maintaining consistency and allowing the vectorizer to generate the correct extraction or shuffle logic.

## Example

### Original IR
```llvm
define <4 x i32> @test(<4 x i32> %v1, <4 x i32> %v2) {
entry:
  %e0 = extractelement <4 x i32> %v1, i32 0
  %e1 = extractelement <4 x i32> %v1, i32 1
  %e3 = extractelement <4 x i32> %v1, i32 3
  %f0 = extractelement <4 x i32> %v2, i32 0
  %f1 = extractelement <4 x i32> %v2, i32 1
  %f3 = extractelement <4 x i32> %v2, i32 3
  %add0 = add i32 %e0, %f0
  %add1 = add i32 %e1, %f1
  %add3 = add i32 %e3, %f3
  %i0 = insertelement <4 x i32> poison, i32 %add0, i32 0
  %i1 = insertelement <4 x i32> %i0, i32 %add1, i32 1
  %i2 = insertelement <4 x i32> %i1, i32 poison, i32 2
  %i3 = insertelement <4 x i32> %i2, i32 %add3, i32 3
  ret <4 x i32> %i3
}
```
### Optimized IR
```llvm
define <4 x i32> @test(<4 x i32> %v1, <4 x i32> %v2) {
entry:
  %0 = shufflevector <4 x i32> poison, <4 x i32> poison, <4 x i32> <i32 0, i32 1, i32 poison, i32 3>
  %1 = shufflevector <4 x i32> %v2, <4 x i32> poison, <4 x i32> <i32 0, i32 1, i32 poison, i32 3>
  %2 = add <4 x i32> %0, %1
  ret <4 x i32> %2
}
```

---

# Issue 123639

## Incorrect Shuffle Mask Generation for BuildVector with Mixed-Length Input Vectors

**Description**
The bug is triggered when the SLP Vectorizer attempts to optimize a gather or buildvector operation that combines elements from multiple existing vector values.

1. **Triggering Pattern**: The code contains a sequence of operations (such as a loop with cross-iteration dependencies or repeated scalar patterns) that the SLP vectorizer attempts to group into a gather or buildvector operation. This operation reuses elements from multiple source vectors, and crucially, these source vectors have varying lengths (vector factors).
2. **Incorrect Transformation Logic**: To optimize the gather operation, the vectorizer generates a `shufflevector` instruction to combine the elements from the source vectors. When constructing the combined shuffle mask, the vectorizer calculates the index offsets for elements of subsequent source vectors based solely on the length of the *first* source vector, rather than the maximum length across all input vectors.
3. **Resulting Miscompilation**: If the first source vector has a smaller length than the other input vectors, the calculated index offsets are incorrect. This results in a `shufflevector` instruction with an invalid mask that extracts the wrong elements from the source vectors, ultimately leading to incorrect runtime computations. Additionally, instability in detecting reused entries can cause mismatches between cost estimation and actual code generation.

## Example

### Original IR
```llvm
define <4 x i32> @test(<2 x i32> %v1, <4 x i32> %v2) {
entry:
  %e0 = extractelement <2 x i32> %v1, i32 0
  %e1 = extractelement <2 x i32> %v1, i32 1
  %e2 = extractelement <4 x i32> %v2, i32 2
  %e3 = extractelement <4 x i32> %v2, i32 3
  %i0 = insertelement <4 x i32> poison, i32 %e0, i32 0
  %i1 = insertelement <4 x i32> %i0, i32 %e1, i32 1
  %i2 = insertelement <4 x i32> %i1, i32 %e2, i32 2
  %i3 = insertelement <4 x i32> %i2, i32 %e3, i32 3
  ret <4 x i32> %i3
}
```
### Optimized IR
```llvm
define <4 x i32> @test(<2 x i32> %v1, <4 x i32> %v2) {
entry:
  %0 = shufflevector <2 x i32> %v1, <2 x i32> poison, <4 x i32> <i32 0, i32 1, i32 poison, i32 poison>
  %1 = shufflevector <4 x i32> %0, <4 x i32> %v2, <4 x i32> <i32 0, i32 1, i32 4, i32 5>
  ret <4 x i32> %1
}
```

---

# Issue 125259

## Incorrect Slice Size Calculation for Gathered Scalars in SLP Vectorization

**Description:**
The bug is triggered during Superword-Level Parallelism (SLP) vectorization when the compiler attempts to construct a vector from a collection of independent scalar values (often referred to as a gather or build-vector operation).

During this process, the vectorizer divides the elements into parts or slices to generate the appropriate vector shuffle instructions. However, the logic incorrectly calculates the size of these slices based on the *original* number of scalar elements in the vectorization tree entry, rather than the *actual* number of gathered scalars. The number of gathered scalars can differ from the original count if elements are modified, deduplicated, or optimized away while building the vector shuffles.

Because of this size mismatch, the compiler generates incorrect shuffle masks. This causes the resulting vector to be incorrectly sized or aligned, leaving portions of the vector unintentionally populated with `poison` values. When these partially poisoned vectors are subsequently used in downstream operations—such as comparisons, extensions, or memory stores—it results in undefined behavior and a miscompilation of the program.

To trigger this issue at the LLVM IR level, the code must contain a pattern of scalar operations that the SLP vectorizer decides to group into a gather/build-vector sequence, specifically under conditions where the final number of gathered scalars diverges from the initial scalar count considered by the vectorization tree.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @test_slice_size(ptr %out, i32 %x, i32 %y) {
entry:
  %add.x = add i32 %x, 1
  %add.y = add i32 %y, 2

  %arrayidx0 = getelementptr inbounds i32, ptr %out, i64 0
  store i32 %add.x, ptr %arrayidx0, align 4

  %arrayidx1 = getelementptr inbounds i32, ptr %out, i64 1
  store i32 %add.y, ptr %arrayidx1, align 4

  %arrayidx2 = getelementptr inbounds i32, ptr %out, i64 2
  store i32 %add.x, ptr %arrayidx2, align 4

  %arrayidx3 = getelementptr inbounds i32, ptr %out, i64 3
  store i32 %add.y, ptr %arrayidx3, align 4

  ret void
}

```
### Optimized IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @test_slice_size(ptr %out, i32 %x, i32 %y) {
entry:
  %add.x = add i32 %x, 1
  %add.y = add i32 %y, 2

  %0 = insertelement <2 x i32> poison, i32 %add.x, i32 0
  %1 = insertelement <2 x i32> %0, i32 %add.y, i32 1

  ; The bug: Incorrect slice size calculation leads to a shuffle mask that fails to
  ; duplicate the gathered scalars, leaving the upper half of the vector as poison.
  %2 = shufflevector <2 x i32> %1, <2 x i32> poison, <4 x i32> <i32 0, i32 1, i32 poison, i32 poison>

  store <4 x i32> %2, ptr %out, align 4
  ret void
}

```

---

# Issue 129057

## Incorrect Truncation of Multi-Use Scalars During Vectorization Demotion

**Description:**
The bug occurs during vectorization when the compiler attempts to optimize the vector tree by demoting (truncating) values to a narrower bitwidth. The triggering pattern involves the following sequence:

1. A scalar value within the operations targeted for vectorization has multiple uses.
2. The vectorizer analyzes the value and decides to truncate it to a narrower bitwidth to optimize the vectorized operations.
3. However, the compiler fails to verify if this truncation is safe for *all* uses of the scalar. While the use within the immediate vectorized chain might tolerate the narrower bitwidth, another use of the same scalar requires the original, wider bitwidth (e.g., an arithmetic operation or a comparison against a large constant that exceeds the capacity of the narrower type).
4. Because the safety check for multi-use scalars is missing, the value is prematurely truncated, leading to the irreversible loss of significant upper bits.
5. When the truncated value is later extended back to its original width to satisfy the other uses, the lost bits alter the semantics of the program (such as flipping the result of a comparison), ultimately causing a miscompilation.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define i32 @test_demote_multi_use(i32 %x, i32 %y, ptr %p) {
entry:
  %add1 = add i32 %x, 100000
  %add2 = add i32 %y, 100000
  %trunc1 = trunc i32 %add1 to i16
  %trunc2 = trunc i32 %add2 to i16
  store i16 %trunc1, ptr %p, align 2
  %p2 = getelementptr inbounds i16, ptr %p, i64 1
  store i16 %trunc2, ptr %p2, align 2
  %cmp = icmp ugt i32 %add1, 65535
  %res = zext i1 %cmp to i32
  ret i32 %res
}

```
### Optimized IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define i32 @test_demote_multi_use(i32 %x, i32 %y, ptr %p) {
entry:
  %0 = insertelement <2 x i32> poison, i32 %x, i32 0
  %1 = insertelement <2 x i32> %0, i32 %y, i32 1
  %2 = trunc <2 x i32> %1 to <2 x i16>
  %3 = add <2 x i16> %2, <i16 -31072, i16 -31072>
  store <2 x i16> %3, ptr %p, align 2
  %4 = extractelement <2 x i16> %3, i32 0
  %5 = zext i16 %4 to i32
  %cmp = icmp ugt i32 %5, 65535
  %res = zext i1 %cmp to i32
  ret i32 %res
}

```

---

# Issue 135113

## Incorrect Reuse of Splat Shufflevector with Poison Mask Elements

**Description**:
The bug is triggered by a flaw in how the SLP vectorizer reuses existing vector instructions when broadcasting (splatting) a scalar value across a vector. The strategy to trigger this issue involves the following sequence:

1. **Splat Requirement**: The compiler attempts to vectorize a sequence of operations that share a common scalar operand, which requires creating a vector by splatting (broadcasting) this scalar into multiple lanes.
2. **Instruction Reuse**: To optimize the generated code, the vectorizer searches for existing `shufflevector` instructions in the program that already perform the same zero-element splat operation.
3. **Mismatched Poison Lanes**: The compiler finds an existing splat `shufflevector`, but its shuffle mask contains `poison` (or undefined) elements in certain lanes. Meanwhile, the newly requested splat operation demands valid, well-defined values in some of those exact same lanes.
4. **Flawed Matching Logic**: The vectorizer's matching logic incorrectly identifies the existing `shufflevector` as a perfect substitute because both are broadly classified as "zero-element splats." It fails to check if the existing instruction's mask is at least as defined as the requested mask.
5. **Poison Propagation**: By reusing the existing, less-defined `shufflevector`, `poison` values are inadvertently injected into lanes that strictly require valid data.
6. **Miscompilation**: These `poison` values propagate through subsequent vectorized operations (such as a horizontal vector reduction), ultimately corrupting the final result and causing the program to return `poison` or exhibit undefined behavior.

## Example

### Original IR
```llvm
define i32 @test(i32 %val, <2 x i32> %x, ptr %p) {
entry:
  %ins = insertelement <2 x i32> poison, i32 %val, i32 0
  %shuf1 = shufflevector <2 x i32> %ins, <2 x i32> poison, <2 x i32> <i32 0, i32 poison>
  store <2 x i32> %shuf1, ptr %p

  %x0 = extractelement <2 x i32> %x, i32 0
  %x1 = extractelement <2 x i32> %x, i32 1

  %add0 = add i32 %val, %x0
  %add1 = add i32 %val, %x1

  %red = add i32 %add0, %add1

  ret i32 %red
}
```
### Optimized IR
```llvm
declare i32 @llvm.vector.reduce.add.v2i32(<2 x i32>)

define i32 @test(i32 %val, <2 x i32> %x, ptr %p) {
entry:
  %ins = insertelement <2 x i32> poison, i32 %val, i32 0
  %shuf1 = shufflevector <2 x i32> %ins, <2 x i32> poison, <2 x i32> <i32 0, i32 poison>
  store <2 x i32> %shuf1, ptr %p

  %0 = add <2 x i32> %shuf1, %x
  %red = call i32 @llvm.vector.reduce.add.v2i32(<2 x i32> %0)

  ret i32 %red
}
```

---

# Issue 138923

## Incorrect Vectorization of Strided Loads Requiring Reordering

**Description**:
The bug is triggered when the vectorizer attempts to vectorize a sequence of strided, unmasked memory loads that require reordering.

When the order of the scalar loads in the source code does not match their sequential memory addresses, the vectorizer must reorder the elements to form the correct vector. However, the transformation logic incorrectly attempts to optimize these accesses by generating a widened or interleaved load sequence without properly accounting for the required reordering. This results in a load and shuffle sequence that fails to place the loaded values into the correct vector lanes, leading to a miscompilation.

Furthermore, the vectorizer may widen the load to cover the entire strided memory range without verifying if it is safe to unconditionally load from the extended addresses. This can potentially lead to unsafe memory accesses if the widened load reads past valid memory boundaries.

## Example

### Original IR
```llvm
define <4 x i32> @test_strided_reorder(ptr %p) {
entry:
  %p0 = getelementptr inbounds i32, ptr %p, i64 0
  %p1 = getelementptr inbounds i32, ptr %p, i64 2
  %p2 = getelementptr inbounds i32, ptr %p, i64 4
  %p3 = getelementptr inbounds i32, ptr %p, i64 6

  ; Out of order scalar loads
  %v1 = load i32, ptr %p1, align 4
  %v0 = load i32, ptr %p0, align 4
  %v3 = load i32, ptr %p3, align 4
  %v2 = load i32, ptr %p2, align 4

  ; Insert into vector in sequential lane order
  %i0 = insertelement <4 x i32> poison, i32 %v1, i32 0
  %i1 = insertelement <4 x i32> %i0, i32 %v0, i32 1
  %i2 = insertelement <4 x i32> %i1, i32 %v3, i32 2
  %i3 = insertelement <4 x i32> %i2, i32 %v2, i32 3

  ret <4 x i32> %i3
}
```
### Optimized IR
```llvm
define <4 x i32> @test_strided_reorder(ptr %p) {
entry:
  ; Widened load covering the entire strided range (potentially unsafe)
  %0 = load <8 x i32>, ptr %p, align 4
  ; Incorrect shuffle mask that fails to account for the required reordering
  ; Correct mask should be <i32 2, i32 0, i32 6, i32 4>
  %1 = shufflevector <8 x i32> %0, <8 x i32> poison, <4 x i32> <i32 0, i32 2, i32 4, i32 6>
  ret <4 x i32> %1
}
```

---

# Issue 139202

## Incorrect Vectorization due to 32-bit Truncation of 64-bit Pointer Offsets

**Description**:
The bug is triggered by a sequence of memory operations (such as loads or stores) that access memory using large offsets from a common base pointer. These offsets are large enough to require a 64-bit representation, exceeding the capacity of a standard 32-bit integer.

To trigger the miscompilation, the offsets are constructed such that their lower 32 bits form a contiguous sequence of memory addresses, spaced exactly by the size of the accessed elements (e.g., 0, 8, 16, 24 for 8-byte elements). However, the upper 32 bits of some offsets are non-zero, meaning the actual memory locations are widely separated and strictly non-contiguous.

When the compiler's vectorization analysis calculates the distances between these pointers to check for consecutive accesses, it incorrectly truncates the 64-bit pointer differences into 32-bit integers. Because of this truncation, the large, non-contiguous offsets are masked, and the compiler only sees the contiguous lower 32 bits. Deceived into believing that the memory accesses are strictly adjacent, the compiler erroneously combines the separate scalar memory operations into a single vector memory operation (e.g., a contiguous vector load or store). This results in a miscompilation where data is read from or written to incorrect memory locations.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @test_vectorize_truncation_bug(ptr %base, <4 x i64> %val) {
entry:
  ; Offsets: 0, 8, 4294967312 (0x100000010), 4294967320 (0x100000018)
  ; Lower 32 bits are 0, 8, 16, 24 (contiguous for 8-byte elements)
  %ptr0 = getelementptr i8, ptr %base, i64 0
  %ptr1 = getelementptr i8, ptr %base, i64 8
  %ptr2 = getelementptr i8, ptr %base, i64 4294967312
  %ptr3 = getelementptr i8, ptr %base, i64 4294967320

  %v0 = extractelement <4 x i64> %val, i32 0
  %v1 = extractelement <4 x i64> %val, i32 1
  %v2 = extractelement <4 x i64> %val, i32 2
  %v3 = extractelement <4 x i64> %val, i32 3

  store i64 %v0, ptr %ptr0, align 8
  store i64 %v1, ptr %ptr1, align 8
  store i64 %v2, ptr %ptr2, align 8
  store i64 %v3, ptr %ptr3, align 8

  ret void
}

```
### Optimized IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @test_vectorize_truncation_bug(ptr %base, <4 x i64> %val) {
entry:
  %ptr0 = getelementptr i8, ptr %base, i64 0
  ; The compiler incorrectly assumes the pointers are contiguous due to 32-bit truncation
  ; of the pointer differences, erroneously combining the scalar stores into a vector store.
  store <4 x i64> %val, ptr %ptr0, align 8
  ret void
}

```

---

# Issue 165878

## Incorrect Type Demotion in Alternate Opcode Vectorization Involving Bitwidth-Sensitive Operations

**Description**:
The bug is triggered when the vectorizer groups two different operations into an alternate opcode vectorization sequence (e.g., a multiplication and a logical shift) and attempts to demote their types based on minimum bitwidth analysis.

If the operations operate on a wider integer type but their inputs are extended from a narrower type, the vectorizer may decide to shrink the bitwidth of the vectorized operations to optimize the code. However, if the alternate operation is bitwidth-sensitive (such as a shift, division, or remainder) and uses an operand that is only valid for the wider type (e.g., a constant shift amount that is greater than or equal to the narrower bitwidth), the demotion becomes unsafe.

The vectorizer incorrectly relies on the analysis of the main operation and applies the type demotion to both operations. This results in the bitwidth-sensitive operation becoming invalid in the narrower type (e.g., producing poison or undefined behavior due to an out-of-bounds shift amount), ultimately leading to a miscompilation.

To trigger this issue, one must construct a pattern where a bitwidth-sensitive operation and a regular operation are vectorized together as alternate opcodes, with inputs that encourage type demotion, and an operand in the sensitive operation that exceeds the bounds of the newly demoted type.

## Example

### Original IR
```llvm
define <2 x i8> @test(<2 x i8> %x) {
entry:
  %0 = extractelement <2 x i8> %x, i32 0
  %1 = zext i8 %0 to i32
  %2 = mul i32 %1, 5
  %3 = trunc i32 %2 to i8
  %4 = extractelement <2 x i8> %x, i32 1
  %5 = zext i8 %4 to i32
  %6 = shl i32 %5, 8
  %7 = trunc i32 %6 to i8
  %8 = insertelement <2 x i8> poison, i8 %3, i32 0
  %9 = insertelement <2 x i8> %8, i8 %7, i32 1
  ret <2 x i8> %9
}
```
### Optimized IR
```llvm
define <2 x i8> @test(<2 x i8> %x) {
entry:
  %0 = mul <2 x i8> %x, <i8 5, i8 8>
  %1 = shl <2 x i8> %x, <i8 5, i8 8>
  %2 = shufflevector <2 x i8> %0, <2 x i8> %1, <2 x i32> <i32 0, i32 3>
  ret <2 x i8> %2
}
```

---

# Issue 173784

## Vectorization of Short-Circuiting Boolean Logic into Eager Reductions Introducing Poison

**Description**:
The bug is triggered when a chain of scalar boolean logical operations (such as logical OR or AND, often represented by `select` instructions) is vectorized into a horizontal vector reduction.

In the original scalar IR, these operations exhibit short-circuiting behavior: if the final result can be determined by the first operand (e.g., a `true` in a logical OR chain), the subsequent operands are not evaluated. This short-circuiting is crucial for correctness when the unevaluated operands might be `poison` or `undef`, as it prevents the undefined behavior from affecting the final result.

During vectorization, the compiler groups these scalar operands into a vector and replaces the logical chain with a vector reduction intrinsic (e.g., `llvm.vector.reduce.or`). However, unlike scalar short-circuiting logic, vector reductions evaluate all lanes eagerly. If any of the vector lanes contain a `poison` value that would have been safely bypassed in the scalar version, the eager evaluation of the reduction observes it and propagates the `poison` to the final result.

This transformation breaks the original semantics by introducing `poison` into the program in cases where the scalar code would have safely produced a well-defined value, leading to a miscompilation.

## Example

### Original IR
```llvm
define i1 @test(<4 x i1> %v) {
entry:
  %e0 = extractelement <4 x i1> %v, i32 0
  %e1 = extractelement <4 x i1> %v, i32 1
  %s1 = select i1 %e0, i1 true, i1 %e1
  %e2 = extractelement <4 x i1> %v, i32 2
  %s2 = select i1 %s1, i1 true, i1 %e2
  %e3 = extractelement <4 x i1> %v, i32 3
  %s3 = select i1 %s2, i1 true, i1 %e3
  ret i1 %s3
}
```
### Optimized IR
```llvm
declare i1 @llvm.vector.reduce.or.v4i1(<4 x i1>)

define i1 @test(<4 x i1> %v) {
entry:
  %0 = call i1 @llvm.vector.reduce.or.v4i1(<4 x i1> %v)
  ret i1 %0
}
```

---

# Issue 173796

## Miscompilation in Boolean Reduction Trees with Mixed-Position Poison Operands

**Description**:
The bug is triggered when an optimization pass processes boolean reduction chains (such as logical AND/OR operations represented by `select` instructions) that contain a shared, potentially poison value used in mixed positions within the same reduction tree.

Specifically, the pattern involves an intermediate value that is used in two different roles:
1. **As a first operand (e.g., a condition)**: In this position, the operand is poison-propagating.
2. **As a second operand (e.g., a value)**: In this position, the operand's poison state can be semantically suppressed by short-circuiting logic (e.g., if the condition evaluates to a dominating constant that skips the evaluation of the second operand).

The optimization logic incorrectly classifies this shared intermediate value as strictly poison-propagating based solely on its use as a first operand. It fails to account for the fact that the value is also used as a second operand where its poison could be suppressed.

Because of this incomplete classification, the pass performs unsafe transformations—such as incorrectly reordering operands or omitting necessary `freeze` instructions. This breaks the original short-circuiting semantics of the scalar IR, allowing poison to incorrectly propagate to the final result when it should have been suppressed.

## Example

### Original IR
```llvm
define i1 @test(i1 %c1, i1 %v, i1 %c2) {
entry:
  %and1 = select i1 %c1, i1 %v, i1 false
  %and2 = select i1 %v, i1 %c2, i1 false
  %res = select i1 %and1, i1 %and2, i1 false
  ret i1 %res
}
```
### Optimized IR
```llvm
define i1 @test(i1 %c1, i1 %v, i1 %c2) {
entry:
  %0 = and i1 %c1, %v
  %res = and i1 %0, %c2
  ret i1 %res
}
```

---

# Issue 174041

## Incorrect Vectorization of Interchangeable Identity Operations

**Description**:
The bug is triggered by presenting the vectorizer with a sequence of different scalar binary operations that each act as an identity operation due to their specific constant operands (for example, a bitwise XOR with zero and a bitwise AND with all-ones). The vectorizer incorrectly identifies these distinct operations as interchangeable and attempts to combine them into a single vector instruction.

To achieve this, it selects one of the opcodes (e.g., the AND operation) and applies it across a mixed vector of the original constants. However, the chosen opcode may not maintain its identity semantics when paired with the constant from the other operation (for instance, applying an AND operation with a zero constant evaluates to zero, rather than preserving the original value). This invalid unification alters the semantics of the original scalar operations, leading to a miscompilation where specific vector lanes are incorrectly computed instead of retaining their original values.

## Example

### Original IR
```llvm
define <2 x i32> @test(<2 x i32> %v) {
entry:
  %v0 = extractelement <2 x i32> %v, i32 0
  %v1 = extractelement <2 x i32> %v, i32 1
  %op0 = xor i32 %v0, 0
  %op1 = and i32 %v1, -1
  %r0 = insertelement <2 x i32> poison, i32 %op0, i32 0
  %r1 = insertelement <2 x i32> %r0, i32 %op1, i32 1
  ret <2 x i32> %r1
}
```
### Optimized IR
```llvm
define <2 x i32> @test(<2 x i32> %v) {
entry:
  %0 = and <2 x i32> %v, <i32 0, i32 -1>
  ret <2 x i32> %0
}
```

---

# Issue 75437

## Incorrect Handling of Dynamic Indices in Vector Element Tracking

**Description**:
The bug is triggered when a vector is modified using an insertion operation with a non-constant (dynamic) index, whose exact position is unknown at compile time.

When the vectorizer attempts to parallelize operations involving this vector, it analyzes the chain of insertion instructions to determine which elements of the resulting vector are undefined or poison. This information is used to optimize the merging of the original vector with newly vectorized elements (e.g., using shuffle operations).

However, when the vectorizer encounters an insertion with a dynamic index, it simply ignores it instead of conservatively assuming that the insertion could affect any element in the vector. As a result, the vectorizer incorrectly marks elements as undefined. This flawed analysis leads the vectorizer to discard the dynamically inserted elements during the transformation, completely removing the insertion operation and resulting in a miscompilation.

## Example

### Original IR
```llvm
define <4 x i32> @test(i32 %val, i32 %idx, i32 %a, i32 %b) {
entry:
  %v1 = insertelement <4 x i32> poison, i32 %val, i32 %idx
  %v2 = insertelement <4 x i32> %v1, i32 %a, i32 0
  %v3 = insertelement <4 x i32> %v2, i32 %b, i32 1
  ret <4 x i32> %v3
}
```
### Optimized IR
```llvm
define <4 x i32> @test(i32 %val, i32 %idx, i32 %a, i32 %b) {
entry:
  %0 = insertelement <2 x i32> poison, i32 %a, i32 0
  %1 = insertelement <2 x i32> %0, i32 %b, i32 1
  %2 = shufflevector <2 x i32> %1, <2 x i32> poison, <4 x i32> <i32 0, i32 1, i32 poison, i32 poison>
  ret <4 x i32> %2
}
```
