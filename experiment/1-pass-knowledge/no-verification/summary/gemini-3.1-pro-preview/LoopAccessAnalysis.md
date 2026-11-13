# Subsystem Knowledge for LoopAccessAnalysis
## Elements Frequently Missed

*   **Pointer Offset Bit-Widths and Truncation**: The analysis frequently misses the actual bit-width requirements of pointer offsets (e.g., 64-bit vs. 32-bit). By unsafely truncating 64-bit pointer differences into 32-bit integers during consecutive access checks, it loses critical information about the upper bits, masking large memory distances.
*   **Execution Context of Memory Accesses (Conditional vs. Unconditional)**: The analysis fails to distinguish between memory accesses that are guaranteed to execute and those that are conditionally bypassed. It incorrectly applies properties derived from conditionally executed instructions (like no-wrap flags) globally to the entire loop.
*   **Loop Context of SCEV Add-Recurrences**: When evaluating pointer arithmetic, the analysis misses the explicit verification of which specific loop (e.g., inner vs. outer loop in a nest) a Scalar Evolution (SCEV) add-recurrence belongs to, leading to flawed difference-based calculations.
*   **Loop-Variance of Underlying Objects**: The analysis overlooks whether the base pointer or underlying object of a memory access is loop-invariant or loop-variant (e.g., loaded from memory inside the loop). It assumes static bounds can be generated for objects that actually change dynamically per iteration.
*   **Scope and Lifetime of Alias Metadata**: The analysis misses the declaration location of scoped alias metadata (e.g., `!alias.scope`). It fails to recognize that metadata declared *inside* the loop body provides only iteration-local guarantees, not cross-iteration guarantees.

## Patterns Not Well Handled

### Pattern 1: Large Non-Contiguous Memory Accesses Mimicking Contiguity
When memory operations use 64-bit pointer offsets where the lower 32 bits form a contiguous sequence but the upper 32 bits are non-zero and non-contiguous, the analysis mishandles the distance calculation. By truncating the 64-bit pointer differences to 32 bits, the compiler is deceived into seeing strictly adjacent memory accesses. This causes the analysis to incorrectly combine separate scalar memory operations into a single contiguous vector memory operation, leading to miscompilations where data is accessed at the wrong memory locations.

### Pattern 2: Conditionally Dereferenced Pointers with No-Wrap Flags
When a loop contains a conditionally executed memory access using a pointer derived from an instruction with a no-wrap flag (like `inbounds` or `nusw`), the analysis incorrectly assumes the pointer never wraps under any circumstance. It fails to account for the fact that if the conditional access is bypassed, the pointer might wrap and safely yield a poison value without causing undefined behavior. Applying this no-wrap assumption globally leads to flawed dependence distance calculations and unsafe loop transformations like invalid vectorization or load forwarding.

### Pattern 3: Cross-Loop Address Recurrences in Nested Loops
In nested loop structures, memory accesses may use pointers derived from different induction variables (e.g., one loop-invariant pointer derived from the outer loop, and one derived from the inner loop). When attempting to create difference-based runtime pointer checks for the innermost loop, the analysis assumes all SCEV add-recurrences belong to the loop currently being analyzed without explicitly verifying this property. This mismatch in loop context causes the compiler to miscalculate or silently drop required runtime alias checks, allowing unsafe vectorization of overlapping memory regions.

### Pattern 4: Indirect Memory Accesses with Loop-Variant Base Pointers
When a loop contains indirect memory accesses where the base pointer is loaded from memory during each iteration, the underlying object is loop-variant. The analysis mishandles these unknown, dynamic dependencies by attempting to generate runtime memory dependence checks. Because the base pointers change across iterations, the compiler cannot accurately determine memory bounds or dependence distances. This results in the generation of flawed runtime checks or the incorrect assumption that the accesses are safe, leading to invalid optimizations when the pointers alias at runtime.

### Pattern 5: Iteration-Local Scoped Alias Metadata in Cross-Iteration Analysis
When a loop contains memory accesses annotated with scoped alias metadata (like `!alias.scope` and `!noalias`) and the scopes are explicitly declared inside the loop body, the non-aliasing guarantees are strictly iteration-local. The analysis mishandles this pattern by erroneously applying these single-iteration guarantees to cross-iteration memory dependence checks. This flawed cross-iteration analysis masks true loop-carried dependencies, deceiving the compiler into performing illegal and unsafe loop transformations.
