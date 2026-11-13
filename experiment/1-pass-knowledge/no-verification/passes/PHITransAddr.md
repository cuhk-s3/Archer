# Issue 30999

## Incorrect Address Selection During PHI Translation Lacking Dominance Constraints

**Description**

The bug is triggered during compiler optimization passes that perform PHI translation of memory addresses across basic blocks, such as Global Value Numbering (GVN) or Partial Redundancy Elimination (PRE).

When translating an address expression to a predecessor block, the optimization searches for an existing instruction that computes the equivalent translated address. If this search does not strictly enforce dominance constraints, the compiler may select an instruction that computes the correct address but resides in a basic block that does not dominate the target block.

Because this selected instruction is located in a non-dominating block, it is bound to a specific control-flow context. It may carry preconditions or assumptions—such as specific values of loop induction variables or branch conditions—that are valid in its own block but do not hold true in the target block.

When subsequent analyses (such as alias analysis) evaluate this translated address, they incorrectly apply the context-specific assumptions of the non-dominating instruction to the target block. This leads to flawed analysis results, such as incorrectly concluding that two pointers do not alias. Consequently, the optimization pass performs invalid transformations, like incorrectly eliminating memory loads or replacing them with values from unrelated loop iterations or execution paths, resulting in a miscompilation.
