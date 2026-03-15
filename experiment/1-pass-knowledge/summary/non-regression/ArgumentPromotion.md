# Subsystem Knowledge for ArgumentPromotion
## Elements Frequently Missed

* **Memory Offsets and Sub-locations**: The optimization frequently misses the distinction between different offsets or sub-locations derived from the same base pointer argument. It treats the base pointer as a single entity for caching purposes, ignoring that different `getelementptr` instructions access distinct memory regions.
* **Location-Specific Alias Caching**: The pass misses the necessity of keying its "block transparency" (non-modifying status) cache by the exact memory location (base pointer + offset + size). Instead, it incorrectly keys the cache solely by the basic block, leading to false negatives in alias detection.
* **Intervening Stores to Partial Aliases**: Stores that modify only specific sub-locations of a pointer argument (e.g., storing to index 1 but not index 0) are missed. If the analysis evaluates a safe sub-location first, the store instruction is entirely ignored for subsequent, overlapping sub-locations.

## Patterns Not Well Handled

### Pattern 1: Multiple Loads at Different Offsets with Partial Block Modification
This pattern occurs when a function takes a pointer argument and performs multiple loads from it at different offsets (e.g., using `getelementptr` with different indices). Somewhere in the control flow preceding these loads, a basic block modifies the memory at one specific offset but leaves another offset untouched.

**Issues Caused:** The optimization analyzes the loads sequentially. If it first analyzes a load from an offset that is *not* modified by the block, it caches the block as "transparent." When it subsequently analyzes a load from an offset that *is* modified, it reuses the coarse-grained cache and skips the alias check. This results in the compiler invalidly promoting the pointer argument and passing stale, pre-loaded values instead of the correctly modified memory contents.

**Why it is not well handled:** The caching mechanism in the ArgumentPromotion pass is too coarse. It associates the "transparent" status with the basic block itself rather than the specific memory location (offset and size) being queried. The pass fails to invalidate or separate cache entries for different memory locations derived from the same underlying pointer argument.

### Pattern 2: Implicit Aliasing Between Global Variables and Promoted Arguments
This pattern involves a pointer argument that receives a global variable as its actual parameter. Within the function, a basic block directly stores to that global variable (or a specific offset of it) using its global identifier, rather than storing through the pointer argument itself. Later, the function loads from the pointer argument.

**Issues Caused:** Alias analysis is typically capable of detecting that the direct store to the global variable modifies the memory pointed to by the argument. However, because of the flawed caching mechanism triggered by multiple offsets, the alias query is bypassed entirely. The pass assumes the block is safe based on a previous check for a different offset, missing the aliasing store.

**Why it is not well handled:** The optimization pass assumes that once a block is deemed safe for one load derived from an argument, it is safe for all loads derived from that argument. It does not account for the fact that aliasing relationships (especially with global variables) are strictly tied to specific memory offsets and sizes, not just the general presence of a basic block.
