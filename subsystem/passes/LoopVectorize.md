# Issue 107051

## Disagreement Between Cost Model and VPlan for Forced Scalar Calls

**Description**
The bug is triggered when the loop vectorizer processes a loop containing a function call that must be kept scalar (a "forced scalar"), for instance, because the call is uniform across vector lanes or constrained by other dependencies. The optimization pass contains a flaw where the logic responsible for deciding whether to widen (vectorize) function calls does not check if the call instruction has already been identified as a forced scalar.

Consequently, the optimizer may incorrectly decide to widen the call or calculate costs assuming a vectorized version is used, ignoring the requirement to scalarize it. This leads to an internal inconsistency where the legacy cost model and the VPlan (Vector Plan) cost model diverge in their decisions or cost estimations for the loop. This disagreement triggers an assertion failure intended to ensure that the chosen vectorization factor and the generated plan are consistent.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-i64:64-i128:128-n32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @test(ptr %a, float %b, i64 %n) {
entry:
  %cmp = icmp sgt i64 %n, 0
  br i1 %cmp, label %loop.preheader, label %exit

loop.preheader:
  br label %loop

loop:
  %iv = phi i64 [ 0, %loop.preheader ], [ %iv.next, %loop ]
  ; The call to @foo has a loop-invariant (uniform) argument %b.
  ; This uniformity can trigger the 'forced scalar' logic in VPlan.
  ; However, the presence of a vector variant (via attribute) tempts the
  ; cost model to widen the call, leading to the disagreement.
  %call = call float @foo(float %b) #0
  %addr = getelementptr float, ptr %a, i64 %iv
  store float %call, ptr %addr
  %iv.next = add i64 %iv, 1
  %exit.cond = icmp eq i64 %iv.next, %n
  br i1 %exit.cond, label %exit, label %loop

exit:
  ret void
}

declare float @foo(float)
declare <4 x float> @vec_foo(<4 x float>)

; Define a vector variant for @foo with VF=4, unmasked.
attributes #0 = { "vector-function-abi-variant"="_ZGVnN4v_foo(vec_foo)" }
```
### Optimized IR
```llvm
target datalayout = "e-m:e-i64:64-i128:128-n32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @test(ptr %a, float %b, i64 %n) {
entry:
  %cmp = icmp sgt i64 %n, 0
  br i1 %cmp, label %loop.preheader, label %exit

loop.preheader:
  %min.iters.check = icmp ult i64 %n, 4
  br i1 %min.iters.check, label %scalar.ph, label %vector.ph

vector.ph:
  %n.vec = and i64 %n, -4
  ; The invariant argument %b is broadcasted (splatted) for the vector call.
  %broadcast.splatinsert = insertelement <4 x float> poison, float %b, i64 0
  %broadcast.splat = shufflevector <4 x float> %broadcast.splatinsert, <4 x float> poison, <4 x i32> zeroinitializer
  br label %vector.body

vector.body:
  %index = phi i64 [ 0, %vector.ph ], [ %index.next, %vector.body ]
  ; The vectorizer generates a vector call using the variant @vec_foo.
  %vec.call = call <4 x float> @vec_foo(<4 x float> %broadcast.splat)
  %vec.ind = getelementptr float, ptr %a, i64 %index
  store <4 x float> %vec.call, ptr %vec.ind, align 4
  %index.next = add i64 %index, 4
  %vec.cmp = icmp eq i64 %index.next, %n.vec
  br i1 %vec.cmp, label %middle.block, label %vector.body

middle.block:
  %cmp.n = icmp eq i64 %n, %n.vec
  br i1 %cmp.n, label %exit, label %scalar.ph

scalar.ph:
  %bc.resume.val = phi i64 [ %n.vec, %middle.block ], [ 0, %loop.preheader ]
  br label %loop

loop:
  %iv = phi i64 [ %bc.resume.val, %scalar.ph ], [ %iv.next, %loop ]
  %call = call float @foo(float %b) #0
  %addr = getelementptr float, ptr %a, i64 %iv
  store float %call, ptr %addr
  %iv.next = add i64 %iv, 1
  %exit.cond = icmp eq i64 %iv.next, %n
  br i1 %exit.cond, label %exit, label %loop

exit:
  ret void
}

