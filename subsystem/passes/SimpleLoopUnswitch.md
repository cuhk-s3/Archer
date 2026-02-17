# Issue 63962

## Incorrect Branch Successor Mapping during Loop Condition Injection

**Description**
The bug is triggered during a loop unswitching optimization when the compiler attempts to inject or reconstruct invariant conditions. When replacing or recreating a conditional branch instruction that controls flow between the loop body (backedge) and a loop exit, the transformation fails to preserve the original mapping between the condition's boolean outcome and its target successors.

Instead of copying the specific "true" and "false" targets from the original instruction, the compiler blindly constructs a new branch where the successor leading back into the loop is assigned to the "true" path (or a fixed default), and the exit successor is assigned to the "false" path. If the original source code was structured such that the "false" outcome kept execution inside the loop (and "true" exited), this rigid reconstruction effectively inverts the control flow logic. This results in the loop terminating when it should continue, or continuing when it should terminate, leading to a miscompilation.

## Example

### Original IR
```llvm
define void @test_loop_unswitch_bug(i1 %cond, i32 %N) {
entry:
  br label %header

header:
  %i = phi i32 [ 0, %entry ], [ %inc, %latch ]
  ; The invariant condition is checked here.
  ; Note the structure: True -> Exit, False -> Loop Body.
  ; This is the inverse of the canonical 'if (cond) { loop } else { exit }'.
  br i1 %cond, label %exit, label %body

body:
  ; Loop body logic
  %inc = add i32 %i, 1
  br label %latch

latch:
  %cmp = icmp slt i32 %inc, %N
  br i1 %cmp, label %header, label %exit

exit:
  ret void
}
```
### Optimized IR
```llvm
define void @test_loop_unswitch_bug(i1 %cond, i32 %N) {
entry:
  ; The loop unswitching pass has hoisted the invariant condition.
  ; BUG: The compiler assumed a canonical mapping (True->Loop, False->Exit)
  ; ignoring the original instruction's mapping (True->Exit, False->Loop).
  br i1 %cond, label %header.us, label %exit

header.us:
  ; This path is taken when %cond is TRUE.
  ; Originally, this should have exited.
  ; Due to the bug, it executes the loop body.
  %i.us = phi i32 [ 0, %entry ], [ %inc.us, %latch.us ]
  %inc.us = add i32 %i.us, 1
  br label %latch.us

latch.us:
  %cmp.us = icmp slt i32 %inc.us, %N
  br i1 %cmp.us, label %header.us, label %exit

exit:
  ; This path is taken when %cond is FALSE.
  ; Originally, this should have entered the loop.
  ; Due to the bug, it exits immediately.
  ret void
}
```
