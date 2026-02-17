# Subsystem Knowledge for GVNSink

## Elements Frequently Missed

*   **Source Element Types in `getelementptr` Instructions**: The optimization pass frequently overlooks the source element type associated with GEP instructions. While it correctly verifies that the opcode and the operands (base pointer and indices) are identical across predecessor blocks, it fails to validate that the types being indexed into are the same. Since the source element type determines the stride (byte size) of the index calculation, missing this element leads to incorrect memory address computations when the types differ in size (e.g., `i8` vs `i32`).

## Patterns Not Well Handled

### Pattern 1: Sinking Type-Dependent Address Calculations
This pattern occurs when a control flow graph splits into multiple branches that eventually merge into a single successor, and each branch contains a `getelementptr` instruction using identical operands (same base pointer and same index value) but different source element types.

*   **The Issue**: The GVNSink pass identifies these instructions as candidates for sinking because they appear structurally identical (same opcode, same arguments). However, GEP semantics rely heavily on the source type to calculate offsets (Offset = Index * SizeOf(Type)). By sinking these into a single instruction with a single type, the pass forces a uniform stride calculation on all paths.
*   **Why it is not well handled**: The logic prioritizes operand equality and opcode matching but fails to treat the source element type as a critical constraint for equivalence. Consequently, paths that originally required a larger stride (e.g., 4 bytes for `i32`) are incorrectly optimized to use the stride of the sunk instruction (e.g., 1 byte for `i8`), resulting in memory corruption or invalid pointer arithmetic.