# Subsystem Knowledge for NewGVN
## Elements Frequently Missed

* **Restrictive Return Attributes**: Attributes such as `nonnull`, `range`, `align`, `dereferenceable`, and `noundef` attached to function calls or intrinsics are frequently overlooked during equivalence checking and value replacement.
* **Poison-Generating Semantics**: The optimization pass misses the fact that violating restrictive attributes causes the instruction to evaluate to `poison`. It fails to account for whether this `poison` is safely ignored in the original control flow.
* **Attribute Intersection and Stripping Logic**: The pass lacks or bypasses the necessary logic to intersect, drop, or reconcile incompatible attributes when replacing a dominated instruction with a dominating one.

## High-Level Patterns Not Well Handled

### Pattern 1: Asymmetric Attribute Propagation during Value Replacement
When the optimization pass identifies two identical function calls (or intrinsics) with the same arguments, it routinely replaces the dominated call with the dominating call to eliminate redundancy. However, it does not properly handle cases where the dominating call possesses more restrictive return attributes (e.g., `nonnull`) than the dominated call. By blindly substituting the value without stripping or intersecting the mismatched attributes, the pass forces the restrictive constraints onto the dominated context. If the runtime value violates these constraints, the optimized program incorrectly evaluates to `poison` in contexts where the original program would have evaluated to a well-defined value.

### Pattern 2: Unsafe Poison Leakage Across Control Flow
The optimization pass fails to respect the control-flow masking of `poison` values. In the original IR, a dominating call with restrictive attributes might evaluate to `poison` for certain inputs, but the program's control flow guarantees that this `poison` value is never actually consumed or is safely ignored (e.g., branching away before use). Meanwhile, a dominated call on a different control flow path lacks these attributes and safely processes the same inputs. When the pass replaces the dominated call with the dominating one, it leaks the `poison` value across basic blocks into a path where it is actively consumed. This results in a miscompilation where the optimized program is strictly more poisonous than the original source.
