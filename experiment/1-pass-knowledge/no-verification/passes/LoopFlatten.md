# Issue 58441

## Loop Flattening Miscompilation due to Unchecked External Uses of Step Instruction

**Description**:
The bug is triggered by a nested loop structure where the inner loop's induction variable escapes the loop nest. Specifically, the final value of the inner induction variable is used outside the loop (for example, when it represents a global variable whose final value is stored and observable after the loops terminate).

At the LLVM IR level, an induction variable is typically represented by a PHI node at the loop header, and its update is handled by a step instruction inside the loop (e.g., `next_val = phi_val + 1`). When the final value of this induction variable is used outside the loop, the external use often references the *step instruction* via a Loop-Closed SSA (LCSSA) PHI node at the loop exit, rather than referencing the induction variable's PHI node directly.

The miscompilation occurs because the Loop Flattening optimization pass fails to comprehensively check for these external users. While the pass correctly checks if the induction variable's *PHI node* has users outside the inner loop, it neglects to check if the *step instruction* has external users.

When the step instruction is the only value escaping the loop, the pass incorrectly assumes the inner induction variable is strictly internal and used solely for loop control. Consequently, it proceeds to flatten the loop by merging the inner and outer loops and removing the inner loop's backedge. Because the pass believes the inner induction variable is dead/internal, it optimizes it away instead of correctly rewriting it (e.g., by replacing it with a modulo operation on the new flattened induction variable).

As a result of removing the inner loop's backedge, the inner induction variable's PHI node loses its loop-carried incoming value and degrades to its initial value (e.g., `0`). The step instruction then statically evaluates to `initial_value + step` (e.g., `0 + 1 = 1`) for every iteration of the flattened loop. When the flattened loop terminates, this incorrect constant value is propagated to the external users instead of the correct final loop exit value, leading to a miscompilation and incorrect program output.

---

# Issue 59339

## Loop Flattening Miscompilation due to Extra Uses of Outer Induction Variable Multiplication

**Description**:
To trigger this bug, construct a nested loop structure that is a candidate for loop flattening. Within the outer loop, include a multiplication instruction that multiplies the outer loop's induction variable by the inner loop's trip count. Use this multiplication in the inner loop to compute a flattened array index (e.g., `InnerIV + OuterIV * InnerTripCount`).

Crucially, introduce an additional, independent use of this multiplication instruction elsewhere in the loop (for example, to compute a different pointer offset or value in the outer loop).

When the loop flattening optimization is applied, it merges the nested loops into a single loop and replaces the outer loop's induction variable with a new flattened induction variable that iterates over the total combined trip count. However, the optimization fails to verify whether the multiplication instruction has uses other than the specific flattened index computation it expects.

As a result of the transformation, the multiplication instruction now computes `FlattenedIV * InnerTripCount` instead of `OuterIV * InnerTripCount`. Because the multiplication has extra uses, those independent uses will receive an entirely different and incorrect sequence of values (scaling up much faster than in the original unflattened loop), leading to a miscompilation and incorrect memory accesses.
