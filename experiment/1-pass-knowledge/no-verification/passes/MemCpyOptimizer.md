# Issue 130632

## Incorrect Insertion Point for Memory Copy Promotion Due to Finding the Last Instead of First Clobber

**Description:**
The bug is triggered when the compiler attempts to optimize a load-store pair (typically involving aggregate types) by replacing it with a direct memory copy operation (such as `memcpy` or `memmove`).

For this transformation to be semantically correct, the compiler must ensure that the source memory location is not modified between the original load and the newly inserted memory copy. If there are instructions that modify (clobber) the source memory between the load and the store, the compiler attempts to safely promote the memory copy by inserting it *before* the clobbering instruction.

The issue arises when there are **multiple** memory operations between the load and the store that potentially clobber the source memory. The flawed analysis logic searches backwards from the store and identifies the *last* clobbering instruction (the one closest to the store) as the insertion point, rather than scanning forward from the load to find the *first* clobbering instruction.

As a result, the compiler inserts the memory copy just before the last clobber, inadvertently placing it *after* an earlier clobber. This causes the newly inserted memory copy to read modified data instead of the original data present at the time of the load, leading to a miscompilation.

---

# Issue 133984

## Incomplete Removal of Alias Metadata During Memory Allocation Merging

**Description**:
The bug is triggered when an optimization pass merges two distinct memory allocations (such as stack allocations) into a single allocation. Because the two previously separate memory regions are combined, memory accesses (like loads, stores, or memory copies) that previously did not alias may now alias one another.

To maintain correctness, the compiler must invalidate or update alias-related metadata on the instructions accessing these allocations to reflect the new aliasing properties. The issue occurs when the optimization removes only a subset of the alias metadata (e.g., `noalias`) while leaving other alias-related metadata intact (such as `tbaa`, `tbaa.struct`, or `alias.scope`). The retained, now-stale metadata incorrectly informs subsequent analysis passes that the memory accesses still do not alias, leading to invalid optimizations and miscompilations later in the pipeline.

---

# Issue 70578

## Failure to Update Alias Metadata When Forwarding Memory Copies to ByVal Arguments

**Description**:
When an optimization pass forwards a memory copy's source directly to a function call that takes the copy's destination as a `byval` argument, it must ensure that the alias metadata on the call instruction is correctly updated.

If the original call instruction has alias metadata (such as `!alias.scope` or `!noalias`) that indicates it does not alias the source memory location, replacing the argument with the source directly without updating the metadata creates an inconsistency. The modified call now accesses the source memory location but retains metadata claiming it does not.

This incorrect aliasing information can mislead subsequent optimization passes, such as Dead Store Elimination (DSE), into incorrectly assuming that prior stores to the source memory location are dead and can be safely removed, resulting in a miscompilation. The issue is triggered when the optimization bypasses the memory copy but fails to combine or drop the alias metadata of the call instruction and the memory copy during the transformation.
