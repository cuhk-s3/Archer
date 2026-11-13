# Subsystem Knowledge for Loads
## Elements Frequently Missed

* **Vectors of Pointers**: The optimization pass's safety validation logic frequently misses vector types that contain pointers (e.g., `<4 x ptr>`). It incorrectly assumes that only scalar pointer types require strict provenance checks, treating pointer vectors as standard non-pointer types.
* **Pointer Provenance in Vector Operations**: The strict provenance rules—dictating that two pointers may hold the exact same memory address but originate from different allocations—are overlooked when pointers are packed into and manipulated as vector elements.

## Patterns Not Well Handled

### Pattern 1: Equality-Based Replacement of Pointer Vectors
The optimization pass attempts to fold or replace values based on equality conditions, such as optimizing a `select` instruction that is driven by an `icmp eq` between two vectors of pointers. While replacing values based on equality is perfectly safe for simple scalar types like integers, it violates strict provenance rules for pointers. Replacing one pointer vector with another simply because their underlying addresses match can lead to the loss or incorrect alteration of the original pointer provenance. This is not well handled because the compiler's safety validation logic fails to recognize the vector as a pointer type, thereby bypassing the necessary provenance checks and unconditionally allowing the unsafe replacement, which can cause invalid memory accesses in later compilation stages.

### Pattern 2: Incomplete Type Classification in Safety Validation
The logic used to validate whether a type requires special handling (such as provenance checks before substitution) only explicitly checks for scalar pointer types. It defaults to treating other composite types, specifically vectors, as safe for unconditional replacement. This causes vectors of pointers to be incorrectly classified as non-pointer types. This pattern is not well handled because the type-checking mechanism lacks comprehensive checks for vector elements (e.g., failing to use checks like `isPtrOrPtrVectorTy()` instead of just `isPointerTy()`), creating a critical blind spot when the compiler handles vectorized memory operations and pointer arithmetic.
