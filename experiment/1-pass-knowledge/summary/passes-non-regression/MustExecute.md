# Issue 57780

## Incorrect Must-Execute Analysis for Loop Latches in Inner Cycles

**Description:**
The bug is triggered in loop optimization passes (such as Loop Invariant Code Motion) when the compiler attempts to determine if a specific basic block is guaranteed to execute (must-execute property) within a loop.

The problematic pattern arises when the loop latch (the basic block containing the backedge to the loop header) is a transitive predecessor of the target block being analyzed. This control flow typically occurs when the latch is part of an inner cycle or has multiple successors, where one path leads back to the loop header and another path leads to the target block.

When analyzing whether all paths lead to the target block, the compiler collects all transitive predecessors of the target block. Because the loop header naturally precedes the target block, it is included in this predecessor set. The flawed logic observes that the loop latch branches to the loop header (via the backedge) and incorrectly assumes this path is safe because the destination (the header) remains within the known predecessor set.

However, this reasoning fails to account for loop semantics: taking the backedge initiates a new loop iteration. In the subsequent iteration, the control flow might take a different path and exit the loop entirely without ever reaching the target block. By treating the backedge as just another path to the target block, the compiler erroneously concludes that the target block must execute. This misclassification leads to invalid optimizations, such as hoisting instructions or promoting memory operations that are not actually guaranteed to execute, ultimately resulting in miscompilations.

## Example

### Original IR
```llvm
define void @test(i1 %c1, i1 %c2, i32 %x) {
entry:
  br label %header

header:
  br i1 %c1, label %latch, label %exit

latch:
  br i1 %c2, label %header, label %target

target:
  %div = sdiv i32 1, %x
  br label %latch

exit:
  ret void
}
```
### Optimized IR
```llvm
define void @test(i1 %c1, i1 %c2, i32 %x) {
entry:
  %div = sdiv i32 1, %x
  br label %header

header:
  br i1 %c1, label %latch, label %exit

latch:
  br i1 %c2, label %header, label %target

target:
  br label %latch

exit:
  ret void
}
```
