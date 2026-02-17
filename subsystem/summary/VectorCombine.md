## Elements Frequently Missed

*   **Trapping Instruction Safety**: The optimization pass frequently overlooks that certain instructions (e.g., `sdiv`, `urem`, `lshr`) can trigger Undefined Behavior (UB) if their operands are modified or if they are executed speculatively. It often assumes that if the original vector instruction was safe, the transformed scalar or hoisted instruction is also safe, failing to account for `poison` or `undef` values becoming active triggers for UB (e.g., division by zero/poison, over-shifting).
*   **Implicit Poison and Undef Semantics**: The pass often mishandles the subtle distinctions between `poison` and `undef`, particularly regarding Out-of-Bounds (OOB) indices. It misses that an OOB `insertelement` yields `poison` (safe to discard), whereas an OOB `extractelement` yields `undef` (unsafe if used as a divisor).
*   **Sub-byte Element Layouts**: The pass frequently misses the memory layout implications of bit-packed vectors (specifically `<N x i1>`). It incorrectly treats them as having byte-aligned elements during scalarization, leading to adjacent memory corruption when converting vector stores to scalar stores.
*   **Operand Commutativity**: The pass fails to consistently verify operand ordering when vectorizing scalar instructions. It tends to assume operations are commutative or that lane ordering is preserved, leading to swapped operands in non-commutative operations like `shl`, `sub`, or `icmp` with specific predicates.
*   **Vector Dimension Mismatches**: The pass misses correct type validation when handling operations between vectors of different sizes (e.g., extracting from a large vector to insert into a small one). It often incorrectly uses the destination type to validate indices derived from the source type.

## Patterns Not Well Handled

### Pattern 1: Unsafe Scalarization and Narrowing
The optimizer aggressively attempts to reduce vector operations to scalar operations or narrower types to improve performance. However, it fails to verify that the constraints of the wider/vector type apply to the narrower/scalar type.
*   **Shift Narrowing**: When narrowing `zext` -> `shift` patterns, the pass fails to check if the shift amount, while valid for the wide type, exceeds the bit width of the narrow type, causing poison.
*   **Packed Vector Scalarization**: When scalarizing load/store sequences for `i1` vectors, the pass ignores bit-packing, replacing safe vector memory ops with scalar ops that overwrite adjacent bits.
*   **OOB Index Scalarization**: When scalarizing binary ops involving `insertelement`, it propagates OOB indices to `extractelement`, turning a safe `poison` state into an immediate UB `undef` state.

### Pattern 2: Speculative Hoisting over Trapping Operations
The optimizer attempts to reduce instruction count by hoisting shuffles or logic before arithmetic operations (e.g., transforming `shuffle(op(A), op(B))` to `op(shuffle(A, B))`).
*   **Poison Propagation**: This pattern is mishandled when the shuffle mask contains `poison`. The optimization propagates this `poison` into the operands of the arithmetic instruction. If the arithmetic instruction is a trapping operation (like `sdiv` or `urem`), introducing `poison` into the divisor triggers immediate Undefined Behavior, whereas the original code would have simply discarded the result of that lane.

### Pattern 3: Incorrect Merging of Non-Isomorphic Operations
The optimizer tries to combine multiple scalar or vector instructions into a single vector instruction (SLP-style vectorization or shuffle folding).
*   **Non-Commutative BinOps**: When combining extracted scalar logic back into vectors, the pass incorrectly maps LHS/RHS scalar operands to vector lanes without respecting the order required for non-commutative operations (e.g., `shl`), effectively swapping the arguments.
*   **Predicate Swapping**: When merging comparisons with different predicates (e.g., `slt` and `sgt`) into a single shuffle, the pass attempts to unify them by swapping operands but fails to ensure the resulting vector semantics match the original logic, leading to incorrect boolean results.

### Pattern 4: Cross-Size Vector Data Movement
The optimizer struggles with sequences involving `extractelement` and `insertelement` when the source and destination vectors have different lengths.
*   **Cost Model Mismatches**: When converting extract-insert chains into shuffles, the pass incorrectly queries the Target Transform Info (TTI) using the destination vector type for validation while using indices derived from the larger source vector. This leads to assertion failures or incorrect cost estimation because the indices are considered out-of-bounds for the smaller destination type.