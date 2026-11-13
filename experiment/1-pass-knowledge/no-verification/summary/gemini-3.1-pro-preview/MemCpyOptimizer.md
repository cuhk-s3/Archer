# Subsystem Knowledge for MemCpyOptimizer
## Elements Frequently Missed

*   **Comprehensive Alias Metadata (`tbaa`, `tbaa.struct`, `alias.scope`)**: While the optimization pass might remember to drop basic metadata like `noalias` during memory transformations, it frequently misses other critical alias-related metadata. This leaves stale aliasing information attached to instructions.
*   **Call Site Metadata During Argument Forwarding**: When a memory copy is bypassed and its source is forwarded directly to a function call (e.g., as a `byval` argument), the pass frequently misses the need to update or drop the alias metadata attached to the call instruction itself.
*   **The First Clobbering Instruction**: When analyzing the memory dependency chain between a load and a store, the pass frequently misses the *first* instruction that clobbers the source memory. Because the analysis scans backwards from the store, it incorrectly stops at the *last* clobbering instruction instead.

## Patterns Not Well Handled

### Pattern 1: Incomplete Alias Metadata Invalidation During Memory Transformations
When the MemCpyOptimizer performs transformations that alter memory access targets or combine memory regions—such as merging two distinct stack allocations or forwarding a `memcpy` source directly to a `byval` function argument—the aliasing properties of the involved memory locations fundamentally change. Accesses that previously did not alias may now alias.

This pattern is not well handled because the pass often applies a piecemeal approach to metadata cleanup rather than a holistic one. It might successfully strip `noalias` tags but leave behind `tbaa`, `tbaa.struct`, or `alias.scope` metadata. Similarly, it might update the operands of a call instruction but forget to intersect or drop the metadata on the call instruction itself. As a result, stale metadata survives the transformation, falsely informing subsequent passes (like Dead Store Elimination) that certain memory accesses do not overlap. This leads to aggressive and incorrect optimizations, such as deleting stores that are actually still required.

### Pattern 2: Flawed Dependency Scanning for Instruction Insertion
When the optimizer attempts to promote a load-store pair (often involving aggregate types) into a direct memory copy (`memcpy` or `memmove`), it must find a safe insertion point for the new instruction. To maintain semantic correctness, the memory copy must be placed before any instruction that modifies (clobbers) the source memory.

This pattern is poorly handled when there are *multiple* clobbering instructions between the original load and store. The pass relies on a flawed backward-scanning heuristic, searching from the store upwards. Consequently, it identifies the *last* clobber (the one closest to the store) as the insertion point, rather than scanning forward from the load to find the *first* clobber. This logic error causes the compiler to insert the new memory copy after earlier clobbers have already executed, resulting in the `memcpy` reading modified, incorrect data instead of the original data captured by the initial load.
