# Subsystem Knowledge for LoopVectorize

## Elements Frequently Missed

*   **Poison-Generating Operands in Speculated Chains**: The optimization pass frequently misses that while a memory location might be safe to access (dereferenceable), the *computation chain* used to derive its address may involve `poison` values (e.g., from PHI nodes merging valid pointers with `poison` on non-taken paths). Speculating these chains unconditionally leads to Undefined Behavior.
*   **Scalar-Only Users of Vector Plans**: The pass often overlooks scenarios where a recipe initially planned for vectorization (like a Pointer Induction) ends up having *only* scalar users due to Dead Code Elimination (DCE). The code generator fails to handle the absence of vector users, leading to crashes or assertion failures.
*   **Uniform or Loop-Invariant Operands in Complex Constructs**: The optimizer struggles to correctly identify or handle operands that are uniform (invariant) across vector lanes when they appear in complex constructs like function calls or First-Order Recurrences. This leads to unnecessary widening or degenerate PHI nodes that violate SSA rules.
*   **Scalar Vector Factors (VF=1) with Interleaving**: Specific logic required for handling loops that are interleaved but not widened (VF=1) is frequently missed. This includes missing logic for selecting exit values from specific lanes and incorrect application of vector transformations (like cast widening) to scalar instructions.
*   **Forced Scalar Constraints**: The cost model frequently misses or ignores "forced scalar" decisions made by the VPlan (e.g., for uniform calls), leading to a divergence where the cost model assumes vectorization is possible/profitable while the plan requires scalarization.

## Patterns Not Well Handled

### Pattern 1: Inconsistency Between Cost Model and VPlan Lowering
The optimization pass exhibits a fragile synchronization between the legacy Cost Model (which decides *if* and *how* to vectorize) and the VPlan (which executes the transformation). Bugs arise when the Cost Model makes assumptions (e.g., "this call can be widened") that contradict constraints discovered during VPlan construction (e.g., "this call must be scalar due to uniformity"). Similarly, if VPlan optimizations (like DCE) change the state of the graph (e.g., removing all vector users of an induction), the lowering phase often fails to adapt, asserting that vector values must exist when they are no longer needed.

### Pattern 2: Handling of Scalar-Interleaved Loops (VF=1)
The Loop Vectorizer treats the configuration of `VF=1` (Scalar) combined with `Interleave Count > 1` as a second-class citizen. High-level patterns that work for `VF > 1` are often blindly applied to `VF=1` or entirely omitted.
*   **Omission:** Logic to select the correct live-out value from an early exit is often guarded by `if (VF > 1)`, causing interleaved scalar loops to return incorrect results.
*   **Incorrect Application:** Optimization recipes (like simplifying cast sequences) may replace a scalar recipe (`VPReplicateRecipe`) with a widened vector recipe, ignoring that the context is explicitly scalar, resulting in invalid IR where vector operations are forced into scalar data flows.

### Pattern 3: Unsafe Speculation of Conditional Logic
The vectorizer aggressively attempts to linearize control flow by speculating instructions (moving them from conditional blocks to unconditional blocks). The pattern of checking only the *terminal* instruction's safety (e.g., "is this load safe?") is insufficient. The optimizer fails to verify the transitive safety of the *operand chain*. If the address computation depends on control flow (via PHIs) that produces `poison` on false paths, hoisting the computation exposes the program to Undefined Behavior, even if the load itself targets valid memory.

### Pattern 4: Degenerate First-Order Recurrences
The pass handles standard recurrences well but fails when the recurrence is trivial or degenerate. Specifically, when the initial value (incoming from preheader) and the update value (incoming from backedge) are identical, the recurrence is effectively a loop-invariant value. The vectorizer fails to simplify this pattern, instead constructing a full recurrence cycle with PHI nodes. Because the inputs are identical, this results in degenerate PHI structures that confuse the code generator and violate SSA dominance rules during the final IR construction.