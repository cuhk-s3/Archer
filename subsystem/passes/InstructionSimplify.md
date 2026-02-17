# Issue 115574

## Incorrect Pointer Substitution in Select Simplification

**Description**: 
The bug is triggered when the optimizer simplifies a `select` instruction whose condition is an equality comparison (`icmp eq`) between two pointer values. The optimization logic incorrectly assumes that if two pointers compare equal, they are semantically equivalent and can be freely substituted for one another. Consequently, the optimizer replaces one pointer operand with the other (e.g., simplifying `select (a == b) ? a : b` to `b`).

This transformation is invalid because LLVM pointers carry provenance information. Two pointers may share the same memory address (comparing equal) but originate from different underlying allocations. Substituting one for the other changes the provenance of the resulting value, which constitutes a miscompilation. The issue arises because the optimizer fails to verify that the pointers are safe to replace (i.e., that they share the same provenance or that provenance does not matter in the context) before applying the substitution.

## Example

### Original IR
```llvm
define i8* @test_provenance_select(i8* %a, i8* %b) {
  %cmp = icmp eq i8* %a, %b
  %res = select i1 %cmp, i8* %a, i8* %b
  ret i8* %res
}
```
### Optimized IR
```llvm
define i8* @test_provenance_select(i8* %a, i8* %b) {
  ret i8* %b
}
```


---

# Issue 58977

## Incorrect Logic Simplification Involving Partial Undef Vectors in Bitwise NOT Patterns

## Description
The bug occurs in an instruction simplification pass that optimizes boolean logic expressions, specifically targeting the pattern `(B ^ ~A) | (A & B)` to simplify it to `B ^ ~A`. The error stems from how the optimizer identifies the bitwise NOT operation (`~A`). The pattern matcher permits the `~A` term to be represented by an XOR instruction with a constant vector that includes `undef` elements, effectively treating `undef` as the required all-ones value.

However, the validity of the transformation relies on the strict property that `~A` is the complement of `A`. When `undef` is present, the operation behaves as `A ^ undef`. In the original expression, the term `(A & B)` can mask the undefined behavior (e.g., if `A` and `B` are both 1, `A & B` is 1, forcing the result of the OR operation to 1 regardless of the `undef` value). By simplifying the expression to just `B ^ ~A`, this masking term is removed, exposing the `undef` value in the result. This allows the transformed code to produce a value (e.g., 0) that was impossible in the original code (which was forced to 1), resulting in a miscompilation.

## Example

### Original IR
```llvm
define <2 x i32> @bug_trigger(<2 x i32> %a, <2 x i32> %b) {
  %not_a = xor <2 x i32> %a, <i32 -1, i32 undef>
  %xor_part = xor <2 x i32> %b, %not_a
  %and_part = and <2 x i32> %a, %b
  %res = or <2 x i32> %xor_part, %and_part
  ret <2 x i32> %res
}
```
### Optimized IR
```llvm
define <2 x i32> @bug_trigger(<2 x i32> %a, <2 x i32> %b) {
  %not_a = xor <2 x i32> %a, <i32 -1, i32 undef>
  %res = xor <2 x i32> %b, %not_a
  ret <2 x i32> %res
}
```


---

# Issue 64339

## Incorrect Simplification of (X - 1) & PowerOf2 due to Zero Handling

**Description**
The bug is triggered during the simplification of a bitwise `AND` instruction where one operand is a constant power of two and the other operand is a value `X` decremented by one (represented as `add X, -1`). The compiler attempts to optimize this pattern by analyzing whether `X` is known to be a power of two.

The issue arises because the analysis incorrectly treats zero as a valid value for `X` in this context (checking if `X` is "zero or a power of two"). However, the transformation logic relies on `X` being a strictly non-zero power of two.
- If `X` is a non-zero power of two (e.g., 4), `X - 1` creates a mask of lower bits (e.g., 3 or `011`).
- If `X` is zero, `X - 1` wraps around to all ones (e.g., -1).

By allowing `X` to be zero, the compiler applies logic intended for the bitmask pattern to the all-ones case, resulting in an incorrect simplification.

## Example

### Original IR
```llvm
define i32 @test(i1 %c) {
  %x = select i1 %c, i32 32, i32 0
  %sub = add i32 %x, -1
  %and = and i32 %sub, 32
  ret i32 %and
}
```
### Optimized IR
```llvm
define i32 @test(i1 %c) {
  ret i32 0
}
```


---

# Issue 68683

## Incorrect Propagation of Poison via PHI Node Simplification with Undef

**Description**
The bug is triggered when the optimizer simplifies a PHI node that merges a specific value $V$ and an `undef` constant. The optimization logic incorrectly assumes that such a PHI node can always be replaced by $V$.

This transformation is invalid if $V$ is not guaranteed to be non-poison. In LLVM IR, `undef` represents an arbitrary bit pattern, whereas `poison` represents a value resulting from an erroneous operation (like signed overflow) that causes undefined behavior if subsequently used in certain ways. If $V$ is `poison`, replacing the PHI node with $V$ causes the program to produce `poison` on the control flow path that originally produced `undef`. Since replacing `undef` with `poison` is forbidden (as it introduces potential undefined behavior where there was none), this simplification leads to a miscompilation.

## Example

### Original IR
```llvm
define i32 @test_poison_propagation(i1 %cond, i32 %x) {
entry:
  %v = add nsw i32 %x, 1
  br i1 %cond, label %bb1, label %bb2

bb1:
  br label %merge

bb2:
  br label %merge

merge:
  %res = phi i32 [ %v, %bb1 ], [ undef, %bb2 ]
  ret i32 %res
}
```
### Optimized IR
```llvm
define i32 @test_poison_propagation(i1 %cond, i32 %x) {
entry:
  %v = add nsw i32 %x, 1
  br i1 %cond, label %bb1, label %bb2

bb1:
  br label %merge

bb2:
  br label %merge

merge:
  ret i32 %v
}
```


---

# Issue 98753

## Incorrect Simplification of Logic Operations with Undef Operands

**Description**:
The bug is triggered by an optimization that simplifies logical `and` or `or` instructions where one operand is a comparison (e.g., `icmp`) and the other is a value dependent on that comparison. The optimizer attempts to eliminate the comparison and replace the entire expression with the dependent value (e.g., transforming `(A != B) && C` to `C`). This transformation is performed if the dependent value `C` can be proven to simplify to the operation's absorbing element (e.g., `false` for `and`, `true` for `or`) under the assumption that the comparison yields that absorbing result (e.g., assuming `A == B`).

The issue arises because the simplification logic incorrectly allows `undef` values within `C` to be refined to the specific absorbing constant required to justify the transformation. The optimizer assumes that because `undef` *can* be the absorber, `C` *is* the absorber. However, the replacement instruction is simply `C`, which still contains the original `undef` value. At runtime, this `undef` is not constrained to the chosen constant and may resolve to the opposite value. Consequently, the optimized code may evaluate to `true` (or `false`) in cases where the original expression was guaranteed to evaluate to the absorber value due to the comparison, leading to a miscompilation.

## Example

### Original IR
```llvm
define i1 @test(i8 %a, i8 %b) {
  %cmp = icmp ne i8 %a, %b
  %c = select i1 %cmp, i1 true, i1 undef
  %res = and i1 %cmp, %c
  ret i1 %res
}
```
### Optimized IR
```llvm
define i1 @test(i8 %a, i8 %b) {
  %cmp = icmp ne i8 %a, %b
  %c = select i1 %cmp, i1 true, i1 undef
  ret i1 %c
}
```
