# Issue 112356

## Unrecognized Poison-Generating Flags on Compare Instructions

**Description**: 
The bug is triggered by utilizing a compare instruction with a poison-generating flag (such as `samesign`) within a conditionally executed context, like a `select` instruction or a conditional branch. 

When optimizations attempt to simplify the control flow or conditional operations, they may bypass the condition and unconditionally evaluate or return the result of the compare instruction. Because the compiler's analysis fails to recognize that this specific flag can generate poison when its semantic conditions are violated (e.g., operands having different signs), it incorrectly assumes the instruction is safe to hoist or evaluate unconditionally. This leads to a miscompilation where the optimized program yields a poison value instead of a well-defined result under circumstances where the original condition would have prevented the poison from being observed.

## Example

### Original IR
```llvm
define i1 @test(i32 %a) {
entry:
  %cond = icmp sge i32 %a, 0
  %cmp = icmp samesign ult i32 %a, 10
  %res = select i1 %cond, i1 %cmp, i1 false
  ret i1 %res
}
```
### Optimized IR
```llvm
define i1 @test(i32 %a) {
entry:
  %cmp = icmp samesign ult i32 %a, 10
  ret i1 %cmp
}
```


---

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

# Issue 59301

## Incorrect `nsw` (No Signed Wrap) Inference for 1-bit Integer Multiplication

**Description**: 
The bug is triggered when the compiler attempts to deduce and attach the `nsw` (no signed wrap) flag to a 1-bit integer multiplication (`mul i1`). 

The optimization logic incorrectly assumes that multiplying a value by `1` will never result in a signed overflow, which is a valid assumption for wider integer types. However, for 1-bit integers, the representable signed value range is `[-1, 0]`, and the bit pattern for `1` actually represents `-1`. When multiplying `-1` by `-1` (i.e., `1 * 1` in 1-bit arithmetic), the true mathematical result is `1`. Because `1` falls outside the representable 1-bit signed range of `[-1, 0]`, the operation inherently experiences a signed overflow. 

By erroneously assuming no overflow can occur and adding the `nsw` flag, the compiler introduces poison values when the operands evaluate to `1`. To trigger this miscompilation, one needs to construct an LLVM IR containing a 1-bit multiplication where the operands can be `1`, and then run an optimization pass (such as correlated value propagation) that infers overflow flags based on constant ranges.

## Example

### Original IR
```llvm
define i1 @test(i1 %x) {
  %mul = mul i1 %x, 1
  ret i1 %mul
}

```
### Optimized IR
```llvm
define i1 @test(i1 %x) {
  %mul = mul nsw i1 %x, 1
  ret i1 %mul
}

```


---

# Issue 59887

## Incorrect Constant Range Calculation for 1-Bit Absolute Value

The bug is triggered when the compiler attempts to compute the constant range for an absolute value operation on a 1-bit integer. 

When the input range of the operation contains both negative and non-negative values (i.e., it crosses zero, which is the case for a full 1-bit range), the compiler calculates the upper bound of the resulting absolute value range by finding the maximum possible absolute value and adding one. However, for a 1-bit integer, adding one to the maximum absolute value causes an overflow, wrapping the upper bound back to zero. 

This wrap-around causes the compiler's range analysis to incorrectly construct an empty constant range instead of a full range. Consequently, optimization passes that rely on these ranges (such as Correlated Value Propagation) misinterpret the empty range and incorrectly fold the operation or subsequent dependent instructions into a constant (e.g., `false` or `0`), leading to a miscompilation.

## Example

### Original IR
```llvm
declare i1 @llvm.abs.i1(i1, i1)

define i1 @test(i1 %x) {
  %abs = call i1 @llvm.abs.i1(i1 %x, i1 false)
  ret i1 %abs
}
```
### Optimized IR
```llvm
define i1 @test(i1 %x) {
  ret i1 false
}
```


---

# Issue 61984

## Incorrect Elimination of Bitcast Between Same-Width Floating-Point Types

**Description:**
The bug is triggered by a sequence of cast instructions involving floating-point types that share the same bit width but have different internal representations (such as `bfloat` and `half`). Specifically, the pattern consists of a `bitcast` instruction converting a value from one floating-point type to another of the same width, immediately followed by a floating-point cast instruction (such as a floating-point extension or truncation).

The compiler's optimization logic incorrectly assumes that a `bitcast` between any two floating-point types of the same size is a semantic no-op. Based on this flawed assumption, it attempts to optimize the cast pair by eliminating the `bitcast` entirely and applying the second floating-point cast directly to the original source type. 

However, because the source and destination types of the `bitcast` have different binary representations (e.g., different allocations for exponent and mantissa bits), the `bitcast` fundamentally alters the interpreted numerical value. Bypassing the `bitcast` and directly casting the original type leads to an incorrect conversion. This causes subsequent operations, such as constant folding or comparisons, to operate on the wrong numerical value, ultimately resulting in a miscompilation.

## Example

### Original IR
```llvm
define float @test_bitcast_bfloat_to_half_fpext(bfloat %x) {
entry:
  %bc = bitcast bfloat %x to half
  %ext = fpext half %bc to float
  ret float %ext
}

```
### Optimized IR
```llvm
define float @test_bitcast_bfloat_to_half_fpext(bfloat %x) {
entry:
  %ext = fpext bfloat %x to float
  ret float %ext
}

```
