# Subsystem Knowledge for SeparateConstOffsetFromGEP

## Elements Frequently Missed

* **Poison-Generating Flags (`nuw`, `nsw`) on Truncation Instructions**: The optimization pass frequently misses the semantic implications of preserving `nuw` and `nsw` flags when cloning, moving, or distributing `trunc` instructions. It fails to recognize that these flags cannot be blindly copied to new instructions.
* **Intermediate Value Constraints**: The pass misses the mathematical reality that constraints (like no-unsigned-wrap) satisfied by the final result of an arithmetic operation are not necessarily satisfied by its individual operands prior to the operation.
* **Interaction Between Constant Offsets and Truncated Bits**: The pass overlooks cases where an operand might have non-zero upper bits that would trigger poison upon direct truncation, but those bits are safely canceled out or modified by a constant offset in the original arithmetic operation before the truncation occurs.

## Patterns Not Well Handled

### Pattern 1: Distributing Truncation over Arithmetic Operations with Poison-Generating Flags
When the compiler attempts to separate a constant offset from a GEP index calculation, it often distributes a truncation instruction (`trunc`) over the operands of an arithmetic operation (such as `add`, `sub`, or `or`). If the original `trunc` instruction possesses poison-generating flags (`nuw` or `nsw`), the optimization pass incorrectly preserves and copies these flags onto the newly cloned `trunc` instructions that are applied directly to the individual operands. 

This pattern causes severe miscompilations because it introduces invalid poison values. The conditions required by the `nuw` or `nsw` flags might be perfectly satisfied by the final result of the arithmetic operation, but violated by the raw operands. For example, an operand might contain high bits that would cause a `trunc nuw` to yield poison, but in the original IR, adding a constant offset rolls over or cancels out those bits before the truncation is evaluated. The pass is not well handled because the transformation logic lacks the necessary safety checks to strip poison-generating flags (`dropPoisonGeneratingFlags()`) when pushing truncations down the def-use chain through arithmetic instructions.