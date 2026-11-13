# Subsystem Knowledge for FlattenCFG
## Elements Frequently Missed

* **Intermediate PHI Nodes**: PHI nodes located exactly at the shared merge point (exit block of the first region and entry block of the second) are frequently missed. The optimization pass fails to update their incoming values and blocks when the surrounding control flow is flattened.
* **Original Predecessor-Successor Edges**: The control flow edges entering the intermediate merge point are modified or removed during the merge. The pass misses the necessary corresponding updates to the data dependencies (PHI incoming blocks) that rely on these original edges.

## Patterns Not Well Handled

### Pattern 1: Merging Consecutive Conditional Regions with Intermediate PHI Nodes
This pattern occurs when the control flow graph contains two sequential conditional structures (such as consecutive if-regions) where the exit block of the first conditional region also serves as the entry block for the second. Crucially, this shared intermediate block contains one or more PHI nodes responsible for selecting values based on the control flow path taken through the first region.

**Issues Caused:**
When FlattenCFG attempts to merge these two conditional regions into a single, simplified control flow structure, it alters the branches and predecessor-successor relationships. However, it leaves the PHI nodes at the intermediate merge point in an inconsistent state. Because the original control flow edges entering the merge point are modified or removed, the PHI nodes lose their correct incoming blocks and values. This leads to broken data dependencies, malformed LLVM IR, and incorrect runtime execution.

**Why it is not well handled:**
The transformation logic in the FlattenCFG pass is overly focused on updating PHI nodes in the *final* successors of the newly merged region. It lacks the necessary accounting for local data dependencies (PHI nodes) located at the intermediate merge points that are being structurally altered, bypassed, or absorbed during the flattening process.
