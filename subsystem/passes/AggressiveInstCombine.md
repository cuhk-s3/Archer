# Issue 118467

## Incorrect Offset Truncation in Load Folding

**Description**
The bug occurs in the `AggressiveInstCombine` pass when the optimizer attempts to fold consecutive loads into a single, wider load instruction. To perform this transformation, the compiler calculates the address for the new load by stripping constant offsets from the original pointer and accumulating them into a single value.

The issue arises during the reconstruction of the pointer address. The transformation logic incorrectly truncates the accumulated constant offset to a 32-bit integer, regardless of the target architecture's pointer size (e.g., 64 bits). If the original constant offset is a large positive value that has its 31st bit set (interpretable as negative in a 32-bit signed context), this truncation preserves that bit pattern. When the 32-bit offset is subsequently used in a pointer arithmetic instruction (like `getelementptr`), it is sign-extended to match the pointer's native width. This sign extension converts the intended large positive offset into a negative offset, causing the generated code to access an incorrect memory address.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define i32 @test_load_combine_truncation(ptr %p) {
entry:
  ; Load low 16 bits from offset 2147483648 (0x80000000)
  ; This large positive offset triggers the truncation bug during optimization.
  %gep1 = getelementptr inbounds i8, ptr %p, i64 2147483648
  %v1 = load i16, ptr %gep1, align 2
  %z1 = zext i16 %v1 to i32

  ; Load high 16 bits from offset 2147483650 (0x80000002)
  %gep2 = getelementptr inbounds i8, ptr %p, i64 2147483650
  %v2 = load i16, ptr %gep2, align 2
  %z2 = zext i16 %v2 to i32

  ; Combine the two i16 loads into a single i32 value
  %sh = shl i32 %z2, 16
  %res = or i32 %z1, %sh
  ret i32 %res
}
```
### Optimized IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define i32 @test_load_combine_truncation(ptr %p) {
entry:
  ; The AggressiveInstCombine pass folds the two loads into one i32 load.
  ; However, due to the bug, the offset 2147483648 (0x80000000) is truncated to 32 bits,
  ; interpreted as negative, and sign-extended to -2147483648 (0xFFFFFFFF80000000).
  %0 = getelementptr inbounds i8, ptr %p, i64 -2147483648
  %1 = load i32, ptr %0, align 2
  ret i32 %1
}
```
