# Subsystem Knowledge for SROA
## Elements Frequently Missed

* **Padding Bits in Non-Standard Types**: Types with non-standard bit widths (e.g., `i6`) or structs with bitfields where the semantic data size is strictly less than the allocated byte size. The optimization pass frequently misses the fact that these "padding" bits might hold semantically meaningful data rather than just undefined garbage.
* **Discrepancy Between Data Size and Store Size**: The distinction between the actual number of bits used by a type (Data Size) and the number of bytes it occupies in memory (Store Size). SROA overlooks this discrepancy when converting byte-level operations to type-level operations.
* **Raw Byte-Level Semantics of Memory Intrinsics**: Intrinsics like `llvm.memcpy` operate on raw bytes, explicitly copying everything within the specified size, including padding. SROA misses the preservation of these raw byte semantics when promoting the intrinsics to typed `load` and `store` instructions.

## Patterns Not Well Handled

### Pattern 1: Replacing Raw Memory Copies with Typed Loads/Stores for Padded Types
This pattern occurs when SROA attempts to promote memory operations by replacing `llvm.memcpy` (or similar memory intrinsics) with direct, typed `load` and `store` instructions based on the underlying `alloca` type.

**Issue Caused**: When the allocated type contains padding bits (e.g., an `i6` type occupying a full 8-bit byte in memory), the typed `load` and `store` instructions only copy the valid value bits defined by the type and ignore the padding. If the original `memcpy` was sized to copy the entire byte, replacing it with a typed access silently drops the data residing in the padding bits, leading to data loss and miscompilation.

**Why it is not well handled**: The optimization pass assumes that padding bits within an allocated type are undefined or dead, and therefore safely ignorable. It fails to compare the explicit byte size of the `memcpy` against the semantic data size of the type. Because it does not verify whether the raw copy covers potentially live padding bits, it incorrectly applies the transformation.

### Pattern 2: Implicit Type Punning and Union-Like Memory Accesses
This pattern involves memory that is allocated with a specific type (like a padded integer or struct) but is written to or read from using raw byte operations (`memcpy`) to interact with another memory region of a potentially different type.

**Issue Caused**: This pattern often represents implicit type punning or union behavior, where the "padding" of one type overlaps with valid data of another type (e.g., an array of bytes). When SROA promotes the `alloca` to an SSA register using the allocated type, it destroys the overlapping data stored in the padding, breaking the type punning semantics.

**Why it is not well handled**: SROA relies heavily on the declared type of the `alloca` to dictate the semantics and bit-width of the promoted SSA values. It lacks robust checks to detect when memory is being used in a type-agnostic or punned manner via raw byte copies. Consequently, it incorrectly enforces the strict boundaries of the allocated type on memory regions that are being utilized for broader, byte-level data storage.
