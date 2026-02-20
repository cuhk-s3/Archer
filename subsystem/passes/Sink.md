# Issue 51188

## Sinking Non-Returning Instructions into Conditional Blocks

**Description**: 
The bug is triggered by placing an instruction that is not guaranteed to return (such as a function call lacking the `willreturn` attribute) before a conditional branch. The instruction must otherwise appear safe to move, meaning it lacks side effects that typically prevent code motion (e.g., it does not write to memory or throw exceptions). The result of this instruction is then used exclusively within one of the conditional branch's target blocks.

Because the optimization pass fails to verify whether the instruction is guaranteed to return, it incorrectly sinks the instruction out of its original unconditional execution path and into the conditionally executed block where its result is used. 

This transformation is invalid because it alters the program's control flow and termination behavior. If the original instruction does not return (e.g., it enters an infinite loop or traps), sinking it past the branch allows the branch and potentially other instructions to execute. This can lead to miscompilations, such as the program terminating when it should have hung, or exposing undefined behavior (like branching on an `undef` or uninitialized value) that would have been safely preempted by the non-returning instruction in the original code.

## Example

### Original IR
```llvm
declare i32 @foo() readnone

define i32 @test(i1 %cond) {
entry:
  %val = call i32 @foo()
  br i1 %cond, label %if.then, label %if.end

if.then:
  ret i32 %val

if.end:
  ret i32 0
}

```
### Optimized IR
```llvm
declare i32 @foo() readnone

define i32 @test(i1 %cond) {
entry:
  br i1 %cond, label %if.then, label %if.end

if.then:
  %val = call i32 @foo()
  ret i32 %val

if.end:
  ret i32 0
}

```
