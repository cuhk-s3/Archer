# Subsystem Knowledge for CloneFunction
## Elements Frequently Missed

* **Incomplete PHI Nodes**: The transient, partially constructed state of PHI nodes during the cloning process is frequently overlooked. Simplification routines miss the fact that not all incoming values and basic blocks have been remapped or added to the PHI node yet.
* **Pending Control Flow Graph (CFG) Edges**: The structural incompleteness of the CFG during the block-by-block cloning phase is missed. Analyses assume the CFG is fully formed when evaluating instruction simplifications.
* **PHI-Dependent Instructions**: Instructions (such as `icmp` or binary operators) that consume the outputs of PHI nodes are evaluated prematurely. The pass misses the requirement that the simplification of these dependent instructions must be deferred until the underlying PHI node is fully resolved.

## Patterns Not Well Handled

### Pattern 1: Eager Simplification of Instructions Dependent on Incomplete PHIs
During function cloning or inlining, the compiler duplicates basic blocks and instructions, and eagerly attempts to simplify these newly cloned instructions on the fly to optimize the IR. A critical issue arises when an instruction (such as a comparison) depends on a newly cloned PHI node. Because the entire control flow graph has not been fully traversed, the PHI node may still be in an incomplete state, lacking its full set of incoming values or blocks.

**Issues Caused**: The simplification analysis (e.g., logic that attempts to thread operations over PHI nodes) inspects this partially constructed PHI node. Lacking the complete set of incoming values, the analysis makes unsound assumptions based on the partial state. Consequently, it incorrectly folds the instruction (e.g., evaluating a comparison to a constant boolean value) and replaces it in the cloned function, leading to a miscompilation.

**Why it is not well handled**: The `CloneFunction` utility interleaves instruction duplication with eager simplification (like `InstructionSimplify`) to reduce overhead and optimize the IR as early as possible. However, the pass lacks a robust dependency-tracking mechanism to defer the simplification of PHI-dependent instructions until the CFG reconstruction is complete and all PHI incoming edges are fully resolved. The simplification API is invoked without context regarding the transient state of the cloning process.
