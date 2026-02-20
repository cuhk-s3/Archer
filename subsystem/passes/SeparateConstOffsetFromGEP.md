# Issue 154116

## Improper Preservation of Poison-Generating Flags when Distributing Truncation over Arithmetic Operations

**Description**: 
The bug occurs when a truncation instruction (`trunc`) with poison-generating flags (such as `nuw` or `nsw`) is applied to the result of an arithmetic operation (e.g., `add`, `sub`, or `or`) that involves a constant offset. During optimization, the compiler attempts to separate the constant offset by distributing the truncation over the operands of the arithmetic operation. However, the optimization incorrectly preserves the poison-generating flags on the newly cloned truncation instructions. 

Because the conditions required by the `nuw` or `nsw` flags might be satisfied by the final result of the arithmetic operation but not by its individual operands (for instance, an operand might have non-zero truncated bits that are later canceled out by the constant offset), the distributed truncation instructions can incorrectly evaluate to a poison value. This leads to a miscompilation where valid input IR is transformed into IR that produces poison. 

To trigger this bug, one needs to construct a sequence where an arithmetic operation with a constant offset is followed by a `trunc` instruction with `nuw` or `nsw` flags, and ensure that the individual operands would violate the `nuw`/`nsw` constraints if truncated directly before the arithmetic operation takes place.

## Example

### Original IR
```llvm
define i8 @test_add_nuw(i16 %x) {
  %add = add i16 %x, 257
  %trunc = trunc nuw i16 %add to i8
  ret i8 %trunc
}
```
### Optimized IR
```llvm
define i8 @test_add_nuw(i16 %x) {
  %trunc = trunc nuw i16 %x to i8
  %add = add i8 %trunc, 1
  ret i8 %add
}
```
