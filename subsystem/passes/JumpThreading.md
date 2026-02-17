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
