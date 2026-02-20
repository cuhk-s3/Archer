# Subsystem Knowledge for LoopAccessAnalysis

## Elements Frequently Missed

*   **Upper Bits of 64-bit Pointer Offsets**: The analysis frequently misses the upper 32 bits of 64-bit offsets in `getelementptr` instructions. When evaluating memory addresses, it fails to account for the full 64-bit value, causing large offsets to be misinterpreted.
*   **Target Pointer Index Types**: The analysis misses the strict adherence to the target's native pointer index size (e.g., `i64` on 64-bit architectures) during distance evaluation, improperly falling back to or truncating down to narrower integer types (e.g., `i32`).
*   **Non-Contiguous Accesses with Contiguous Lower Bits**: The analysis misses the true spatial relationship of memory accesses that are widely separated in memory but happen to have lower 32 bits that form a perfectly contiguous sequence (e.g., `0`, `8`, `16`, `24`).

## Patterns Not Well Handled

### Pattern 1: Truncation in Pointer Distance Calculation
When the compiler evaluates whether a sequence of memory operations (loads or stores) accesses consecutive memory locations, it calculates the differences between their pointer offsets. If the analysis incorrectly truncates these 64-bit differences into 32-bit integers, large gaps between addresses are masked. For example, offsets like `0x0`, `0x8`, `0x100000010`, and `0x100000018` will appear as `0`, `8`, `16`, and `24` after 32-bit truncation. This pattern is not well handled because the underlying arithmetic in the dependence or consecutive-access checks fails to account for integer truncation, deceiving the compiler into identifying a false contiguous stride.

### Pattern 2: Erroneous Vectorization of Widely Separated Scalar Memory Operations
Based on the flawed distance calculation described above, the compiler attempts to optimize scalar memory operations by combining them into a single vector memory operation (e.g., replacing multiple scalar `store` instructions with a single vector `store`). This pattern is poorly handled because the vectorizer lacks a robust secondary validation step to ensure the original scalar pointers strictly fall within the contiguous memory bounds of the newly generated vector pointer. Because the safety checks rely entirely on the truncated distance metrics, the compiler blindly merges the operations, resulting in data being read from or written to completely incorrect memory locations.