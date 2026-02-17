# Issue 52950

## Unsafe Hoisting of Vectorized Loads Across Non-Returning Instructions

The bug is triggered when the vectorizer identifies a sequence of contiguous scalar loads that can be combined into a single vector load. The issue arises when these loads are interleaved with an instruction that is not guaranteed to return control to the successor (e.g., a function call that may exit the program, loop infinitely, or throw).

The optimization incorrectly hoists the combined vector load to a point before this intervening instruction. In the original program, the later loads are guarded by the execution of the intervening instruction; if that instruction does not return, the later loads are never executed. If the memory accessed by those later loads is invalid (e.g., out of bounds), the original program is safe because the access is skipped. However, the transformed code performs the full vector load unconditionally before the guard, potentially triggering undefined behavior (such as a fault) on paths where the program should have exited or diverged safely.

## Example

### Original IR
```llvm
define i32 @test_unsafe_hoist(ptr %ptr) {
entry:
  %val0 = load i32, ptr %ptr, align 4
  call void @may_not_return()
  %ptr1 = getelementptr inbounds i32, ptr %ptr, i64 1
  %val1 = load i32, ptr %ptr1, align 4
  %sum = add i32 %val0, %val1
  ret i32 %sum
}

declare void @may_not_return()
```
### Optimized IR
```llvm
define i32 @test_unsafe_hoist(ptr %ptr) {
entry:
  %0 = load <2 x i32>, ptr %ptr, align 4
  call void @may_not_return()
  %1 = extractelement <2 x i32> %0, i32 0
  %2 = extractelement <2 x i32> %0, i32 1
  %sum = add i32 %1, %2
  ret i32 %sum
}

declare void @may_not_return()
```
