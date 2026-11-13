# Subsystem Knowledge for SROA
## Elements Frequently Missed

* **Padding Bits in Non-Standard Types**: Types where the actual data size is strictly less than the memory store size (e.g., non-standard integers like `i6`, or structs containing bitfields). The optimization pass frequently misses the fact that these "padding" bits can contain live, semantically meaningful data.
* **Byte-Level Semantics of Memory Intrinsics**: Intrinsics like `llvm.memcpy` operate on raw bytes rather than typed values. The pass misses the critical distinction between copying raw bytes (which preserves padding) and copying typed values (which discards padding).
* **Type Punning and Union Memory Accesses**: Memory regions that are accessed via multiple types (e.g., written as a byte array, but allocated as a struct with padding). The pass frequently misses the implicit data dependencies hidden within the padding bits during type punning.

## Patterns Not Well Handled

### Pattern 1: Replacing Raw Memory Copies with Typed Loads/Stores for Padded Types
**Description**:
This pattern occurs when an `alloca` is created for a type that contains padding bits (where the data size is smaller than the store size). A raw memory copy (`llvm.memcpy`) is then used to copy data into or out of this allocation, with the copy size explicitly covering the full byte size of the memory region (including the padding). SROA attempts to optimize this by replacing the raw `memcpy` with a direct, typed `load` and `store` of the allocated type.

**Issues Caused**:
This transformation causes silent data loss. Because the optimization replaces a raw byte-level copy with a typed operation, only the valid value bits defined by the specific LLVM IR type are preserved. The padding bits, which were correctly copied by the original `memcpy`, are ignored and lost. If the underlying memory is part of a union or is later accessed via a different type (such as an array of bytes), the lost padding bits result in corrupted data and miscompilation.

**Why it is not well handled**:
SROA aggressively attempts to promote memory to registers by assigning a specific LLVM IR type to the memory region. In doing so, it incorrectly assumes that the allocated type's value bits represent the entirety of the live data in that memory region. The pass fails to account for the fact that raw memory intrinsics bypass type-level semantics and operate on the full allocated byte size. It lacks the necessary checks to prevent promotion to typed loads/stores when the memory operation size exceeds the strict data size of the chosen type.
