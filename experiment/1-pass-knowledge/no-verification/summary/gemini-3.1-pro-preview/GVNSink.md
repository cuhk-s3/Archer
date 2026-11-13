# Subsystem Knowledge for GVNSink
## Elements Frequently Missed

* **GEP Source Element Types**: The optimization pass frequently misses verifying the source element type of `getelementptr` (GEP) instructions. It incorrectly assumes that GEPs are equivalent candidates for sinking if they merely share the same number of operands, ignoring the underlying type being indexed.
* **Type-Dependent Scaling Factors**: The pass overlooks the implicit scaling factors applied during memory address computation. Because the size of the source element type dictates the multiplier for the offset indices, failing to check this element leads to fundamentally different address calculations being treated as identical.

## Patterns Not Well Handled

### Pattern 1: Sinking GEP Instructions with Heterogeneous Source Element Types
This pattern occurs when multiple predecessor basic blocks contain `getelementptr` instructions that flow into a common successor block, where the GEPs share the same number of operands but operate on different source element types (e.g., an `i8` type in one block and a larger struct type in another).

**Issues Caused:**
When the pass sinks these distinct GEPs into a single GEP instruction in the common successor block, it uses a PHI node to select the index operand based on the incoming control flow edge. However, the newly sunk GEP is forced to use only one specific source element type. Consequently, it applies an incorrect scaling factor to the indices originating from control flow paths that originally used a different source element type, resulting in corrupted memory address calculations and severe miscompilations.

**Why it is not well handled:**
The equivalence checking mechanism in GVNSink is too shallow for GEP instructions. The heuristic primarily relies on matching the number of operands to determine if instructions can be sunk and merged. It fails to enforce strict equality of the instructions' full type signatures—specifically the `SourceElementType`—which is a critical component that dictates the actual semantics and mathematical scaling of the GEP's address computation.
