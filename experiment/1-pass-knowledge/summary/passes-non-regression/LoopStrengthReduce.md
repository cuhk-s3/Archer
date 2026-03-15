# Issue 58039

## Incorrect Type Conversion of Normalized Post-Increment Induction Variables

**Description**:
The bug is triggered during loop optimizations that attempt to simplify or reduce the strength of loop induction variables. It specifically involves induction variables that have "post-increment" uses, meaning the value of the variable is used after it has been stepped or updated (often occurring outside the loop or at the loop's exit).

To handle these post-increment uses, the compiler normalizes the underlying recurrence expression, which typically involves shifting its starting value to align with the post-increment state.

The bug manifests when these post-increment uses also require a type conversion, such as a sign-extension to a wider integer type or a truncation to a narrower one. The compiler's transformation logic incorrectly applies the type extension or truncation directly to the *already normalized* recurrence expression.

Because the normalized expression has a shifted base value, naively extending or truncating it can alter its wrapping semantics or sign-bit behavior in the new type. For example, an expression that correctly represents the post-increment value in the original type might yield an incorrect sequence of values when its normalized form is directly sign-extended to a wider type. This flawed transformation leads to miscompilations where the program computes and uses an incorrect value for the induction variable in the converted type.

## Example

### Original IR
```llvm
define i32 @test_postinc_sext(i1 %c) {
entry:
  br label %loop

loop:
  %iv = phi i8 [ 127, %entry ], [ %iv.next, %loop ]
  %iv.next = add i8 %iv, 1
  br i1 %c, label %exit, label %loop

exit:
  %iv.lcssa = phi i8 [ %iv.next, %loop ]
  %ext = sext i8 %iv.lcssa to i32
  ret i32 %ext
}
```
### Optimized IR
```llvm
define i32 @test_postinc_sext(i1 %c) {
entry:
  br label %loop

loop:
  %indvars.iv = phi i32 [ 127, %entry ], [ %indvars.iv.next, %loop ]
  %indvars.iv.next = add nsw i32 %indvars.iv, 1
  br i1 %c, label %exit, label %loop

exit:
  %ext = phi i32 [ %indvars.iv.next, %loop ]
  ret i32 %ext
}
```
