# Issue 80113

## Failure to Clear Poison-Generating Flags on Fully Demanded Users

**Description:**
The bug occurs during bit-tracking dead code elimination when an instruction is simplified based on its demanded bits, but the compiler fails to properly update the assumptions of its users. The triggering strategy involves the following pattern:

1. **Partially Demanded Definition**: Generate an integer instruction (the definition) where only a subset of its bits are actually demanded by its users.
2. **Poison-Generating User**: Use this instruction as an operand in a subsequent instruction (the user) that is decorated with poison-generating flags (e.g., `nsw` for no signed wrap, `nuw` for no unsigned wrap, or `exact`).
3. **Fully Demanded User**: Ensure that all bits of this user instruction are demanded by its own subsequent users in the def-use chain.
4. **Simplification and Flag Retention**: During optimization, the compiler simplifies the definition instruction by altering its undemanded bits (e.g., zeroing them out). Because the input to the user instruction has changed, the compiler is supposed to clear the poison-generating flags on the user to prevent it from erroneously producing a poison value.
5. **Incorrect Pruning Logic**: The compiler incorrectly assumes that if a user instruction has *all* of its bits demanded, neither it nor its def-use chain needs to be processed. Consequently, it skips the user instruction entirely and fails to drop its poison-generating flags.
6. **Miscompilation**: At runtime, the altered input from the simplified definition causes the user instruction to violate its retained poison-generating flags (e.g., causing an overflow). This produces a poison value that propagates through the program, leading to incorrect execution results.

## Example

### Original IR
```llvm
define i32 @test(i32 %x, i32 %z) {
  %y = shl i32 %z, 8
  %A = or i32 %x, %y
  %B = shl nsw i32 %A, 24
  ret i32 %B
}
```
### Optimized IR
```llvm
define i32 @test(i32 %x, i32 %z) {
  %A = or i32 %x, 0
  %B = shl nsw i32 %A, 24
  ret i32 %B
}
```
