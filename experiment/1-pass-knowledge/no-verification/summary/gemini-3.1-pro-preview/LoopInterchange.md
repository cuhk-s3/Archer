# Subsystem Knowledge for LoopInterchange
## Elements
 Frequently Missed

*   **Non-Strict Dependence Components (LE/GE
):** The legality checker fails to correctly decompose dependence vectors containing "Equal" components alongside directional components. It treats these as strictly
 directional, missing the reality that the dependence remains tied to the "Equal" loop level.
*   **Alias Analysis
 Confidence Levels:** When dependence analysis returns "MayAlias" or incomplete information, the pass fails to default to a conservative stance
. It incorrectly assumes independence where uncertainty exists, missing the requirement to prove safety before interchanging.
*   **Instruction Flags (
`nsw`/`nuw`):** The pass treats loop-carried reductions as mathematically invariant transformations without accounting for the semantic contract
 of integer overflow flags. It fails to strip these flags, missing that the reordering changes the intermediate values, rendering the original
 overflow guarantees invalid.
*   **Memory Dimension Mapping:** The pass fails to account for cases where the loop nest depth is greater
 than the array access dimensions, missing the potential for hidden dependencies across higher-order loops.

## Patterns Not Well Handled

###
 Pattern 1: Dependence Approximation and Over-Simplification
The optimization pass relies on a reductionist approach to dependence vectors. In
 multi-level loop nests, the logic transforms complex, multi-dimensional dependencies into simplified binary representations. By collapsing non-strict (
LE/GE) directions into strict direction markers during legality checks, the compiler discards the crucial "Equal" component that prevents
 illegal reordering. This pattern indicates a systemic failure to perform a complete "Worst-Case Scenario" check when dependence vectors
 are ambiguous.

### Pattern 2: Assumption of Order-Invariance for Operations with Semantics
The pass assumes
 that if an operation (like a reduction) is associative, its execution order can be freely modified. It fails to account for instructions
 that carry metadata (e.g., `nsw`, `nuw`) which are order-dependent. This pattern highlights
 that the optimization treats IR as a pure mathematical expression rather than an ordered sequence of operations with strict overflow constraints, failing to validate
 whether the metadata still holds true after the iteration space is transformed.

### Pattern 3: Optimistic Legality under
 Alias Ambiguity
The pass exhibits an "optimistic" legality check pattern where it interprets the absence of explicit, prov
able dependence as evidence of independence. When alias analysis or dependence calculation cannot determine an exact distance (due to pointer aliasing
 or misaligned loop/array dimensionality), the pass incorrectly treats the loop iterations as parallel. This pattern suggests that the pass lacks a robust fallback mechanism
 to inhibit transformation when the dependence information is "confused" or incomplete, prioritizing aggressive transformation over correctness.
