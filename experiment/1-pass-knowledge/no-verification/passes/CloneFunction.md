# Issue 87534

## Premature Instruction Simplification with Incomplete PHI Nodes During Function Cloning

**Description**:
The bug is triggered during function cloning or inlining when the compiler attempts to simplify instructions before the control flow graph and its associated PHI nodes are fully reconstructed.

The triggering pattern involves the following sequence:
1. A function being cloned contains a PHI node and a subsequent instruction (such as a comparison) that depends on the value produced by this PHI node.
2. As the compiler duplicates basic blocks and instructions, it eagerly attempts to simplify newly cloned instructions on the fly to optimize the IR.
3. When the instruction depending on the PHI node is processed, the PHI node may still be in an incomplete state. This happens because the entire control flow graph has not been fully traversed, meaning some incoming values or blocks for the PHI node have not yet been remapped or resolved.
4. The simplification analysis (e.g., logic that attempts to thread operations like comparisons over PHI nodes) inspects this partially constructed PHI node. Lacking the complete set of incoming values, the analysis makes unsound assumptions based on the partial state.
5. Consequently, the analysis incorrectly folds the instruction (e.g., evaluating a comparison to a constant boolean value) and replaces it in the cloned function, leading to a miscompilation.
