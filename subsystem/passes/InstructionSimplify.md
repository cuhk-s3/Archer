# Issue 114191

## Eager Poison Folding of Vector Division/Remainder Threaded Over Select

The bug is triggered by a vector integer division or remainder instruction where the divisor is a `select` instruction. The `select` chooses between two constant vectors, and at least one of these constant vectors contains a zero or `undef` element. 

When the compiler attempts to optimize this pattern by threading the division or remainder operation over the `select`, it evaluates the operation against each constant vector independently. During this process, if the simplification logic encounters a constant vector with a zero or `undef` element as the divisor, it eagerly folds the entire division or remainder operation for that vector into `poison` (due to division by zero being undefined behavior). 

This transformation is incorrect because the zero or `undef` element might be masked out by the `select` condition at runtime. By unconditionally folding the operation to `poison`, the compiler introduces a miscompilation, as the `poison` value propagates to the final result even when the division by zero would not have dynamically occurred.

## Example

### Original IR
```llvm
define <2 x i32> @test_sdiv(<2 x i1> %cond, <2 x i32> %x) {
  %sel = select <2 x i1> %cond, <2 x i32> <i32 1, i32 0>, <2 x i32> <i32 2, i32 1>
  %div = sdiv <2 x i32> %x, %sel
  ret <2 x i32> %div
}
```
### Optimized IR
```llvm
define <2 x i32> @test_sdiv(<2 x i1> %cond, <2 x i32> %x) {
  %div.2 = sdiv <2 x i32> %x, <i32 2, i32 1>
  %div = select <2 x i1> %cond, <2 x i32> poison, <2 x i32> %div.2
  ret <2 x i32> %div
}
```


---

# Issue 115574

## Invalid Pointer Substitution Based on Equality Comparison

**Description**: 
The bug is triggered when the compiler simplifies a `select` instruction whose condition is an equality comparison (`icmp eq`) between two pointers. The optimization logic assumes that if two pointers compare equal, they are strictly equivalent and can be freely substituted for one another. Consequently, it replaces one pointer with the other in the arms of the `select` (or within expressions evaluated in the arms). 

However, in LLVM IR, pointers are not just addresses; they also carry provenance information (i.e., which memory allocation they belong to). Two pointers can have the exact same address (e.g., one pointing to the end of an allocation and another to the beginning of an adjacent one) but possess entirely different provenance. Substituting one pointer for another based solely on address equality can incorrectly change the provenance of the pointer returned by the `select`. This loss or alteration of provenance information violates the memory model and can lead to miscompilations in subsequent memory alias analyses or memory access optimizations.

## Example

### Original IR
```llvm
define ptr @test(ptr %p, ptr %q) {
  %cmp = icmp eq ptr %p, %q
  %sel = select i1 %cmp, ptr %p, ptr %q
  ret ptr %sel
}
```
### Optimized IR
```llvm
define ptr @test(ptr %p, ptr %q) {
  ret ptr %q
}
```


---

# Issue 58977

## Incorrect Logic Fold with Partial Undef Vector in Bitwise NOT Matching

**Description**: 
The bug is triggered by providing a vector logical expression that matches a specific simplification pattern involving a bitwise NOT operation (for example, the pattern `(B ^ ~A) | (A & B) --> B ^ ~A`). 

In LLVM IR, a bitwise NOT is typically represented as an XOR instruction with an all-ones constant. To trigger the miscompilation, the all-ones vector constant used in the XOR must contain `undef` elements (a partial undef vector). 

When the compiler's simplification logic matches this XOR instruction as a strict bitwise NOT, it proceeds to apply the logical fold. However, because of the `undef` lanes, the XOR does not strictly behave as a bitwise NOT for those specific lanes. This breaks the fundamental logical identity required for the transformation. As a result, the compiler replaces the original expression with a simplified version that is semantically inequivalent, potentially evaluating to a different value or becoming more undefined than the original source expression.

## Example

