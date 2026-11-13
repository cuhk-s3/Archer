# Issue 105988

## Incorrect Minimum Bitwidth Analysis for Nodes Used by Comparison Instructions

**Description**:
The bug is triggered when the vectorizer performs minimum bitwidth analysis on a vectorized node (such as a gather node) whose results are used by comparison instructions. During this analysis, the vectorizer attempts to determine the minimum required bitwidth for the node's elements by examining the type sizes of its user instructions.

However, comparison instructions inherently produce a boolean result, meaning their output type size is always 1 bit, regardless of the size of the operands being compared. The vectorizer incorrectly considers this 1-bit result size as a valid constraint for the operands' bitwidth. This flaw causes the analysis to erroneously conclude that the operands can be truncated or evaluated at a much smaller bitwidth (e.g., 1 bit). Consequently, this leads to an invalid type reduction and a miscompilation where the comparison operations are performed on incorrectly truncated values.

---

# Issue 106909

## Vectorization of Strict Floating-Point Operations on Targets with Unsafe Vector FP Semantics

**Description**:
The bug is triggered when the SLP vectorizer processes a sequence of isomorphic scalar floating-point instructions (such as binary operations or function calls) that are candidates for vectorization. These instructions lack fast-math flags, indicating that they require strict adherence to IEEE floating-point semantics (e.g., proper handling of denormalized numbers).

On certain target architectures, vector floating-point instructions are not fully IEEE compliant and may exhibit unsafe behaviors, such as implicit denormal flushing. The incorrect transformation occurs because the vectorizer fails to query the target-specific safety constraints regarding floating-point vectorization. Consequently, it incorrectly groups the strict scalar floating-point operations into vector instructions. This leads to a miscompilation where the generated vector code violates the strict IEEE semantics required by the original scalar instructions.

---

# Issue 113425

## Incorrect Replacement of `undef` with Potentially `poison` Values During Vectorization

**Description:**
The bug is triggered when the SLP vectorizer attempts to vectorize a sequence of scalar instructions (such as binary operations) where one or more operands are `undef`. To construct the vector operands efficiently and avoid additional shuffle or `insertelement` instructions, the vectorizer may choose to reuse an existing vector that perfectly matches the non-`undef` operands in their respective lanes.

For the lanes corresponding to the `undef` operands, the vectorizer implicitly substitutes them with the values present in the reused vector at those same lanes. The miscompilation occurs because the vectorizer fails to verify whether the substituted elements from the reused vector are guaranteed not to be `poison`.

If the reused vector contains `poison` (or can evaluate to `poison` at runtime) in those lanes, the transformation effectively replaces an `undef` value with a `poison` value. In LLVM IR semantics, `poison` is a stronger, more restrictive state than `undef`. For example, multiplying `undef` by zero can be optimized to yield zero, whereas multiplying `poison` by zero strictly yields `poison`. Consequently, this invalid substitution makes the resulting vectorized program more poisonous than the original scalar code, violating IR semantics and leading to incorrect execution results.

---

# Issue 113810

## Redundant Vector Node Creation for Subset of Previously Vectorized Scalars

**Description**:
During SLP vectorization, the compiler builds a tree of vector operations by grouping scalar instructions. When evaluating a new list of scalars to vectorize, it checks for overlaps with already existing vector nodes to avoid redundant work and maintain correct dependencies.

The bug is triggered when the current list of scalars being considered for vectorization is a subset of the scalars already vectorized in an existing node. The overlap detection logic was incomplete: it only identified an overlap if the existing node's scalars were fully contained within the new list, but failed to recognize when the new list was fully contained within the existing node.

Because of this missing check, the vectorizer incorrectly creates a new, separate vector node for the subset of scalars instead of reusing the existing node or gathering the values from it. This redundant vector node creation disrupts the instruction scheduling and dependency tracking, ultimately causing the compiler to emit vector instructions that do not dominate all of their uses, leading to invalid LLVM IR and a compilation crash.

---

# Issue 114738

## Vectorization of Short-Circuiting Boolean Reductions Leaking Poison

**Description:**
The bug is triggered when a sequence of scalar operations that implement short-circuiting boolean logic (such as `select` instructions used for logical AND/OR) is vectorized into a vector reduction operation (e.g., `reduce_or` or `reduce_and`).

In the original scalar IR, the short-circuiting behavior ensures that certain operands are not evaluated if the result is already determined by earlier operands. This safely masks potential `poison` values. However, when transformed into a vector reduction, all lanes are evaluated unconditionally. If any lane contains `poison`, it propagates through the reduction, causing the final result to become `poison` (making the target more poisonous than the source).

