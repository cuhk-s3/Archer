# Issue 113997

## Miscompilation due to Improper Handling of Call Attributes during CSE/GVN

**Description:**
The bug occurs when Common Subexpression Elimination (CSE) or Global Value Numbering (GVN) optimizations replace a function call with a dominating equivalent call without properly reconciling their return attributes.

The bug triggering strategy involves the following sequence:
1. The program contains two identical function calls (or intrinsics) with the same arguments, making the dominated call a candidate for elimination.
2. The dominating call possesses more restrictive return attributes (such as `range` or `nonnull`) compared to the dominated call.
3. For specific inputs, the dominating call evaluates to `poison` because its restrictive attributes are violated. However, in the original program, this `poison` value is safely ignored or masked by the control flow.
4. The dominated call, which lacks these restrictive attributes (or has more relaxed ones), evaluates to a well-defined value for the same inputs.
5. The optimization pass replaces the dominated call with the dominating call but fails to intersect or strip the incompatible attributes.
6. As a result, the uses of the dominated call incorrectly receive the `poison` value from the dominating call, leading to a miscompilation where the optimized program is more poisonous than the original source.

## Example

### Original IR
```llvm
declare ptr @foo(ptr) memory(none)

define ptr @test(ptr %p, i1 %c) {
entry:
  %call1 = call nonnull ptr @foo(ptr %p)
  br i1 %c, label %then, label %else

then:
  ret ptr %call1

else:
  %call2 = call ptr @foo(ptr %p)
  ret ptr %call2
}

```
### Optimized IR
```llvm
declare ptr @foo(ptr) memory(none)

define ptr @test(ptr %p, i1 %c) {
entry:
  %call1 = call nonnull ptr @foo(ptr %p)
  br i1 %c, label %then, label %else

then:
  ret ptr %call1

else:
  ret ptr %call1
}

```

---

# Issue 64598

## Stale Analysis Cache due to Unnotified Instruction Deletion during PHI Deduplication

**Description:**
During optimization, a pass may identify and eliminate duplicate PHI nodes within a basic block to simplify the control flow graph. The bug occurs when the utility responsible for this deduplication directly removes and frees the memory of the duplicate PHI nodes without notifying the calling optimization pass.

Because the optimization pass maintains internal analysis caches (such as memory dependence or value numbering information) that are keyed by instruction memory addresses, directly deleting the instructions leaves stale pointers in these caches. If a new instruction is subsequently allocated at the exact same memory address as one of the deleted PHI nodes, the optimization pass will incorrectly look up and reuse the stale analysis data for the new instruction. This causes the compiler to make incorrect assumptions about the program's data flow or memory dependencies, ultimately leading to invalid transformations and miscompilation.

## Example

### Original IR
```llvm
define i32 @test(i1 %cond, i32* %p) {
entry:
  br i1 %cond, label %bb1, label %bb2

bb1:
  br label %bb3

bb2:
  br label %bb3

bb3:
  %phi1 = phi i32 [ 1, %bb1 ], [ 2, %bb2 ]
  %phi2 = phi i32 [ 1, %bb1 ], [ 2, %bb2 ]
  %load = load i32, i32* %p
  %add = add i32 %phi1, %load
  ret i32 %add
}
```
### Optimized IR
```llvm
define i32 @test(i1 %cond, i32* %p) {
entry:
  br i1 %cond, label %bb1, label %bb2

bb1:
  br label %bb3

bb2:
  br label %bb3

bb3:
  %phi1 = phi i32 [ 1, %bb1 ], [ 2, %bb2 ]
  %add = add i32 %phi1, %phi1
  ret i32 %add
}
```

---

# Issue 82884

## Incorrect Preservation of Poison-Generating Flags when Replacing Overflow Intrinsic Results

**Description**:
The bug is triggered by a transformation that replaces the extraction of a mathematical result from an overflow-checking intrinsic with an equivalent standard binary operator.

In LLVM IR, overflow-checking intrinsics (such as `llvm.sadd.with.overflow` or `llvm.smul.with.overflow`) return a struct containing both the computed arithmetic result (which wraps around on overflow) and a boolean flag indicating whether an overflow occurred. Extracting the arithmetic result (via an `extractvalue` instruction at index 0) yields a well-defined value that never evaluates to poison, even if the operation overflows.

The miscompilation happens when an optimization pass (like GVN or InstCombine) identifies that this extracted result is equivalent to the result of a standard binary operator elsewhere in the code, and attempts to replace the `extractvalue` instruction with that binary operator. If the replacement binary operator is decorated with poison-generating flags (such as `nsw` for no signed wrap or `nuw` for no unsigned wrap), those flags must be stripped.

However, because the original `extractvalue` instruction does not support or carry these flags, the compiler's default flag-intersection logic fails to clear them from the replacement instruction. As a result, the replacement instruction retains its `nsw`/`nuw` flags. If the operation actually overflows at runtime, the incorrectly preserved flags cause the instruction to produce a poison value instead of the expected wrapped integer, leading to downstream miscompilations.

## Example

### Original IR
```llvm
declare { i32, i1 } @llvm.sadd.with.overflow.i32(i32, i32)

define i1 @test(i32 %a, i32 %b, ptr %p, ptr %q) {
entry:
  %add = add nsw i32 %a, %b
  store i32 %add, ptr %p
  %ov = call { i32, i1 } @llvm.sadd.with.overflow.i32(i32 %a, i32 %b)
  %ext = extractvalue { i32, i1 } %ov, 0
  store i32 %ext, ptr %q
  %ext1 = extractvalue { i32, i1 } %ov, 1
  ret i1 %ext1
}
```
### Optimized IR
```llvm
declare { i32, i1 } @llvm.sadd.with.overflow.i32(i32, i32)

define i1 @test(i32 %a, i32 %b, ptr %p, ptr %q) {
entry:
  %add = add nsw i32 %a, %b
  store i32 %add, ptr %p
  %ov = call { i32, i1 } @llvm.sadd.with.overflow.i32(i32 %a, i32 %b)
  store i32 %add, ptr %q
  %ext1 = extractvalue { i32, i1 } %ov, 1
  ret i1 %ext1
}
```