### Original IR
```llvm
define <2 x i32> @test(<2 x i32> %a, <2 x i32> %b) {
  %nota = xor <2 x i32> %a, <i32 -1, i32 undef>
  %xor = xor <2 x i32> %b, %nota
  %and = and <2 x i32> %a, %b
  %or = or <2 x i32> %xor, %and
  ret <2 x i32> %or
}
```
### Optimized IR
```llvm
define <2 x i32> @test(<2 x i32> %a, <2 x i32> %b) {
  %nota = xor <2 x i32> %a, <i32 -1, i32 undef>
  %xor = xor <2 x i32> %b, %nota
  ret <2 x i32> %xor
}
```


---

# Issue 64339

## Incorrect Simplification of `AND` with Power-of-Two Constant and Decremented Value

**Description**:
The bug is triggered by a bitwise `and` instruction where one operand is a constant power of two, and the other operand is an expression of the form `X - 1` (represented in IR as `X + (-1)`). 

The compiler attempts to optimize this pattern by checking if `X` is a power of two. If `X` is a strictly positive power of two, `X - 1` forms a contiguous bitmask of lower bits (e.g., `8 - 1 = 7`, which is `0b111` in binary). The compiler can then determine the result of the `and` operation based on the relative bit positions of `X` and the constant power of two, often folding it to zero if the constant's set bit falls outside the mask.

However, the compiler's analysis incorrectly allowed `X` to be zero (i.e., checking if `X` is "a power of two *or zero*"). If `X` is zero, `X - 1` evaluates to `-1` (where all bits are set to 1). In this scenario, `-1 & Constant` should simply evaluate to the `Constant`. Because the optimization logic assumed `X - 1` behaved strictly as a lower-bit mask, it incorrectly evaluated the bitwise intersection and erroneously folded the entire `and` expression to zero.

To trigger this bug, a program must construct an `and` operation matching this pattern where `X` is known by the compiler's analysis to be either a power of two or zero, and `X` actually evaluates to zero at runtime. The compiler will incorrectly optimize the expression to zero instead of the expected constant, leading to a miscompilation.

## Example

### Original IR
```llvm
define i32 @test(i32 %y) {
  %x = and i32 %y, 8
  %dec = add i32 %x, -1
  %res = and i32 %dec, 8
  ret i32 %res
}
```
### Optimized IR
```llvm
define i32 @test(i32 %y) {
  ret i32 0
}
```


---

# Issue 68683

## Incorrect Simplification of PHI Nodes with Undef and Potentially Poisonous Inputs

**Description**: 
The bug is triggered by a PHI node that receives a mix of `undef` and a common value `X` from its incoming edges. The compiler's simplification logic attempts to fold the PHI node directly to the common value `X` by ignoring the `undef` inputs. 

However, this transformation is invalid if `X` is not statically guaranteed to be free of `poison`. In LLVM IR, replacing an `undef` value with `poison` is not a valid refinement, because `poison` is a stronger, more restrictive state that can propagate and lead to undefined behavior. By folding the PHI node to `X`, the compiler inadvertently makes the result more poisonous on the control flow paths that originally provided `undef`. 

To trigger this miscompilation, one can construct a control flow graph containing a PHI node where at least one incoming edge provides `undef`, and the other edges provide a common value that could potentially evaluate to `poison` at runtime. The optimization pass will incorrectly delete the PHI node and replace its uses with the potentially poisonous value.

## Example

### Original IR
```llvm
define i32 @test(i1 %c, i32 %v) {
entry:
  %x = add nsw i32 %v, 1
  br i1 %c, label %if.then, label %if.end

if.then:
  br label %if.end

if.end:
  %phi = phi i32 [ %x, %if.then ], [ undef, %entry ]
  ret i32 %phi
}
```
### Optimized IR
```llvm
define i32 @test(i1 %c, i32 %v) {
entry:
  %x = add nsw i32 %v, 1
  ret i32 %x
}
```


---

# Issue 77320

## Incorrect Simplification of Vector Select Involving Cross-Lane Bitcasts

**Description**: 
The bug is triggered when the compiler attempts to simplify a vector `select` instruction by exploiting the equivalence implied by its vector condition (e.g., an element-wise equality comparison). The optimization logic tries to replace occurrences of one compared operand with the other within the computation of the selected values, assuming that the equivalence holds on a strictly per-lane basis. 

