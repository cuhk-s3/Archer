# Issue 154116

## Incorrect Preservation of Poison-Generating Flags during Truncation Distribution

The bug is triggered when the optimizer attempts to separate constant offsets by distributing a truncation instruction over binary operations, such as addition. When splitting an expression like `trunc nuw (Variable + Constant)` to operate on the components individually, the optimizer creates a new truncation instruction for the variable operand and incorrectly copies the `nuw` (No Unsigned Wrap) flag from the original instruction.

This transformation is unsound because the `nuw` flag on the original expression only guarantees that the final sum fits within the destination type, not that the individual operands do. If the variable operand has bits set that are discarded during truncation (for example, if it is a negative value), the new `trunc nuw` instruction produces a poison value, whereas the original expression was well-defined. This results in the introduction of undefined behavior.

## Example

### Original IR
```llvm
define i8 @test(i32 %x) {
  %add = add nuw i32 %x, 1
  %trunc = trunc i32 %add to i8
  ret i8 %trunc
}
```
### Optimized IR
```llvm
define i8 @test(i32 %x) {
  %trunc = trunc i32 %x to i8
  %add = add nuw i8 %trunc, 1
  ret i8 %add
}
```
