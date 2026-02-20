# Issue 64081

## Incorrect Replacement of Memory Copy with Typed Load/Store for Types with Padding

**Description**:
The bug is triggered by a specific interaction between raw memory copy operations and types that contain padding bits. The strategy to trigger this issue at the LLVM IR level involves the following steps:

1. **Allocate Memory with Padding**: Create an `alloca` instruction using a type where the actual data size is smaller than the memory store size (i.e., the type contains padding bits). This often occurs with non-standard integer sizes (like `i6`) or structs containing bitfields, where the type does not fully occupy the bytes allocated for it.
2. **Perform a Raw Memory Copy**: Use a memory copy intrinsic (such as `llvm.memcpy`) to copy data into or out of this allocated memory. The size of the copy should cover the full byte size of the memory region, meaning it explicitly copies the bits that the allocated type considers to be "padding".
3. **Trigger the Optimization**: An optimization pass (like SROA) analyzes the memory copy and attempts to replace it with a direct, typed `load` and `store` of the allocated type to promote the memory to registers.
4. **Data Loss**: Because the optimization replaces the raw byte-level copy with a typed load/store, the operation only preserves the valid value bits defined by the type. The padding bits, which were correctly copied by the original `memcpy`, are ignored and lost. 

This leads to a miscompilation if the underlying memory is actually part of a union or is later accessed via a different type (like an array of bytes) where those "padding" bits contain semantically meaningful data.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

declare void @llvm.memcpy.p0.p0.i64(ptr noalias nocapture writeonly, ptr noalias nocapture readonly, i64, i1 immarg)

define void @test_padding_memcpy(ptr %src, ptr %dst) {
entry:
  %a = alloca i6, align 1
  call void @llvm.memcpy.p0.p0.i64(ptr align 1 %a, ptr align 1 %src, i64 1, i1 false)
  call void @llvm.memcpy.p0.p0.i64(ptr align 1 %dst, ptr align 1 %a, i64 1, i1 false)
  ret void
}
```
### Optimized IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @test_padding_memcpy(ptr %src, ptr %dst) {
entry:
  %0 = load i6, ptr %src, align 1
  store i6 %0, ptr %dst, align 1
  ret void
}
```
