# Issue 60748

## Incorrect Propagation of Poison-Generating Flags in Remainder Synthesis

**Description:**
The bug is triggered when an optimization pass identifies a division instruction and a remainder instruction sharing the same operands and attempts to consolidate them. The optimization replaces the explicit remainder instruction with an arithmetic sequence derived from the division result (typically `Remainder = Dividend - (Quotient * Divisor)`).

The flaw arises because the optimization reuses the existing division instruction to compute the remainder without stripping its poison-generating flags (such as `exact`). If the runtime operands violate the condition implied by the flag (e.g., the dividend is not an exact multiple of the divisor), the division yields a `poison` value. In the original code, the remainder instruction would produce a well-defined result regardless of the division's exactness. However, in the transformed code, the synthesized remainder calculation depends on the division's result. Consequently, the `poison` value propagates to the calculated remainder, replacing a previously well-defined value with `poison`. This can lead to undefined behavior if the remainder is subsequently stored in memory or used in other operations.

## Example

### Original IR
```llvm
define i32 @test_rem_synthesis_bug(i32 %a, i32 %b) {
  %div = sdiv exact i32 %a, %b
  call void @use(i32 %div)
  %rem = srem i32 %a, %b
  ret i32 %rem
}

declare void @use(i32)
```
### Optimized IR
```llvm
define i32 @test_rem_synthesis_bug(i32 %a, i32 %b) {
  %div = sdiv exact i32 %a, %b
  call void @use(i32 %div)
  %mul = mul i32 %div, %b
  %rem = sub i32 %a, %mul
  ret i32 %rem
}

declare void @use(i32)
```
