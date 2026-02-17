# Issue 116249

## Summary Title
Incorrect Preservation of `samesign` Flag During Integer Comparison Narrowing

## Description
The bug occurs when an optimization narrows the bit width of an integer comparison (e.g., converting a 32-bit comparison to an 8-bit comparison) to simplify control flow or loop exit conditions. Specifically, if the original comparison instruction carries the `samesign` flag, the optimizer incorrectly preserves this flag on the new, narrower comparison instruction.

The `samesign` flag asserts that both operands share the same sign bit. However, narrowing the type changes the position of the sign bit. Operands that shared a sign bit in the wider type (often because they were zero-extended and thus both positive) may have differing sign bits when truncated to the narrower type. By retaining the `samesign` flag on the narrowed operation, the compiler introduces undefined behavior for inputs where the new sign bits differ, leading to a miscompilation.

## Example

### Original IR
```llvm
define i1 @test_samesign_narrowing(i8 %a, i8 %b) {
  %ext_a = zext i8 %a to i32
  %ext_b = zext i8 %b to i32
  %cmp = icmp samesign ult i32 %ext_a, %ext_b
  ret i1 %cmp
}
```
### Optimized IR
```llvm
define i1 @test_samesign_narrowing(i8 %a, i8 %b) {
  %cmp = icmp samesign ult i8 %a, %b
  ret i1 %cmp
}
```


---

# Issue 66986

## Unsafe Speculation of Trapping Instructions during Loop Exit Expansion

**Description**
The bug is triggered during the Linear Function Test Replacement (LFTR) transformation within the induction variable simplification pass. This optimization aims to replace a loop's complex exit condition with a simpler comparison against a pre-calculated exit count. The issue arises when the Scalar Evolution (SCEV) expression representing this exit count involves a potentially trapping operation, such as integer division, which is guarded by a conditional check in the original LLVM IR.

When the optimization expands this SCEV expression into executable instructions to form the new loop test, it fails to verify whether the operations are safe to execute speculatively. As a result, the trapping instruction is hoisted out of its protective context (e.g., moved to the loop preheader) and executed unconditionally. If the runtime values trigger the trap (for example, a divisor is zero), the program crashes, whereas the original code would have safely skipped the operation due to the guard.

## Example

### Original IR
```llvm
define void @func(i32 %n, i32 %d) {
entry:
  br label %loop

loop:
  %i = phi i32 [ 0, %entry ], [ %inc, %latch ]
  ; Guard: If d is 0, exit the loop safely.
  %guard = icmp eq i32 %d, 0
  br i1 %guard, label %exit, label %latch

latch:
  ; The exit condition depends on multiplication by d.
  ; This implies a division by d to calculate the trip count.
  %mul = mul i32 %i, %d
  %cond = icmp ult i32 %mul, %n
  %inc = add i32 %i, 1
  br i1 %cond, label %loop, label %exit

exit:
  ret void
}
```
### Optimized IR
```llvm
define void @func(i32 %n, i32 %d) {
entry:
  ; BUG: The trip count calculation (involving udiv) is hoisted to the preheader.
  ; This executes unconditionally. If %d is 0, this instruction traps,
  ; whereas the original code would have safely exited via the guard.
  %tmp = sub i32 %n, 1
  %trip.count = udiv i32 %tmp, %d
  %limit = add i32 %trip.count, 1
  br label %loop

loop:
  %i = phi i32 [ 0, %entry ], [ %inc, %latch ]
  %guard = icmp eq i32 %d, 0
  br i1 %guard, label %exit, label %latch

latch:
  ; LFTR has replaced the original exit condition with a check against the pre-calculated limit.
  %inc = add i32 %i, 1
  %exitcond = icmp ne i32 %inc, %limit
  br i1 %exitcond, label %loop, label %exit

exit:
  ret void
}
```
