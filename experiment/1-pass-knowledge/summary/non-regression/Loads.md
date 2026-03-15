# Subsystem Knowledge for Loads
## Elements Frequently Missed

* **Vectors of Pointers (`<N x ptr>`)**: The safety validation logic frequently misses vector types that contain pointers. It often checks strictly for scalar pointer types, incorrectly classifying pointer vectors as non-pointer types (similar to integers) and bypassing necessary pointer-specific checks.
* **Pointer Provenance in Vectorized Operations**: The strict provenance rules—dictating that two pointers may hold the same memory address but originate from different allocations—are frequently overlooked when pointers are packed into vectors.

## Patterns Not Well Handled

### Pattern 1: Equality-Based Replacement of Pointer Vectors
**Description**: The optimization pass attempts to fold or replace one vector of pointers with another based on an equality condition, such as folding a `select` instruction driven by an `icmp eq` between two pointer vectors.
**Issues Caused**: This pattern leads to miscompilations where the original pointer provenance is lost or incorrectly altered. Because two pointers can have the same address but different provenances, replacing one with the other can cause invalid memory accesses (such as illegal Loads) later in the compilation pipeline.
**Why it is not well handled**: The compiler applies integer-based folding rules to pointer vectors. Because the safety validation logic fails to recognize the vector as a pointer type, it bypasses the strict provenance checks that would normally prevent this unsafe replacement.

### Pattern 2: Incomplete Type Validation for Pointer Constraints
**Description**: The compiler uses scalar-specific type checks (e.g., checking if a value is strictly a scalar pointer) rather than comprehensive checks that account for vectors of pointers (e.g., failing to use checks like `isPtrOrPtrVectorTy()`).
**Issues Caused**: Safety mechanisms designed to protect memory operations and pointer integrity are silently skipped for vector types.
**Why it is not well handled**: The type-checking logic is not fully generalized to handle LLVM's orthogonal type system, where pointers can be elements of vectors. This creates a blind spot in the optimization pass where scalar pointers are safely constrained, but vectors of pointers are incorrectly treated as simple data types.
