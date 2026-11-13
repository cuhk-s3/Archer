# Issue 62992

## Unsafe Hoisting of Potentially Trapping Loop-Invariant Expressions

**Description**:
The bug is triggered when a loop optimization pass attempts to simplify an induction variable comparison by hoisting its loop-invariant operands into the loop preheader.

In the original program, the loop-invariant expression may contain a potentially trapping operation (such as an integer division or remainder). To prevent runtime faults, this operation is typically guarded by a condition within the loop body (e.g., checking that the divisor is not zero), ensuring it is only executed when safe.

However, the optimization transformation fails to verify whether the loop-invariant expression is safe to expand and execute speculatively at the new insertion point in the preheader. By unconditionally hoisting and expanding the expression outside the loop, the compiler bypasses the original protective guards. As a result, the potentially trapping operation is executed unconditionally before the loop begins, leading to runtime exceptions (such as a division by zero fault) that would not have occurred in the unoptimized code.
