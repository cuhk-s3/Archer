# Subsystem Knowledge for NewGVN

## Elements Frequently Missed

*   **Call Site Attributes and Metadata**: The optimization pass frequently overlooks specific attributes (e.g., `nonnull`, `noundef`) and metadata (e.g., `!range`) attached to function calls. While it correctly identifies that the function and operands are identical, it fails to verify that the metadata of the replacement instruction is compatible with (i.e., not stricter than) the instruction being replaced.
*   **Memory-Defining Properties of Simplifiable Instructions**: The optimizer misses the memory-defining nature of certain instructions (specifically intrinsics) when those instructions can be symbolically simplified to a value (such as an input argument via the `returned` attribute). It treats them purely as value flows, neglecting their role in the MemorySSA or memory congruence system.
*   **Intersection of Constraints**: The logic misses the necessity of intersecting constraints when performing Global Value Numbering (GVN). It assumes that if two values are congruent, they are interchangeable, failing to account for scenarios where the "leader" of the congruence class produces `poison` under conditions where the "member" does not.

## Patterns Not Well Handled

### Pattern 1: Unsafe CSE with Stricter Dominating Metadata
This pattern occurs when the optimizer identifies two function calls as redundant because they share the same callee and operands. However, the dominating call (the one kept) carries strict metadata (like `!range` or `nonnull`) that implies undefined behavior or `poison` for certain inputs, while the dominated call (the one removed) does not.
*   **Issue**: The optimizer replaces the "safe" instruction with the "strict" instruction. If the runtime data violates the strict metadata but is valid for the original loose instruction, the program enters an undefined state (poison) that did not exist in the original code.
*   **Why it is not well handled**: The equivalence check focuses on the value computation (function + args) but ignores the "side constraints" imposed by metadata. The system lacks a mechanism to either strip the metadata from the leader or prevent the replacement when the leader is stricter than the follower.

### Pattern 2: Oversimplification of Memory-Defining Intrinsics with `returned` Arguments
This pattern involves intrinsic functions that serve a dual purpose: they modify memory (side effect) and return one of their arguments (value flow).
*   **Issue**: When NewGVN sees the `returned` attribute, it aggressively simplifies the instruction to the input operand during symbolic evaluation. Consequently, the instruction is treated as a simple value pass-through. The optimizer fails to register this instruction as a distinct memory state definition within the memory congruence class.
*   **Why it is not well handled**: There is a disconnect between the value simplification logic and the memory dependency logic. The system assumes that if an instruction simplifies to a pre-existing value, it does not need to be tracked as a complex memory operation, leading to corrupted memory states and assertion failures when updating memory dependencies.