# Issue 64289

## Summary Title
Retention of ReadOnly Attribute on Modified ByVal Arguments in Tail Recursion Elimination

## Description
The bug is triggered when the Tail Recursion Elimination pass optimizes a recursive function that accepts a `byval` argument marked with the `readonly` attribute. When converting the tail recursion into a loop, the optimizer reuses the stack memory allocated for the `byval` argument to store the parameters for the next iteration. This involves writing new data into the `byval` pointer's memory location.

However, the transformation fails to remove the `readonly` attribute from the function parameter. This results in invalid Intermediate Representation (IR) where a pointer marked `readonly` is explicitly written to within the function body. Subsequent optimization passes, relying on the `readonly` contract, may incorrectly assume the memory pointed to by the argument is never modified, leading to miscompilations such as optimizing away necessary loads or creating infinite loops.

## Example

### Original IR
```llvm
define void @test_readonly_byval(i32* readonly byval(i32) %a) {
entry:
  %val = load i32, i32* %a, align 4
  %cond = icmp eq i32 %val, 0
  br i1 %cond, label %ret, label %recurse

recurse:
  %sub = sub i32 %val, 1
  %stack_arg = alloca i32, align 4
  store i32 %sub, i32* %stack_arg, align 4
  tail call void @test_readonly_byval(i32* byval(i32) %stack_arg)
  ret void

ret:
  ret void
}
```
### Optimized IR
```llvm
define void @test_readonly_byval(i32* readonly byval(i32) %a) {
entry:
  %stack_arg = alloca i32, align 4
  br label %tailrecurse

tailrecurse:
  %val = load i32, i32* %a, align 4
  %cond = icmp eq i32 %val, 0
  br i1 %cond, label %ret, label %recurse

recurse:
  %sub = sub i32 %val, 1
  store i32 %sub, i32* %stack_arg, align 4
  %tmp = load i32, i32* %stack_arg, align 4
  store i32 %tmp, i32* %a, align 4
  br label %tailrecurse

ret:
  ret void
}
```
