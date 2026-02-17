# Issue 51188

## Sinking Instructions Without Return Guarantees

**Description**: 
The bug is triggered when the optimizer sinks an instruction, such as a function call, from a source block to a destination block that is not guaranteed to execute (e.g., moving code past a conditional branch). The optimization logic fails to verify whether the instruction is guaranteed to return (i.e., it lacks the `willreturn` attribute). If the instruction has the potential to not return (for example, by entering an infinite loop), sinking it changes the program's termination behavior. In the original code, the non-returning behavior occurs unconditionally, whereas in the transformed code, the program may terminate successfully if the control flow bypasses the block into which the instruction was sunk.

## Example

### Original IR
```llvm
declare i32 @might_loop() readonly nounwind

define i32 @test_sink(i1 %cond) {
entry:
  ; The call is executed unconditionally in the source block.
  ; Since @might_loop lacks 'willreturn', it may infinite loop.
  %val = call i32 @might_loop()
  br i1 %cond, label %if.then, label %if.end

if.then:
  ; The result is only used in this conditional block.
  ret i32 %val

if.end:
  ret i32 0
}
```
### Optimized IR
```llvm
declare i32 @might_loop() readonly nounwind

define i32 @test_sink(i1 %cond) {
entry:
  br i1 %cond, label %if.then, label %if.end

if.then:
  ; The call has been sunk into the conditional block.
  ; If %cond is false, the potential infinite loop is skipped.
  ; This changes the program's termination behavior, which is incorrect.
  %val = call i32 @might_loop()
  ret i32 %val

if.end:
  ret i32 0
}
```
