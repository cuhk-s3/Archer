# Subsystem Knowledge for unknown
## Elements Frequently Missed

*   **Poison-Generating Flags (`nuw`, `nsw`, `exact`)**: These flags are frequently missed or ignored during instruction hashing and equivalence comparisons (e.g., in Global Value Numbering). This omission causes the compiler to treat instructions with different strictness levels as identical.
*   **Undefined Values (`undef`)**: The non-deterministic nature of `undef` is often missed during instruction expansion or operand duplication. Compilers fail to recognize that multiple uses of the same `undef` value can evaluate to different concrete values if not explicitly frozen.
*   **Implicit Memory Writes**: Memory accesses performed implicitly by runtime environments (such as exception handling personality functions writing to SEH catch objects) are missed because they lack explicit representation in the LLVM IR prior to their use.
*   **Specific Offsets in Alias Analysis**: Fine-grained offset values are frequently dropped or ignored when merging partial alias results from different control flow paths, reducing the precision of the analysis to a generic "partial alias" state.
*   **TBAA Metadata Mismatches**: The semantic difference between Type-Based Alias Analysis (TBAA) tags on loads and stores to the same memory location is missed, leading the compiler to incorrectly assume they do not alias.
*   **Precomputed Structural Metadata**: During dynamic format upgrades (e.g., switching from 32-bit to 64-bit archive formats), previously computed structural metadata (like string table offsets) is missed and not recalculated, leading to malformed outputs.
*   **Specific Relocation Types**: The unique relocation math required for specific Thread-Local Storage (TLS) models (like `local-exec`) is missed during object file emission, resulting in default or zeroed offsets.

## Patterns Not Well Handled

### Pattern 1: Unsafe Operand Duplication Involving `undef`
Transformations that optimize complex instructions by breaking them down into simpler, multi-instruction sequences (such as converting an unsigned remainder into a comparison and a select) often duplicate the original operands. This pattern is not well handled because it fails to account for the semantics of `undef`. If an un-frozen `undef` operand is duplicated, each use can independently evaluate to a different concrete value. This breaks the mathematical invariants of the original instruction (e.g., a remainder returning a value larger than the divisor) and leads to silent miscompilations.

### Pattern 2: Improper Handling of Metadata and Flags During Code Motion and Merging
When the compiler merges identical instructions or moves instructions across the IR (such as pushing `freeze` instructions to operands), it frequently mishandles value-restricting metadata (`!range`, `!nonnull`) and poison-generating flags. This pattern causes issues because the compiler either incorrectly propagates restrictive flags to execution paths where they do not belong, or infers strict metadata based on the properties of pre-transformed (potentially poison) operands. When the transformed code executes, it violates these improperly applied constraints, generating `poison` or triggering aggressive, invalid downstream simplifications.

### Pattern 3: Over-Reliance on Explicit IR for Memory and Lifetime Analysis
Optimization passes like stack coloring and memory dependence analysis rely heavily on explicit IR instructions to determine variable lifetimes and memory clobbers. This pattern is poorly handled when runtime mechanisms (like SEH unwinding) perform implicit memory writes before any explicit IR instruction references the memory, or when TBAA metadata mismatches trick the alias analysis into returning `NoAlias` for overlapping accesses. Because the analyses trust the explicit IR and metadata blindly, they incorrectly merge overlapping stack slots or bypass valid stores, resulting in corrupted memory or loads being incorrectly resolved to uninitialized memory (`undef`).

### Pattern 4: Loss of Precision in Aggregated Analyses
When the compiler aggregates data from multiple sources—such as merging alias analysis results from different branches of a PHI node or `select` instruction—it often simplifies the data to a lowest common denominator. This pattern is not well handled because critical fine-grained information, such as specific memory offsets in partial aliases, is discarded. Downstream memory optimization passes (like Dead Store Elimination or GVN) then operate on this overly broad and inaccurate information, leading to invalid reordering of memory accesses or the erroneous elimination of necessary stores.

### Pattern 5: Desynchronization of Precomputed State During Emission
In the backend and object emission phases, the compiler sometimes computes structural or relocation data early in the pipeline, but fails to update this data if the underlying context changes. This pattern is evident when an archive dynamically upgrades from a 32-bit to a 64-bit format due to size constraints, but the writer continues to use the 32-bit precomputed offsets. Similarly, it occurs when the emitter fails to apply the correct relocation calculations for specific TLS models. This desynchronization results in malformed binary structures, corrupted archives, and incorrect memory offsets at runtime.
