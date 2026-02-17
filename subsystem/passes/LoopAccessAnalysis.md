# Issue 139202

## Incorrect Vectorization of Distant Memory Accesses due to Offset Truncation

**Description**
The bug is triggered when the compiler's vectorization analysis attempts to determine if separate memory accesses (such as loads or stores) are consecutive in memory and thus eligible to be merged into a single vector instruction. To make this determination, the compiler calculates the byte offset or distance between the pointers of the candidate instructions.

The issue arises because the logic responsible for calculating this distance stores the result in a narrow integer type (typically 32-bit) instead of a type sufficient to hold the full pointer difference (typically 64-bit). When the actual distance between two pointers is very large (e.g., exceeding 4GB), the value is truncated to fit the narrow type. If the lower bits of this large, truncated offset happen to match the size of the elements being accessed, the compiler incorrectly perceives the widely separated pointers as being adjacent. Consequently, the vectorizer erroneously combines these non-consecutive accesses into a single vector operation, leading to incorrect memory accesses at runtime.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @test_offset_truncation(ptr %base, i32 %v1, i32 %v2) {
entry:
  ; Store the first value at the base address
  store i32 %v1, ptr %base, align 4

  ; Calculate a pointer at an offset of (2^30 + 1) elements.
  ; In bytes: (1073741825 * 4) = 4294967300 = 0x100000004 bytes.
  ; If the compiler truncates the offset difference to 32 bits, it sees 0x00000004.
  ; This matches sizeof(i32), causing the compiler to think this store is adjacent to the first.
  %p2 = getelementptr i32, ptr %base, i64 1073741825
  store i32 %v2, ptr %p2, align 4

  ret void
}
```
### Optimized IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @test_offset_truncation(ptr %base, i32 %v1, i32 %v2) {
entry:
  ; The compiler incorrectly merged the two distant stores into a single vector store
  ; at the base address, overwriting memory at base+4 instead of base+4GB+4.
  %0 = insertelement <2 x i32> poison, i32 %v1, i32 0
  %1 = insertelement <2 x i32> %0, i32 %v2, i32 1
  store <2 x i32> %1, ptr %base, align 4
  ret void
}
```


---

# Issue 57315

## Incorrect Runtime Pointer Difference Check for Nested Loop Recurrences

**Description**
The bug is triggered when the compiler performs Loop Access Analysis to generate runtime memory checks for loop vectorization. Specifically, the issue occurs during the creation of "difference checks," which are optimizations that validate memory safety by comparing the distance between two pointers to determine if they alias.

The vulnerability arises in nested loop structures when the analysis compares two memory access patterns that are both represented as Add Recurrence expressions (SCEVAddRecExpr). In the triggering scenario:
1.  One memory access evolves within the innermost loop (the loop currently being analyzed/vectorized).
2.  The other memory access evolves within an enclosing outer loop, making it invariant with respect to the innermost loop.

The optimization logic incorrectly assumes that if both memory addresses are Add Recurrences, they must both be evolving within the innermost loop. It fails to verify the loop depth associated with each recurrence. Consequently, the compiler applies a difference check logic intended for pointers iterating within the same loop scope to pointers from different loop levels. This results in the generation of insufficient or incorrect runtime checks, allowing the vectorizer to proceed with unsafe transformations when the memory regions actually overlap.

## Example

### Original IR
```llvm
define void @test(i32* %a, i32* %b, i64 %n) {
entry:
  br label %outer.header

outer.header:
  %i = phi i64 [ 0, %entry ], [ %i.next, %outer.latch ]
  %b.addr = getelementptr inbounds i32, i32* %b, i64 %i
  br label %inner.header

inner.header:
  %j = phi i64 [ 0, %outer.header ], [ %j.next, %inner.body ]
  %a.addr = getelementptr inbounds i32, i32* %a, i64 %j
  br label %inner.body

inner.body:
  %val = load i32, i32* %b.addr, align 4
  store i32 %val, i32* %a.addr, align 4
  %j.next = add nuw nsw i64 %j, 1
  %cond = icmp eq i64 %j.next, %n
  br i1 %cond, label %inner.exit, label %inner.header

inner.exit:
  br label %outer.latch

outer.latch:
  %i.next = add nuw nsw i64 %i, 1
  %outer.cond = icmp eq i64 %i.next, %n
  br i1 %outer.cond, label %exit, label %outer.header

exit:
  ret void
}
```
### Optimized IR
```llvm
define void @test(i32* %a, i32* %b, i64 %n) {
entry:
  br label %outer.header

outer.header:
  %i = phi i64 [ 0, %entry ], [ %i.next, %outer.latch ]
  %b.addr = getelementptr inbounds i32, i32* %b, i64 %i
  br label %inner.check

inner.check:
  ; BUG: The runtime check incorrectly assumes both pointers evolve in the inner loop.
  ; It checks if the distance between the base pointers is safe for the vector width (16 bytes),
  ; ignoring that %a iterates through the loop while %b.addr stays constant.
  %a.int = ptrtoint i32* %a to i64
  %b.int = ptrtoint i32* %b.addr to i64
  %diff = sub i64 %a.int, %b.int
  %conflict = icmp ult i64 %diff, 16
  br i1 %conflict, label %inner.scalar.header, label %inner.vector.ph

inner.vector.ph:
  %n.vec = and i64 %n, -4
  br label %inner.vector.body

inner.vector.body:
  %index = phi i64 [ 0, %inner.vector.ph ], [ %index.next, %inner.vector.body ]
  %vec.ind = getelementptr inbounds i32, i32* %a, i64 %index
  %b.val = load i32, i32* %b.addr, align 4
  %b.vec = insertelement <4 x i32> poison, i32 %b.val, i32 0
  %b.splat = shufflevector <4 x i32> %b.vec, <4 x i32> poison, <4 x i32> zeroinitializer
  %vec.ptr = bitcast i32* %vec.ind to <4 x i32>*
  store <4 x i32> %b.splat, <4 x i32>* %vec.ptr, align 4
  %index.next = add i64 %index, 4
  %vec.cond = icmp eq i64 %index.next, %n.vec
  br i1 %vec.cond, label %inner.middle.block, label %inner.vector.body

inner.middle.block:
  %cmp.n = icmp eq i64 %n, %n.vec
  br i1 %cmp.n, label %inner.exit, label %inner.scalar.header

inner.scalar.header:
  %j.scalar = phi i64 [ 0, %inner.check ], [ %n.vec, %inner.middle.block ], [ %j.next, %inner.scalar.body ]
  %a.addr.scalar = getelementptr inbounds i32, i32* %a, i64 %j.scalar
  br label %inner.scalar.body

inner.scalar.body:
  %val.scalar = load i32, i32* %b.addr, align 4
  store i32 %val.scalar, i32* %a.addr.scalar, align 4
  %j.next = add nuw nsw i64 %j.scalar, 1
  %cond = icmp eq i64 %j.next, %n
  br i1 %cond, label %inner.exit, label %inner.scalar.header

inner.exit:
  br label %outer.latch

outer.latch:
  %i.next = add nuw nsw i64 %i, 1
  %outer.cond = icmp eq i64 %i.next, %n
  br i1 %outer.cond, label %exit, label %outer.header

exit:
  ret void
}
```
