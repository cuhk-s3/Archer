# Subsystem Knowledge for InstructionSimplify

## Elements Frequently Missed

*   **Undef and Poison Refinement Rules**: The strict distinction between `undef` and `poison` is frequently overlooked. Replacing an `undef` value with a potentially `poison` value is an invalid refinement, as `poison` is a stronger state that triggers undefined behavior.
*   **Partial `undef` Lanes in Vector Constants**: When matching logical identities (like bitwise NOT via an XOR with all-ones), the presence of `undef` elements in vector constants is missed. These `undef` lanes break the strict logical identity required for the transformation.
*   **Pointer Provenance**: Pointers are often incorrectly treated as simple integer addresses. When pointers are compared for equality, the optimization misses that they may have different provenance (originating from different allocations), leading to invalid substitutions that break memory alias analysis.
*   **Cross-Lane Vector Operations**: Instructions that alter vector lane configurations, such as `bitcast` between vectors of different element sizes, are missed during per-lane equivalence tracking. This causes the compiler to incorrectly assume per-lane isolation when data is actually mixing across lanes.
*   **Semantics of `freeze` Instructions**: The core guarantee of `freeze`—that it resolves `poison` to an arbitrary but *consistent* value—is missed during context-dependent simplification. The pass incorrectly assumes it can replace the `freeze` with a specific concrete constant based on local control flow.
*   **Zero Edge Cases in Value Tracking**: When analyzing variables for mathematical properties (e.g., checking if a value is a power of two), the edge case where the value might be exactly zero is missed, leading to incorrect bitwise evaluations (e.g., assuming `X - 1` is a lower-bit mask when `X` could be `0`, resulting in `-1`).

## Patterns Not Well Handled

### Pattern 1: Context-Dependent Operand Substitution Based on Equality
The optimization pass frequently uses equality conditions (e.g., `icmp eq` driving a `select` instruction or a branch) to substitute one operand for another within the selected values. While mathematically sound for simple scalars, this pattern is poorly handled when the equivalence is not absolute across all contexts. 
*   **Pointers**: Substituting pointers based on address equality strips or alters provenance information, violating the memory model.
*   **Vectors with Casts**: Substituting vector operands based on element-wise equality fails if the def-use chain contains a `bitcast` that changes the lane count, as the operation ceases to be strictly per-lane.
*   **Frozen Poison**: Substituting a variable with a constant based on an equality check fails if that variable is derived from a `freeze` instruction. It forces the non-deterministic `freeze` to resolve to a specific constant, breaking the requirement that all uses observe the same arbitrary runtime value.

### Pattern 2: Eager Evaluation and Threading Over Conditional Constructs
The pass attempts to simplify code by threading operations over conditional constructs (like `select`) or by folding control-flow merges (like `phi` nodes) by ignoring "don't care" inputs such as `undef`. This pattern is not well handled because it ignores the dynamic masking provided by the control flow.
*   **Eager Poisoning**: Threading operations like division over a `select` causes the compiler to evaluate the division against all possible constant inputs independently. If one input is zero, it eagerly folds the operation to `poison`, even if that zero input would be dynamically masked out by the `select` condition.
*   **Invalid PHI Folding**: Folding a `phi` node to a common value `X` by ignoring incoming `undef` edges is invalid if `X` can evaluate to `poison`. This inadvertently propagates `poison` into control flow paths that originally safely yielded `undef`.

### Pattern 3: Applying Scalar Logical Identities to Vectors
The pass matches complex logical expressions against known simplification patterns (e.g., `(B ^ ~A) | (A & B) --> B ^ ~A`). This pattern is poorly handled when applied to vector types because the optimization logic assumes the entire vector behaves uniformly according to the scalar identity.
*   **Broken Identities**: If the constant vector used to form the identity (e.g., the all-ones vector for a bitwise NOT) contains `undef` lanes, the operation does not strictly behave as the matched identity for those specific lanes. The compiler applies the fold globally, resulting in a semantically inequivalent expression that evaluates incorrectly in the `undef` lanes.