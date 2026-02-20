# Subsystem Knowledge for Loads

## Elements Frequently Missed

* **Vector of Pointers (`<N x ptr>`)**: The optimization pass's type-checking logic frequently misses vector types when checking for pointer properties. It often only checks for scalar pointer types (e.g., using `isPointerTy()` instead of `isPtrOrPtrVectorTy()`), causing vectors of pointers to be incorrectly classified and treated as non-pointer types (like standard integers).
* **Pointer Provenance in Non-Scalar Types**: The strict provenance rules—which dictate that two pointers may hold the exact same memory address but originate from entirely different allocations—are frequently overlooked when the pointers are packed inside a vector. The compiler misses the necessary provenance validation checks for these composite types.

## Patterns Not Well Handled

### Pattern 1: Equality-Based Replacement of Pointer Vectors
The optimization pass attempts to simplify and fold `select` instructions that are driven by an `icmp eq` (equality comparison) between two vectors of pointers. For example, if the code checks whether `<2 x ptr> %p` equals `<2 x ptr> %q`, the optimizer tries to replace all selected instances of `%p` with `%q`. 

**Issues Caused**: This pattern causes miscompilations because it violates strict pointer provenance rules. Replacing one pointer with another solely based on address equality strips or alters the original pointer's provenance. When subsequent `load` or `store` instructions attempt to access memory using the replaced pointer vector, the compiler's alias analysis may incorrectly assume the memory access is invalid or does not alias with the original allocation, leading to illegal memory optimizations or crashes.

**Why it is not well handled**: The underlying safety validation logic is incomplete. While the compiler correctly prevents equality-based substitution for scalar pointers by enforcing provenance checks, the logic fails to generalize to vector types. Because the type-checker does not recognize `<N x ptr>` as a pointer type requiring provenance preservation, it bypasses the safety checks entirely and unconditionally allows the unsafe replacement.