However, if the def-use chain of the selected value includes a `bitcast` instruction that changes the number of vector lanes (e.g., casting between vectors with different element sizes but the same total bit width), the operation is no longer strictly per-lane. A `bitcast` that alters the lane count effectively mixes data across the original lanes, making it a cross-lane operation. 

The compiler fails to recognize such `bitcast` instructions as cross-lane operations. Consequently, it incorrectly propagates the per-lane equivalence through the `bitcast`, replacing operands and simplifying the computation (e.g., incorrectly folding a subtraction to zero) even when the condition might only be true for a subset of the original lanes. This invalid assumption breaks the per-lane semantics of the vector `select`, leading to an incorrect fold and miscompilation of the selected value.

## Example

### Original IR
```llvm
define <4 x i32> @test(<4 x i32> %a, <4 x i32> %b, <4 x i32> %c) {
  %cond = icmp eq <4 x i32> %a, %b
  %cast_a = bitcast <4 x i32> %a to <2 x i64>
  %cast_b = bitcast <4 x i32> %b to <2 x i64>
  %sub = sub <2 x i64> %cast_a, %cast_b
  %cast_sub = bitcast <2 x i64> %sub to <4 x i32>
  %sel = select <4 x i1> %cond, <4 x i32> %cast_sub, <4 x i32> %c
  ret <4 x i32> %sel
}
```
### Optimized IR
```llvm
define <4 x i32> @test(<4 x i32> %a, <4 x i32> %b, <4 x i32> %c) {
  %cond = icmp eq <4 x i32> %a, %b
  %sel = select <4 x i1> %cond, <4 x i32> zeroinitializer, <4 x i32> %c
  ret <4 x i32> %sel
}
```


---

# Issue 91178

## Incorrect Simplification of `freeze` Instructions During Context-Dependent Operand Replacement

**Description**:
The bug is triggered by a miscompilation during context-dependent instruction simplification. The strategy involves the following high-level pattern:

1. **Poison-Generating Operation**: The IR contains an operation that can potentially evaluate to `poison` under certain conditions (e.g., an out-of-bounds shift, invalid arithmetic, etc.).
2. **Freeze Instruction**: A `freeze` instruction is applied to the result of this operation. The purpose of `freeze` is to ensure that if its operand is `poison`, it non-deterministically resolves to a fixed, arbitrary value, which must then be consistently observed by all subsequent uses.
3. **Context-Dependent Simplification**: An optimization pass attempts to simplify a dependent expression by assuming a specific context (e.g., replacing a variable with a known constant based on a `select` condition or a specific branch path).
4. **Invalid Refinement**: Under this assumed context, the optimization simplifies the operand of the `freeze` instruction to a concrete, non-poison value (effectively refining the potential `poison` to a specific constant, such as `0`). It then propagates this simplification through the `freeze`, replacing the `freeze` instruction itself with that concrete value during the analysis.
5. **Miscompilation**: By simplifying the `freeze` to a specific constant, the compiler incorrectly assumes that the `freeze` will always yield that exact value under the given context. However, at runtime, the `freeze` might resolve the `poison` to a completely different value. This false assumption leads the compiler to incorrectly fold or replace complex expressions (e.g., replacing an entire expression with the `freeze` instruction itself), resulting in a mismatch between the optimized code and the actual runtime behavior. 

In summary, the bug occurs because the optimization pass fails to respect the semantics of `freeze` during operand replacement. It incorrectly assumes a specific resolved value for a frozen `poison`, breaking the guarantee that all uses of the `freeze` must observe the same, potentially arbitrary, runtime value.

## Example

### Original IR
```llvm
define i32 @test(i32 %x) {
  %shl = shl i32 1, %x
  %fr = freeze i32 %shl
  %cmp = icmp eq i32 %x, 32
  %sel = select i1 %cmp, i32 0, i32 %fr
  ret i32 %sel
}
```
### Optimized IR
```llvm
define i32 @test(i32 %x) {
  %shl = shl i32 1, %x
  %fr = freeze i32 %shl
  ret i32 %fr
}
```