declare float @foo(float)
declare <4 x float> @vec_foo(<4 x float>)
attributes #0 = { "vector-function-abi-variant"="_ZGVnN4v_foo(vec_foo)" }
```


---

# Issue 142957

## Incorrect Speculation of Loads with Poison-Dependent Address Computations

The bug is triggered when the loop vectorizer attempts to speculate a conditional load instruction—converting it from a predicated execution to an unconditional one—without sufficiently verifying the safety of the instruction chain used to compute the load's address.

In this scenario, a load instruction inside a loop is guarded by a control flow condition. The memory address used by this load is derived from a chain of instructions. Crucially, some operands in this chain are conditionally defined or produce `poison` values when the guarding condition is false (for example, a PHI node merging a computed value with `poison` from a non-executing path).

The optimizer incorrectly marks the load as safe to speculate (execute unconditionally) based solely on the properties of the memory region (e.g., it is dereferenceable), failing to check if the *address computation* itself is safe to execute speculatively. Consequently, the vectorized code computes the address and performs the load even when the original condition is false. On these paths, the address computation consumes `poison` values, resulting in a `poison` pointer. Loading from a `poison` pointer causes immediate Undefined Behavior, miscompiling the valid input program.

## Example

### Original IR
```llvm
define void @test(i64* %a, i64* %b, i1* %cond_ptr, i64 %n) {
entry:
  br label %loop

loop:
  %i = phi i64 [ 0, %entry ], [ %i.next, %latch ]
  %c_addr = getelementptr inbounds i1, i1* %cond_ptr, i64 %i
  %c = load i1, i1* %c_addr
  br i1 %c, label %then, label %else

then:
  %ptr_valid = getelementptr inbounds i64, i64* %a, i64 %i
  br label %merge

else:
  br label %merge

merge:
  %ptr = phi i64* [ %ptr_valid, %then ], [ poison, %else ]
  br i1 %c, label %load_block, label %latch

load_block:
  %val = load i64, i64* %ptr
  %out_addr = getelementptr inbounds i64, i64* %b, i64 %i
  store i64 %val, i64* %out_addr
  br label %latch

latch:
  %i.next = add i64 %i, 1
  %exit = icmp eq i64 %i.next, %n
  br i1 %exit, label %exit_block, label %loop

exit_block:
  ret void
}
```
### Optimized IR
```llvm
define void @test(i64* %a, i64* %b, i1* %cond_ptr, i64 %n) {
entry:
  br label %vector.body

vector.body:
  %index = phi i64 [ 0, %entry ], [ %index.next, %vector.body ]
  
  ; Load condition vector (VF=2)
  %c_addr = getelementptr inbounds i1, i1* %cond_ptr, i64 %index
  %c_vec_ptr = bitcast i1* %c_addr to <2 x i1>*
  %mask = load <2 x i1>, <2 x i1>* %c_vec_ptr
  
  ; Scalarized address computation
  %i0 = add i64 %index, 0
  %i1 = add i64 %index, 1
  
  %c0 = extractelement <2 x i1> %mask, i32 0
  %c1 = extractelement <2 x i1> %mask, i32 1
  
  %ptr_valid_0 = getelementptr inbounds i64, i64* %a, i64 %i0
  %ptr_valid_1 = getelementptr inbounds i64, i64* %a, i64 %i1
  
  ; The Bug: Address selection includes poison
  %ptr0 = select i1 %c0, i64* %ptr_valid_0, i64* poison
  %ptr1 = select i1 %c1, i64* %ptr_valid_1, i64* poison
  
  ; The Bug: Unconditional speculation of load using potentially poison pointer
  %v0 = load i64, i64* %ptr0
  %v1 = load i64, i64* %ptr1
  
  ; Stores
  %out0 = getelementptr inbounds i64, i64* %b, i64 %i0
  %out1 = getelementptr inbounds i64, i64* %b, i64 %i1
  store i64 %v0, i64* %out0
  store i64 %v1, i64* %out1
  
  %index.next = add i64 %index, 2
  %cond = icmp eq i64 %index.next, %n
  br i1 %cond, label %exit, label %vector.body

exit:
  ret void
}
```


---

# Issue 144212

## Vectorization of Trivial First-Order Recurrences with Identical Inputs

## Description
The bug is triggered when the Loop Vectorizer processes a loop containing a First-Order Recurrence (FOR) that is effectively trivial. This specific condition arises when the initial value of the recurrence (incoming from the loop preheader) is identical to the updated value (incoming from the loop backedge). Because the input and the update are the same, the recurrence variable is loop-invariant.

When the vectorizer encounters this pattern, it constructs a vectorization plan that treats the variable as a standard recurrence, creating a recurrence PHI recipe where both the start and backedge operands refer to the same underlying value. During the subsequent code generation phase, this degenerate structure causes the compiler to generate invalid LLVM IR. Specifically, the instruction sequence created to handle the recurrence (typically involving vector PHI nodes and shuffle/splice operations) fails to respect SSA dominance rules, leading to a verification failure where a defined instruction does not dominate all its uses.

## Example

### Original IR
```llvm
define void @test_trivial_recurrence(float* %ptr, float %val, i64 %N) {
entry:
  %cmp = icmp sgt i64 %N, 0
  br i1 %cmp, label %loop, label %exit

loop:
  %iv = phi i64 [ 0, %entry ], [ %iv.next, %loop ]
  ; The trivial First-Order Recurrence: start and backedge values are identical (%val)
  %recur = phi float [ %val, %entry ], [ %val, %loop ]
  
  %gep = getelementptr inbounds float, float* %ptr, i64 %iv
  store float %recur, float* %gep
  
  %iv.next = add i64 %iv, 1
  %exitcond = icmp eq i64 %iv.next, %N
  br i1 %exitcond, label %exit, label %loop

exit:
  ret void
}
```
### Optimized IR
```llvm
define void @test_trivial_recurrence(float* %ptr, float %val, i64 %N) {
entry:
  %cmp = icmp sgt i64 %N, 0
  br i1 %cmp, label %vector.ph, label %exit

vector.ph:
  %broadcast.splatinsert = insertelement <4 x float> poison, float %val, i64 0
  %broadcast.splat = shufflevector <4 x float> %broadcast.splatinsert, <4 x float> poison, <4 x i32> zeroinitializer
  br label %vector.body

vector.body:
  %index = phi i64 [ 0, %vector.ph ], [ %index.next, %vector.body ]
  ; The degenerate recurrence PHI created by the vectorizer
  ; Both incoming values refer to the same loop-invariant value (%broadcast.splat)
  %vec.recur = phi <4 x float> [ %broadcast.splat, %vector.ph ], [ %broadcast.splat, %vector.body ]
  
  %gep = getelementptr inbounds float, float* %ptr, i64 %index
  %gep.cast = bitcast float* %gep to <4 x float>*
  store <4 x float> %vec.recur, <4 x float>* %gep.cast, align 4
  
  %index.next = add i64 %index, 4
  %vec.exitcond = icmp eq i64 %index.next, %N
  br i1 %vec.exitcond, label %exit, label %vector.body

exit:
  ret void
}
```


---

# Issue 154967

## Missing Exit Value Selection in Interleaved Scalar Loops with Early Exits

**Description**

The miscompilation is triggered when the loop vectorizer processes a loop containing an uncountable early exit (e.g., a `break` or `return` dependent on a runtime condition) under a configuration that uses a scalar Vector Factor (VF=1) combined with loop interleaving (Interleave Count > 1).

In this scenario, the vectorizer effectively unrolls the loop body multiple times within a single iteration of the transformed loop. When an early exit condition is met, the generated code must identify exactly which of the unrolled iterations triggered the exit to select the correct live-out value (such as the induction variable).

The bug occurred because the transformation logic responsible for generating the instructions to detect the "first active lane" (the specific iteration causing the exit) and extract the corresponding value was restricted to vector VFs (VF > 1). Consequently, when compiling with a scalar VF and interleaving, this selection logic was omitted. This resulted in the loop exiting upon the condition, but propagating an incorrect value (often from a different iteration within the interleaved group) to the subsequent code, leading to a runtime failure.

## Example

### Original IR
```llvm
define i32 @test_search(i32* %src, i32 %n) {
entry:
  br label %loop

loop:
  %iv = phi i32 [ 0, %entry ], [ %iv.next, %latch ]
  %gep = getelementptr inbounds i32, i32* %src, i32 %iv
  %val = load i32, i32* %gep
  %cond = icmp eq i32 %val, 100
  br i1 %cond, label %exit, label %latch

latch:
  %iv.next = add i32 %iv, 1
  %loop.cond = icmp ult i32 %iv.next, %n
  br i1 %loop.cond, label %loop, label %exit

exit:
  %res = phi i32 [ %iv, %loop ], [ -1, %latch ]
  ret i32 %res
}
```
### Optimized IR
```llvm
define i32 @test_search(i32* %src, i32 %n) {
entry:
  br label %vector.body

vector.body:
  %index = phi i32 [ 0, %entry ], [ %index.next, %vector.body ]
  %gep = getelementptr inbounds i32, i32* %src, i32 %index
  %val = load i32, i32* %gep
  %cmp = icmp eq i32 %val, 100
  %index.1 = add i32 %index, 1
  %gep.1 = getelementptr inbounds i32, i32* %src, i32 %index.1
  %val.1 = load i32, i32* %gep.1
  %cmp.1 = icmp eq i32 %val.1, 100
  %found = or i1 %cmp, %cmp.1
  %index.next = add i32 %index, 2
  br i1 %found, label %exit, label %vector.body

exit:
  ; BUG: The PHI node incorrectly selects the base induction variable %index
  ; regardless of whether the first lane (%cmp) or second lane (%cmp.1) triggered the exit.
  ; It fails to select %index.1 when %cmp is false and %cmp.1 is true.
  %res = phi i32 [ %index, %vector.body ]
  ret i32 %res
}
```


---

# Issue 169780

## Unhandled Scalar-Only Pointer Induction in Vector Plan Lowering

**Description**
The bug is triggered during the loop vectorization process when a loop contains a pointer induction variable that the compiler initially plans to widen (vectorize). During the optimization phases of the Vector Plan (VPlan), transformations—such as dead code elimination or instruction simplification—may remove all vector-typed dependencies on this induction variable. As a result, the induction variable recipe remains in the plan but is utilized solely by scalar operations.

The incorrect transformation logic occurs during the final phase of converting the vector plan into concrete machine instructions. The compiler operates under the assumption that any "widen pointer induction" recipe reaching this stage must be used to generate vector values. It asserts failure if it encounters such a recipe that is used exclusively for scalars. The compiler fails to detect this state change and does not fallback to generating the equivalent scalar pointer arithmetic (base address plus step offset), causing a crash.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @test(i8* %ptr, i64 %n) {
entry:
  br label %loop

loop:
  %iv = phi i64 [ 0, %entry ], [ %iv.next, %loop ]
  %p = phi i8* [ %ptr, %entry ], [ %p.next, %loop ]
  
  ; This load is vectorizable, causing VPlan to create a WidenPointerInduction recipe.
  ; However, the result is unused, so VPlan DCE will remove the load recipe.
  %val = load i8, i8* %p
  
  ; This call forces scalar usage of the pointer.
  ; After the load is removed, the pointer induction is used ONLY by this scalar call.
  call void @use(i8* %p)
  
  %p.next = getelementptr i8, i8* %p, i64 1
  %iv.next = add i64 %iv, 1
  %cond = icmp eq i64 %iv.next, %n
  br i1 %cond, label %exit, label %loop, !llvm.loop !0

exit:
  ret void
}

declare void @use(i8*)

!0 = distinct !{!0, !1}
!1 = !{!"llvm.loop.vectorize.width", i32 2}
```
### Optimized IR
```llvm
target datalayout = "e-m:e-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define void @test(i8* %ptr, i64 %n) {
entry:
  %min.iters.check = icmp ult i64 %n, 2
  br i1 %min.iters.check, label %scalar.ph, label %vector.ph

vector.ph:
  %n.vec = and i64 %n, -2
  br label %vector.body

vector.body:
  %index = phi i64 [ 0, %vector.ph ], [ %index.next, %vector.body ]
  %next.gep = getelementptr i8, i8* %ptr, i64 %index
  
  ; The load has been eliminated by DCE.
  ; The pointer induction is used to generate scalars for the call.
  %scalar.gep.0 = getelementptr i8, i8* %next.gep, i64 0
  call void @use(i8* %scalar.gep.0)
  %scalar.gep.1 = getelementptr i8, i8* %next.gep, i64 1
  call void @use(i8* %scalar.gep.1)
  
  %index.next = add nuw i64 %index, 2
  %1 = icmp eq i64 %index.next, %n.vec
  br i1 %1, label %middle.block, label %vector.body, !llvm.loop !0

middle.block:
  %cmp.n = icmp eq i64 %n, %n.vec
  br i1 %cmp.n, label %exit, label %scalar.ph

scalar.ph:
  %bc.resume.val = phi i64 [ %n.vec, %middle.block ], [ 0, %entry ]
  %bc.resume.val1 = phi i8* [ %next.gep, %middle.block ], [ %ptr, %entry ]
  br label %loop

loop:
  %iv = phi i64 [ %bc.resume.val, %scalar.ph ], [ %iv.next, %loop ]
  %p = phi i8* [ %bc.resume.val1, %scalar.ph ], [ %p.next, %loop ]
  %val = load i8, i8* %p
  call void @use(i8* %p)
  %p.next = getelementptr i8, i8* %p, i64 1
  %iv.next = add i64 %iv, 1
  %cond = icmp eq i64 %iv.next, %n
  br i1 %cond, label %exit, label %loop, !llvm.loop !2

exit:
  ret void
}

declare void @use(i8*)

!0 = distinct !{!0, !1}
!1 = !{!"llvm.loop.isvectorized", i32 1}
!2 = distinct !{!2, !1}
```


