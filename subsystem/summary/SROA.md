## Elements Frequently Missed

*   **Non-Standard Integer Types with Padding**: Types such as `i6`, `i9`, or `i24` where the logical bit-width is smaller than the physical storage size (store size). The optimization pass frequently overlooks that the "padding" bits between the logical width and the storage width are not guaranteed to be preserved by typed instructions.
*   **Data Persistence in Padding Regions**: The assumption that bits residing in the padding region of a variable are "garbage" or undefined. In the context of unions or bitcasts, these bits often contain valid data belonging to other overlapping members, which is missed when converting memory operations to typed scalar operations.
*   **Semantic Distinction Between `memcpy` and Typed `store`**: The fundamental difference between `memcpy` (which preserves all bits in the memory range, including padding) and a typed `store` (which only preserves bits defined by the type's logical width). The pass misses that replacing the former with the latter is lossy for types with padding.

## Patterns Not Well Handled

### Pattern 1: Conversion of `memcpy` to Typed Store on Union Members with Padding
This pattern occurs when SROA attempts to scalarize an aggregate `alloca` (typically representing a `union`) that contains a member with a non-standard integer type (e.g., `i6` stored in a byte). When the original IR contains a `memcpy` writing to this memory location, SROA optimizes it by converting the `memcpy` into a `load` and a typed `store` of the scalar type.

**Why it is not well handled**: The optimization fails to account for the physical storage layout. A `memcpy` of 1 byte writes 8 bits of data. However, a `store i6` only defines the lower 6 bits; the upper 2 bits (padding) are not preserved or are implicitly zeroed/undefined by the typed operation. If the memory is later accessed via a different type (e.g., reading the full `i8` via a different union member), the data in the padding bits is lost or corrupted, leading to a value mismatch compared to the unoptimized code.