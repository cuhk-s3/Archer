# Issue 89672

## Summary Title
Speculation of High-Alignment Stores Based on Low-Alignment Predecessors

## Description
The bug is triggered when the optimizer attempts to speculate (hoist) a store instruction from a conditionally executed basic block into a predecessor block. To ensure the speculation is safe (i.e., does not introduce a fault), the optimizer checks if there is a preceding memory access (load or store) to the same pointer in the predecessor block, using it as proof that the pointer is valid and dereferenceable.

However, the transformation incorrectly assumes that proving dereferenceability is sufficient to preserve the properties of the hoisted store. It fails to verify that the alignment of the preceding access is greater than or equal to the alignment of the store being hoisted. If the store in the conditional block specifies a stricter (larger) alignment than the preceding access, hoisting it imposes that stricter alignment requirement unconditionally. This leads to undefined behavior (e.g., misaligned memory access) on execution paths where the pointer only satisfies the lower alignment guarantee of the original preceding access.

## Example

### Original IR
```llvm
define void @test_alignment_speculation(i32* %ptr, i1 %cond) {
entry:
  ; Predecessor access with low alignment (1). This proves dereferenceability.
  %val = load i32, i32* %ptr, align 1
  br i1 %cond, label %if.then, label %if.end

if.then:
  ; Conditional store with high alignment (4).
  ; If %cond is false, this strict alignment is not required in the original code.
  store i32 %val, i32* %ptr, align 4
  br label %if.end

if.end:
  ret void
}
```
### Optimized IR
```llvm
define void @test_alignment_speculation(i32* %ptr, i1 %cond) {
entry:
  %val = load i32, i32* %ptr, align 1
  ; The optimizer speculates the store to the entry block to remove the branch.
  ; BUG: It incorrectly preserves the 'align 4' from the conditional block.
  ; This introduces Undefined Behavior (misaligned access) if %ptr is not 4-byte aligned,
  ; even if %cond would have been false.
  store i32 %val, i32* %ptr, align 4
  ret void
}
```
