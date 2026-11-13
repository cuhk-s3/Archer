# Subsystem Knowledge for Evaluator
## Elements Frequently Missed

* **Memory Intrinsic Size/Length Arguments**: The Evaluator frequently misses or ignores the `len` (size) argument of memory-setting intrinsics (like `llvm.memset`) when verifying if the memory operation is redundant. It fails to ensure that the redundancy check covers the entire specified length.
* **Subsequent Bytes/Elements in Global Initializers**: When inspecting the destination memory of a write operation, the Evaluator frequently misses the values of subsequent bytes or elements, erroneously relying solely on the value of the first byte or element at offset zero.
* **Heterogeneous Aggregate Initializers**: Complex initializers for arrays, vectors, or structs that contain a mix of different values (e.g., where the first element is zero but the following elements are non-zero) are frequently mishandled during compile-time evaluation of memory overwrites.

## Patterns Not Well Handled

### Pattern 1: Flawed Redundancy Elimination for Memory-Setting Intrinsics
When the Evaluator processes memory-setting intrinsics (such as `llvm.memset`) during the compile-time evaluation of global constructors, it attempts to optimize away the intrinsic if it believes the destination memory already contains the target value. However, this pattern is poorly handled because the Evaluator performs a shallow, partial check: it only inspects the first byte or element of the destination. If the first byte matches the value being set, the Evaluator incorrectly concludes that the entire memory range already matches and drops the intrinsic as a no-op. This causes a miscompilation where the rest of the memory range is never updated.

### Pattern 2: Bulk Overwriting of Mixed-Value Global Variables
A common pattern involves a global variable that is statically initialized with a mix of values (e.g., `[2 x i32] [i32 0, i32 1]`) and is subsequently overwritten by a bulk memory operation in a global constructor (e.g., zeroing out the entire array). The Evaluator fails to properly simulate this bulk overwrite because it assumes the static initializer's first element is representative of the entire variable's state. Consequently, the Evaluator skips the memory operation, leaving the global variable partially updated and allowing stale, non-matching data to persist in the subsequent bytes of the global variable.
