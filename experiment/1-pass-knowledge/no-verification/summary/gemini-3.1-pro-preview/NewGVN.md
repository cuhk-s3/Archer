# Subsystem Knowledge for NewGVN
## Elements Frequently Missed

* **Return Attributes (`range`, `nonnull`, etc.)**: The optimization pass frequently misses the need to intersect or strip restrictive return attributes when replacing one function call or intrinsic with another. It overlooks the fact that these attributes can alter the poison-generating semantics of an instruction.
* **Reverse Post-Order (RPO) / Topological Indices**: RPO numbers and topological ordering constraints are missed or improperly weighted during the leader selection process within congruence classes, especially in the presence of complex control flow.
* **Poison Semantics and Control Flow Masking**: The pass misses the contextual safety of `poison` values. It fails to account for the fact that a dominating instruction might safely evaluate to `poison` because its uses are masked by control flow, whereas the dominated instruction requires a well-defined value.
* **Dominance Constraints in Leader Selection**: The strict requirement that a chosen representative value (leader) must dominate all the values it replaces is frequently missed when resolving congruence classes in cyclic graphs.

## Patterns Not Well Handled

### Pattern 1: Improper Attribute Reconciliation During Value Replacement
When NewGVN identifies two function calls or intrinsics as computing equivalent values (Common Subexpression Elimination), it replaces the dominated call with the dominating call. However, this pattern is not well handled because the pass fails to intersect or strip incompatible return attributes (such as `range` or `nonnull`) during the replacement.

**Issues Caused:** If the dominating call possesses more restrictive attributes than the dominated call, it may evaluate to `poison` for certain inputs. Because the pass blindly replaces the dominated call without dropping these restrictive attributes, the `poison` value leaks into the uses of the dominated call. This results in a miscompilation where the optimized program is more poisonous than the original source.

**Why it is not well handled:** The pass equates basic value equivalence with strict semantic equivalence. It focuses on the equivalence of the operands and the operation but overlooks the subtle, poison-generating differences introduced by function attributes and metadata, failing to apply a safe intersection of these properties.

### Pattern 2: Topologically Inverted Leader Selection in Congruence Classes
In programs with complex control flow, such as loops or unstructured jumps, NewGVN groups instructions that compute equivalent values into a single congruence class. To perform replacements, it selects a representative instruction called the "leader." This pattern is poorly handled when the pass selects a leader that has a higher Reverse Post-Order (RPO) number—meaning it appears later in the control flow—than the instructions it is supposed to replace.

**Issues Caused:** Selecting a leader that appears later in the control flow violates the topological ordering of dependencies. This inversion creates a cyclic dependency during symbolic evaluation or value replacement. As a result, the analysis fails to stabilize, leading to either compiler non-termination (infinite loops during the optimization phase) or miscompilation due to incorrect value replacements.

**Why it is not well handled:** The leader selection heuristic in the congruence class resolution phase does not strictly enforce dominance or topological ordering (RPO) constraints. In cyclic graphs, the value numbering algorithm's optimistic assumptions can temporarily group instructions in ways that break topological invariants, and the pass lacks robust safeguards to prevent a later instruction from being chosen as the canonical representative for earlier ones.