---

# Issue 76986

## Incorrect Replacement of Scalarized Cast Recipes with Widened Vector Recipes

**Description**
The bug is triggered during the VPlan transformation phase of the loop vectorizer when the compiler attempts to simplify sequences of cast instructions (such as a truncation followed by an extension, or redundant casts). The optimization logic identifies a cast recipe that can be folded or replaced by a simpler cast based on the types of its operands.

However, the transformation incorrectly replaces the existing recipe with a widened (vector) cast recipe without verifying if the original recipe was designated for scalar execution (a `VPReplicateRecipe`). This distinction is critical when the loop is being interleaved but not vectorized (VF=1), or when specific instructions must remain scalar. By substituting a scalarizing recipe with a vectorizing one, the compiler introduces mismatched vector operations into a scalar context, leading to invalid Intermediate Representation (IR) or assertion failures during code generation.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-i64:64-i128:128-n32:64-S128"
target triple = "aarch64-unknown-linux-gnu"

define void @test_cast_fold(i32* %src, i32* %dst, i64 %N) {
entry:
  br label %loop

loop:
  %iv = phi i64 [ 0, %entry ], [ %iv.next, %loop ]
  %gep.src = getelementptr inbounds i32, i32* %src, i64 %iv
  %val = load i32, i32* %gep.src, align 4
  
  ; The cast sequence that triggers the simplification logic
  %trunc = trunc i32 %val to i16
  %ext = zext i16 %trunc to i32
  
  %gep.dst = getelementptr inbounds i32, i32* %dst, i64 %iv
  store i32 %ext, i32* %gep.dst, align 4
  
  %iv.next = add i64 %iv, 1
  %exitcond = icmp eq i64 %iv.next, %N
  br i1 %exitcond, label %exit, label %loop

exit:
  ret void
}
```
### Optimized IR
```llvm
target datalayout = "e-m:e-i64:64-i128:128-n32:64-S128"
target triple = "aarch64-unknown-linux-gnu"

