# Issue 142286

## Incorrect Unreachable Default Branch in Switch Instructions Due to Out-of-Range Cases

### Description
This bug occurs during the optimization of `switch` instructions when the compiler attempts to determine if the default destination is unreachable. The miscompilation is triggered by an inconsistency between different analysis methods used to evaluate the switch condition's possible values.

The bug triggering strategy involves the following sequence:
1. **Restricted Condition Range**: The compiler determines that the condition of a `switch` instruction has a restricted, known range of possible values (e.g., a bounded integer range).
2. **Out-of-Range Cases**: The `switch` instruction contains explicit cases with values that fall outside this known valid range.
3. **Inconsistent Dead Case Elimination**: The compiler iterates through the cases and uses a specific analysis query to check if each case is unreachable. However, due to analysis limitations or inconsistencies, this query may fail to prove that an out-of-range case is impossible. As a result, the out-of-range case is incorrectly kept and counted as a "reachable" case.
4. **Faulty Coverage Assumption**: The compiler compares the total count of these supposedly reachable cases against the total number of possible values in the condition's known range. If the number of surviving cases equals or exceeds the size of the range, the compiler assumes that all possible valid values are explicitly covered by the cases.
5. **Miscompilation**: Because the counted cases include out-of-range values, the actual cases *within* the valid range do not cover all possible runtime values. Despite this, the compiler erroneously marks the default destination of the `switch` as unreachable. At runtime, if the condition evaluates to a valid value that lacks an explicit case, the program will branch to an unreachable block, leading to undefined behavior or a crash.

## Example

### Original IR
```llvm
declare void @f1()
declare void @f2()
declare void @f5()
declare void @f_def()

define void @test(i8 range(i8 1, 4) %x) {
entry:
  switch i8 %x, label %default [
    i8 1, label %case1
    i8 2, label %case2
    i8 5, label %case5
  ]

default:
  call void @f_def()
  ret void

case1:
  call void @f1()
  ret void

case2:
  call void @f2()
  ret void

case5:
  call void @f5()
  ret void
}
```
### Optimized IR
```llvm
declare void @f1()
declare void @f2()
declare void @f5()
declare void @f_def()

define void @test(i8 range(i8 1, 4) %x) {
entry:
  switch i8 %x, label %default [
    i8 1, label %case1
    i8 2, label %case2
    i8 5, label %case5
  ]

default:
  unreachable

case1:
  call void @f1()
  ret void

case2:
  call void @f2()
  ret void

case5:
  call void @f5()
  ret void
}
```


---

# Issue 68682

## Incorrect Simplification of Absolute Value Intrinsic with Undef Operand

**Description**

The bug occurs when a compiler optimization pass attempts to simplify an absolute value intrinsic (e.g., `llvm.abs`) based on the inferred value range or predicates of its operand. 

The triggering strategy involves the following sequence:
1. The operand of the absolute value intrinsic is constructed such that it can be either a known non-negative (or non-positive) value or `undef` (for example, through a PHI node with an `undef` incoming value).
2. The absolute value intrinsic is configured such that taking the absolute value of the minimum signed integer (`INT_MIN`) is well-defined and does not yield poison (i.e., the `is_int_min_poison` flag is set to `false`).
3. The compiler's value tracking analysis evaluates the range or predicate of the operand. When encountering `undef`, the analysis optimistically assumes that `undef` can take a specific value that satisfies the non-negative (or non-positive) condition.
4. Relying on this optimistic analysis, the optimization pass concludes that the operand is always non-negative (or non-positive) and replaces the absolute value intrinsic directly with the operand (or its negation).
5. This transformation is invalid and leads to a miscompilation. The original absolute value intrinsic guarantees that its result is strictly non-negative (or exactly `INT_MIN`). However, replacing the intrinsic with the operand itself allows the `undef` value to be evaluated as any arbitrary negative value later in the program. This incorrectly expands the set of possible values, violating the semantics of the absolute value operation. 

To correctly handle this pattern, the analysis must treat `undef` as a full range (rather than optimistically assigning it a constrained value) whenever the absolute value intrinsic does not treat `INT_MIN` as poison.

## Example

### Original IR
```llvm
declare i32 @llvm.abs.i32(i32, i1 immarg)

define i32 @test(i1 %c) {
entry:
  br i1 %c, label %if.then, label %if.end

if.then:
  br label %if.end

if.end:
  %p = phi i32 [ 5, %if.then ], [ undef, %entry ]
  %abs = call i32 @llvm.abs.i32(i32 %p, i1 false)
  ret i32 %abs
}

```
### Optimized IR
```llvm
declare i32 @llvm.abs.i32(i32, i1 immarg)

define i32 @test(i1 %c) {
entry:
  br i1 %c, label %if.then, label %if.end

if.then:
  br label %if.end

if.end:
  %p = phi i32 [ 5, %if.then ], [ undef, %entry ]
  ret i32 %p
}

```
