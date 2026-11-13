# Issue 108854

## Speculation of Instructions Without Context-Aware Safety Checks

**Description**

The bug triggering strategy involves exploiting the compiler's instruction speculation logic by relying on local safety guarantees that become invalid when instructions are hoisted to a new context. The miscompilation occurs because the compiler evaluates the safety of an instruction based on its original location rather than its intended new location.

To trigger this issue at the LLVM IR level:

1. **Control Flow Setup**: Construct a control flow graph with a conditional branch that guards a specific basic block, which then flows into a subsequent merge block.
2. **Local Safety Guarantees**: Inside the conditionally executed block, introduce an instruction that establishes a local safety property. This is typically achieved using metadata (such as `dereferenceable` or `align` attributes) or local assumptions attached to an instruction (e.g., a pointer load).
3. **Dependent Instruction**: Within the same conditional block, add a dependent instruction (such as a memory access) that relies on the previously established local property to be considered safe for execution.
4. **PHI Node Usage**: Use the result of the dependent instruction as an incoming value for a PHI node in the merge block.
5. **Triggering the Miscompilation**: When the compiler attempts to simplify the control flow (e.g., by folding the PHI node and eliminating the conditional branch), it will try to speculatively hoist the instructions from the conditional block into the dominating predecessor block.
6. **Incorrect Transformation**: The compiler's safety check for speculation evaluates the dependent instruction in its original context, ignoring the new insertion point. It incorrectly concludes that the instruction is safe to hoist based on the local metadata or assumptions. However, these local properties are often discarded or become invalid when the instructions are moved. Consequently, the instruction is hoisted to a location where its safety guarantees no longer hold, leading to invalid IR and potential undefined behavior (e.g., an unconditionally executed memory access that may fault).

---

# Issue 89672

## Speculation of Store with Higher Alignment than Preceding Memory Access

**Description**:
The bug is triggered when a compiler optimization speculates a store instruction from a conditionally executed basic block and hoists it into a preceding block. This speculation is typically justified by the presence of a prior memory access (either a load or a store) to the same memory location in the preceding block, which proves that the pointer is safe to access.

However, an issue arises if the conditionally executed store has a higher alignment requirement than the preceding memory access. The higher alignment might only be valid when the branch condition is satisfied. When the optimization hoists the store and unconditionally executes it while retaining its higher alignment, it introduces a potential alignment fault. The pointer is only unconditionally guaranteed to meet the lower alignment of the preceding access, making it unsafe to speculate a memory operation with a stricter alignment requirement without adjusting it.
