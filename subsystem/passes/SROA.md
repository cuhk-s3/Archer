# Issue 64081

## Incorrect Conversion of Memcpy to Typed Store for Types with Padding

**Description:**
The bug is triggered when the Scalar Replacement of Aggregates (SROA) pass splits an aggregate `alloca` (typically representing a union) into smaller scalar components. The issue specifically arises when one of the resulting scalar types has a logical bit-width that is smaller than its physical storage size in memory (e.g., a non-standard integer type like `i6` which occupies a full byte).

When SROA processes a memory intrinsic (such as `memcpy`) that overlaps with this new scalar `alloca`, it attempts to optimize the intrinsic by converting the raw memory copy into a typed `store` instruction. However, a typed `store` only preserves the bits defined by the type's logical size; it does not guarantee the preservation of bits in the "padding" region (the difference between the type size and the store size). In the context of a union, these padding bits may contain valid data belonging to another member of the union. By replacing the bit-preserving `memcpy` with a typed `store`, the compiler inadvertently discards or corrupts the data residing in these padding bits, leading to a miscompilation.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define i8 @test_padding_loss() {
entry:
  %src = alloca i8, align 1
  store i8 -1, i8* %src, align 1
  %dst = alloca { i6 }, align 1
  %dst.i8 = bitcast { i6 }* %dst to i8*
  call void @llvm.memcpy.p0i8.p0i8.i64(i8* align 1 %dst.i8, i8* align 1 %src, i64 1, i1 false)
  %val = load i8, i8* %dst.i8, align 1
  ret i8 %val
}

declare void @llvm.memcpy.p0i8.p0i8.i64(i8* noalias nocapture writeonly, i8* noalias nocapture readonly, i64, i1 immarg)
```
### Optimized IR
```llvm
target datalayout = "e-m:e-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define i8 @test_padding_loss() {
entry:
  %src = alloca i8, align 1
  store i8 -1, i8* %src, align 1
  %src.cast = bitcast i8* %src to i6*
  %src.load = load i6, i6* %src.cast, align 1
  %val = zext i6 %src.load to i8
  ret i8 %val
}
```
