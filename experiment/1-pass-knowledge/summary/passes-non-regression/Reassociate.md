# Issue 57683

## Incorrect Reuse of Partially Poisoned Vector Operations

**Description**:
The bug is triggered by exploiting the compiler's instruction reuse and matching logic during the reassociation of vector expressions. The strategy involves the following steps:

1. **Create a Partially Poisoned Operation**: Generate a vector arithmetic operation (such as a negation via subtraction) using a constant vector that contains a mix of valid elements (e.g., zeros) and `poison` or `undef` elements.
2. **Safe Consumption**: Use the result of this partially poisoned operation in a subsequent instruction that safely discards or ignores the `poison`/`undef` lanes, such as a `shufflevector` or `extractelement` mask. This ensures the original program semantics remain well-defined and valid.
3. **Introduce a Fully Defined Operation**: Introduce another instruction in the same function that requires the fully defined version of the same computation (e.g., a full negation of the same input vector, but without any `poison` or `undef` lanes).
4. **Trigger the Miscompilation**: The compiler's optimization pass scans for existing, equivalent expressions to reuse. It incorrectly matches the partially poisoned operation as a valid substitute for the fully defined operation, failing to account for the fact that the constant operand contains `poison` or `undef` lanes.
5. **Poison Propagation**: The pass replaces the fully defined computation with the partially poisoned one. Because the new context does not discard the invalid lanes, `poison` or `undef` values are propagated into vector lanes that were previously well-defined, ultimately leading to an incorrect result and a miscompilation.

## Example

### Original IR
```llvm
define <2 x i32> @test(<2 x i32> %x) {
entry:
  %partially_poisoned = sub <2 x i32> <i32 0, i32 poison>, %x
  %safe_use = extractelement <2 x i32> %partially_poisoned, i32 0
  %fully_defined = sub <2 x i32> zeroinitializer, %x
  %res = insertelement <2 x i32> %fully_defined, i32 %safe_use, i32 0
  ret <2 x i32> %res
}
```
### Optimized IR
```llvm
define <2 x i32> @test(<2 x i32> %x) {
entry:
  %partially_poisoned = sub <2 x i32> <i32 0, i32 poison>, %x
  %safe_use = extractelement <2 x i32> %partially_poisoned, i32 0
  %res = insertelement <2 x i32> %partially_poisoned, i32 %safe_use, i32 0
  ret <2 x i32> %res
}
```

---

# Issue 91417

## Failure to Drop Poison-Generating Flags During Operand Weight Reduction in Associative Expressions

**Description:**
The bug is triggered by constructing an expression tree of associative operations (such as integer multiplication) that repeatedly applies the operation to the same operand.

To trigger the issue, the following conditions must be met:
1. **Repeated Operands**: The expression must use the same operand multiple times, accumulating a high "weight" (occurrence count) for that operand.
2. **Weight Reduction**: The total weight of the operand must be large enough to trigger a mathematical simplification based on finite-precision arithmetic properties. For example, in integer multiplication, the compiler may use Carmichael's theorem to reduce the number of multiplications for a specific bit-width (e.g., reducing `x^5` to `x^3` in 3-bit arithmetic).
3. **Poison-Generating Flags**: One or more instructions in the original expression tree must be decorated with poison-generating flags (such as `nsw` for no signed wrap or `nuw` for no unsigned wrap).

When the compiler optimizes the expression, it reduces the operand's weight and rewrites the expression tree to perform fewer operations. During this process, it reuses some of the original instructions but fails to clear their poison-generating flags because those specific instructions fall outside the tracked range of modified expressions.

Because the mathematical reduction alters the intermediate values computed by the chain of operations, the original flags may no longer be valid for the new intermediate results. Preserving these flags on the modified expression tree causes the operations to incorrectly trigger overflow conditions and produce `poison` values, ultimately leading to a miscompilation.

## Example

### Original IR
```llvm
define i3 @test(i3 %a, i3 %b) {
entry:
  %x = add i3 %a, 1
  %y = add i3 %x, %b
  %m1 = mul nsw i3 %x, %y
  %m2 = mul nsw i3 %m1, %x
  %m3 = mul nsw i3 %m2, %x
  %m4 = mul nsw i3 %m3, %x
  %m5 = mul nsw i3 %m4, %x
  ret i3 %m5
}
```
### Optimized IR
```llvm
define i3 @test(i3 %a, i3 %b) {
entry:
  %x = add i3 %a, 1
  %y = add i3 %x, %b
  %m1 = mul i3 %x, %x
  %m2 = mul nsw i3 %m1, %x
  %m5 = mul i3 %m2, %y
  ret i3 %m5
}
```
