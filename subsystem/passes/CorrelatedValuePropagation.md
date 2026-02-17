# Issue 142286

## Incorrect Default Case Elimination in Switch Instructions

**Description**
The bug occurs in an optimization that attempts to eliminate the default destination of a `switch` instruction by proving it is unreachable. The optimization relies on comparing the size of the inferred value range of the switch condition (the number of possible values it can take) against the number of explicit switch cases that are determined to be reachable.

The logic posits that if the number of reachable explicit cases is greater than or equal to the size of the condition's value range, then the explicit cases must exhaustively cover the range, making the default destination dead.

The issue arises because the calculation of "reachable cases" can include case values that fall strictly outside the inferred value range. This happens when the specific analysis used to prune individual cases fails to prove a case is impossible, even if it contradicts the broader value range constraint. Consequently, the count of reachable cases becomes artificially inflated. This leads the compiler to incorrectly satisfy the condition (case count $\ge$ range size) and erroneously mark the default destination as unreachable, even when there are valid values within the range that are not covered by any explicit case and should execute the default path.

## Example

### Original IR
```llvm
define i32 @test_switch_bug(i32 %x) {
entry:
  ; The condition is limited to range [0, 4) (values 0, 1, 2, 3)
  %cond = and i32 %x, 3
  switch i32 %cond, label %default [
    i32 0, label %case_valid
    i32 1, label %case_valid
    i32 2, label %case_valid
    ; This case is outside the range [0, 4), but counts towards the case count
    i32 5, label %case_valid
  ]

case_valid:
  ret i32 1

default:
  ; This path should be taken when %cond is 3
  ret i32 0
}
```
### Optimized IR
```llvm
define i32 @test_switch_bug(i32 %x) {
entry:
  %cond = and i32 %x, 3
  ; The optimizer incorrectly determines that the 4 explicit cases cover the range of size 4,
  ; making the default unreachable. However, case 5 is impossible, and value 3 is missing.
  switch i32 %cond, label %unreachable [
    i32 0, label %case_valid
    i32 1, label %case_valid
    i32 2, label %case_valid
    i32 5, label %case_valid
  ]

case_valid:
  ret i32 1

unreachable:
  unreachable
}
```


---

# Issue 68682

## Incorrect Removal of `llvm.abs` Intrinsic on `undef` Values

**Description**
The bug is triggered when the compiler attempts to optimize an `llvm.abs` (absolute value) intrinsic call by determining if the operation is redundant. The optimizer replaces `abs(x)` with `x` if it can prove that `x` is already non-negative (or `INT_MIN`, for which the operation is also an identity in two's complement).

The issue arises when the operand `x` is a value that can be `undef` (undefined) on certain execution paths, such as a PHI node that merges a known non-negative value with an `undef` value. The compiler's range analysis incorrectly assumes that the `undef` value satisfies the non-negative condition or ignores it, leading to the conclusion that the `abs` operation can be safely removed. However, `undef` can resolve to any bit pattern at runtime, including negative integers. If the `abs` operation is elided and the value resolves to a negative number, the program incorrectly preserves the negative sign instead of computing the positive magnitude, resulting in a miscompilation.

## Example

### Original IR
```llvm
define i32 @test_abs_undef(i1 %cond) {
entry:
  br i1 %cond, label %bb_pos, label %bb_undef

bb_pos:
  br label %merge

bb_undef:
  br label %merge

merge:
  %x = phi i32 [ 1, %bb_pos ], [ undef, %bb_undef ]
  %res = call i32 @llvm.abs.i32(i32 %x, i1 false)
  ret i32 %res
}

declare i32 @llvm.abs.i32(i32, i1)
```
### Optimized IR
```llvm
define i32 @test_abs_undef(i1 %cond) {
entry:
  br i1 %cond, label %bb_pos, label %bb_undef

bb_pos:
  br label %merge

bb_undef:
  br label %merge

merge:
  %x = phi i32 [ 1, %bb_pos ], [ undef, %bb_undef ]
  ret i32 %x
}
```
