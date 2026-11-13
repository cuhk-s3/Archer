# Subsystem Knowledge for VectorCombine
## Elements Frequently Missed

*   **Commutativity Properties of Binary Operations**: The optimization pass frequently fails to check whether a binary operation is commutative before reordering or combining operands. This leads to swapped Left-Hand Side (LHS) and Right-Hand Side (RHS) operands in non-commutative operations like shifts (`shl`, `lshr`, `ashr`), resulting in incorrect calculations.
*   **Poison/Undef Semantics in Shuffle Masks**: The presence of `poison` or `undef` elements in `shufflevector` masks is often overlooked when reordering instructions. The pass fails to recognize that moving these masks can expose poison values to operations that cannot safely handle them.
*   **Out-of-Bounds Indices**: The pass misses checks for out-of-bounds indices in `insertelement` or `extractelement` instructions. It assumes indices are valid and attempts to extract or manipulate corresponding lanes from other operands, inadvertently generating `poison` values during the transformation.
*   **Target Endianness and Data Layout**: The pass frequently misses querying the target's Data Layout for endianness. It hardcodes little-endian assumptions (e.g., calculating bit offsets simply as `index * element_size`), which causes incorrect bit extraction on big-endian targets.
*   **Scalar Element Size vs. Total Vector Size**: When checking if memory operations can be simplified, the pass mistakenly verifies if the *entire vector type* is byte-sized (a multiple of 8 bits) rather than checking if the *individual scalar elements* are byte-sized (e.g., missing the distinction for types like `<32 x i1>`).
*   **UB-Sensitive Operations (Division/Remainder)**: The pass fails to identify operations that trigger immediate Undefined Behavior (UB) when fed a `poison` operand (such as the divisor in `sdiv`, `udiv`, `srem`, `urem`). It treats these operations identically to safe arithmetic operations during transformations.

## Patterns Not Well Handled

### Pattern 1: Unsafe Scalarization Introducing Undefined Behavior
The pass struggles with scalarizing vector operations when one of the operands evaluates to `poison` (e.g., due to an out-of-bounds `insertelement`). In the original vector form, the `poison` lane might safely propagate without causing harm. However, when the pass scalarizes the operation, it extracts the `poison` value and feeds it directly into a scalar binary operation. If this scalar operation is UB-sensitive (like integer division or remainder), the transformation incorrectly elevates a safe `poison` propagation into immediate Undefined Behavior.

### Pattern 2: Unsafe Hoisting of Shufflevectors Above UB-Sensitive Operations
The pass attempts to optimize code by hoisting `shufflevector` instructions above binary operations (e.g., converting `shuffle(op(A, B))` into `op(shuffle(A), shuffle(B))`). This pattern is poorly handled when the original shuffle mask contains `poison` or `undef` elements and the binary operation is UB-sensitive (like division). By hoisting the shuffle, the pass forces the division operation to execute with `poison` divisors in certain lanes, introducing UB that did not exist in the original IR where the division occurred before the poison-introducing shuffle.

### Pattern 3: Vectorization of Non-Commutative Operations on Extracted Elements
When the pass attempts to vectorize a sequence involving `extractelement`, `icmp`, and a subsequent scalar binary operation, it often fails to preserve the strict operand ordering required by non-commutative operations. The transformation packs the extracted elements into a vector and applies a vector binary operation, but the logic mapping the original scalar LHS and RHS to the new vector lanes is flawed. This results in the operands being swapped, causing miscompilations for operations like shifts or subtraction.

### Pattern 4: Scalarization of Memory Accesses for Sub-Byte Elements
The pass attempts to optimize vector memory accesses (load/store followed by element extraction/insertion) by replacing them with direct scalar memory accesses to the specific element. This pattern is poorly handled for vectors with non-byte-sized elements (e.g., `i1` vectors). Because the pass only checks if the total vector size is byte-aligned, it emits scalar loads/stores for sub-byte elements. The backend later expands these into full byte-sized memory accesses, which incorrectly overwrites and clobbers adjacent bits belonging to other vector elements.

### Pattern 5: Endian-Unaware Vector-to-Scalar Bitwise Packing
To optimize vector element extractions, the pass sometimes packs an entire vector into a single large scalar integer and replaces the `extractelement` with scalar bitwise logical right shifts and AND masks. This pattern is poorly handled because the bit offset calculation assumes a little-endian memory layout (where index 0 is at the least significant bits). On big-endian targets, this hardcoded assumption causes the shift operation to isolate the wrong bits, leading to the extraction of completely incorrect values.
