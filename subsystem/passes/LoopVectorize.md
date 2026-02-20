# Issue 122602

## Incorrect Uniformity Analysis for Induction Variables with Outside Users

**Description:**
The bug is triggered by a loop containing an induction variable where the induction update instruction (e.g., the increment operation) is used outside the loop. 

The strategy to trigger this issue involves the following conditions:
1. **Uniform Inside Users**: All users of the induction update instruction *inside* the loop must be uniform (for example, the induction PHI node itself or other uniform operations).
2. **Outside Users**: The induction update instruction (or a chain of instructions derived from it) must have at least one user *outside* the loop, typically using it as an exit value.
3. **Flawed Uniformity Analysis**: The loop vectorizer's uniformity analysis incorrectly ignores users outside the loop when determining if an instruction is uniform. Because all inside-loop users are uniform, the vectorizer mistakenly classifies the induction update as uniform.
4. **Miscompilation**: During vectorization, uniform instructions are often optimized to only compute or preserve the scalar value for the first vector lane. However, the user outside the loop requires the value from the final loop iteration (which corresponds to the last active lane of the vector). Because the instruction was treated as uniform, the correct final value is not extracted, and the outside user receives an incorrect value (e.g., from the first lane), leading to a miscompilation. 

By ensuring the induction update is used outside the loop while keeping its internal uses uniform, the vectorizer is tricked into applying an invalid scalarization/uniformity optimization, failing to provide the correct exit value.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define i32 @test(i32* %a, i32 %n) {
entry:
  br label %for.body

for.body:
  %iv = phi i32 [ 0, %entry ], [ %iv.next, %for.body ]
  %iv.next = add i32 %iv, 1
  %arrayidx = getelementptr inbounds i32, i32* %a, i32 %iv
  store i32 0, i32* %arrayidx, align 4
  %cmp = icmp slt i32 %iv.next, %n
  br i1 %cmp, label %for.body, label %for.end

for.end:
  %iv.next.lcssa = phi i32 [ %iv.next, %for.body ]
  ret i32 %iv.next.lcssa
}
```
### Optimized IR
```llvm
target datalayout = "e-m:e-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define i32 @test(i32* %a, i32 %n) {
entry:
  %min.iters.check = icmp ult i32 %n, 4
  br i1 %min.iters.check, label %scalar.ph, label %vector.ph

vector.ph:
  %n.vec = and i32 %n, -4
  br label %vector.body

vector.body:
  %index = phi i32 [ 0, %vector.ph ], [ %index.next, %vector.body ]
  %vec.ind = phi <4 x i32> [ <i32 0, i32 1, i32 2, i32 3>, %vector.ph ], [ %vec.ind.next, %vector.body ]
  %step.add = add <4 x i32> %vec.ind, <i32 1, i32 1, i32 1, i32 1>
  %0 = add i32 %index, 0
  %1 = getelementptr inbounds i32, i32* %a, i32 %0
  %2 = getelementptr inbounds i32, i32* %1, i32 0
  %3 = bitcast i32* %2 to <4 x i32>*
  store <4 x i32> zeroinitializer, <4 x i32>* %3, align 4
  %index.next = add nuw i32 %index, 4
  %vec.ind.next = add <4 x i32> %vec.ind, <i32 4, i32 4, i32 4, i32 4>
  %4 = icmp eq i32 %index.next, %n.vec
  br i1 %4, label %middle.block, label %vector.body

middle.block:
  %cmp.n = icmp eq i32 %n.vec, %n
  ; Miscompilation: extracting from lane 0 instead of lane 3 because the instruction was incorrectly marked as uniform
  %vector.extract = extractelement <4 x i32> %step.add, i32 0
  br i1 %cmp.n, label %for.end, label %scalar.ph

scalar.ph:
  %bc.resume.val = phi i32 [ %n.vec, %middle.block ], [ 0, %entry ]
  br label %for.body

for.body:
  %iv = phi i32 [ %bc.resume.val, %scalar.ph ], [ %iv.next, %for.body ]
  %iv.next = add i32 %iv, 1
  %arrayidx = getelementptr inbounds i32, i32* %a, i32 %iv
  store i32 0, i32* %arrayidx, align 4
  %cmp = icmp slt i32 %iv.next, %n
  br i1 %cmp, label %for.body, label %for.end