The miscompilation happens because the vectorizer fails to freeze the vectorized reduction operand to prevent this `poison` leakage. The logic for inserting the `freeze` instruction was overly restrictive, only triggering when the root instruction of the reduction was strictly classified as a boolean logic operation or under specific operand-tracking conditions. This caused the compiler to miss cases where short-circuiting boolean logic was present elsewhere in the reduction tree, leading to incorrect transformations.

---

# Issue 117170

## Incorrect Shuffle Mask Generation for Vectors of Different Sizes in SLP Vectorization

**Description**:
The bug is triggered when the SLP vectorizer attempts to vectorize a sequence of scalar operations (such as load-math-store chains) that require shuffling elements from multiple source vectors to form the vectorized operands. The issue arises when the source vectors being shuffled have sizes (vector factors) that differ from the size of the resulting shuffle mask.

During the generation of the shuffle mask, the vectorizer must adjust the indices for elements originating from the second source vector by adding an offset. However, the vectorizer incorrectly uses the size of the resulting mask as this offset, rather than the actual vector factor of the input vectors. Consequently, the generated `shufflevector` instruction contains incorrect mask indices. This causes the shuffle operation to extract the wrong elements—such as erroneously referencing elements from the first vector instead of the second, or picking elements from incorrect positions—ultimately leading to a miscompilation of the vectorized code.

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

---

# Issue 122324

## Incorrect Shuffle Mask Composition for Reused Gathered Scalars in SLP Vectorization

**Description**:
The bug is triggered during the vectorization of scalar operations when the vectorizer gathers scalar values into a vector, and some of these scalar values are reused (i.e., the same scalar appears in multiple lanes of the gathered vector).

To correctly position these reused scalars, the vectorizer generates shuffle masks. When these masks are subsequently combined with other masks (for example, when extending or further rearranging the vector elements), the logic responsible for composing the masks fails to correctly map the indices of the reused scalars.

This incorrect mask composition results in the emission of a `shufflevector` instruction with a flawed mask. Consequently, incorrect values are placed into the vector lanes, leading to a miscompilation where the vectorized code produces different results compared to the original scalar code.

---

# Issue 122430

## Incorrect Shuffle Mask Generation for Gather/BuildVector with Subregisters in SLP Vectorizer

**Description**:
The miscompilation is triggered when the SLP vectorizer attempts to optimize a gather or buildvector sequence where the scalar elements can be sourced from existing vector registers.

1. **Gather to Shuffle Optimization**: When building a vector from scalar elements, the vectorizer checks if these elements originate from already vectorized registers. If so, it tries to replace the costly gather operation with a more efficient `shufflevector` instruction.
2. **Subregister Cost Estimation**: If the source vector registers are larger than the vector being built (i.e., the operation involves extracting subregisters), the vectorizer generates a temporary submask. This submask adjusts the element indices (e.g., using modulo arithmetic) to accurately estimate the cost of extracting from the smaller subregister.
3. **Corrupted Mask Application**: The bug occurs because the vectorizer incorrectly takes this temporary, adjusted submask—which was strictly intended for cost estimation—and applies it as the actual mask for the final `shufflevector` instruction.
4. **Resulting Miscompilation**: Because the submask's indices were mathematically altered for the cost model, copying them directly into the IR produces a `shufflevector` instruction with corrupted indices. This causes the compiled code to extract and operate on the wrong vector elements, leading to a runtime value mismatch.

---

# Issue 122583

## Incorrect Handling of Poison Lanes in Vectorized Extract Instructions

**Description**:
When the SLP vectorizer processes a bundle of extract instructions (such as `extractelement` or `extractvalue`), it may encounter lanes within the vectorization list that are represented as `poison` values (e.g., due to unused lanes or padding). During the operand gathering phase, if a lane is identified as `poison`, the vectorizer incorrectly assigned a `poison` value as the source operand (i.e., the underlying vector or aggregate being extracted from) for that specific lane.

Because the vectorization of extract instructions heavily relies on analyzing their source operands to generate correct shuffle masks or vector combinations, replacing the source operand with `poison` disrupts this logic. It prevents the vectorizer from correctly identifying and matching the common source vector or aggregate across all lanes. Consequently, this leads to malformed vector transformations, such as generating incorrect shuffle masks or improperly propagating `poison` values into the final vectorized instructions. This ultimately causes miscompilations where the compiled program evaluates to a `poison` or undefined result.

