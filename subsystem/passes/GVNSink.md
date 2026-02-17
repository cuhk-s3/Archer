# Issue 85333

## Summary Title
Incorrect Sinking of GetElementPtr Instructions with Different Source Element Types

## Description
The bug is triggered when the optimization pass attempts to sink `getelementptr` (GEP) instructions from multiple predecessor blocks into a common successor block. The optimizer identifies these instructions as candidates for merging based on having the same opcode and the same number of operands, but it fails to verify that they operate on the same source element type.

In LLVM IR, GEP instructions calculate memory addresses by scaling the index operand by the size of the source element type. If the candidate instructions operate on types of different sizes (e.g., a byte type versus a larger structure type), the indices represent different physical byte offsets. When the optimizer sinks these instructions into a single GEP in the successor block, it forces all paths to use the element type of the sunk instruction. Consequently, for paths where the original type size differed, the index is scaled incorrectly (e.g., treated as a byte offset instead of a structure offset), resulting in the computation of an invalid memory address.

## Example

### Original IR
```llvm
define ptr @sink_gep_bug(i1 %cond, ptr %base, i64 %idx) {
entry:
  br i1 %cond, label %bb.true, label %bb.false

bb.true:
  ; Calculates address: base + idx * 1 (sizeof i8)
  %gep1 = getelementptr i8, ptr %base, i64 %idx
  br label %end

bb.false:
  ; Calculates address: base + idx * 4 (sizeof i32)
  %gep2 = getelementptr i32, ptr %base, i64 %idx
  br label %end

end:
  %res = phi ptr [ %gep1, %bb.true ], [ %gep2, %bb.false ]
  ret ptr %res
}
```
### Optimized IR
```llvm
define ptr @sink_gep_bug(i1 %cond, ptr %base, i64 %idx) {
entry:
  br i1 %cond, label %bb.true, label %bb.false

bb.true:
  br label %end

bb.false:
  br label %end

end:
  ; BUG: The optimizer sunk the GEPs but failed to check the source element type.
  ; It arbitrarily picked i8, so the path from bb.false now calculates
  ; base + idx * 1 instead of base + idx * 4.
  %sunk_gep = getelementptr i8, ptr %base, i64 %idx
  ret ptr %sunk_gep
}
```
