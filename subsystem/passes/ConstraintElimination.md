# Issue 105785

## Incorrect Folding of 3-Way Comparison Intrinsics Due to Misinterpreted Analysis Result

**Description**: 
The bug is triggered when a 3-way comparison intrinsic (such as `scmp` or `ucmp`) is used with operands that can be proven to be strictly unequal by the compiler's constraint analysis. 

When the optimization pass attempts to simplify the intrinsic, it queries the analysis to check if the two operands are equal. The analysis correctly determines that the equality condition is definitively false and returns this result (typically as an optional boolean value). However, due to a logic error in evaluating the result (e.g., checking if the optional result *has a value* rather than if the value itself is *true*), the pass misinterprets the definitive "false" as a "true". 

Consequently, the pass incorrectly assumes the operands are equal and erroneously folds the 3-way comparison intrinsic to `0`, leading to a miscompilation.

## Example

### Original IR
```llvm
declare i8 @llvm.scmp.i8.i32(i32, i32)
declare void @llvm.assume(i1)

define i8 @test_scmp_miscompile(i32 %x, i32 %y) {
entry:
  %cmp = icmp ne i32 %x, %y
  call void @llvm.assume(i1 %cmp)
  %res = call i8 @llvm.scmp.i8.i32(i32 %x, i32 %y)
  ret i8 %res
}

```
### Optimized IR
```llvm
declare i8 @llvm.scmp.i8.i32(i32, i32)
declare void @llvm.assume(i1)

define i8 @test_scmp_miscompile(i32 %x, i32 %y) {
entry:
  %cmp = icmp ne i32 %x, %y
  call void @llvm.assume(i1 %cmp)
  ret i8 0
}

```


---

# Issue 116553

## Incorrect Propagation of Induction Variable Bounds to Non-Dedicated Loop Exits

**Description:**
The bug occurs in the Constraint Elimination pass when it infers facts about induction variables in loop exit blocks. When a loop exits based on a condition in its header, the pass assumes that the induction variable satisfies a specific bound (e.g., less than or equal to the loop limit) in all of the loop's exit blocks. 

To trigger this bug, the following strategy can be used at the LLVM IR level:
1. **Construct a Loop with an Induction Variable:** Create a loop where the header contains an exiting condition (such as an equality or inequality check) based on an induction variable.
2. **Introduce a Non-Dedicated Exit Block:** Define an exit block for this loop that is non-dedicated. A non-dedicated exit block has incoming edges from outside the loop or from paths that bypass the loop header, meaning the loop header does not strictly dominate the exit block.
3. **Add Constraints in the Exit Path:** Place a conditional branch, check, or instruction in the non-dedicated exit block (or its successors) that depends on the induction variable or the loop bound.
4. **Trigger the Miscompilation:** The compiler will incorrectly propagate the loop's exit bound to this non-dedicated exit block, assuming the bound holds true for all paths reaching the block. Because the block can be reached via paths where the loop header was never executed, this invalid assumption leads to the erroneous elimination or simplification of constraints, ultimately causing a miscompilation.

## Example

### Original IR
```llvm
define i1 @test_non_dedicated_exit(i32 %n, i1 %c) {
entry:
  br i1 %c, label %loop.header, label %exit

loop.header:
  %iv = phi i32 [ 0, %entry ], [ %iv.next, %loop.latch ]
  %cmp = icmp ult i32 %iv, %n
  br i1 %cmp, label %loop.latch, label %exit

loop.latch:
  %iv.next = add i32 %iv, 1
  br label %loop.header

exit:
  %iv.lcssa = phi i32 [ 0, %entry ], [ %iv, %loop.header ]
  %cmp.exit = icmp uge i32 %iv.lcssa, %n
  ret i1 %cmp.exit
}
```
### Optimized IR
```llvm
define i1 @test_non_dedicated_exit(i32 %n, i1 %c) {
entry:
  br i1 %c, label %loop.header, label %exit

loop.header:
  %iv = phi i32 [ 0, %entry ], [ %iv.next, %loop.latch ]
  %cmp = icmp ult i32 %iv, %n
  br i1 %cmp, label %loop.latch, label %exit

loop.latch:
  %iv.next = add i32 %iv, 1
  br label %loop.header

exit:
  %iv.lcssa = phi i32 [ 0, %entry ], [ %iv, %loop.header ]
  ret i1 true
}
```


---

# Issue 137937

## Incorrect Operand Replacement in Logical Operations with Poison-Generating Flags

**Description:**
The bug is triggered when the compiler attempts to simplify an operand of a logical operation (such as `or` or `and`) based on the context implied by its other operand, without properly handling poison-generating flags. 

