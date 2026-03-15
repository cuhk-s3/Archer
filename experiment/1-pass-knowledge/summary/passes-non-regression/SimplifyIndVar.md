# Issue 62992

## Unsafe Hoisting of Potentially Trapping Loop-Invariant Expressions

**Description**:
The bug is triggered when a loop optimization pass attempts to simplify an induction variable comparison by hoisting its loop-invariant operands into the loop preheader.

In the original program, the loop-invariant expression may contain a potentially trapping operation (such as an integer division or remainder). To prevent runtime faults, this operation is typically guarded by a condition within the loop body (e.g., checking that the divisor is not zero), ensuring it is only executed when safe.

However, the optimization transformation fails to verify whether the loop-invariant expression is safe to expand and execute speculatively at the new insertion point in the preheader. By unconditionally hoisting and expanding the expression outside the loop, the compiler bypasses the original protective guards. As a result, the potentially trapping operation is executed unconditionally before the loop begins, leading to runtime exceptions (such as a division by zero fault) that would not have occurred in the unoptimized code.

## Example

### Original IR
```llvm
define void @test(i32 %n, i32 %x, i32 %d) {
entry:
  br label %loop

loop:
  %i = phi i32 [ 0, %entry ], [ %i.next, %latch ]
  %cmp.guard = icmp ne i32 %d, 0
  br i1 %cmp.guard, label %guarded, label %latch

guarded:
  %div = sdiv i32 %x, %d
  %cmp = icmp slt i32 %i, %div
  br i1 %cmp, label %body, label %latch

body:
  br label %latch

latch:
  %i.next = add i32 %i, 1
  %exitcond = icmp eq i32 %i.next, %n
  br i1 %exitcond, label %exit, label %loop

exit:
  ret void
}
```
### Optimized IR
```llvm
define void @test(i32 %n, i32 %x, i32 %d) {
entry:
  %div = sdiv i32 %x, %d
  br label %loop

loop:
  %i = phi i32 [ 0, %entry ], [ %i.next, %latch ]
  %cmp.guard = icmp ne i32 %d, 0
  br i1 %cmp.guard, label %guarded, label %latch

guarded:
  %cmp = icmp slt i32 %i, %div
  br i1 %cmp, label %body, label %latch

body:
  br label %latch

latch:
  %i.next = add i32 %i, 1
  %exitcond = icmp eq i32 %i.next, %n
  br i1 %exitcond, label %exit, label %loop

exit:
  ret void
}
```
