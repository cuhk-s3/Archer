# Subsystem Knowledge for MemoryDependenceAnalysis

## Elements Frequently Missed

* **Access Size in Cache Lookups**: The dependence cache relies heavily on the base pointer but frequently misses or mishandles the exact access size during cache reuse. It fails to recognize that a cached dependence result for a larger size is not universally applicable to a smaller size.
* **Strict Aliasing and UB Isolation**: The analysis misses the need to isolate Undefined Behavior (UB) assumptions (such as those derived from out-of-bounds sizes) from valid accesses. It allows UB-derived aliasing conclusions to bleed into strictly valid memory operations that share the same base pointer.
* **Cache Invalidation for Size Reductions**: The mechanism to invalidate, bypass, or re-evaluate cached dependence results when a subsequent query uses a strictly smaller, valid size is missing. Instead, the analysis conservatively and incorrectly restarts the query using the larger size from the cache.

## Patterns Not Well Handled

### Pattern 1: Mixed-Size Memory Accesses to the Same Base Pointer
When the LLVM IR contains multiple memory operations (loads or stores) targeting the exact same base pointer but using different access sizes (e.g., casting an `i8*` to an `i16*` for a larger load, alongside a standard `i8` load), the caching mechanism conflates their dependence queries. MemoryDependenceAnalysis caches the dependence result using the size of the first analyzed access. When a subsequent access with a smaller size queries the cache, the analysis incorrectly reuses the cached entry and its larger size instead of evaluating the smaller access independently. This leads to downstream optimization passes receiving inaccurate clobbering or aliasing information.

### Pattern 2: Cache Poisoning via Out-of-Bounds (UB) Accesses
This pattern occurs when a larger memory access reads or writes past the valid bounds of an underlying object (e.g., loading 2 bytes from a 1-byte global variable), and is followed by a valid, in-bounds access to the same object on a different control flow path. The out-of-bounds access triggers aggressive, UB-based alias analysis assumptions (e.g., assuming an intervening store cannot alias because the large load implies a different object structure or size). These aggressive assumptions are cached. When the valid, smaller access is analyzed, it inherits these flawed, UB-based assumptions from the cache. This leads to severe miscompilations, such as Global Value Numbering (GVN) incorrectly forwarding stale values or eliminating necessary memory operations because it falsely believes an intervening store does not clobber the valid load.