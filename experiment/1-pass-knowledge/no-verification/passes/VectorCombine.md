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

---

# Issue 115575

## Scalarization of Vector Operations with Out-of-Bounds Insertion Indices

**Description**:
The bug occurs when the compiler attempts to scalarize a vector binary operation or comparison where one of the operands is an `insertelement` instruction using an out-of-bounds index.

When an insertion index is greater than or equal to the number of elements in the vector, the `insertelement` instruction evaluates to `poison`. In the original IR, the subsequent vector operation simply takes this `poison` vector and propagates it, resulting in a `poison` value without causing Undefined Behavior (UB).

However, during the scalarization transformation, the compiler attempts to fold the operation by extracting the corresponding element from the other operand (such as a constant vector) using the same out-of-bounds index. This out-of-bounds extraction yields a `poison` value. The compiler then constructs a scalar version of the binary operation using the originally inserted scalar and the extracted `poison` value.

For certain operations, such as integer division (`sdiv`, `udiv`) or remainder (`srem`, `urem`), having `poison` as an operand (e.g., as the divisor) triggers immediate Undefined Behavior. Consequently, the transformation incorrectly elevates a safe `poison` result into UB, leading to a miscompilation where the optimized code is less defined than the original code.

---

# Issue 158197

## Endian-Unaware Vector-to-Scalar Packing and Extraction

**Description**:
The bug is triggered by a transformation that attempts to optimize vector element extractions by packing an entire vector into a single, large scalar integer. Once packed, the optimization replaces the original vector extraction instructions with scalar bitwise operations, specifically logical right shifts and bitwise AND masks, to isolate the desired vector lane.

The vulnerability lies in the calculation of the shift amount used to locate the specific element within the packed integer. The transformation hardcodes a little-endian assumption, calculating the bit offset simply as the element index multiplied by the element size (i.e., assuming the element at index 0 resides in the least significant bits).

On big-endian targets, the memory layout dictates that the first vector element occupies the most significant bits of the packed integer. Because the transformation fails to query the target's data layout to adjust the bit offset accordingly, it shifts by the wrong amount and extracts incorrect bits. To trigger this issue, the input LLVM IR must contain vector extraction operations that the compiler attempts to scalarize into bitwise arithmetic while compiling for a target with a big-endian data layout.

---

# Issue 67060

## Scalarization of Memory Operations on Vectors with Non-Byte-Sized Elements

**Description:**
The bug is triggered by a sequence of instructions that modify or extract a single element of a vector in memory (e.g., loading a vector, inserting or extracting an element, and then storing or using the result).

Specifically, the issue occurs when the vector type has a total size that is a multiple of bytes (i.e., it is byte-sized), but its individual scalar elements are not byte-sized (such as a vector of `i1` elements, like `<32 x i1>`).

The optimization pass attempts to simplify the operation by scalarizing it—replacing the full vector memory access with a direct scalar memory access (load or store) to the specific element. However, the transformation logic incorrectly verifies the byte-size property against the entire vector type rather than the scalar element type. Since the whole vector is byte-sized, the check passes, and the pass emits a scalar memory operation for the non-byte-sized element.

When this scalar memory operation is later lowered by the backend, it is expanded to a full byte-sized memory access. For a store, this results in writing a full byte, which incorrectly clobbers adjacent bits belonging to other vector elements.

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
