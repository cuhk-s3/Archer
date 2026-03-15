# Subsystem Knowledge for VectorCombine
## Elements Frequently Missed

*   **Commutativity and Operand Ordering**: The optimization pass frequently misses checking whether a binary operation is commutative (e.g., `shl`, `sub`) before vectorizing scalar operations. This leads to swapping or mishandling the left-hand and right-hand operands, resulting in incorrect evaluations.
*   **Poison-to-UB Safety Constraints**: The pass fails to recognize when a transformation will feed a `poison` value into an instruction that triggers immediate Undefined Behavior (UB), such as integer division (`sdiv`, `udiv`) or remainder (`srem`, `urem`).
*   **Out-of-Bounds Index Validation**: The pass misses validating whether indices used in `insertelement` or `extractelement` instructions are within bounds before using them to drive scalarization logic. Using out-of-bounds indices during transformations inadvertently generates `poison` values.
*   **Target Endianness and DataLayout**: The pass frequently misses querying the target's `DataLayout` to determine endianness. It relies on hardcoded little-endian assumptions when calculating bit offsets for vector-to-scalar packing and extraction, causing failures on big-endian targets.
*   **Scalar Element Byte-Size Verification**: When scalarizing memory operations, the pass checks if the overall vector type is byte-sized (a multiple of 8 bits) but misses checking if the individual scalar element type (e.g., `i1`) is byte-sized.

## Patterns Not Well Handled

### Pattern 1: Transformations Escalating Poison to Undefined Behavior
The pass struggles with transformations that reorder instructions or scalarize operations involving `poison` values and strict arithmetic instructions (like division or remainder). For example, hoisting a `shufflevector` with a `poison` mask above a division, or scalarizing an out-of-bounds `insertelement` into a division. These patterns are not well handled because the pass evaluates the structural legality of the fold but ignores the semantic legality of `poison` propagation. By moving the generation of `poison` (via masks or out-of-bounds indices) to become an operand of a UB-triggering instruction, the pass incorrectly escalates a safely propagated `poison` value into immediate Undefined Behavior.

### Pattern 2: Endian-Unaware Vector-to-Scalar Bitwise Packing
The pass attempts to optimize vector element extractions by casting the entire vector to a large scalar integer and using bitwise shifts and AND masks to isolate specific lanes. This pattern is poorly handled because the bit-offset calculation assumes a little-endian memory layout (where index 0 is in the least significant bits). Because the pass fails to integrate target-specific `DataLayout` queries, this transformation extracts completely incorrect bits on big-endian architectures, leading to silent miscompilations.

### Pattern 3: Vectorization of Non-Commutative Operations on Extracted Elements
When the pass encounters scalar binary operations applied to elements extracted from vectors (often via intermediate comparisons), it attempts to fold them into a single vector binary operation followed by an extraction. This pattern is not well handled for non-commutative operations (like logical shifts). The transformation logic fails to strictly track and preserve the original left/right operand ordering during the synthesis of the new vector instruction. Consequently, the optimized vector instruction evaluates with reversed arguments, producing incorrect results.

### Pattern 4: Scalarization of Memory Accesses for Sub-Byte Elements
The pass attempts to simplify vector memory accesses by replacing full vector loads/stores with direct scalar loads/stores to specific elements. This pattern is poorly handled when the vector consists of non-byte-sized elements (e.g., `<32 x i1>`). The pass incorrectly validates the byte-size property against the aggregate vector type rather than the scalar element type. Because the backend cannot address sub-byte memory directly, it expands the scalar `i1` store into a full byte store. This causes the optimized code to overwrite and clobber adjacent bits in memory that belong to other vector elements.
