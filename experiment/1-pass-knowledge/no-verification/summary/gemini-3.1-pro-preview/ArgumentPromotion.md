# Subsystem Knowledge for ArgumentPromotion
## Elements Frequently Missed

* **Memory Offsets and Sub-locations**: The optimization pass frequently misses the distinction between different memory offsets (e.g., accessed via `getelementptr` instructions) derived from the same base pointer argument. It treats the base pointer as a single entity during caching, ignoring the fine-grained sub-locations.
* **Location-Specific Block Transparency**: The caching mechanism misses the required granularity to track whether a basic block is "transparent" (non-modifying) for a *specific memory location*. It incorrectly caches transparency at the block level rather than the block-and-location level.
* **Partial Modifying Stores**: Store instructions that modify only a specific sub-location of a pointer argument are overlooked. If a block is previously cached as transparent during the analysis of a different, unmodified sub-location, the pass completely misses the store that modifies the current sub-location.

## Patterns Not Well Handled

### Pattern 1: Multiple Loads at Different Offsets from a Single Pointer Argument
This pattern occurs when a function receives a pointer argument (such as a struct pointer) and performs multiple loads from it using different offsets to access various fields. The ArgumentPromotion pass analyzes these loads sequentially to ensure no modifications occur before them. However, because the pass caches the "transparent" status of basic blocks without tying that status to the specific offset being analyzed, the alias analysis for subsequent loads at different offsets is incorrectly bypassed. This leads to the pass conflating the safety of one memory location with the safety of another.

### Pattern 2: Partial Memory Modification within a Basic Block
This pattern involves a basic block on the control flow path that contains a store instruction modifying only a specific offset of a pointer argument, while leaving other offsets of that same pointer untouched. If the optimization pass first evaluates a load corresponding to the untouched offset, it correctly determines that the block does not modify that specific memory and caches the block as "transparent." When the pass subsequently evaluates a load corresponding to the modified offset, it reuses the flawed cache entry. As a result, it ignores the modifying store, skips the necessary alias checks, and invalidly promotes the pointer argument, causing the compiled code to use stale, pre-loaded values instead of the updated memory contents.
