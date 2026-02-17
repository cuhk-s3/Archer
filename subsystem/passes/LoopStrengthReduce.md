# Issue 38847

## Incorrect Type Extension of Post-Increment Loop Induction Variables

**Description**
The bug is triggered during the Loop Strength Reduction (LSR) optimization pass when the compiler generates alternative formulae for loop induction variables that require type promotion (e.g., sign-extending a narrower integer to a wider one).

The issue specifically affects "post-increment" uses of induction variables—instances where the variable is used after the loop's increment step has been applied. When creating a widened version of such a variable, the compiler incorrectly applies the type extension directly to the normalized recurrence expression (the abstract formula representing the loop variable's evolution, such as `{Start, +, Step}`).

This approach is flawed because it ignores potential arithmetic overflows or wrapping that occur in the original, narrower type during the increment. By extending the recurrence parameters directly, the calculation is moved to the wider type domain where the wrap-around does not happen (or happens at a much larger value). Consequently, the optimized code computes a value that differs from the original program semantics, which relied on the modular arithmetic behavior of the narrower type.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @test_lsr_postinc_overflow(i32* %ptr) {
entry:
  br label %loop

loop:
  ; Induction variable starts at INT_MAX (2147483647)
  %iv = phi i32 [ 2147483647, %entry ], [ %iv.next, %loop ]
  
  ; Increment causes signed overflow to INT_MIN (-2147483648)
  %iv.next = add i32 %iv, 1
  
  ; Post-increment use: Sign extend the wrapped value
  ; Correct behavior: sext(INT_MIN) -> 0xFFFFFFFF80000000 (negative i64)
  %idx = sext i32 %iv.next to i64
  
  ; Memory access using the extended index
  %gep = getelementptr i32, i32* %ptr, i64 %idx
  store i32 1, i32* %gep
  
  ; Exit condition
  %cond = icmp eq i32 %iv.next, -2147483648
  br i1 %cond, label %exit, label %loop

exit:
  ret void
}
```
### Optimized IR
```llvm
target datalayout = "e-m:e-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @test_lsr_postinc_overflow(i32* %ptr) {
entry:
  br label %loop

loop:
  ; BUG: LSR creates a wide induction variable (i64) but incorrectly extends the recurrence.
  ; Instead of wrapping to negative, it extends the domain to positive.
  ; 2147483647 + 1 in i64 is 2147483648 (0x0000000080000000).
  %lsr.iv = phi i64 [ 2147483648, %entry ], [ %lsr.iv.next, %loop ]
  
  %lsr.iv.next = add i64 %lsr.iv, 1
  
  ; The GEP now uses the positive 64-bit index instead of the negative wrapped index.
  %gep = getelementptr i32, i32* %ptr, i64 %lsr.iv
  store i32 1, i32* %gep
  
  ; Exit condition updated to match the wide IV (demonstrating the logic shift)
  %cond = icmp eq i64 %lsr.iv, 2147483648
  br i1 %cond, label %exit, label %loop

exit:
  ret void
}
```


---

# Issue 62852

## Incorrect Sign-Extension of Post-Loop Induction Variables

**Description**:
The bug is triggered when the LoopStrengthReduce (LSR) pass promotes an induction variable (IV) to a wider type (e.g., from `i32` to `i64`) and that IV is used outside the loop (a post-increment use). When generating the expression for the widened IV's value at the loop exit, the compiler incorrectly extends the IV's recurrence relation.

Specifically, when handling post-increment uses, the compiler uses a normalized form of the recurrence expression and applies an extension (typically sign-extension) to match the wider type. If the original narrow IV evolved to a value that is negative when interpreted as signed (e.g., `-1` or `0xFFFFFFFF`), the widened recurrence produces a sign-extended value (e.g., `0xFFFFFFFFFFFFFFFF`). However, if the original program used this value in a context that treats it as unsigned (such as `urem` or `zext`), the extra high bits introduced by the sign-extension result in a miscalculation. The compiler fails to account for the fact that extending the normalized recurrence directly does not preserve the correct bitwise value required by the original unsigned use of the narrow IV.

## Example

### Original IR
```llvm
target datalayout = "n8:16:32:64"
target triple = "x86_64-unknown-linux-gnu"

define i64 @buggy_sign_ext() {
entry:
  br label %loop

loop:
  %iv = phi i32 [ 0, %entry ], [ %iv.next, %loop ]
  %iv.next = add i32 %iv, -1
  %cond = icmp eq i32 %iv.next, -1
  br i1 %cond, label %exit, label %loop

exit:
  ; The original intention is to zero-extend the 32-bit value -1 (0xFFFFFFFF)
  ; to 64-bit (0x00000000FFFFFFFF).
  %res = zext i32 %iv.next to i64
  ret i64 %res
}
```
### Optimized IR
```llvm
target datalayout = "n8:16:32:64"
target triple = "x86_64-unknown-linux-gnu"

define i64 @buggy_sign_ext() {
entry:
  br label %loop

loop:
  ; LSR promotes the IV to i64.
  %lsr.iv = phi i64 [ 0, %entry ], [ %lsr.iv.next, %loop ]
  %lsr.iv.next = add i64 %lsr.iv, -1
  %cond = icmp eq i64 %lsr.iv.next, -1
  br i1 %cond, label %exit, label %loop

exit:
  ; BUG: The compiler incorrectly uses the sign-extended widened IV directly.
  ; The value of %lsr.iv.next is -1 (0xFFFFFFFFFFFFFFFF), which differs from
  ; the expected zero-extended value (0x00000000FFFFFFFF).
  ret i64 %lsr.iv.next
}
```
