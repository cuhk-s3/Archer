# Issue 123920

## Incorrect Handling of Non-Strict Dependence Directions in Loop Interchange

**Description**

The bug is triggered by a loop nest (typically three or more levels deep) containing memory accesses that form a data dependence. The strategy to trigger this issue involves constructing a memory dependence with a specific combination of direction vectors across the loop levels:

1. **Non-Strict Outer Dependence**: An outer loop must have a non-strict dependence direction, such as "Less than or Equal" (LE) or "Greater than or Equal" (GE).
2. **Conflicting Inner Dependences**: The inner loops must have dependence directions (e.g., "Less than" and "Greater than") such that interchanging them would be illegal if the outer loop's dependence were strictly "Equal". For instance, swapping the inner loops might result in a "Greater than" direction at the second level, which is invalid if the first level is "Equal" because it implies the dependence flows backward in execution order.

The incorrect transformation logic occurs during the legality check for loop interchange. The compiler's dependence matrix incorrectly approximates the non-strict directions (LE and GE) as strict directions (strictly "Less than" or strictly "Greater than"), completely discarding the "Equal" component.

Because the compiler assumes the dependence is strictly carried by the outer loop, it incorrectly concludes that the inner loops can be safely interchanged without violating the dependence. This bypasses the legality checks that would have otherwise caught the invalid permutation under the "Equal" condition, leading the compiler to perform an unsafe loop interchange and resulting in a miscompilation.

---

# Issue 140238

## Loop Interchange Miscompilation due to Incorrect Handling of Confused Memory Dependencies

**Description**:
The bug is triggered by a nested loop structure containing memory accesses where the exact data dependencies cannot be precisely determined by the compiler's dependence analysis. This ambiguity typically arises in two scenarios at the IR level:
1. Memory accesses involving pointers that may alias (e.g., pointers passed as function arguments where alias analysis returns a "MayAlias" result).
2. Memory accesses where the number of accessed dimensions is less than the depth of the loop nest (e.g., accessing a 1D array inside a 3D loop nest).

In such cases, the dependence analysis fails to compute exact dependence distances or directions, yielding a "confused" or incomplete dependence result with zero levels of information. The loop interchange transformation incorrectly handles this lack of information by padding the missing levels in the dependence vector with "independent" markers.

Because the dependence is treated as completely independent across the loop iterations, the legality check mistakenly concludes that there are no loop-carried dependencies preventing the transformation. This causes the compiler to perform an unsafe loop interchange. The illegal transformation can violate actual memory dependencies (e.g., reading and writing to overlapping memory regions in the wrong order) or alter the execution order of non-associative operations (such as floating-point reductions), ultimately resulting in a miscompilation.

---

# Issue 148228

## Loop Interchange with Integer Reductions Retaining No-Wrap Flags

**Description**:
The bug is triggered when a nested loop contains an integer reduction operation (such as addition or multiplication) that is marked with no-wrap flags (e.g., `nsw` for no signed wrap, or `nuw` for no unsigned wrap). These flags assert that the reduction operations will not overflow when executed in their original order.

When the loop interchange optimization swaps the inner and outer loops, it fundamentally alters the evaluation order of the reduction. While the final mathematical result of the reduction might remain the same, the intermediate values calculated during the reordered execution can differ significantly and may cause an integer overflow that did not occur in the original loop structure.

The incorrect transformation logic lies in the optimization's failure to strip these no-wrap flags during the interchange process. By preserving the `nsw` or `nuw` flags on the reduction instructions after changing their execution order, the compiler incorrectly assumes that the new sequence of operations is also guaranteed not to overflow. This false assumption introduces undefined behavior or poison values, leading to subsequent miscompilations when other optimization passes rely on these invalid flags.
