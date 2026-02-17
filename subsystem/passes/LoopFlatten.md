# Issue 58441

## Incorrect Live-Out Value Update for Global Inner Induction Variable in Loop Flattening

**Description**:
The bug is triggered when the Loop Flattening optimization pass transforms a nested loop structure where the inner loop's induction variable is a global variable (or is otherwise used after the loop nest). The optimization flattens the nested loops into a single loop and attempts to manage the inner induction variable by recalculating its value based on the new flattened loop counter (typically using a modulo operation relative to the inner loop's trip count).

The incorrect transformation logic fails to preserve the correct "live-out" value of the inner induction variable. In the original nested loop execution, the inner induction variable reaches its exit value (equal to the loop bound) at the end of each inner loop run. However, the flattened loop implementation only computes the induction variable's value for the valid iterations of the loop body (up to `bound - 1`). The transformation does not explicitly generate code to update the global variable to its expected exit value after the flattened loop terminates. As a result, the global variable retains an incorrect intermediate value (such as the value from the last iteration) instead of the correct exit value, leading to a miscompilation when the variable is read subsequently.

## Example

### Original IR
```llvm
@g = common global i32 0, align 4

define void @test(i32 %N, i32 %M, i32* %A) {
entry:
  %cmp.n = icmp sgt i32 %N, 0
  %cmp.m = icmp sgt i32 %M, 0
  %cond = and i1 %cmp.n, %cmp.m
  br i1 %cond, label %outer.ph, label %exit

outer.ph:
  br label %outer.header

outer.header:
  %i = phi i32 [ 0, %outer.ph ], [ %i.next, %outer.latch ]
  br label %inner.header

inner.header:
  %j = phi i32 [ 0, %outer.header ], [ %j.next, %inner.body ]
  %mul = mul i32 %i, %M
  %offset = add i32 %mul, %j
  %ptr = getelementptr i32, i32* %A, i32 %offset
  store i32 0, i32* %ptr
  br label %inner.body

inner.body:
  %j.next = add nuw nsw i32 %j, 1
  ; The global variable tracks the inner induction variable.
  ; In the original loop, the last value stored for each outer iteration is M.
  store i32 %j.next, i32* @g
  %exitcond = icmp eq i32 %j.next, %M
  br i1 %exitcond, label %outer.latch, label %inner.header

outer.latch:
  %i.next = add nuw nsw i32 %i, 1
  %exitcond.outer = icmp eq i32 %i.next, %N
  br i1 %exitcond.outer, label %exit, label %outer.header

exit:
  ret void
}
```
### Optimized IR
```llvm
@g = common global i32 0, align 4

define void @test(i32 %N, i32 %M, i32* %A) {
entry:
  %cmp.n = icmp sgt i32 %N, 0
  %cmp.m = icmp sgt i32 %M, 0
  %cond = and i1 %cmp.n, %cmp.m
  br i1 %cond, label %loop.ph, label %exit

loop.ph:
  %flatten.tripcount = mul i32 %N, %M
  br label %loop.header

loop.header:
  %iv = phi i32 [ 0, %loop.ph ], [ %iv.next, %loop.header ]
  %ptr = getelementptr i32, i32* %A, i32 %iv
  store i32 0, i32* %ptr
  
  %iv.next = add nuw nsw i32 %iv, 1
  
  ; Incorrect transformation: The inner IV is reconstructed from the flattened IV.
  ; On the last iteration (iv.next == N*M), this computes (N*M) % M == 0.
  ; The global @g is left with 0 instead of the expected exit value M.
  %j.reconstructed = urem i32 %iv.next, %M
  store i32 %j.reconstructed, i32* @g
  
  %exitcond = icmp eq i32 %iv.next, %flatten.tripcount
  br i1 %exitcond, label %exit, label %loop.header

exit:
  ret void
}
```
