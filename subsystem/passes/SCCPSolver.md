# Issue 93096

## Incorrect Constant Range Propagation for Undef Values

**Description**: 
The bug is triggered when a constant propagation pass computes the constant range of an operation that has an operand potentially evaluating to `undef`. The strategy to trigger this miscompilation involves the following steps:

1. **Introduce an `undef` Value**: Create a value that can be `undef`, typically through a PHI node where at least one incoming value is explicitly `undef` (e.g., from an entry block or an unexecuted path).
2. **Perform Range-Tracked Operations**: Use this potentially `undef` value as an operand in an instruction that supports constant range tracking. This includes binary operators (such as bitwise `and`, `or`, or arithmetic operations) and cast instructions (such as `zext` or `trunc`).
3. **Trigger Incorrect Range Calculation**: The constant propagation analysis evaluates the resulting constant range of the operation but incorrectly ignores the `undef` possibility. Instead of treating the `undef` as a full range or acknowledging that the result could be undefined, it computes an overly optimistic (narrower) range based solely on the known, defined values.
4. **Exploit the Optimistic Range**: Consume the result of this operation in a subsequent instruction where the compiler applies range-based optimizations. For example, pass the value to a `trunc` instruction. Because the compiler incorrectly assumes certain bits are guaranteed to be zero (due to the narrow range), it erroneously attaches poison-generating flags like `nuw` (no unsigned wrap) or `nsw` (no signed wrap), or it might incorrectly fold an `icmp` condition. 

This sequence leads to a miscompilation because the actual runtime value can fall outside the incorrectly computed constant range due to the presence of the `undef` operand, violating the assumptions made by the applied optimizations.

## Example

### Original IR
```llvm
define i8 @test(i1 %c, ptr %p) {
entry:
  br i1 %c, label %if.then, label %if.end

if.then:
  br label %if.end

if.end:
  %phi = phi i32 [ undef, %entry ], [ 0, %if.then ]
  store i32 %phi, ptr %p
  %add = add i32 %phi, 64
  %trunc = trunc i32 %add to i8
  ret i8 %trunc
}
```
### Optimized IR
```llvm
define i8 @test(i1 %c, ptr %p) {
entry:
  br i1 %c, label %if.then, label %if.end

if.then:
  br label %if.end

if.end:
  %phi = phi i32 [ undef, %entry ], [ 0, %if.then ]
  store i32 %phi, ptr %p
  %add = add i32 %phi, 64
  %trunc = trunc nuw nsw i32 %add to i8
  ret i8 %trunc
}
```
