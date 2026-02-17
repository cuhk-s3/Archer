# Issue 105785

## Summary Title
Incorrect Folding of Three-Way Comparison Intrinsics on Proven Inequality

## Description
The bug is triggered when the Constraint Elimination pass attempts to optimize three-way comparison intrinsics (e.g., `scmp`, `ucmp`) by checking if their operands are equal based on dominating constraints. The optimization logic queries the constraint system, which returns a result indicating whether the equality condition is proven true, proven false, or unknown. The error arises because the code checks for the *presence* of a definitive proof result (whether true or false) rather than verifying that the result specifically proves equality (true). Consequently, when the constraint system successfully proves that the operands are *not* equal (returning a "proven false" result), the optimizer misinterprets this as a valid signal to apply the optimization. It then incorrectly replaces the comparison intrinsic with zero (the value representing equality), leading to a miscompilation where unequal operands result in an equality return value.

## Example

### Original IR
```llvm
define i8 @test_scmp_bug(i32 %a, i32 %b) {
entry:
  ; Establish a constraint where %a is strictly less than %b
  %cmp = icmp slt i32 %a, %b
  br i1 %cmp, label %then, label %else

then:
  ; Inside this block, %a < %b is known.
  ; Therefore, %a == %b is proven false.
  ; The bug causes the optimizer to see the 'proven' status and incorrectly fold this to 0.
  %res = call i8 @llvm.scmp.i8.i32(i32 %a, i32 %b)
  ret i8 %res

else:
  ret i8 0
}

declare i8 @llvm.scmp.i8.i32(i32, i32)
```
### Optimized IR
```llvm
define i8 @test_scmp_bug(i32 %a, i32 %b) {
entry:
  %cmp = icmp slt i32 %a, %b
  br i1 %cmp, label %then, label %else

then:
  ; The call to llvm.scmp has been incorrectly replaced with 0
  ret i8 0

else:
  ret i8 0
}

declare i8 @llvm.scmp.i8.i32(i32, i32)
```


---

# Issue 116553

## Incorrect Propagation of Induction Variable Constraints to Non-Dominated Exit Blocks

**Description**:
The bug is triggered in the `ConstraintElimination` pass when it analyzes loops with induction variables. The optimization logic infers that if a loop is exited, the induction variable must satisfy a specific bound derived from the loop header's comparison (e.g., if the loop continues while `IV < Limit`, then `IV <= Limit` must hold at the exit). The pass attempts to propagate this inferred fact to the loop's exit blocks to facilitate further simplifications.

The critical flaw is that the transformation applies this constraint to **all** exit blocks of the loop without verifying that the loop header dominates them. In LLVM IR, a loop exit block can be a merge point (such as a shared return block) that is also reachable via control flow paths that bypass the loop entirely. For such "non-dedicated" exits, the loop header does not dominate the block. By adding the loop-dependent constraint to these blocks, the optimizer incorrectly assumes the fact holds on all paths, including those that never executed the loop. This introduces a false assumption into the constraint system, leading to invalid simplifications and miscompilation of code on the bypassing paths.

## Example

### Original IR
```llvm
define i1 @test(i32 %start, i32 %limit, i1 %cond) {
entry:
  br i1 %cond, label %exit, label %loop

loop:
  %iv = phi i32 [ %start, %entry ], [ %iv.next, %loop ]
  %iv.next = add i32 %iv, 1
  %cmp = icmp ult i32 %iv, %limit
  br i1 %cmp, label %loop, label %exit

exit:
  %val = phi i32 [ %start, %entry ], [ %iv, %loop ]
  %res = icmp uge i32 %val, %limit
  ret i1 %res
}
```
### Optimized IR
```llvm
define i1 @test(i32 %start, i32 %limit, i1 %cond) {
entry:
  br i1 %cond, label %exit, label %loop

loop:
  %iv = phi i32 [ %start, %entry ], [ %iv.next, %loop ]
  %iv.next = add i32 %iv, 1
  %cmp = icmp ult i32 %iv, %limit
  br i1 %cmp, label %loop, label %exit

exit:
  %val = phi i32 [ %start, %entry ], [ %iv, %loop ]
  ret i1 true
}
```


