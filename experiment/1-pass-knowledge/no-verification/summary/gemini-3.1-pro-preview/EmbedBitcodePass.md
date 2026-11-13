# Subsystem Knowledge for EmbedBitcodePass
## Elements Frequently Missed

* **`blockaddress` Constants**: These constants are frequently missed during the value remapping phase of module cloning. Because they are constants that reference specific basic blocks within a function, the cloning infrastructure often fails to update them to point to the newly cloned basic blocks, leaving them pointing to the original blocks or becoming invalid.
* **`indirectbr` Instructions**: Instructions that rely on `blockaddress` constants to implement indirect control flow (such as indirect gotos). They are indirectly missed because the underlying block addresses they consume are not correctly translated during the cloning process.
* **Basic Block Labels**: The actual targets of the `blockaddress` constants. The mapping between the original basic block labels and the cloned basic block labels is frequently dropped or improperly applied to constant expressions during the duplication process.

## High-Level Patterns Not Well Handled

### Pattern 1: Module Cloning with Indirect Control Flow (`blockaddress` and `indirectbr`)

**Description of the Pattern**:
This pattern involves LLVM IR that implements indirect control flow—typically indirect gotos—using a combination of `blockaddress` constants and `indirectbr` instructions. During the `EmbedBitcodePass`, the compiler must duplicate (clone) the entire module so that the bitcode can be embedded into the object file as data.

**Issues Caused**:
When this pattern is present, the cloned module retains invalid, unmapped, or corrupted label addresses. If the embedded bitcode is later extracted and executed (or optimized further, such as in LTO), the `indirectbr` instructions will jump to incorrect memory locations. This leads to severe runtime failures, including corrupted control flow, silent miscompilations, or immediate crashes like illegal instruction faults.

**Why it is Not Well Handled**:
The issue stems from a deficiency in the compiler's module cloning infrastructure used by the `EmbedBitcodePass`. While standard instructions and values are easily duplicated and remapped to their new counterparts, `blockaddress` represents a unique edge case: it is a constant, but it holds a reference to a specific `BasicBlock` inside a specific `Function`. The cloning logic's constant remapping phase fails to correctly look up and substitute the original basic block with the newly cloned basic block. Consequently, the deep copy is incomplete, and the cloned module is left with dangling references that break the indirect control flow graph.