To ensure correct vectorization, the source operand for these `poison` lanes should be set to match the source operand of the primary extract instruction in the bundle, maintaining consistency and allowing the vectorizer to generate the correct extraction or shuffle logic.

---

# Issue 123639

## Incorrect Shuffle Mask Generation for BuildVector with Mixed-Length Input Vectors

**Description**
The bug is triggered when the SLP Vectorizer attempts to optimize a gather or buildvector operation that combines elements from multiple existing vector values.

1. **Triggering Pattern**: The code contains a sequence of operations (such as a loop with cross-iteration dependencies or repeated scalar patterns) that the SLP vectorizer attempts to group into a gather or buildvector operation. This operation reuses elements from multiple source vectors, and crucially, these source vectors have varying lengths (vector factors).
2. **Incorrect Transformation Logic**: To optimize the gather operation, the vectorizer generates a `shufflevector` instruction to combine the elements from the source vectors. When constructing the combined shuffle mask, the vectorizer calculates the index offsets for elements of subsequent source vectors based solely on the length of the *first* source vector, rather than the maximum length across all input vectors.
3. **Resulting Miscompilation**: If the first source vector has a smaller length than the other input vectors, the calculated index offsets are incorrect. This results in a `shufflevector` instruction with an invalid mask that extracts the wrong elements from the source vectors, ultimately leading to incorrect runtime computations. Additionally, instability in detecting reused entries can cause mismatches between cost estimation and actual code generation.

---

# Issue 125259

## Incorrect Slice Size Calculation for Gathered Scalars in SLP Vectorization

**Description:**
The bug is triggered during Superword-Level Parallelism (SLP) vectorization when the compiler attempts to construct a vector from a collection of independent scalar values (often referred to as a gather or build-vector operation).

During this process, the vectorizer divides the elements into parts or slices to generate the appropriate vector shuffle instructions. However, the logic incorrectly calculates the size of these slices based on the *original* number of scalar elements in the vectorization tree entry, rather than the *actual* number of gathered scalars. The number of gathered scalars can differ from the original count if elements are modified, deduplicated, or optimized away while building the vector shuffles.

Because of this size mismatch, the compiler generates incorrect shuffle masks. This causes the resulting vector to be incorrectly sized or aligned, leaving portions of the vector unintentionally populated with `poison` values. When these partially poisoned vectors are subsequently used in downstream operations—such as comparisons, extensions, or memory stores—it results in undefined behavior and a miscompilation of the program.

To trigger this issue at the LLVM IR level, the code must contain a pattern of scalar operations that the SLP vectorizer decides to group into a gather/build-vector sequence, specifically under conditions where the final number of gathered scalars diverges from the initial scalar count considered by the vectorization tree.

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

---

# Issue 129244

## Incorrect Bitwidth Analysis for Signed Integers Feeding Unsigned-to-Float Conversions

**Description:**
The bug is triggered when a sequence of integer operations produces a signed value (or a value not known to be strictly positive) that is subsequently used as an operand for an unsigned integer-to-floating-point conversion (`uitofp`).

During vectorization, the compiler performs a minimum bitwidth analysis to determine if the integer operations can be safely truncated or narrowed to a smaller type to optimize the vectorized code. However, the analysis fails to correctly bound the maximum required bitwidth when a signed integer node feeds directly into an unsigned conversion.

Because the analysis does not properly account for the interaction between the signed nature of the incoming value and the unsigned interpretation of the conversion, it may incorrectly narrow the integer operations. When a negative value is truncated and then interpreted as unsigned during the floating-point conversion, its magnitude is drastically altered. This invalid narrowing leads to an incorrect floating-point result and an overall miscompilation of the program.

---

# Issue 130082

## Vectorization of PHI Nodes with Multiple Edges from the Same Predecessor

**Description:**
The bug is triggered when the compiler attempts to vectorize multiple scalar PHI nodes into a single vector PHI node, specifically in scenarios where these PHI nodes have multiple incoming edges originating from the *same* predecessor basic block. This control-flow pattern frequently occurs with `switch` statements where multiple cases branch to the same destination block, resulting in duplicate predecessor entries in the PHI nodes.

During the vectorization process, the compiler must gather, align, and map the incoming values from the scalar PHIs to the corresponding edges of the newly created vector PHI node. When multiple edges share the same predecessor block, the compiler's internal analysis tracks these edges to resolve the incoming values.

