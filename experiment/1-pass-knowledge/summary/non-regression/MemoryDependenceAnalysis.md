# Subsystem Knowledge for MemoryDependenceAnalysis
## Elements Frequently Missed

* **Exact Memory Access Size in Cache Keys**: The caching mechanism in MemoryDependenceAnalysis frequently misses incorporating the exact access size as a strict constraint for cache reuse. It incorrectly assumes that reusing a cached dependence result with a larger access size is a safe, conservative fallback for a smaller access.
* **Undefined Behavior (UB) Boundaries**: The analysis misses the critical distinction between valid accesses and out-of-bounds (UB) accesses when sharing cache entries. By artificially inflating the size of a small, valid access to match a cached larger access, the analysis inadvertently crosses object boundaries.
* **Alias Analysis Context Sensitivity**: The pass misses the fact that Alias Analysis (AA) results can drastically change based on the size of the query. A larger size might trigger UB-based "no-alias" deductions (since OOB accesses cannot legally alias valid pointers), which are then incorrectly applied to smaller, valid accesses.

## Patterns Not Well Handled

### Pattern 1: Mixed-Size Accesses to the Same Base Pointer
This pattern occurs when a program accesses the exact same memory location (base pointer) using different types or sizes across different execution paths. For example, an `i16` load and an `i8` load might both target the same `i8` global variable via bitcasts.
**Why it is not well handled**: MemoryDependenceAnalysis caches dependence queries based primarily on the pointer. When it encounters the larger access first, it caches the dependence using that larger size. When it subsequently processes the smaller access, instead of invalidating the cache or treating the smaller access independently, it reuses the cached entry and evaluates the dependence using the larger size. This conflates the dependence properties of two distinct accesses and corrupts the analysis for the smaller access.

### Pattern 2: UB-Poisoning of Valid Memory Dependencies via Cache Reuse
This pattern involves a control flow graph where one branch contains an out-of-bounds (OOB) memory access (which is UB if executed), another branch contains a strictly valid, smaller access to the same pointer, and an intervening store to an unknown pointer exists before the branches.
**Why it is not well handled**: Alias Analysis can aggressively deduce that an OOB access does not alias with certain pointers because executing an OOB access is undefined behavior. When MemoryDependenceAnalysis reuses the larger (OOB) size to query dependencies for the smaller (valid) access, it incorrectly inherits this UB-driven "no-alias" deduction. As a result, the analysis falsely concludes that the intervening store cannot clobber the valid load. Optimization passes like Global Value Numbering (GVN) rely on this flawed dependence information to illegally forward values across the potentially aliasing store, leading to miscompilations.