The strategy to trigger this issue involves the following steps:
1. **Create a Logical Operation with a Flag**: Introduce a binary logical operation that includes a poison-generating flag. For example, an `or` instruction with the `disjoint` flag, which asserts that the two operands never have common bits set to `1` simultaneously.
2. **Establish an Implied Condition**: Formulate the operands (typically comparison instructions) such that one operand's value implies the other's value under certain conditions. For instance, design the conditions so that if the first operand of the `or` is `false`, the second operand is statically guaranteed to be `true`.
3. **Trigger the Flawed Optimization**: The compiler analyzes the logical operation and uses the implied context (e.g., assuming the first operand is `false` to evaluate the second) to simplify the second operand to a constant (`true`). It then replaces the operand in-place while leaving the original logical instruction and its poison-generating flag intact.
4. **Violate the Flag**: Provide an input where the first operand evaluates to `true`. Because the second operand was replaced with the constant `true`, the instruction now evaluates `true OR true`. This violates the `disjoint` flag's requirement that both operands cannot share set bits, causing the instruction to produce a `poison` value and leading to a miscompilation.

In abstract terms, replacing an operand based on short-circuiting logic is unsafe if the instruction carries exactness or disjointness flags, as the replacement can create invalid combinations of operands for paths that would have otherwise been short-circuited. The correct approach is to simplify the entire logical instruction rather than replacing its operands in-place.

## Example

### Original IR
```llvm
define i1 @test(i32 %x) {
entry:
  %a = icmp eq i32 %x, 0
  %b = icmp ne i32 %x, 0
  %res = or disjoint i1 %a, %b
  ret i1 %res
}
```
### Optimized IR
```llvm
define i1 @test(i32 %x) {
entry:
  %a = icmp eq i32 %x, 0
  %res = or disjoint i1 %a, true
  ret i1 %res
}
```


---

# Issue 140481

## Incorrect Handling of Integer Overflow in Linear Expression Decomposition

**Description:**
The bug is triggered by a sequence of arithmetic instructions (such as additions, subtractions, multiplications, or shifts) involving variables and large constants. When the compiler attempts to analyze and decompose these chained operations into a linear mathematical expression (e.g., representing them as a sum of variables with coefficients and a constant offset) to build constraints, the internal calculation of these coefficients or offsets can exceed the bounds of the compiler's internal integer representation (typically 64-bit signed integers). 

If the compiler's decomposition logic silently allows these internal values to overflow or wrap around without invalidating the decomposition, it generates an incorrect mathematical model of the program's values. Consequently, optimization passes that rely on these mathematical constraints to prove properties about variables will evaluate comparisons based on the corrupted model. This leads to invalid simplifications, such as incorrectly folding a comparison instruction to `true` or `false`, ultimately resulting in a miscompilation.

## Example

### Original IR
```llvm
define i1 @test_overflow(i128 %x) {
entry:
  %cmp.pre = icmp sgt i128 %x, 0
  br i1 %cmp.pre, label %then, label %else

then:
  %mul1 = mul nsw i128 %x, 4611686018427387904
  %mul2 = mul nsw i128 %mul1, 3
  %cmp = icmp sgt i128 %mul2, 0
  ret i1 %cmp

else:
  ret i1 false
}

```
### Optimized IR
```llvm
define i1 @test_overflow(i128 %x) {
entry:
  %cmp.pre = icmp sgt i128 %x, 0
  br i1 %cmp.pre, label %then, label %else

then:
  %mul1 = mul nsw i128 %x, 4611686018427387904
  %mul2 = mul nsw i128 %mul1, 3
  %cmp = icmp sgt i128 %mul2, 0
  ret i1 false

else:
  ret i1 false
}

```


---

# Issue 68751

## Incorrect Decomposition of Wide Integer Types in Constraint Elimination

**Description**: 
The bug is triggered when the compiler analyzes constraints and conditions involving integer types that are wider than the internal coefficient representation used by the optimization pass (typically 64 bits). 

When the compiler attempts to simplify comparisons or conditional branches, it decomposes the underlying arithmetic expressions (such as additions, multiplications, or extensions) into a linear system of variables and constant coefficients. However, if the original integer types are wider than the internal fixed-width integers used to store these coefficients, the arithmetic performed on the coefficients during decomposition can overflow or wrap around. 

Because this internal wrapping does not match the actual semantics of the operations in the original, wider bit width, the compiler constructs an invalid mathematical model of the constraints. This mismatch leads the compiler to deduce incorrect relationships between values, resulting in miscompilations where conditions are erroneously evaluated as always true or always false, and necessary branches or checks are incorrectly eliminated.

## Example