If the internal tracking mechanism relies on unordered data structures (such as hash maps or sets keyed by the memory addresses of the basic blocks or values), iterating over them yields a non-deterministic order. Because of this non-determinism, the vectorizer fails to consistently match the correct scalar values to their exact corresponding edges. As a result, the compiler can miscompile the code by assigning incorrect incoming values to the vector PHI node, or by erroneously synthesizing unrelated/garbage instructions (such as a poison load) to fill in the mismatched incoming edges.

---

# Issue 131355

## Vectorization of PHI Nodes with Multiple Edges from the Same Predecessor

**Description:**
The bug is triggered when a vectorizer processes a `phi` node that has multiple incoming edges from the exact same predecessor basic block. This pattern frequently occurs when multiple cases of a `switch` instruction branch to the same destination block, causing the `phi` node to list the same incoming block and value multiple times.

During the vectorization of such a `phi` node, the compiler iterates over its incoming edges. When it processes the first edge from the predecessor block, it correctly vectorizes the incoming value and records the visited block. When it encounters subsequent edges from the same predecessor, it recognizes that the block has already been visited and correctly reuses the previously vectorized value to construct the new vectorized `phi` node.

However, the miscompilation occurs because the vectorizer fails to update its internal vectorization tree state for these subsequent, duplicate edges. Specifically, it neglects to register the reused vectorized value with the corresponding operand entry in the tree. Because this internal state is left uninitialized, later stages of the vectorization process that rely on this operand entry end up using a `poison` or undefined value. This ultimately leads to the generation of invalid LLVM IR, such as introducing memory operations (e.g., loads) from `poison` pointers.

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

---

# Issue 135410

## Incorrect Minimum Bitwidth Analysis for Integer-to-Float Conversions

**Description:**
The bug is triggered when a compiler optimization (such as a vectorizer) attempts to reduce the bitwidth of integer values that are being gathered into a vector.

When the original scalar integer values are used by integer-to-floating-point conversion instructions (like `sitofp` or `uitofp`), the optimization's minimum bitwidth analysis incorrectly assumes that the integers can be safely truncated to a smaller bitwidth and later extended back before the conversion. This typically occurs when the same integer values are also used by other instructions that explicitly truncate them, which misleads the analysis into believing that the upper bits of the original integers are redundant and can be discarded.

However, integer-to-float conversions are strictly dependent on the exact value and sign of the source integer. Truncating an integer to a smaller bitwidth and subsequently sign-extending or zero-extending it back can fundamentally alter its value. For example, a large positive integer might be truncated into a value that represents a negative number in the smaller bitwidth; when sign-extended back to the original bitwidth, it becomes a large negative number. Consequently, applying the integer-to-float conversion on this modified value produces a completely incorrect floating-point result, leading to a miscompilation.

---

# Issue 138923

## Incorrect Vectorization of Strided Loads Requiring Reordering

**Description**:
The bug is triggered when the vectorizer attempts to vectorize a sequence of strided, unmasked memory loads that require reordering.

When the order of the scalar loads in the source code does not match their sequential memory addresses, the vectorizer must reorder the elements to form the correct vector. However, the transformation logic incorrectly attempts to optimize these accesses by generating a widened or interleaved load sequence without properly accounting for the required reordering. This results in a load and shuffle sequence that fails to place the loaded values into the correct vector lanes, leading to a miscompilation.

Furthermore, the vectorizer may widen the load to cover the entire strided memory range without verifying if it is safe to unconditionally load from the extended addresses. This can potentially lead to unsafe memory accesses if the widened load reads past valid memory boundaries.

---

# Issue 139202

## Incorrect Vectorization due to 32-bit Truncation of 64-bit Pointer Offsets

**Description**:
The bug is triggered by a sequence of memory operations (such as loads or stores) that access memory using large offsets from a common base pointer. These offsets are large enough to require a 64-bit representation, exceeding the capacity of a standard 32-bit integer.

To trigger the miscompilation, the offsets are constructed such that their lower 32 bits form a contiguous sequence of memory addresses, spaced exactly by the size of the accessed elements (e.g., 0, 8, 16, 24 for 8-byte elements). However, the upper 32 bits of some offsets are non-zero, meaning the actual memory locations are widely separated and strictly non-contiguous.

