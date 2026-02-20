# Issue 54023

## Incorrect Dead Block Elimination for Non-Canonical Loop Exit Blocks

**Description**: 
The bug is triggered when a loop optimization pass processes a loop that is not in canonical form, specifically where an exit block of the loop has predecessors originating from outside the loop. 

During control flow simplification, the optimization evaluates the reachability of loop exit blocks. If it determines that an exit block is no longer reachable from within the loop (i.e., all edges from inside the loop to the exit block are dead), it incorrectly assumes the exit block is entirely dead. Because the logic fails to account for predecessors outside the loop, the pass erroneously removes or marks the exit block as dead. 

This breaks the control flow for execution paths originating outside the loop that still rely on reaching that exit block, leading to miscompilations such as infinite loops or invalid control flow graphs. To trigger this issue, a sequence of passes must first break the loop's canonical form (e.g., by creating an external edge to a loop exit block) and subsequently perform loop control flow simplification that evaluates exit block reachability based solely on intra-loop edges.

## Example

### Original IR
```llvm
define void @test(i1 %c1, i1 %c2) {
entry:
  br i1 %c1, label %loop.header, label %exit

loop.header:
  br i1 false, label %exit, label %loop.latch

loop.latch:
  br i1 %c2, label %loop.header, label %loop.end

loop.end:
  ret void

exit:
  ret void
}

```
### Optimized IR
```llvm
define void @test(i1 %c1, i1 %c2) {
entry:
  br i1 %c1, label %loop.header, label %dead_exit

loop.header:
  br label %loop.latch

loop.latch:
  br i1 %c2, label %loop.header, label %loop.end

loop.end:
  ret void

dead_exit:
  unreachable
}

```
