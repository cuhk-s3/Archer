# Issue 64289

## Tail Recursion Elimination Modifying `readonly byval` Arguments

**Description**:
The bug is triggered when a function takes a parameter with both `byval` (pass-by-value) and `readonly` attributes, and contains a tail-recursive call. During tail recursion elimination, the compiler transforms the recursive call into a loop. To update the arguments for the next loop iteration, the optimization reuses the existing parameter's memory by inserting memory copy instructions that overwrite the original `byval` argument.

However, the transformation fails to strip the `readonly` attribute from the function parameter. This creates a semantic contradiction in the IR where a parameter explicitly marked as read-only is being written to. Subsequent optimization passes rely on the `readonly` attribute and incorrectly assume the parameter's memory is never modified throughout the function execution. This false assumption leads to severe downstream miscompilations, such as incorrectly eliding memory loads or optimizing terminating conditions into infinite loops.

## Example

### Original IR
```llvm
%struct.S = type { i64, i64 }

define void @test(%struct.S* byval(%struct.S) readonly align 8 %arg, i32 %count) {
entry:
  %cmp = icmp eq i32 %count, 0
  br i1 %cmp, label %return, label %recurse

recurse:
  %sub = sub i32 %count, 1
  %new_arg = alloca %struct.S, align 8
  tail call void @test(%struct.S* byval(%struct.S) %new_arg, i32 %sub)
  ret void

return:
  ret void
}

```
### Optimized IR
```llvm
%struct.S = type { i64, i64 }

declare void @llvm.memcpy.p0i8.p0i8.i64(i8* noalias nocapture writeonly, i8* noalias nocapture readonly, i64, i1 immarg)

define void @test(%struct.S* byval(%struct.S) readonly align 8 %arg, i32 %count) {
entry:
  br label %tailrecurse

tailrecurse:                                      ; preds = %recurse, %entry
  %count.tr = phi i32 [ %count, %entry ], [ %sub, %recurse ]
  %cmp = icmp eq i32 %count.tr, 0
  br i1 %cmp, label %return, label %recurse

recurse:                                          ; preds = %tailrecurse
  %sub = sub i32 %count.tr, 1
  %new_arg = alloca %struct.S, align 8
  %0 = bitcast %struct.S* %arg to i8*
  %1 = bitcast %struct.S* %new_arg to i8*
  call void @llvm.memcpy.p0i8.p0i8.i64(i8* align 8 %0, i8* align 8 %1, i64 16, i1 false)
  br label %tailrecurse

return:                                           ; preds = %tailrecurse
  ret void
}

```
