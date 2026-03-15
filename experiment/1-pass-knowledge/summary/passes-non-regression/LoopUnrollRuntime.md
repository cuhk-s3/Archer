# Issue 80289

## Incorrect Constant Extension for Loop Trip Counts Larger Than 64 Bits During Runtime Unrolling

**Description**:
The bug is triggered during runtime loop unrolling when the compiler needs to compute the backedge count to determine the number of extra iterations for a prologue or epilogue loop.

Specifically, the issue occurs under the following conditions:
1. A loop is subjected to runtime unrolling.
2. The loop's trip count is represented by an integer type wider than 64 bits (e.g., `i128`).
3. The trip count is not guaranteed to be free of `undef` or `poison` values.

Because of the potential for `undef` or `poison` values, the compiler inserts a `freeze` instruction on the trip count and manually computes the backedge count by adding `-1` to the frozen value. However, when constructing the `-1` constant for the addition, the compiler uses a 64-bit representation of `-1` and incorrectly zero-extends it to the wider integer type (e.g., resulting in `UINT64_MAX` for an `i128` type) instead of properly sign-extending it to an all-ones value.

As a result, instead of subtracting one from the trip count, the compiler adds a large positive constant. This leads to an incorrect backedge count calculation, causing the unrolled loop's prologue or epilogue to execute the wrong number of iterations and resulting in a miscompilation.

## Example

### Original IR
```llvm
define void @test(i128 %n, ptr %p) {
entry:
  br label %loop

loop:
  %iv = phi i128 [ 0, %entry ], [ %iv.next, %loop ]
  %gep = getelementptr i32, ptr %p, i128 %iv
  store i32 0, ptr %gep
  %iv.next = add i128 %iv, 1
  %exitcond = icmp eq i128 %iv.next, %n
  br i1 %exitcond, label %exit, label %loop, !llvm.loop !0

exit:
  ret void
}

!0 = distinct !{!0, !1}
!1 = !{!"llvm.loop.unroll.count", i32 4}

```
### Optimized IR
```llvm
define void @test(i128 %n, ptr %p) {
entry:
  %0 = freeze i128 %n
  %1 = add i128 %0, 18446744073709551615
  %xtraiter = and i128 %0, 3
  %lcmp.mod = icmp ne i128 %xtraiter, 0
  br i1 %lcmp.mod, label %loop.prol.preheader, label %loop.prol.loopexit

loop.prol.preheader:
  br label %loop.prol

loop.prol:
  %iv.prol = phi i128 [ 0, %loop.prol.preheader ], [ %iv.next.prol, %loop.prol ]
  %prol.iter = phi i128 [ 0, %loop.prol.preheader ], [ %prol.iter.next, %loop.prol ]
  %gep.prol = getelementptr i32, ptr %p, i128 %iv.prol
  store i32 0, ptr %gep.prol
  %iv.next.prol = add i128 %iv.prol, 1
  %prol.iter.next = add i128 %prol.iter, 1
  %prol.iter.cmp = icmp ne i128 %prol.iter.next, %xtraiter
  br i1 %prol.iter.cmp, label %loop.prol, label %loop.prol.loopexit, !llvm.loop !2

loop.prol.loopexit:
  %iv.unr = phi i128 [ 0, %entry ], [ %iv.next.prol, %loop.prol ]
  %2 = icmp ult i128 %1, 3
  br i1 %2, label %exit, label %loop.preheader

loop.preheader:
  br label %loop

loop:
  %iv = phi i128 [ %iv.unr, %loop.preheader ], [ %iv.next.3, %loop ]
  %gep = getelementptr i32, ptr %p, i128 %iv
  store i32 0, ptr %gep
  %iv.next = add i128 %iv, 1
  %gep.1 = getelementptr i32, ptr %p, i128 %iv.next
  store i32 0, ptr %gep.1
  %iv.next.1 = add i128 %iv, 2
  %gep.2 = getelementptr i32, ptr %p, i128 %iv.next.1
  store i32 0, ptr %gep.2
  %iv.next.2 = add i128 %iv, 3
  %gep.3 = getelementptr i32, ptr %p, i128 %iv.next.2
  store i32 0, ptr %gep.3
  %iv.next.3 = add i128 %iv, 4
  %exitcond.3 = icmp eq i128 %iv.next.3, %0
  br i1 %exitcond.3, label %exit, label %loop

exit:
  ret void
}

!0 = distinct !{!0, !1}
!1 = !{!"llvm.loop.unroll.count", i32 4}
!2 = distinct !{!2, !3}
!3 = !{!"llvm.loop.unroll.disable"}

```
