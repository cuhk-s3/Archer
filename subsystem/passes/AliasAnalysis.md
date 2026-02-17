# Issue 72831

## Incorrect Alias Analysis Assumption on Wrapped Scaled Indices

**Description**:
The bug is triggered during alias analysis of `GetElementPtr` (GEP) instructions that involve variable indices. When decomposing a GEP instruction, the analysis identifies a variable index that is known to be non-zero. Based on this, the logic incorrectly assumes that the contribution of this variable index to the total offset (calculated as `variable_index * scale`) must have an absolute value of at least one.

However, this assumption fails to account for wrapping arithmetic (integer overflow). Even if the variable index itself is non-zero, multiplying it by the scale factor can result in a value that wraps to zero (or a value smaller than expected) within the bit width of the pointer type. Consequently, the analysis erroneously determines that the memory access is offset from the base pointer by at least one byte, leading it to conclude that two actually aliasing pointers do not alias (NoAlias). This incorrect NoAlias result allows subsequent optimization passes to incorrectly eliminate or reorder memory stores or loads.

## Example

### Original IR
```llvm
define i32 @test(i32* %ptr, i64 %idx) {
  ; Establish that %idx is not zero
  %nz = icmp ne i64 %idx, 0
  call void @llvm.assume(i1 %nz)

  ; Store initial value to base pointer
  store i32 1, i32* %ptr

  ; Calculate GEP with variable index. 
  ; Note: 'inbounds' is intentionally omitted. Without inbounds, the calculation 
  ; is modulo arithmetic. If %idx * sizeof(i32) wraps to 0 (e.g. idx = 2^62), 
  ; %gep equals %ptr.
  %gep = getelementptr i32, i32* %ptr, i64 %idx

  ; Store new value to GEP. If %gep aliases %ptr, this overwrites the 1.
  store i32 2, i32* %gep

  ; Load from base pointer. 
  ; If the compiler incorrectly assumes NoAlias due to %idx != 0, 
  ; it will forward '1' instead of reloading or seeing '2'.
  %val = load i32, i32* %ptr
  ret i32 %val
}

declare void @llvm.assume(i1)
```
### Optimized IR
```llvm
define i32 @test(i32* %ptr, i64 %idx) {
  %nz = icmp ne i64 %idx, 0
  call void @llvm.assume(i1 %nz)
  store i32 1, i32* %ptr
  %gep = getelementptr i32, i32* %ptr, i64 %idx
  store i32 2, i32* %gep
  ; The load has been incorrectly eliminated and replaced with the constant 1
  ; because the optimizer assumed %gep could not alias %ptr.
  ret i32 1
}

declare void @llvm.assume(i1)
```


---

# Issue 79175

## Stale Dominator Tree Usage in Alias Analysis during Jump Threading

**Description**
The bug is triggered during the Jump Threading optimization pass, which actively modifies the Control Flow Graph (CFG) to simplify control flow. As part of its operation, the pass attempts to eliminate partially redundant load instructions by checking if the loaded value is already available from a dominating definition (such as a previous store or load).

To safely perform this replacement, the pass queries Alias Analysis (AA) to ensure that no intervening instructions clobber (write to) the memory location being loaded. The Alias Analysis logic relies on the Dominator Tree to reason about pointer validity, object lifetimes, and potential aliasing relationships.

The issue arises because the Jump Threading pass updates the Dominator Tree lazily or leaves it in a stale state while performing these queries on the modified CFG. Consequently, Alias Analysis uses incorrect dominance information, leading it to erroneously conclude that a clobbering store does not alias the load or that the memory dependency is preserved. This causes the optimizer to incorrectly replace a load instruction with a stale value, ignoring a necessary reload from memory after a store to the same location.

## Example

### Original IR
```llvm
define i32 @test_jump_threading_clobber(i32* %ptr, i32* %clobber, i1 %cond) {
entry:
  store i32 42, i32* %ptr
  br i1 %cond, label %mid, label %other

other:
  br label %mid

mid:
  %p = phi i32 [ 0, %entry ], [ 1, %other ]
  ; This store may clobber %ptr. If AA uses a stale Dominator Tree,
  ; it might incorrectly determine NoAlias between %clobber and %ptr.
  store i32 99, i32* %clobber
  %check = icmp eq i32 %p, 0
  br i1 %check, label %dest, label %exit

dest:
  ; If threaded from entry, %ptr should contain 99 (if aliased) or 42 (if not).
  ; The bug causes this load to be replaced by 42 unconditionally.
  %val = load i32, i32* %ptr
  ret i32 %val

exit:
  ret i32 0
}
```
### Optimized IR
```llvm
define i32 @test_jump_threading_clobber(i32* %ptr, i32* %clobber, i1 %cond) {
entry:
  store i32 42, i32* %ptr
  br i1 %cond, label %mid.thread, label %other

other:
  br label %mid

mid.thread:
  ; Threaded path from entry -> mid -> dest
  store i32 99, i32* %clobber
  ; BUG: The load was replaced by 42, ignoring the potential clobber above.
  ret i32 42

mid:
  ; Path from other -> mid -> exit
  store i32 99, i32* %clobber
  br label %exit

exit:
  ret i32 0
}
```