define void @test_cast_fold(i32* %src, i32* %dst, i64 %N) {
entry:
  br label %vector.body

vector.body:
  %index = phi i64 [ 0, %entry ], [ %index.next, %vector.body ]
  
  ; VF=1, IC=2: Scalar loads are expected
  %gep.src = getelementptr inbounds i32, i32* %src, i64 %index
  %l0 = load i32, i32* %gep.src, align 4
  %gep.src.1 = getelementptr inbounds i32, i32* %gep.src, i64 1
  %l1 = load i32, i32* %gep.src.1, align 4
  
  ; BUG: The optimizer incorrectly introduced a widened vector operation (and)
  ; instead of keeping scalar casts, despite VF=1. This requires packing scalars.
  %vec.ins.0 = insertelement <2 x i32> poison, i32 %l0, i64 0
  %vec.ins.1 = insertelement <2 x i32> %vec.ins.0, i32 %l1, i64 1
  %vec.op = and <2 x i32> %vec.ins.1, <i32 65535, i32 65535>
  
  ; Extracting back to scalar for storage
  %e0 = extractelement <2 x i32> %vec.op, i64 0
  %gep.dst = getelementptr inbounds i32, i32* %dst, i64 %index
  store i32 %e0, i32* %gep.dst, align 4
  
  %e1 = extractelement <2 x i32> %vec.op, i64 1
  %gep.dst.1 = getelementptr inbounds i32, i32* %gep.dst, i64 1
  store i32 %e1, i32* %gep.dst.1, align 4
  
  %index.next = add i64 %index, 2
  %cond = icmp eq i64 %index.next, %N
  br i1 %cond, label %exit, label %vector.body

exit:
  ret void
}
```
