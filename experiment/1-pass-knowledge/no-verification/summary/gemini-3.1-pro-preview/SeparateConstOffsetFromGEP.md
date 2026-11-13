# Subsystem Knowledge for SeparateConstOffsetFromGEP
## Elements Frequently Missed

* **Poison-Generating Flags (`nuw`, `nsw`) on Truncation Instructions**: The optimization pass frequently misses the semantic implications of preserving `nuw` (no unsigned wrap) and `nsw` (no signed wrap) flags when cloning and moving `trunc` instructions. It fails to strip these flags when the instruction's context changes.
* **Operand-Level vs. Result-Level Overflow Conditions**: The pass misses the distinction that overflow/wrap conditions satisfied by the final result of an arithmetic operation do not necessarily hold true for its individual operands when they are evaluated or truncated independently.

## Patterns Not Well Handled

### Pattern 1: Distributing Truncation with Poison-Generating Flags over Arithmetic Operations
When the optimization pass attempts to separate a constant offset from a GetElementPtr (GEP) instruction, it often distributes a truncation (`trunc`) instruction over the operands of an underlying arithmetic operation (such as `add`, `sub`, or `or`).

**Issues Caused**: If the original `trunc` instruction possesses poison-generating flags (`nuw` or `nsw`), the pass incorrectly preserves and copies these flags onto the newly cloned, distributed `trunc` instructions. Because an individual operand might have non-zero truncated bits that would normally be canceled out by the constant offset during the arithmetic operation, truncating the operand directly with `nuw`/`nsw` flags can violate the wrap constraints. This transforms valid IR into miscompiled IR that incorrectly evaluates to a `poison` value.

**Why it is not well handled**: The pass's cloning mechanism assumes that the mathematical distributivity of truncation over addition/subtraction also applies to the strict overflow semantics of LLVM IR. It does not account for the fact that intermediate values (the isolated variable operand and the isolated constant offset) might temporarily exceed truncation bounds before they are combined. Consequently, the pass lacks the necessary logic to safely drop `nuw` and `nsw` flags when pushing a `trunc` instruction up the def-use chain through an arithmetic operation.
