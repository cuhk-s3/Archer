# Issue 62992

## Speculative Hoisting of Trapping Instructions during Loop Invariant Expansion

**Description**
The bug is triggered when the compiler attempts to simplify a comparison involving a loop induction variable by hoisting the loop-invariant operand of that comparison into the loop preheader. The optimization identifies an expression that does not vary within the loop and generates code to compute this expression before the loop begins, aiming to canonicalize the loop or reduce computational overhead.

However, the transformation fails to verify whether the expression is safe to execute speculatively. Specifically, it does not check if the expression contains instructions that can trap, such as integer division or remainder operations, which cause a runtime fault if the divisor is zero. In the original code, these operations are typically guarded by conditional checks (e.g., ensuring the divisor is non-zero) or are located within control flow that prevents their execution under unsafe conditions. By moving the computation to the preheader without preserving these guards, the compiler causes the trapping instruction to execute unconditionally. Consequently, if the runtime values trigger the trap (e.g., a zero divisor), the program crashes with an exception, violating the semantics of the original guarded code.

## Example

### Original IR
```llvm
define void @test_loop_hoist(i32 %n, i32 %d) {
entry:
  br label %header

header:
  %i = phi i32 [ 0, %entry ], [ %i.next, %latch ]
  %cond = icmp slt i32 %i, %n
  br i1 %cond, label %body, label %exit

body:
  ; This instruction is loop invariant but can trap (divide by zero).
  ; It is guarded by the loop condition (i < n).
  %div = sdiv i32 42, %d
  %cmp = icmp eq i32 %i, %div
  br label %latch

latch:
  %i.next = add i32 %i, 1
  br label %header

exit:
  ret void
}
```
### Optimized IR
```llvm
define void @test_loop_hoist(i32 %n, i32 %d) {
entry:
  ; BUG: The trapping instruction is hoisted to the preheader.
  ; It now executes unconditionally. If %d is 0 and %n is 0, this traps
  ; whereas the original code would have exited safely.
  %div = sdiv i32 42, %d
  br label %header

header:
  %i = phi i32 [ 0, %entry ], [ %i.next, %latch ]
  %cond = icmp slt i32 %i, %n
  br i1 %cond, label %body, label %exit

body:
  %cmp = icmp eq i32 %i, %div
  br label %latch

latch:
  %i.next = add i32 %i, 1
  br label %header

exit:
  ret void
}
```