for.end:
  %iv.next.lcssa = phi i32 [ %iv.next, %for.body ], [ %vector.extract, %middle.block ]
  ret i32 %iv.next.lcssa
}
```


---

# Issue 149347

## Divergence in Loop-Invariant Analysis for Uniform Stores in Loop Vectorization

**Description:**
The bug is triggered by a mismatch in how different phases of the loop vectorizer determine if a value is loop-invariant, specifically when handling store instructions. 

1. **Target Pattern**: A loop contains a store instruction that writes to a loop-invariant memory address. The value being stored is also loop-invariant, but this invariance is not structurally obvious. For example, the value might be a PHI node where the only active incoming edge provides a constant, while other edges come from dead or unreachable control flow blocks.
2. **Advanced Analysis vs. Structural Analysis**: The vectorizer's cost model and predication logic use an advanced analysis framework (like Scalar Evolution) to evaluate the stored value. This analysis successfully proves that the value is loop-invariant despite the complex control flow.
3. **Bypassing Predication**: Because both the pointer and the stored value are deemed invariant by the advanced analysis, the vectorizer decides that the store does not need to be predicated. It optimizes it into a uniform store that can execute unconditionally.
4. **Code Generation Divergence**: During the actual vector code generation (e.g., via VPlan), the system relies on a simpler, structural invariance check (such as verifying if the value's definition physically resides outside the loop). Under this stricter check, the value is not recognized as invariant.
5. **Incorrect Lane Extraction**: Since the code generator treats the value as a varying vector rather than a uniform scalar, it attempts to perform the uniform store by extracting the value from the last lane of the vector. 
6. **Miscompilation**: Because the store was originally part of conditional control flow or a PHI node with dead paths, the last lane might correspond to a masked-out or inactive execution path. Extracting from this lane yields an incorrect value (e.g., a default or garbage value from the dead branch), which is then stored to memory, resulting in a miscompilation. 

This strategy highlights the danger of using a powerful analysis in the optimization decision phase while relying on a weaker analysis during code generation, leading to inconsistent handling of uniform stores and incorrect lane extractions.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @test(ptr %ptr, i32 %n) {
entry:
  %cmp = icmp sgt i32 %n, 0
  br i1 %cmp, label %loop, label %exit

loop:
  %iv = phi i32 [ 0, %entry ], [ %iv.next, %latch ]
  %val = phi i32 [ 42, %entry ], [ %val.next, %latch ]
  %cond = icmp uge i32 %iv, %n
  br i1 %cond, label %dead, label %latch

dead:
  br label %latch

latch:
  %val.next = phi i32 [ %val, %loop ], [ 24, %dead ]
  store i32 %val.next, ptr %ptr, align 4
  %iv.next = add i32 %iv, 1
  %exitcond = icmp eq i32 %iv.next, %n
  br i1 %exitcond, label %exit, label %loop

exit:
  ret void
}
```
### Optimized IR
```llvm
target datalayout = "e-m:e-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @test(ptr %ptr, i32 %n) {
entry:
  %cmp = icmp sgt i32 %n, 0
  br i1 %cmp, label %vector.ph, label %exit

vector.ph:                                        ; preds = %entry
  %n.rnd.up = add i32 %n, 3
  %n.vec = and i32 %n.rnd.up, -4
  %broadcast.splatinsert = insertelement <4 x i32> poison, i32 %n, i64 0
  %broadcast.splat = shufflevector <4 x i32> %broadcast.splatinsert, <4 x i32> poison, <4 x i32> zeroinitializer
  br label %vector.body

vector.body:                                      ; preds = %vector.body, %vector.ph
  %index = phi i32 [ 0, %vector.ph ], [ %index.next, %vector.body ]
  %vec.ind = phi <4 x i32> [ <i32 0, i32 1, i32 2, i32 3>, %vector.ph ], [ %vec.ind.next, %vector.body ]
  %vec.val = phi <4 x i32> [ <i32 42, i32 42, i32 42, i32 42>, %vector.ph ], [ %vec.val.next, %vector.body ]
  %0 = icmp uge <4 x i32> %vec.ind, %broadcast.splat
  %1 = select <4 x i1> %0, <4 x i32> <i32 24, i32 24, i32 24, i32 24>, <4 x i32> %vec.val
  %2 = extractelement <4 x i32> %1, i32 3
  store i32 %2, ptr %ptr, align 4
  %index.next = add i32 %index, 4
  %vec.ind.next = add <4 x i32> %vec.ind, <i32 4, i32 4, i32 4, i32 4>
  %vec.val.next = select <4 x i1> %0, <4 x i32> <i32 24, i32 24, i32 24, i32 24>, <4 x i32> %vec.val
  %3 = icmp eq i32 %index.next, %n.vec
  br i1 %3, label %middle.block, label %vector.body

middle.block:                                     ; preds = %vector.body
  br label %exit

exit:                                             ; preds = %middle.block, %entry
  ret void
}
```


---

# Issue 154967

## Miscompilation in Loop Vectorization of Uncountable Early Exits with Scalar Vectorization and Interleaving

