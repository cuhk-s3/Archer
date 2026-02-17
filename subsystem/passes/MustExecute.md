# Issue 57780

## Incorrect Must-Execute Analysis with Latch in Inner Cycle

**Description**:
The bug is triggered by a specific control flow pattern within a loop where the loop's latch block (the block that jumps back to the header) is part of an inner cycle or acts as a predecessor to the block being optimized. 

In this scenario, the compiler's "must-execute" analysis attempts to verify that a target basic block is guaranteed to execute whenever the loop is entered. The analysis traverses the predecessors of the target block to ensure all paths lead to it. However, the logic fails to account for the loop backedge when the latch itself is one of these predecessors. If control flow reaches the latch, it can take the backedge to the loop header, effectively bypassing the target block for that execution path. The compiler incorrectly assumes the target block is inevitable, leading it to aggressively hoist instructions (such as memory stores or loads) out of the loop (e.g., during Loop Invariant Code Motion), causing miscompilation when the target block should have been skipped.

## Example

### Original IR
```llvm
define void @test_loop(i1 %c, i32* %p) {
entry:
  br label %header

header:
  br i1 %c, label %latch, label %exit

latch:
  ; The latch block has a backedge to header and a conditional edge to target.
  ; This forms an inner cycle with target.
  %cond = icmp ne i32* %p, null
  br i1 %cond, label %target, label %header

target:
  ; This store is loop invariant but not guaranteed to execute.
  ; If %p is null, flow goes latch -> header, skipping target.
  store i32 1, i32* %p
  br label %latch

exit:
  ret void
}
```
### Optimized IR
```llvm
define void @test_loop(i1 %c, i32* %p) {
entry:
  ; The store is incorrectly hoisted to the entry block.
  ; It now executes unconditionally, causing a crash if %p is null,
  ; even if the original loop would have skipped the target block.
  store i32 1, i32* %p
  br label %header

header:
  br i1 %c, label %latch, label %exit

latch:
  %cond = icmp ne i32* %p, null
  br i1 %cond, label %target, label %header

target:
  br label %latch

exit:
  ret void
}
```
