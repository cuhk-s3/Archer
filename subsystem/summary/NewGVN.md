# Subsystem Knowledge for NewGVN

## Elements Frequently Missed

* **Restrictive Return Attributes**: Attributes attached to function calls or intrinsics, such as `nonnull`, `range`, `align`, `dereferenceable`, and `noundef`. The optimization pass frequently misses the need to evaluate whether these attributes are strictly compatible before substituting one call for another.
* **Poison-Generating Semantics**: The implicit `poison` values generated when restrictive attributes are violated at runtime. The pass misses the fact that these attributes can turn an otherwise well-defined value into `poison` for specific inputs.
* **Attribute Intersection and Stripping Logic**: The necessary reconciliation mechanisms required during instruction replacement. The pass frequently misses the step of dropping or intersecting incompatible attributes (e.g., removing `nonnull` from the dominating call if the replaced dominated call does not possess it) to ensure the resulting value is not more restrictive than the original.

## Patterns Not Well Handled

### Pattern 1: Value Replacement with Asymmetric Call Attributes
This pattern occurs when the optimization pass identifies two identical function calls (same callee and arguments) as equivalent and replaces the dominated call with the dominating call, but the two calls possess asymmetric return attributes. For example, the dominating call might be marked `nonnull` while the dominated call is not. 
**Issues Caused:** By blindly replacing the dominated call without stripping the restrictive attributes from the dominating call, the pass forces the restrictive semantics onto the dominated call's uses. If the value violates the attribute (e.g., a null pointer is returned), it evaluates to `poison` in contexts where it was originally well-defined.
**Why it is not well handled:** NewGVN's equivalence checking focuses primarily on the opcode, callee, and operands to establish value equivalence. It often overlooks the metadata and return attributes that dictate the strictness of the output value, assuming that identical inputs always yield universally interchangeable outputs without adjusting the attributes.

### Pattern 2: Control-Flow Dependent Poison Propagation
This pattern involves a dominating instruction that produces `poison` due to attribute violations for certain inputs, but the original program's control flow safely ignores or masks this `poison` (e.g., the `poison` value is never used or returned on that specific control flow path). A dominated instruction on a different path lacks these restrictive attributes and produces a well-defined value for the exact same inputs.
**Issues Caused:** When the dominated instruction is replaced by the dominating one, the `poison` value escapes its original safe context and flows into the dominated instruction's uses. This leads to a miscompilation where the optimized program is more poisonous than the original source.
**Why it is not well handled:** The optimization pass operates under the assumption that if two instructions compute the same value based on their inputs, the dominating instruction is universally safe to use in place of the dominated one. It fails to perform a control-flow-aware safety analysis regarding poison-generating attributes, neglecting the fact that a value might be conditionally poisonous and unsafe to propagate globally.