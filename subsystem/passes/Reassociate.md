# Issue 57683

## Incorrect Reuse of Vector Negation Containing Poison Elements

**Description**
The bug is triggered when the reassociation pass attempts to optimize vector expressions by reusing an existing subtraction instruction that acts as a negation. The optimizer incorrectly identifies a vector subtraction of the form `C - X` as a valid negation of `X` (i.e., `0 - X`), even when the constant vector `C` contains `poison` or `undef` elements in some lanes. By treating this instruction as a canonical negation and reusing it to rewrite other expressions involving `X`, the compiler introduces `poison` values into lanes that were originally well-defined. This propagation of poison corrupts the resulting vector, leading to incorrect values in the program output.

## Example

### Original IR
```llvm
define <2 x i32> @test(<2 x i32> %x, <2 x i32> %y) {
  ; This subtraction acts as a negation for lane 0, but contains poison in lane 1.
  ; The Reassociate pass might incorrectly identify this as a canonical negation of %x.
  %bad_neg = sub <2 x i32> <i32 0, i32 poison>, %x
  
  ; We must use %bad_neg to prevent Dead Code Elimination from removing it.
  call void @use(<2 x i32> %bad_neg)
  
  ; This is a clean subtraction (y - x). It is well-defined in both lanes.
  ; The optimizer should not replace the implicit negation of %x here with %bad_neg.
  %res = sub <2 x i32> %y, %x
  
  ret <2 x i32> %res
}

declare void @use(<2 x i32>)
```
### Optimized IR
```llvm
define <2 x i32> @test(<2 x i32> %x, <2 x i32> %y) {
  %bad_neg = sub <2 x i32> <i32 0, i32 poison>, %x
  call void @use(<2 x i32> %bad_neg)
  
  ; BUG: The optimizer has replaced 'sub %y, %x' with 'add %bad_neg, %y'.
  ; Since %bad_neg contains poison in lane 1, the result %res now has poison in lane 1,
  ; whereas the original code produced a well-defined value (y1 - x1).
  %res = add <2 x i32> %bad_neg, %y
  
  ret <2 x i32> %res
}

declare void @use(<2 x i32>)
```


---

# Issue 91417

## Summary Title ##
Incorrect Modular Reduction of Exponent Counts in Reassociate Pass

## Description ##
The bug is triggered when the `Reassociate` pass optimizes a sequence of associative binary operations (such as multiplication) where a specific operand is repeated multiple times (e.g., computing a power $x^n$). The optimization logic attempts to reduce the number of repetitions (the exponent) based on modular arithmetic properties, assuming that for a given bitwidth, high powers are equivalent to lower powers (e.g., $x^n \equiv x^m$).

This reduction manifests in two ways:
1.  **Explicit Reduction**: The pass uses number-theoretic properties (such as the Carmichael function) to explicitly lower the exponent count, aiming to simplify the expression tree.
2.  **Implicit Reduction via Counter Overflow**: The pass tracks the number of operand occurrences using an integer variable with the same bitwidth as the operand itself. If the repetition count exceeds the maximum value representable by that bitwidth, the counter overflows (wraps around), effectively reducing the count modulo $2^{\text{bitwidth}}$.

While these reductions are mathematically valid for the values computed in standard modular arithmetic, they are unsound when operations carry `nsw` (No Signed Wrap) or `nuw` (No Unsigned Wrap) flags. The reduction changes the sequence of operations and the intermediate values produced. As a result, the optimized code may trigger an overflow (resulting in a `poison` value) for inputs where the original, longer computation sequence remained within valid bounds and produced a defined result.

## Example

### Original IR
```llvm
define i2 @test_counter_overflow(i2 %x) {
  %1 = mul i2 %x, %x
  %2 = mul i2 %1, %x
  %3 = mul i2 %2, %x
  %4 = mul i2 %3, %x
  ret i2 %4
}
```
### Optimized IR
```llvm
define i2 @test_counter_overflow(i2 %x) {
  ret i2 %x
}
```
