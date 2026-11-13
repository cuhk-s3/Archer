# Issue 97702

## Incorrect Promotion of Uninitialized Memory Load to Poison in Single-Store Allocations

**Description**
The bug is triggered by exploiting the memory-to-register promotion logic for allocations (`alloca`) that only have a single store operation. The strategy involves the following steps:

1. **Create an Allocation**: Define a local memory allocation in the entry block of a function.
2. **Introduce Branching Control Flow**: Create multiple control flow paths (e.g., using a conditional branch).
3. **Perform a Single Store with a Poison Value**: On one of the control flow paths, perform exactly one store operation to the allocated memory. The value being stored must be `poison` or an operation that can evaluate to `poison` (such as an out-of-bounds memory access).
4. **Bypass the Store**: On another control flow path, do not perform any store operations to the allocation, leaving the memory uninitialized.
5. **Load from the Allocation**: Merge the control flow paths and perform a load operation from the allocated memory.

When the compiler's memory promotion pass processes this pattern, it identifies that there is only a single store to the allocation in the entire function. It then attempts to optimize the code by replacing all loads from the allocation directly with the stored value.

This transformation is incorrect because the load instruction can be reached via the path where the store was never executed. On that path, the load reads uninitialized memory, which should evaluate to `undef`. By replacing the load with the stored `poison` value, the compiler incorrectly upgrades an `undef` value to `poison`. Since `poison` is a more restrictive and less defined state than `undef`, this substitution violates IR semantics and results in a miscompilation.
