# Issue 30999

## Incorrect Address Selection During PHI Translation Lacking Dominance Constraints

**Description**

The bug is triggered during compiler optimization passes that perform PHI translation of memory addresses across basic blocks, such as Global Value Numbering (GVN) or Partial Redundancy Elimination (PRE).

When translating an address expression to a predecessor block, the optimization searches for an existing instruction that computes the equivalent translated address. If this search does not strictly enforce dominance constraints, the compiler may select an instruction that computes the correct address but resides in a basic block that does not dominate the target block.

Because this selected instruction is located in a non-dominating block, it is bound to a specific control-flow context. It may carry preconditions or assumptions—such as specific values of loop induction variables or branch conditions—that are valid in its own block but do not hold true in the target block.

When subsequent analyses (such as alias analysis) evaluate this translated address, they incorrectly apply the context-specific assumptions of the non-dominating instruction to the target block. This leads to flawed analysis results, such as incorrectly concluding that two pointers do not alias. Consequently, the optimization pass performs invalid transformations, like incorrectly eliminating memory loads or replacing them with values from unrelated loop iterations or execution paths, resulting in a miscompilation.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-i64:64-f80:128-n8:16:32:64-S128"

declare void @llvm.assume(i1)

define i8 @test(i8* %p, i8* %q, i1 %c) {
entry:
  %q1 = getelementptr inbounds i8, i8* %q, i64 1
  br i1 %c, label %if.then, label %if.else

if.then:
  store i8 1, i8* %q1
  br label %merge

if.else:
  %gep.else = getelementptr inbounds i8, i8* %p, i64 1
  %cmp = icmp ne i8* %gep.else, %q1
  call void @llvm.assume(i1 %cmp)
  store i8 2, i8* %gep.else
  br label %merge

merge:
  %phi = phi i8* [ %p, %if.then ], [ %p, %if.else ]
  %gep.merge = getelementptr inbounds i8, i8* %phi, i64 1
  %load = load i8, i8* %gep.merge
  ret i8 %load
}
```
### Optimized IR
```llvm
target datalayout = "e-m:e-i64:64-f80:128-n8:16:32:64-S128"

declare void @llvm.assume(i1)

define i8 @test(i8* %p, i8* %q, i1 %c) {
entry:
  %q1 = getelementptr inbounds i8, i8* %q, i64 1
  br i1 %c, label %if.then, label %if.else

if.then:
  store i8 1, i8* %q1
  br label %merge

if.else:
  %gep.else = getelementptr inbounds i8, i8* %p, i64 1
  %cmp = icmp ne i8* %gep.else, %q1
  call void @llvm.assume(i1 %cmp)
  store i8 2, i8* %gep.else
  br label %merge

merge:
  %load.phi = phi i8 [ undef, %if.then ], [ 2, %if.else ]
  %phi = phi i8* [ %p, %if.then ], [ %p, %if.else ]
  %gep.merge = getelementptr inbounds i8, i8* %phi, i64 1
  ret i8 %load.phi
}
```
