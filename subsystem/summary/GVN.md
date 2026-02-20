# Subsystem Knowledge for GVN

## Elements Frequently Missed

*   **Call Return Attributes**: Restrictive return attributes on function calls or intrinsics (such as `nonnull`, `range`, `align`, or `dereferenceable`) are frequently missed during equivalence checks. GVN identifies the calls as computing the same value but overlooks the fact that these attributes alter the semantics of the return value.
*   **Poison-Generating Semantics**: The context-sensitive nature of `poison` values is often overlooked. An attribute that is safe and well-defined in a dominating block may evaluate to `poison` in a dominated block due to different control flow conditions.
*   **Cache Invalidation Signals**: Notifications or callbacks for instruction deletion are frequently missed when utility functions (like PHI deduplication) modify the IR. The overarching GVN pass is not alerted that an instruction has been removed.
*   **Instruction Memory Addresses (The ABA Problem)**: The reuse of memory addresses by the allocator is missed by internal analysis caches. Because caches use raw memory pointers as keys, a newly allocated instruction can accidentally inherit the cached analysis data of a previously deleted instruction.

## High-Level Patterns Not Well Handled

### Pattern 1: Incomplete Attribute Reconciliation during Call Replacement
When GVN or CSE identifies two identical function calls where one dominates the other, it routinely replaces the dominated call with the dominating one to save computation. However, the pass handles this replacement poorly when the dominating call possesses more restrictive return attributes than the dominated call. Instead of computing the safe intersection of the attributes or stripping the incompatible ones, GVN blindly substitutes the value. If the restrictive attributes of the dominating call are violated under the control flow path of the dominated call, it generates a `poison` value. This pattern leads to miscompilations where the optimized program propagates `poison` to uses that were perfectly well-defined in the original IR.

### Pattern 2: Silent IR Mutation and Stale Analysis Caches
GVN relies heavily on internal analysis caches (such as Memory Dependence Analysis or Value Numbering) to speed up optimization, typically keying these caches using the memory addresses of the `Instruction` objects. A high-level pattern that is poorly handled is the interaction between GVN and localized IR simplification utilities, such as PHI node deduplication. When these utilities silently delete instructions and free their memory without notifying the GVN pass, the caches are left with dangling pointers. If the compiler's memory allocator subsequently places a new instruction at the exact same memory address, GVN queries its cache, finds a "hit" using the stale pointer, and applies incorrect optimizations based on the deleted instruction's data flow or memory dependencies.