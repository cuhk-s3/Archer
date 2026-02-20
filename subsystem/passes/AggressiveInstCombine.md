# Issue 118467

## Incorrect Offset Truncation During Consecutive Load Folding

**Description:**
The bug is triggered when the compiler attempts to optimize a sequence of consecutive memory loads by folding them into a single, wider memory load. 

1. **Pattern:** A program performs multiple consecutive loads from memory using a base pointer and a large constant offset. The offset is valid for the target's native pointer index type (e.g., 64 bits) but is large enough that its sign bit would be set if it were represented as a smaller fixed-width integer (e.g., a 32-bit integer).
2. **Optimization Logic:** To compute the starting address for the new wider load, the compiler strips and accumulates the constant offsets from the original base pointer. 
3. **Flaw:** During the reconstruction of the new pointer address, the compiler incorrectly instantiates the accumulated constant offset as a smaller fixed-width integer (e.g., 32 bits) instead of preserving the original pointer index type's bit width. 
4. **Consequence:** Because the offset's value has the sign bit set in this truncated representation, it gets incorrectly sign-extended when applied to the new pointer arithmetic. This alters the actual value of the offset (e.g., turning a large positive offset into a negative one), causing the wider load to read from the wrong memory address and resulting in a miscompilation.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define i64 @test(ptr %base) {
entry:
  %gep1 = getelementptr i8, ptr %base, i64 2147483648
  %load1 = load i32, ptr %gep1, align 4
  %gep2 = getelementptr i8, ptr %base, i64 2147483652
  %load2 = load i32, ptr %gep2, align 4
  %ext1 = zext i32 %load1 to i64
  %ext2 = zext i32 %load2 to i64
  %shl = shl i64 %ext2, 32
  %or = or i64 %ext1, %shl
  ret i64 %or
}
```
### Optimized IR
```llvm
target datalayout = "e-m:e-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define i64 @test(ptr %base) {
entry:
  %0 = getelementptr i8, ptr %base, i64 -2147483648
  %1 = load i64, ptr %0, align 4
  ret i64 %1
}
```


---

# Issue 169921

## Incorrect Memory Location in Alias Analysis for Combined Loads

**Description**: 
The bug occurs during an optimization pass that attempts to combine multiple contiguous or overlapping loads into a single, wider load. To ensure the legality of this transformation, the compiler must verify that no intervening instructions (such as stores) modify the memory region accessed by the combined load. This is done by querying the alias analysis framework to check for potential memory overlaps.

However, the compiler constructs an incorrect memory location for the combined load when performing the alias check:
1. **Incorrect Access Size**: It uses the bit width of the combined load instead of its byte size, resulting in an incorrect memory footprint being passed to the alias analysis.
2. **Incorrect Base Pointer**: It uses the memory address of one of the original loads (typically the one at the insertion point) rather than the true base address of the combined load.

Because the alias analysis is queried with a malformed memory region, it may incorrectly conclude that an intervening store does not overlap with the combined load (returning `NoAlias`). This flawed analysis allows the compiler to illegally hoist the combined load above the store. Consequently, the combined load reads stale data instead of the newly stored value, leading to a miscompilation. 

To trigger this bug, the LLVM IR should contain:
1. A sequence of loads from contiguous or overlapping memory locations that the compiler will attempt to combine into a wider load.
2. An intervening store instruction that modifies a portion of the memory being loaded, placed between the original loads in the instruction stream.
3. The memory addresses and types should be structured such that the incorrect base pointer and size calculation causes the alias analysis to miss the overlap between the intervening store and the combined load.

## Example

### Original IR
```llvm
target datalayout = "e"

define i16 @test(ptr %p) {
entry:
  %p1 = getelementptr inbounds i8, ptr %p, i64 1
  %v1 = load i8, ptr %p1, align 1
  
  ; Intervening store that modifies the lower byte of the combined load
  store i8 42, ptr %p, align 1
  
  %v0 = load i8, ptr %p, align 1
  
  ; Combine the two i8 loads into an i16
  %z0 = zext i8 %v0 to i16
  %z1 = zext i8 %v1 to i16
  %s1 = shl i16 %z1, 8
  %res = or i16 %z0, %s1
  
  ret i16 %res
}
```
### Optimized IR
```llvm
target datalayout = "e"

define i16 @test(ptr %p) {
entry:
  ; The combined load is illegally hoisted above the store because the alias analysis
  ; checked the region [%p1, %p1 + 16 bytes) and missed the store at %p.
  %0 = load i16, ptr %p, align 1
  store i8 42, ptr %p, align 1
  ret i16 %0
}
```
