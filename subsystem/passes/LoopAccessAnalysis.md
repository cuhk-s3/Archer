# Issue 139202

## Incorrect Vectorization due to 32-bit Truncation of 64-bit Pointer Offsets

**Description**:
The bug is triggered by a sequence of memory operations (such as loads or stores) that access memory using large offsets from a common base pointer. These offsets are large enough to require a 64-bit representation, exceeding the capacity of a standard 32-bit integer. 

To trigger the miscompilation, the offsets are constructed such that their lower 32 bits form a contiguous sequence of memory addresses, spaced exactly by the size of the accessed elements (e.g., 0, 8, 16, 24 for 8-byte elements). However, the upper 32 bits of some offsets are non-zero, meaning the actual memory locations are widely separated and strictly non-contiguous.

When the compiler's vectorization analysis calculates the distances between these pointers to check for consecutive accesses, it incorrectly truncates the 64-bit pointer differences into 32-bit integers. Because of this truncation, the large, non-contiguous offsets are masked, and the compiler only sees the contiguous lower 32 bits. Deceived into believing that the memory accesses are strictly adjacent, the compiler erroneously combines the separate scalar memory operations into a single vector memory operation (e.g., a contiguous vector load or store). This results in a miscompilation where data is read from or written to incorrect memory locations.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @test_vectorize_truncation_bug(ptr %base, <4 x i64> %val) {
entry:
  ; Offsets: 0, 8, 4294967312 (0x100000010), 4294967320 (0x100000018)
  ; Lower 32 bits are 0, 8, 16, 24 (contiguous for 8-byte elements)
  %ptr0 = getelementptr i8, ptr %base, i64 0
  %ptr1 = getelementptr i8, ptr %base, i64 8
  %ptr2 = getelementptr i8, ptr %base, i64 4294967312
  %ptr3 = getelementptr i8, ptr %base, i64 4294967320

  %v0 = extractelement <4 x i64> %val, i32 0
  %v1 = extractelement <4 x i64> %val, i32 1
  %v2 = extractelement <4 x i64> %val, i32 2
  %v3 = extractelement <4 x i64> %val, i32 3

  store i64 %v0, ptr %ptr0, align 8
  store i64 %v1, ptr %ptr1, align 8
  store i64 %v2, ptr %ptr2, align 8
  store i64 %v3, ptr %ptr3, align 8

  ret void
}

```
### Optimized IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @test_vectorize_truncation_bug(ptr %base, <4 x i64> %val) {
entry:
  %ptr0 = getelementptr i8, ptr %base, i64 0
  ; The compiler incorrectly assumes the pointers are contiguous due to 32-bit truncation
  ; of the pointer differences, erroneously combining the scalar stores into a vector store.
  store <4 x i64> %val, ptr %ptr0, align 8
  ret void
}

```
