# Issue 102597

## Incorrect Constant Difference Calculation for Large Integers in Scalar Evolution

**Description**
The bug is triggered when the compiler's scalar evolution analysis attempts to compute the constant difference between two expressions involving integer types larger than 64 bits (such as `i128`). When the analysis decomposes these expressions and encounters a constant term that needs to be subtracted (mathematically treated as adding the constant multiplied by a negative integer factor), it performs an arithmetic operation combining the wide-width constant and the standard-width factor.

The error occurs because the negative factor is incorrectly zero-extended rather than sign-extended when promoted to the bit width of the large integer constant. Consequently, an operation intended to multiply by a negative value (e.g., -1) is effectively treated as multiplying by a large positive number. This results in the calculation of an erroneous constant difference. Downstream optimization passes, such as induction variable simplification, rely on this incorrect difference to reason about loop behaviors and variable ranges. This can lead the compiler to falsely prove that a runtime condition is always true or false, causing it to incorrectly optimize away necessary checks or assignments within loops.

## Example

### Original IR
```llvm
define i128 @test_bug(i128 %start) {
entry:
  br label %loop

loop:
  %iv = phi i128 [ %start, %entry ], [ %iv.next, %loop ]
  %iv.next = add i128 %iv, 1
  ; Constant C = 2^80 + 3
  %val = add i128 %iv, 1208925819614629174706179
  ; Calculate diff: iv - (iv + C). Should be -C.
  %diff = sub i128 %iv, %val
  %cond = icmp eq i128 %iv, 0
  br i1 %cond, label %exit, label %loop

exit:
  ret i128 %diff
}
```
### Optimized IR
```llvm
define i128 @test_bug(i128 %start) {
entry:
  br label %loop

loop:
  %iv = phi i128 [ %start, %entry ], [ %iv.next, %loop ]
  %iv.next = add i128 %iv, 1
  %cond = icmp eq i128 %iv, 0
  br i1 %cond, label %exit, label %loop

exit:
  ; The return value is incorrectly calculated due to the bug.
  ; Instead of -C, it returns C * (2^64 - 1) due to zero-extension of -1 factor.
  ret i128 340282366920938463463374607428693884925
}
```


---

# Issue 89958

## Speculative Hoisting of Unsafe Division in Loop Bound Expansion

**Description**
The bug is triggered when the compiler expands a Scalar Evolution (SCEV) expression representing a loop's trip count (or backedge taken count) into LLVM IR instructions, typically to facilitate loop vectorization.

The issue arises when the loop has multiple exit conditions, leading to a trip count expression modeled as a sequential minimum or maximum (e.g., `min(ExitCountA, ExitCountB)`). If one of these exit counts involves an unsafe operation, such as an unsigned division (`udiv`), the original code implicitly guards this operation (e.g., the loop might not be entered, or a previous exit condition might be taken before the division is reached).

However, when the compiler expands the `min`/`max` expression into the loop preheader, it generates instructions to evaluate all operands unconditionally. Consequently, the division instruction is executed before the loop begins. If the divisor is zero, this speculative execution causes a division-by-zero trap or undefined behavior, even if the original program would have safely bypassed the division logic.

## Example

### Original IR
```llvm
define void @test_loop(i32 %n, i32 %d) {
entry:
  br label %loop

loop:
  %i = phi i32 [ 0, %entry ], [ %inc, %latch ]
  ; Exit condition 1: i < n
  %cmp1 = icmp ult i32 %i, %n
  br i1 %cmp1, label %guard, label %exit

guard:
  ; Guard ensuring d is not zero before division
  %not_zero = icmp ne i32 %d, 0
  br i1 %not_zero, label %div_check, label %latch

div_check:
  ; Unsafe operation: udiv
  %div = udiv i32 100, %d
  ; Exit condition 2: i == 100 / d
  %cmp2 = icmp eq i32 %i, %div
  br i1 %cmp2, label %exit, label %latch

latch:
  %inc = add i32 %i, 1
  br label %loop

exit:
  ret void
}
```
### Optimized IR
```llvm
define void @test_loop(i32 %n, i32 %d) {
entry:
  ; BUG: The compiler hoisted the unsafe division to the preheader
  ; to calculate the loop trip count (min(n, 100/d)).
  ; This executes unconditionally and traps if d == 0.
  %div.hoisted = udiv i32 100, %d
  br label %loop

loop:
  %i = phi i32 [ 0, %entry ], [ %inc, %latch ]
  %cmp1 = icmp ult i32 %i, %n
  br i1 %cmp1, label %guard, label %exit

guard:
  %not_zero = icmp ne i32 %d, 0
  br i1 %not_zero, label %div_check, label %latch

div_check:
  ; The original division is replaced by the hoisted value
  %cmp2 = icmp eq i32 %i, %div.hoisted
  br i1 %cmp2, label %exit, label %latch

latch:
  %inc = add i32 %i, 1
  br label %loop

exit:
  ret void
}
```
