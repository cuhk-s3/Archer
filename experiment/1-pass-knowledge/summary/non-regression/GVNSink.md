# Subsystem Knowledge for GVNSink
## Elements Frequently Missed

* **GEP Source Element Types (`SourceElementType`)**: The optimization pass frequently misses checking the source element type of `getelementptr` (GEP) instructions. It incorrectly assumes that GEPs with the same opcode, same base pointer, and the same number of operands are equivalent, ignoring the fact that the source element type dictates the semantics of the address computation.
* **Implicit Index Scaling Factors**: The pass fails to account for the implicit mathematical scaling applied to GEP indices. Because the size of the source element type determines the byte stride of the index, missing the type comparison means the pass misses the divergence in the underlying arithmetic operations.

## Patterns Not Well Handled

### Pattern 1: Sinking GEP Instructions with Heterogeneous Source Types
The optimization pass struggles with control flow patterns where multiple predecessor blocks compute memory addresses using `getelementptr` instructions that share the same base pointer and operand count, but operate on different source element types (e.g., one path computes an offset based on an `i8` byte type, while another computes an offset based on a larger `%struct` type).

**Issues Caused:**
When the pass sinks these GEPs into a common successor block, it merges the differing index operands using a newly created PHI node and arbitrarily selects one of the source element types for the sunk GEP. Consequently, the sunk GEP applies a uniform scaling factor to all incoming indices. For the control flow path whose original GEP type was discarded, the index is multiplied by the wrong type size, resulting in a miscompiled, incorrect memory address calculation.

**Why it is not well handled:**
The equivalence checking mechanism in GVNSink is too shallow for instructions with type-dependent semantics. It primarily relies on matching the instruction opcode and the number of operands to determine if instructions can be sunk and merged. It fails to deeply inspect the type parameters—specifically the `SourceElementType` of GEPs—that fundamentally alter the implicit arithmetic (scaling/stride) performed by the instruction.