---

# Issue 137937

## Incorrect Operand Substitution in Disjoint OR Instructions

**Description**:
The bug is triggered when the optimizer attempts to simplify a logical `or` instruction marked with the `disjoint` flag. The optimization logic analyzes the constraints on the instruction's operands and determines that the value of one operand is implied by the other (e.g., deducing that if the first operand is false, the second operand must be true). Based on this deduction, the optimizer replaces the implied operand with a constant boolean value (e.g., `true`) in-place.

This transformation is incorrect because it fails to respect the invariants required by the `disjoint` flag, which mandates that both operands cannot be true simultaneously. In the original code, the operands dynamically satisfied this condition. However, by replacing one operand with a constant `true`, the transformed instruction violates the disjointness constraint whenever the remaining dynamic operand also evaluates to `true`. This results in undefined behavior (poison) in cases where the original program was well-defined. The optimizer should simplify the entire instruction rather than modifying individual operands of instructions with safety constraints like `disjoint`.

## Example

### Original IR
```llvm
define i1 @bug_trigger(i1 %a, i1 %b) {
entry:
  ; Establish the condition that (a || b) is true.
  ; This implies that if %a is false, %b must be true.
  %cond = or i1 %a, %b
  br i1 %cond, label %if.then, label %if.else

if.then:
  ; In this block, we know (%a || %b) is true.
  ; The optimizer might incorrectly use the implication (!%a -> %b) to replace %b with true.
  ; However, if %a is true, %b must be false for 'disjoint' to hold.
  ; Replacing %b with true makes the case (%a=true) poison.
  %res = or disjoint i1 %a, %b
  ret i1 %res

if.else:
  ret i1 false
}
```
### Optimized IR
```llvm
define i1 @bug_trigger(i1 %a, i1 %b) {
entry:
  %cond = or i1 %a, %b
  br i1 %cond, label %if.then, label %if.else

if.then:
  ; The optimizer incorrectly replaced %b with true based on the constraint (!%a -> %b).
  ; This transforms the instruction into 'or disjoint i1 %a, true'.
  ; If %a is true at runtime (which is valid in the original code if %b is false),
  ; this instruction now executes 'true | true' with the disjoint flag, resulting in Poison.
  %res = or disjoint i1 %a, true
  ret i1 %res

if.else:
  ret i1 false
}
```


---

# Issue 140481

## Integer Overflow in Constraint Decomposition Logic

**Description**
The bug is triggered when the Constraint Elimination pass attempts to decompose a chain of integer arithmetic instructions (such as additions, subtractions, multiplications, and shifts) into a linear constraint system (e.g., representing a value as $A \times x + B$). During this decomposition, the compiler computes the linear coefficients and constant offsets by accumulating the constant operands from the instruction sequence. 

If the cumulative magnitude of these calculated coefficients or offsets exceeds the capacity of the compiler's internal fixed-width integer representation (typically 64-bit), an arithmetic overflow occurs. The analysis logic previously failed to detect or handle this overflow, instead using the wrapped result to model the variable's constraints. This results in an incorrect mathematical representation of the program state. The constraint solver then uses these invalid constraints to prove conditions (e.g., determining if a comparison is always true or false), leading to erroneous code simplifications and miscompilation.

## Example

### Original IR
```llvm
define i1 @test_overflow(i128 %x) {
entry:
  ; Ensure x is small so x + 2^64 doesn't overflow i128
  %cmp = icmp ult i128 %x, 100
  br i1 %cmp, label %if.then, label %if.end

if.then:
  ; Add 2^64 to x. In unbounded math, this is x + 18446744073709551616.
  ; If the compiler tracks the offset in a 64-bit integer, it wraps to 0.
  %add = add nuw i128 %x, 18446744073709551616
  ; The comparison should be true (x + 2^64 > x).
  ; If the compiler sees offset 0, it evaluates x > x, which is false.
  %res = icmp ugt i128 %add, %x
  ret i1 %res

if.end:
  ret i1 false
}
```
### Optimized IR
```llvm
define i1 @test_overflow(i128 %x) {
entry:
  %cmp = icmp ult i128 %x, 100
  br i1 %cmp, label %if.then, label %if.end

if.then:
  %add = add nuw i128 %x, 18446744073709551616
  ; The bug causes the compiler to incorrectly fold the comparison to false.
  ret i1 false

if.end:
  ret i1 false
}
```