**Description**: 
The bug occurs during the loop vectorization process when handling loops with uncountable early exits (e.g., data-dependent breaks or returns). To trigger the issue, the following conditions must be combined:
1. A loop contains an uncountable early exit.
2. The loop produces a live-out value that is defined inside the loop and used outside when the early exit is taken (such as returning the loop induction variable).
3. The loop is optimized using a scalar vectorization factor (i.e., a vector width of 1) but with an interleave or unroll factor greater than 1.

When interleaving a loop with an early exit, the compiler evaluates multiple iterations concurrently. If the early exit condition is met, the compiler must determine exactly which interleaved part (or iteration) triggered the exit condition first in order to extract the correct live-out value. 

However, the internal compiler operations responsible for identifying the first active lane and extracting the corresponding value lacked support for scalar vectorization factors. Because of this missing support, the compiler's transformation logic intentionally bypassed generating the necessary extraction steps when the vector width was 1. As a result, the compiled code fails to properly identify the triggering iteration among the interleaved parts, leading to a miscompilation where an incorrect live-out value is extracted and used when the early exit is taken.

## Example

### Original IR
```llvm
define i64 @test_early_exit_live_out(ptr %p) {
entry:
  br label %loop

loop:
  %iv = phi i64 [ 0, %entry ], [ %iv.next, %loop.inc ]
  %gep = getelementptr inbounds i32, ptr %p, i64 %iv
  %val = load i32, ptr %gep, align 4
  %cmp = icmp eq i32 %val, 42
  br i1 %cmp, label %early.exit, label %loop.inc

loop.inc:
  %iv.next = add nuw nsw i64 %iv, 1
  %exitcond = icmp eq i64 %iv.next, 1024
  br i1 %exitcond, label %normal.exit, label %loop, !llvm.loop !0

early.exit:
  %retval = phi i64 [ %iv, %loop ]
  ret i64 %retval

normal.exit:
  ret i64 1024
}

!0 = distinct !{!0, !1, !2}
!1 = !{!"llvm.loop.vectorize.width", i32 1}
!2 = !{!"llvm.loop.interleave.count", i32 4}

```
### Optimized IR
```llvm
define i64 @test_early_exit_live_out(ptr %p) {
entry:
  br label %vector.ph

vector.ph:
  br label %vector.body

vector.body:
  %index = phi i64 [ 0, %vector.ph ], [ %index.next, %vector.body.inc ]
  %0 = add i64 %index, 0
  %1 = add i64 %index, 1
  %2 = add i64 %index, 2
  %3 = add i64 %index, 3
  %4 = getelementptr inbounds i32, ptr %p, i64 %0
  %5 = getelementptr inbounds i32, ptr %p, i64 %1
  %6 = getelementptr inbounds i32, ptr %p, i64 %2
  %7 = getelementptr inbounds i32, ptr %p, i64 %3
  %8 = load i32, ptr %4, align 4
  %9 = load i32, ptr %5, align 4
  %10 = load i32, ptr %6, align 4
  %11 = load i32, ptr %7, align 4
  %12 = icmp eq i32 %8, 42
  %13 = icmp eq i32 %9, 42
  %14 = icmp eq i32 %10, 42
  %15 = icmp eq i32 %11, 42
  %16 = or i1 %12, %13
  %17 = or i1 %16, %14
  %18 = or i1 %17, %15
  br i1 %18, label %vector.early.exit, label %vector.body.inc

vector.body.inc:
  %index.next = add nuw i64 %index, 4
  %19 = icmp eq i64 %index.next, 1024
  br i1 %19, label %middle.block, label %vector.body, !llvm.loop !0

vector.early.exit:
  ; BUG: Incorrectly extracts the live-out value by just using the first part's index
  ; instead of determining which interleaved part triggered the early exit.
  %20 = phi i64 [ %0, %vector.body ]
  br label %early.exit

middle.block:
  br label %normal.exit

early.exit:
  %retval = phi i64 [ %20, %vector.early.exit ]
  ret i64 %retval

normal.exit:
  ret i64 1024
}

!0 = distinct !{!0, !1, !2}
!1 = !{!"llvm.loop.vectorize.width", i32 1}
!2 = !{!"llvm.loop.interleave.count", i32 4}

```


---

# Issue 155162

## Poison Propagation in Early-Exit Loop Vectorization

**Description**: 
When a loop containing an early exit is vectorized, the compiler evaluates the exit condition across multiple lanes simultaneously. To determine if the early exit should be taken, the compiler reduces the boolean results of the condition from all lanes into a single scalar boolean value (typically using a sequence of bitwise OR operations or a vector reduction). 

If the exit condition evaluates to `poison` for any lane—which can happen due to operations like out-of-bounds shifts, invalid memory accesses, or other undefined behaviors in lanes that would normally be unreachable or skipped in the scalar execution—the `poison` value propagates through the boolean reduction. Because bitwise operations with `poison` yield `poison`, the entire reduced scalar result becomes `poison` if even a single lane is `poison`. 