### Original IR
```llvm
define i1 @test_wide_int_truncation(i128 %a) {
entry:
  %pre = icmp ult i128 %a, 10
  br i1 %pre, label %then, label %else

then:
  %add = add nuw i128 %a, 18446744073709551615
  %cmp = icmp ult i128 %add, %a
  ret i1 %cmp

else:
  ret i1 false
}
```
### Optimized IR
```llvm
define i1 @test_wide_int_truncation(i128 %a) {
entry:
  %pre = icmp ult i128 %a, 10
  br i1 %pre, label %then, label %else

then:
  %add = add nuw i128 %a, 18446744073709551615
  ret i1 true

else:
  ret i1 false
}
```


---

# Issue 76713

## Incorrect Decomposition of `nuw` Subtraction with Negative Constants

**Description**: 
The bug is triggered when the compiler analyzes a subtraction instruction marked with the `nuw` (no unsigned wrap) flag, where the second operand (the subtrahend) is a constant that evaluates to a negative value when sign-extended (i.e., a large unsigned constant). 

During constraint elimination, the compiler attempts to decompose expressions into a base variable and a constant offset to build a system of linear constraints. However, the specific pattern-matching logic for `nuw` subtractions fails to correctly process these negative constants, leading to an erroneous offset calculation. 

Because of this flawed decomposition, invalid mathematical facts are introduced into the constraint system. Consequently, the compiler may incorrectly evaluate subsequent conditions based on these flawed constraints, improperly folding branch conditions to constants (such as `true` or `false`). This alters the control flow and results in a miscompilation where the program takes the wrong execution path.

## Example

### Original IR
```llvm
define i1 @test_sub_nuw_negative_constant(i8 %x) {
entry:
  %sub = sub nuw i8 %x, 254
  %cmp = icmp uge i8 %sub, %x
  br i1 %cmp, label %t, label %f

t:
  ret i1 true

f:
  ret i1 false
}
```
### Optimized IR
```llvm
define i1 @test_sub_nuw_negative_constant(i8 %x) {
entry:
  %sub = sub nuw i8 %x, 254
  %cmp = icmp uge i8 %sub, %x
  br i1 true, label %t, label %f

t:
  ret i1 true

f:
  ret i1 false
}
```


---

# Issue 78621

## Unconditional Constraint Addition for Potentially Poisonous Min/Max Intrinsics

**Description**: 
The bug occurs when the compiler's constraint elimination logic unconditionally adds facts about the results of min/max intrinsics (such as `umin`, `umax`, `smin`, `smax`) to its constraint system, without verifying if the intrinsic's result is guaranteed not to be poison. 

To trigger this miscompilation, the following pattern can be constructed at the LLVM IR level:
1. **Generate a Potentially Poisonous Value**: Create an instruction that can produce a poison value under certain conditions by using optimization flags (e.g., `nuw`, `nsw` on a shift or arithmetic operation).
2. **Use in a Min/Max Intrinsic**: Feed this potentially poisonous value as an operand to a min/max intrinsic.
3. **Avoid Undefined Behavior**: Ensure that the result of the min/max intrinsic is not used in any context that would trigger undefined behavior (UB). The poison value should remain unobserved.
4. **Test the Original Input**: Include a separate condition (e.g., an `icmp` instruction) that evaluates the original input used to generate the potentially poisonous value.

When the constraint elimination pass processes the min/max intrinsic, it unconditionally adds constraints relating the intrinsic's result to its operands (e.g., `result <= operand`). By doing so, it implicitly assumes that the result and its operands are not poison. This allows the constraint system to incorrectly deduce properties about the original inputs (for example, assuming an input must be non-negative because a `nuw` flag was present on the derived poison value). Finally, the compiler uses these flawed deductions to incorrectly fold or simplify the separate, independent condition, leading to a miscompilation since the poison value never actually caused UB in the original program.

## Example

### Original IR
```llvm
declare i8 @llvm.umin.i8(i8, i8)

define i1 @test_umin_nuw(i8 %x, ptr %ptr) {
entry:
  %p = add nuw i8 %x, 10
  %m = call i8 @llvm.umin.i8(i8 %p, i8 10)
  store i8 %m, ptr %ptr, align 1
  %cmp = icmp ugt i8 %x, 245
  ret i1 %cmp
}
```
### Optimized IR
```llvm
declare i8 @llvm.umin.i8(i8, i8)

define i1 @test_umin_nuw(i8 %x, ptr %ptr) {
entry:
  %p = add nuw i8 %x, 10
  %m = call i8 @llvm.umin.i8(i8 %p, i8 10)
  store i8 %m, ptr %ptr, align 1
  ret i1 false
}
```
