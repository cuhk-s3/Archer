# Issue 116249

## Incorrect Preservation of `samesign` Flag when Narrowing Comparisons

**Description:**
The bug is triggered when an integer comparison (`icmp`) instruction annotated with the `samesign` flag is optimized by narrowing its operands to a smaller integer type. The `samesign` flag asserts that both operands of the comparison share the same sign (i.e., both are non-negative or both are negative) in their current type. 

When the comparison is narrowed (e.g., from `i32` to `i8`), the position of the sign bit changes to the most significant bit of the new, narrower type. Two values that have the same sign in a wider type may not have the same sign in the narrower type after truncation. For example, `0` and `128` are both non-negative in `i32`, but when truncated to `i8`, `0` remains non-negative while `128` becomes negative. 

The optimization incorrectly preserves the `samesign` flag on the newly narrowed comparison. Because the same-sign guarantee no longer holds for the truncated operands, the comparison evaluates to `poison`. This leads to undefined behavior when the `poison` value is subsequently used, such as in a conditional branch for a loop exit.

## Example

### Original IR
```llvm
define i1 @narrow_icmp_samesign(i8 %x, i8 %y) {
entry:
  %x.ext = zext i8 %x to i32
  %y.ext = zext i8 %y to i32
  %cmp = icmp samesign ult i32 %x.ext, %y.ext
  ret i1 %cmp
}
```
### Optimized IR
```llvm
define i1 @narrow_icmp_samesign(i8 %x, i8 %y) {
entry:
  %cmp = icmp samesign ult i8 %x, %y
  ret i1 %cmp
}
```


---

# Issue 66986

## Unsafe Speculation of Trapping Operations during Loop Exit Count Expansion

**Description:**
The bug is triggered when a loop optimization pass attempts to rewrite a loop's exit condition based on its computed exit count, but incorrectly speculates operations that can trap at runtime. 

1. A loop contains an exit condition that depends on an expression involving a potentially trapping operation, such as an integer division or remainder.
2. In the original program, this trapping operation is safely guarded by control flow (e.g., an `if` statement checking if the divisor is zero) that prevents the operation from executing with invalid operands.
3. The compiler analyzes the loop using Scalar Evolution (SCEV) and computes an expression for the loop's exact exit count, which inherently incorporates the trapping operation.
4. During loop transformations like Linear Function Test Replace (LFTR), the pass attempts to replace the original induction variable-based exit test with a new test against the computed exit count.
5. To do this, the pass expands the SCEV expression for the exit count into actual LLVM IR instructions. However, it fails to verify whether the operations within the expression are safe to unconditionally expand (speculate).
6. Consequently, the potentially trapping operation is generated outside of its original protective control flow guard. When the program executes, the speculated instruction may evaluate with invalid operands (like a zero divisor), leading to a runtime fault such as a floating-point exception.

## Example

### Original IR
```llvm
define void @test(i32 %a, i32 %b) {
entry:
  br label %loop

loop:
  %iv = phi i32 [ 0, %entry ], [ %iv.next, %loop.latch ]
  %cmp1 = icmp eq i32 %b, 0
  br i1 %cmp1, label %exit, label %loop.cont

loop.cont:
  %div = udiv i32 %a, %b
  %cmp2 = icmp ult i32 %iv, %div
  br i1 %cmp2, label %loop.latch, label %exit

loop.latch:
  %iv.next = add i32 %iv, 1
  br label %loop

exit:
  ret void
}
```
### Optimized IR
```llvm
define void @test(i32 %a, i32 %b) {
entry:
  %div.spec = udiv i32 %a, %b
  br label %loop

loop:
  %iv = phi i32 [ 0, %entry ], [ %iv.next, %loop.latch ]
  %cmp1 = icmp eq i32 %b, 0
  br i1 %cmp1, label %exit, label %loop.cont

loop.cont:
  %exitcond = icmp ne i32 %iv, %div.spec
  br i1 %exitcond, label %loop.latch, label %exit

loop.latch:
  %iv.next = add i32 %iv, 1
  br label %loop

exit:
  ret void
}
```