When the compiler's vectorization analysis calculates the distances between these pointers to check for consecutive accesses, it incorrectly truncates the 64-bit pointer differences into 32-bit integers. Because of this truncation, the large, non-contiguous offsets are masked, and the compiler only sees the contiguous lower 32 bits. Deceived into believing that the memory accesses are strictly adjacent, the compiler erroneously combines the separate scalar memory operations into a single vector memory operation (e.g., a contiguous vector load or store). This results in a miscompilation where data is read from or written to incorrect memory locations.

---

# Issue 165878

## Incorrect Type Demotion in Alternate Opcode Vectorization Involving Bitwidth-Sensitive Operations

**Description**:
The bug is triggered when the vectorizer groups two different operations into an alternate opcode vectorization sequence (e.g., a multiplication and a logical shift) and attempts to demote their types based on minimum bitwidth analysis.

If the operations operate on a wider integer type but their inputs are extended from a narrower type, the vectorizer may decide to shrink the bitwidth of the vectorized operations to optimize the code. However, if the alternate operation is bitwidth-sensitive (such as a shift, division, or remainder) and uses an operand that is only valid for the wider type (e.g., a constant shift amount that is greater than or equal to the narrower bitwidth), the demotion becomes unsafe.

The vectorizer incorrectly relies on the analysis of the main operation and applies the type demotion to both operations. This results in the bitwidth-sensitive operation becoming invalid in the narrower type (e.g., producing poison or undefined behavior due to an out-of-bounds shift amount), ultimately leading to a miscompilation.

To trigger this issue, one must construct a pattern where a bitwidth-sensitive operation and a regular operation are vectorized together as alternate opcodes, with inputs that encourage type demotion, and an operand in the sensitive operation that exceeds the bounds of the newly demoted type.

---

# Issue 173784

## Vectorization of Short-Circuiting Boolean Logic into Eager Reductions Introducing Poison

**Description**:
The bug is triggered when a chain of scalar boolean logical operations (such as logical OR or AND, often represented by `select` instructions) is vectorized into a horizontal vector reduction.

In the original scalar IR, these operations exhibit short-circuiting behavior: if the final result can be determined by the first operand (e.g., a `true` in a logical OR chain), the subsequent operands are not evaluated. This short-circuiting is crucial for correctness when the unevaluated operands might be `poison` or `undef`, as it prevents the undefined behavior from affecting the final result.

During vectorization, the compiler groups these scalar operands into a vector and replaces the logical chain with a vector reduction intrinsic (e.g., `llvm.vector.reduce.or`). However, unlike scalar short-circuiting logic, vector reductions evaluate all lanes eagerly. If any of the vector lanes contain a `poison` value that would have been safely bypassed in the scalar version, the eager evaluation of the reduction observes it and propagates the `poison` to the final result.

This transformation breaks the original semantics by introducing `poison` into the program in cases where the scalar code would have safely produced a well-defined value, leading to a miscompilation.

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

---

# Issue 174041

## Incorrect Vectorization of Interchangeable Identity Operations

**Description**:
The bug is triggered by presenting the vectorizer with a sequence of different scalar binary operations that each act as an identity operation due to their specific constant operands (for example, a bitwise XOR with zero and a bitwise AND with all-ones). The vectorizer incorrectly identifies these distinct operations as interchangeable and attempts to combine them into a single vector instruction.

To achieve this, it selects one of the opcodes (e.g., the AND operation) and applies it across a mixed vector of the original constants. However, the chosen opcode may not maintain its identity semantics when paired with the constant from the other operation (for instance, applying an AND operation with a zero constant evaluates to zero, rather than preserving the original value). This invalid unification alters the semantics of the original scalar operations, leading to a miscompilation where specific vector lanes are incorrectly computed instead of retaining their original values.

---

# Issue 75437

## Incorrect Handling of Dynamic Indices in Vector Element Tracking

**Description**:
The bug is triggered when a vector is modified using an insertion operation with a non-constant (dynamic) index, whose exact position is unknown at compile time.

When the vectorizer attempts to parallelize operations involving this vector, it analyzes the chain of insertion instructions to determine which elements of the resulting vector are undefined or poison. This information is used to optimize the merging of the original vector with newly vectorized elements (e.g., using shuffle operations).

However, when the vectorizer encounters an insertion with a dynamic index, it simply ignores it instead of conservatively assuming that the insertion could affect any element in the vector. As a result, the vectorizer incorrectly marks elements as undefined. This flawed analysis leads the vectorizer to discard the dynamically inserted elements during the transformation, completely removing the insertion operation and resulting in a miscompilation.