Subsequently, using this `poison` value as the branch condition for the early exit leads to undefined behavior and miscompilation. To trigger this issue, one can construct a vectorizable loop with an early exit where the condition involves an operation that naturally produces `poison` for certain iterations (e.g., a shift amount exceeding the type's bit-width). When vectorized, the evaluation of these iterations in parallel lanes injects `poison` into the reduction tree, corrupting the control flow.

## Example

### Original IR
```llvm
define i32 @early_exit_poison(ptr %src) {
entry:
  br label %loop

loop:
  %iv = phi i64 [ 0, %entry ], [ %iv.next, %loop.inc ]
  %gep = getelementptr inbounds i32, ptr %src, i64 %iv
  %load = load i32, ptr %gep, align 4
  %shift = shl i32 1, %load
  %cmp1 = icmp eq i32 %shift, 256
  br i1 %cmp1, label %early.exit, label %loop.inc

loop.inc:
  %iv.next = add nuw i64 %iv, 1
  %cmp2 = icmp eq i64 %iv.next, 64
  br i1 %cmp2, label %exit, label %loop

early.exit:
  ret i32 1

exit:
  ret i32 0
}

```
### Optimized IR
```llvm
declare i1 @llvm.vector.reduce.or.v4i1(<4 x i1>)

define i32 @early_exit_poison(ptr %src) {
entry:
  br label %vector.body

vector.body:
  %index = phi i64 [ 0, %entry ], [ %index.next, %vector.body.inc ]
  %0 = getelementptr inbounds i32, ptr %src, i64 %index
  %1 = load <4 x i32>, ptr %0, align 4
  %2 = shl <4 x i32> <i32 1, i32 1, i32 1, i32 1>, %1
  %3 = icmp eq <4 x i32> %2, <i32 256, i32 256, i32 256, i32 256>
  %4 = call i1 @llvm.vector.reduce.or.v4i1(<4 x i1> %3)
  br i1 %4, label %early.exit, label %vector.body.inc

vector.body.inc:
  %index.next = add nuw i64 %index, 4
  %5 = icmp eq i64 %index.next, 64
  br i1 %5, label %exit, label %vector.body

early.exit:
  ret i32 1

exit:
  ret i32 0
}

```


---

# Issue 69097

## Incomplete Invalidation of SCEV Expressions for LCSSA Phi Nodes During Loop Transformations

**Description**: 
The bug is triggered by a sequence of events involving Scalar Evolution (SCEV) and loop transformations that modify the Control Flow Graph (CFG):

1. **Trivial LCSSA Phi Node**: A loop has an exit block containing a trivial LCSSA phi node (e.g., a phi node with a single predecessor from the loop, or where all incoming values are identical).
2. **SCEV Caching**: When SCEV analyzes this trivial phi node, it looks through the phi and caches a SCEV expression (such as an AddRec or an Unknown value) that is defined inside the loop.
3. **CFG Modification**: A loop transformation (such as loop vectorization, unrolling, or peeling) adds a new predecessor to the loop's exit block. This structural change makes the previously trivial LCSSA phi node non-trivial.
4. **Incomplete Invalidation**: The transformation attempts to invalidate the SCEV cache for the modified phi node. However, the standard invalidation mechanism only traverses the IR use-def chains. It fails to catch and invalidate internal SCEV references (such as those used in Backedge Taken Counts) that directly use the loop-defined expressions.
5. **Miscompilation**: Because the internal SCEV uses are not thoroughly invalidated, SCEV retains stale, invalid expressions for the LCSSA phi node. Subsequent analyses or optimizations that query SCEV will receive incorrect information, leading to miscompilations such as incorrect loop trip counts or infinite loops.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define i32 @test(i1 %c) {
entry:
  br label %loop

loop:
  %iv = phi i32 [ 0, %entry ], [ %iv.next, %loop ]
  %iv.next = add nuw nsw i32 %iv, 1
  br i1 %c, label %exit, label %loop

exit:
  %lcssa = phi i32 [ %iv.next, %loop ]
  ret i32 %lcssa
}
```
### Optimized IR
```llvm
target datalayout = "e-m:e-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define i32 @test(i1 %c) {
entry:
  br i1 %c, label %exit, label %loop.peel

loop.peel:
  %iv.next.peel = add nuw nsw i32 0, 1
  br label %loop

loop:
  %iv = phi i32 [ %iv.next.peel, %loop.peel ], [ %iv.next, %loop ]
  %iv.next = add nuw nsw i32 %iv, 1
  br i1 %c, label %exit, label %loop

exit:
  %lcssa = phi i32 [ 1, %entry ], [ %iv.next, %loop ]
  ; Miscompilation: SCEV retained the stale AddRec expression for %lcssa 
  ; and incorrectly evaluated it, replacing the return value with undef or a wrong constant.
  ret i32 undef
}
```
