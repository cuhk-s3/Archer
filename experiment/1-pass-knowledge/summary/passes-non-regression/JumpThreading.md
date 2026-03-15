# Issue 79175

## Incorrect Load Elimination Due to Stale Dominator Tree in Alias Analysis

**Description:**

The bug is triggered by an unsafe interaction between control flow transformations and memory optimization queries relying on outdated analysis data. The strategy unfolds as follows:

1. **Control Flow Modification:** A compiler pass (such as jump threading) performs transformations that alter the Control Flow Graph (CFG). These changes can leave the Dominator Tree temporarily stale or out of sync with the actual CFG.
2. **Redundant Load Optimization:** While the Dominator Tree is in this stale state, the pass attempts to optimize memory accesses, specifically looking to eliminate partially redundant loads by reusing previously loaded values.
3. **Flawed Alias Analysis Query:** To ensure the optimization is safe, the pass queries Alias Analysis to check if any intervening memory writes (e.g., stores) clobber the memory location before the load occurs.
4. **Incorrect Non-Aliasing Deduction:** Alias Analysis internally utilizes the Dominator Tree to make advanced aliasing deductions (such as evaluating contextual assumptions, checking cycles, or decomposing pointer expressions). Because the Dominator Tree is outdated, Alias Analysis evaluates the dominance relationships incorrectly. This leads it to mistakenly conclude that an intervening memory write does *not* alias the load's target address (`NoAlias`), when in reality, it does.
5. **Miscompilation:** Trusting the incorrect Alias Analysis result, the optimization pass assumes the previously loaded value is still valid. It incorrectly eliminates the load instruction, replacing it with a stale value (often by routing an older value through a PHI node). This bypasses the actual memory update performed by the clobbering write, resulting in a miscompilation where the program uses an outdated value.

## Example

### Original IR
```llvm
define i8 @test(i8* %p, i8* %q, i1 %c1) {
entry:
  %load1 = load i8, i8* %p
  br i1 %c1, label %bb1, label %bb2

bb1:
  store i8 42, i8* %q
  br label %bb3

bb2:
  br label %bb3

bb3:
  %phi = phi i1 [ true, %bb1 ], [ false, %bb2 ]
  br i1 %phi, label %bb4, label %bb5

bb4:
  %load2 = load i8, i8* %p
  ret i8 %load2

bb5:
  ret i8 0
}

```
### Optimized IR
```llvm
define i8 @test(i8* %p, i8* %q, i1 %c1) {
entry:
  %load1 = load i8, i8* %p
  br i1 %c1, label %bb1, label %bb5

bb1:
  store i8 42, i8* %q
  ret i8 %load1

bb5:
  ret i8 0
}

```