---

# Issue 68751

## Miscompilation due to Coefficient Overflow in Constraint Analysis of Wide Integers

**Description**:
The bug is triggered when the optimizer's constraint elimination analysis processes LLVM IR containing integer types with a bit width larger than 64 bits. The analysis attempts to decompose arithmetic operations and values into a system of linear constraints to prove relationships between values (e.g., to eliminate redundant comparisons). However, the internal logic uses fixed 64-bit integers to represent the coefficients and constants of these linear equations. When operating on integers wider than 64 bits, the calculation of these coefficients can overflow the 64-bit internal representation, even if the original operation in the IR is valid within its wider bit width. This overflow causes the constraint solver to construct an incorrect mathematical model of the program, leading it to erroneously deduce that certain conditions are always true or false and incorrectly optimize the code.

## Example

### Original IR
```llvm
define i1 @test_wide_integer_overflow(i128 %a) {
entry:
  ; Ensure %a is small enough so that adding 2^64 doesn't overflow 128 bits
  %cond = icmp ult i128 %a, 100
  br i1 %cond, label %then, label %else

then:
  ; Add 2^64 (18446744073709551616) to %a
  ; This constant fits in i128 but overflows int64_t (which is used internally by the buggy analysis)
  %val = add nuw i128 %a, 18446744073709551616
  
  ; Check if %val > %a. This should always be true.
  ; However, if the analysis truncates the constant to 64 bits (becoming 0),
  ; it sees %val = %a + 0, and concludes %val > %a is false.
  %result = icmp ugt i128 %val, %a
  ret i1 %result

else:
  ret i1 false
}
```
### Optimized IR
```llvm
define i1 @test_wide_integer_overflow(i128 %a) {
entry:
  %cond = icmp ult i128 %a, 100
  br i1 %cond, label %then, label %else

then:
  %val = add nuw i128 %a, 18446744073709551616
  ; The optimizer incorrectly determined the comparison is always false
  ret i1 false

else:
  ret i1 false
}
```


---

# Issue 76713

## Incorrect Decomposition of `sub nuw` with Large Constant Operands

**Description**: 
The bug is triggered when the `ConstraintElimination` pass attempts to decompose a subtraction instruction marked with the `nuw` (No Unsigned Wrap) attribute where the second operand (the subtrahend) is a constant. 

The issue arises from how the optimization logic converts the constant operand into an offset for the linear constraint system. The logic incorrectly interprets the constant bit pattern as a signed integer and negates it to compute the additive offset. If the constant represents a large unsigned value that has its most significant bit set (which makes it appear negative in a signed interpretation), the negation results in a small positive value. 

Consequently, the constraint system models the subtraction of a large unsigned number as the addition of a small positive number (e.g., treating `x - 0xFFFF` as `x + 1` for a 16-bit integer). This distortion of the arithmetic relationship leads the optimizer to deduce incorrect facts about value ranges, resulting in the invalid simplification of conditional branches and miscompilation of the program.

## Example

### Original IR
```llvm
define i1 @test(i16 %a) {
entry:
  %cmp = icmp uge i16 %a, 65280
  br i1 %cmp, label %if.then, label %if.end

if.then:
  %sub = sub nuw i16 %a, 65280
  %check = icmp ugt i16 %sub, %a
  ret i1 %check

if.end:
  ret i1 false
}
```
### Optimized IR
```llvm
define i1 @test(i16 %a) {
entry:
  %cmp = icmp uge i16 %a, 65280
  br i1 %cmp, label %if.then, label %if.end

if.then:
  %sub = sub nuw i16 %a, 65280
  ret i1 true

if.end:
  ret i1 false
}
```
