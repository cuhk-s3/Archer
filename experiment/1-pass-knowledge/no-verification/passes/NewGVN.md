# Issue 113997

## Miscompilation due to Improper Handling of Call Attributes during CSE/GVN

**Description:**
The bug occurs when Common Subexpression Elimination (CSE) or Global Value Numbering (GVN) optimizations replace a function call with a dominating equivalent call without properly reconciling their return attributes.

The bug triggering strategy involves the following sequence:
1. The program contains two identical function calls (or intrinsics) with the same arguments, making the dominated call a candidate for elimination.
2. The dominating call possesses more restrictive return attributes (such as `range` or `nonnull`) compared to the dominated call.
3. For specific inputs, the dominating call evaluates to `poison` because its restrictive attributes are violated. However, in the original program, this `poison` value is safely ignored or masked by the control flow.
4. The dominated call, which lacks these restrictive attributes (or has more relaxed ones), evaluates to a well-defined value for the same inputs.
5. The optimization pass replaces the dominated call with the dominating call but fails to intersect or strip the incompatible attributes.
6. As a result, the uses of the dominated call incorrectly receive the `poison` value from the dominating call, leading to a miscompilation where the optimized program is more poisonous than the original source.

---

# Issue 35683

## Cyclic Dependency in Value Numbering due to Incorrect Leader Selection

**Description**:
The bug is triggered by a pattern involving complex control flow (such as loops or unstructured jumps) where multiple instructions compute equivalent values and are grouped into the same congruence class by the Global Value Numbering (GVN) pass.

During this process, the optimization pass selects a representative instruction, known as the "leader," to replace other equivalent instructions within the class. The issue occurs when the selected leader is an instruction that appears later in the control flow (i.e., has a higher Reverse Post-Order or RPO number) than other members of the same class.

Because the leader is evaluated or processed after the instructions it is supposed to replace, it violates the topological ordering of dependencies. This inversion creates a cyclic dependency during symbolic evaluation or value replacement. Consequently, the analysis fails to stabilize correctly, leading to either miscompilation (incorrect value replacements that break the program's semantics) or non-termination (infinite loops) during the optimization phase.
