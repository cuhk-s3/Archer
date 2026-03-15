# Issue 85333

## Sinking of `getelementptr` Instructions with Mismatched Source Element Types

**Description:**
The bug is triggered when multiple predecessor basic blocks contain `getelementptr` (GEP) instructions that flow into a common successor block. These GEP instructions share the same number of operands but operate on different source element types (e.g., one operates on an `i8` type while another operates on a larger struct type).

Because the address computation of a GEP instruction inherently depends on the size of its source element type, GEPs with different types apply different scaling factors to their offset indices. The optimization pass incorrectly identifies these GEPs as equivalent candidates for sinking because it only verifies that they have the same number of operands, failing to ensure that their underlying operations (specifically, their source element types) are identical.

As a result, the pass sinks the distinct GEPs into a single GEP instruction in the common successor block, using a PHI node to select the index operand based on the incoming control flow edge. This leads to a miscompilation because the newly sunk GEP uses only one specific source element type. Consequently, it applies an incorrect scaling factor to the indices originating from control flow paths that originally used a different source element type, resulting in wrong memory address calculations.

## Example

### Original IR
```llvm
%struct.S = type { i32, i32 }

define ptr @test_sink_gep_mismatched_types(i1 %cond, ptr %base, i64 %idx1, i64 %idx2) {
entry:
  br i1 %cond, label %bb1, label %bb2

bb1:
  %gep1 = getelementptr i8, ptr %base, i64 %idx1
  br label %end

bb2:
  %gep2 = getelementptr %struct.S, ptr %base, i64 %idx2
  br label %end

end:
  %res = phi ptr [ %gep1, %bb1 ], [ %gep2, %bb2 ]
  ret ptr %res
}
```
### Optimized IR
```llvm
%struct.S = type { i32, i32 }

define ptr @test_sink_gep_mismatched_types(i1 %cond, ptr %base, i64 %idx1, i64 %idx2) {
entry:
  br i1 %cond, label %bb1, label %bb2

bb1:
  br label %end

bb2:
  br label %end

end:
  %phi.idx = phi i64 [ %idx1, %bb1 ], [ %idx2, %bb2 ]
  %res = getelementptr i8, ptr %base, i64 %phi.idx
  ret ptr %res
}
```
