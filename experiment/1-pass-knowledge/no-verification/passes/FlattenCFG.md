# Issue 70900

## Merging Consecutive Conditional Regions with PHI Nodes at the Merge Point

**Description:**
The bug is triggered when the compiler attempts to optimize the control flow graph by merging two consecutive conditional regions (such as if-regions).

In this specific pattern, the control flow graph contains two sequential conditional structures where the exit block (the merge point) of the first conditional region also serves as the entry block for the second conditional region. The critical condition that triggers the miscompilation is the presence of one or more PHI nodes in this shared intermediate block. These PHI nodes are responsible for selecting values based on which control flow path was taken through the first conditional region.

When the optimization pass decides to merge these two conditional regions into a single, simplified control flow structure, it alters the branches and predecessor-successor relationships. However, the transformation logic fails to account for the PHI nodes located exactly at the merge point. While it might attempt to update PHI nodes in the final successors of the merged region, it leaves the PHI nodes at the intermediate merge point in an inconsistent state. Because the original control flow edges entering the merge point are modified or removed during the merge, the PHI nodes lose their correct incoming blocks and values, leading to broken data dependencies and incorrect runtime execution.
