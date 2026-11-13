# Issue 165382

## Improper Optimization of Hash/CRC Loops with Auxiliary Data Used Outside the Loop

**Description**:
The bug is triggered by constructing a loop that performs a hash or CRC-like computation involving multiple recurrences: a conditional recurrence (representing the hash or CRC value) and a simple recurrence (representing auxiliary data, such as a shifted value or counter). Crucially, the simple recurrence's step operation (the evolution of the data) must have a user outside the loop, such as in the loop's exit block.

When the compiler's hash recognition pass identifies the loop, it attempts to optimize the computation by replacing it with a simplified mathematical equivalent or intrinsic. During this transformation, the pass incorrectly assumes that the auxiliary data is only used internally to compute the hash and completely strips it away. Because the pass fails to verify whether the auxiliary data's step instruction has stray users outside the recurrence itself, the external user is left with an incorrect or undefined value, leading to a miscompilation.
