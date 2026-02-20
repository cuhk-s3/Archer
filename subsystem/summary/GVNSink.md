# Subsystem Knowledge for GVNSink

## Elements Frequently Missed

* **GEP Source Element Types (`SourceElementType`)**: The optimization pass frequently misses verifying the source element type of `getelementptr` (GEP) instructions. It incorrectly assumes that GEPs with the same opcode, base pointer, and number of operands are equivalent, ignoring the fact that the source element type dictates the memory address calculation.
* **Implicit Scaling Factors in Address Computations**: The pass fails to account for the implicit scaling factor applied to GEP offset indices. Because the size of the source element type determines this scaling factor, indices from differently-typed GEPs are treated as interchangeable when they are mathematically distinct.
* **Instruction-Level Type Signatures**: Beyond standard value operands, the pass misses checking the static type signatures embedded within the instructions themselves, which are crucial for instructions whose semantics change based on those types.

## Patterns Not Well Handled

### Pattern 1: Sinking Instructions with Type-Dependent Semantics
The optimization pass relies on a superficial equivalence check that primarily looks at the instruction opcode and the number of operands. It does not well handle instructions whose underlying semantics and mathematical operations depend heavily on an embedded type parameter (such as the source element type in a GEP). By ignoring these type parameters, the pass incorrectly identifies distinct operations as identical candidates for sinking. When these instructions are sunk into a common successor block, the resulting single instruction adopts only one of the original types, fundamentally altering the semantics and corrupting the behavior for the other control flow paths.

### Pattern 2: Merging Operands of Heterogeneous Address Computations via PHI Nodes
The pass attempts to sink instructions by creating PHI nodes in the common successor block to select differing operands (like GEP indices) based on the incoming control flow edge. This pattern is not well handled when the original instructions apply different implicit transformations to those operands. In the case of mismatched GEPs, the indices are meant to be scaled by different type sizes (e.g., `sizeof(i8)` vs `sizeof(%struct.S)`). Merging these indices into a single PHI node and feeding them into a single sunk GEP forces a uniform scaling factor across all paths. This results in severe miscompilations, as the index from one path is incorrectly scaled by the type size of another path, leading to out-of-bounds or misaligned memory accesses.