## Elements Frequently Missed

*   **Instruction Metadata and Attributes**: The optimization pass frequently overlooks metadata attached to specific call sites or instructions, such as `!range`, `nonnull`, or `noundef`. While the operands and opcodes may be identical, these attributes define strict conditions under which the result is well-defined versus `poison`. GVN often treats instructions as equivalent based solely on value computation, missing that one instruction may be "poison-prone" while the other is not.
*   **Analysis Cache Invalidation**: The pass misses necessary triggers to invalidate or update analysis caches (specifically Memory Dependence Analysis) when instructions are deleted. When helper routines remove redundant instructions (like duplicate PHI nodes), the lack of communication with the analysis subsystem leaves stale entries in the cache.
*   **Poison/Undefined Behavior Semantics during Replacement**: The optimizer frequently misses the semantic distinction between a "clean" value and a value that might be `poison` due to stricter constraints. It assumes that if instruction $A$ and instruction $B$ compute the same value, $A$ can always replace $B$, ignoring that $A$ might carry undefined behavior risks that $B$ does not.

## Patterns Not Well Handled

### Pattern 1: Asymmetric Attribute Replacement in CSE
This pattern occurs when the optimizer identifies two instructions (typically function calls) as Common Subexpressions because they share the same opcode and operands. However, the instruction chosen as the replacement (the dominator) possesses stricter attributes or metadata than the instruction being replaced.
*   **The Issue**: The optimizer replaces a "safe" instruction (one with no or loose attributes) with a "strict" instruction (one with attributes like `!range` or `nonnull`).
*   **Why it fails**: If the runtime value violates the strict attributes of the replacement, the result becomes `poison`. The original instruction, lacking those attributes, would have produced a valid value. This transformation introduces Undefined Behavior into a valid program path because GVN fails to intersect or verify that the replacement's attributes are compatible with the replacee's context.

### Pattern 2: Instruction Deletion with Address Reuse
This pattern involves the removal of redundant instructions (such as duplicate PHI nodes) followed immediately by the analysis of other instructions within the same pass execution, without clearing analysis caches.
*   **The Issue**: When an instruction is deleted, its memory address is freed. If the memory allocator reuses this address for a new instruction, the GVN pass—relying on a stale Memory Dependence Analysis cache—may retrieve analysis results keyed to the *old* instruction's address.
*   **Why it fails**: The optimizer applies transformations to the new instruction based on the properties of the deleted instruction (e.g., believing a load depends on a specific store or PHI value that no longer exists or is irrelevant). This leads to incorrect constant folding or dependency resolution because the cache assumes the memory address still represents the deleted logic.