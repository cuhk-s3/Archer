# Issue 52950

## Vectorization of Memory Accesses Across Instructions Not Guaranteed to Transfer Execution

**Description**:
The bug is triggered by exploiting the vectorizer's failure to properly account for instructions that may not return or transfer execution to their successors. The strategy involves the following steps:

1. **Create Contiguous Memory Accesses**: Define a sequence of consecutive memory operations (such as loads or stores) that are typically candidates for being combined into a single, wider vectorized access.
2. **Insert a Non-Returning Instruction**: Interleave these memory accesses with an instruction that does not interfere with the memory state (e.g., an `inaccessiblememonly` function call) but is not guaranteed to transfer execution to its successor. This could be a function call that might exit the program, trap, or loop infinitely (i.e., lacking the `willreturn` attribute).
3. **Introduce Conditional Undefined Behavior**: Ensure that the memory accesses located *after* this non-returning instruction would trigger undefined behavior (such as an out-of-bounds memory access) if they were executed. In the original program, this undefined behavior is avoided if the non-returning instruction halts or diverges execution before reaching the invalid access.
4. **Trigger the Miscompilation**: The optimization pass incorrectly assumes it is safe to group all the contiguous memory accesses together. It hoists or sinks the accesses across the non-returning instruction to form a single vectorized memory operation. 
5. **Resulting Issue**: By moving the later memory accesses before the non-returning instruction, the vectorized program executes the out-of-bounds access unconditionally. This transforms a valid program (where the undefined behavior was dynamically unreachable) into one that triggers unconditional undefined behavior.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

declare void @may_not_return() inaccessiblememonly

define void @test(ptr %p) {
entry:
  store i32 0, ptr %p, align 4
  call void @may_not_return()
  %p2 = getelementptr inbounds i32, ptr %p, i64 1
  store i32 0, ptr %p2, align 4
  ret void
}

```
### Optimized IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

declare void @may_not_return() inaccessiblememonly

define void @test(ptr %p) {
entry:
  store <2 x i32> zeroinitializer, ptr %p, align 4
  call void @may_not_return()
  ret void
}

```
