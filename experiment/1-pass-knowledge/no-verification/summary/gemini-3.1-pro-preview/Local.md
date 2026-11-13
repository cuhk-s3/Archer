# Subsystem Knowledge for Local
## Elements
 Frequently Missed

*   **Attribute/Flag Reconciliation**: When replacing one instruction with
 another (or merging them), the pass often fails to perform a "least-common-denominator" intersection of metadata,
 attributes (`nonnull`, `range`), and wrapping flags (`nsw`, `nuw`). This leads to the introduction
 of poison where it did not previously exist.
*   **External Address-Taken References**: The pass frequently fails to account for
`blockaddress` or other symbolic references to IR blocks/values when modifying control-flow structures. The optimization assumes internal consistency
 while ignoring the external requirements of the runtime/ABI.
*   **Analysis Cache Invalidation**: The pass lacks a
 mechanism to notify internal caches or state trackers when instruction memory is reclaimed. This causes "use-after-free" logic errors
 where new instructions inherit incorrect analysis data from stale pointers.
*   **Contextual Reachability vs. Structural Reachability**: Transformations
 often assume that because a successor is reachable via a new path, the old paths (or the original jump target) are implicitly handled or irrelevant
, failing to verify if the original target is still required by address-taken constants or secondary control flows.

## Patterns
 Not Well Handled

### Pattern 1: Control Flow Threading with Indirect Branch Dependencies
This pattern occurs when transforming
 `indirectbr` instructions or the blocks they target. The pass attempts to perform local CFG simplification without reconciling the global requirements
 of `blockaddress` constants. By redirecting an `indirectbr` to a new block, the pass creates a mismatch
 between the IR's control-flow edges and the actual addresses the program expects to branch to. This is exacerbated when
 PHI nodes or multiple incoming paths exist, as the pass treats the control-flow graph as purely structural, ignoring the semantic
 necessity of the original destination addresses.

### Pattern 2: Semantic Poison Injection during Substitution
This pattern arises during CSE
, GVN, or InstCombine when replacing an operation that is "safe" (e.g., `extractvalue` from
 an overflow intrinsic) with an operation that carries implicit assumptions (e.g., standard binary ops with `nsw`/`nuw`).
 The pass focuses on functional equivalence (the result value) but fails to account for the "poison-potential" of the replacement
. Because the pass does not explicitly strip flags or intersect return attributes, it essentially upgrades the instruction's contract, leading
 to undefined behavior if the inputs violate the new, stricter assumptions.

### Pattern 3: Optimistic Transformation with St
ale State
This pattern involves the interaction between instruction lifecycle management (deletion/replacement) and persistent analysis structures. When the
 pass performs aggressive deduplication (such as PHI removal), it acts locally on the IR without triggering a global update or
 cache invalidation. Because the optimization pass maintains internal caches keyed by memory addresses, the pattern of "delete and re-allocate
" triggers a collision where the pass unknowingly uses data from a previous iteration for a logically unrelated new instruction, leading to silently
 corrupted analysis results.
