# Subsystem Knowledge for SimplifyCFG
## Elements Frequently Missed

* **Context-Dependent Metadata and Attributes**: Metadata (such as `dereferenceable`, `align`, `range`, or `noundef`) and local assumptions attached to instructions are frequently mishandled. The optimization pass misses the fact that these properties are only guaranteed within the specific control-flow context of the original basic block and may become invalid if the instruction is moved to a dominating block.
* **Alignment Discrepancies in Memory Accesses**: The specific alignment values of memory operations are often overlooked during speculation. When using a dominating memory access to prove the safety of a conditional memory access, the pass misses checking if the conditional access has a stricter (higher) alignment requirement than the dominating one.
* **Target Insertion Point Context During Safety Checks**: The context of the new insertion point is frequently missed during safety evaluations. The pass evaluates the safety of an instruction (e.g., whether it is safe to speculatively execute) based on its original location rather than the dominating block it is being hoisted to, leading to false positives in safety checks.

## Patterns Not Well Handled

### Pattern 1: Speculative Hoisting of Memory Operations with Stricter Constraints
This pattern occurs when a conditionally executed memory operation (such as a store) is speculated and hoisted into a dominating block. The justification for this hoisting is typically the presence of a prior memory access (load or store) to the same pointer in the dominating block, which proves the pointer is generally safe to access.

**Issues Caused and Why It Is Not Well Handled**:
The pass assumes that if a pointer is safe to access in the dominating block, any subsequent access to that pointer is also safe to hoist unconditionally. However, it fails to properly handle cases where the conditional access has stricter constraints, specifically a higher alignment requirement. The higher alignment might only be valid when the branch condition is true. By hoisting the instruction without downgrading its alignment to match the dominating access, the pass introduces potential alignment faults, as the pointer is only unconditionally guaranteed to meet the lower alignment of the preceding access.

### Pattern 2: Context-Blind Instruction Speculation Based on Local Guarantees
This pattern involves a conditional basic block containing an instruction that establishes a local safety property (via metadata or local assumptions), followed by a dependent instruction (like a memory access) that relies on this property to be considered safe. The result of this dependent instruction is then used as an incoming value for a PHI node in a subsequent merge block.

**Issues Caused and Why It Is Not Well Handled**:
When SimplifyCFG attempts to simplify the control flow by folding the PHI node and eliminating the conditional branch, it tries to speculatively hoist the dependent instruction into the dominating predecessor block. The pass is not well-equipped to handle this because its safety check evaluates the dependent instruction in its *original* context. It incorrectly concludes that the instruction is safe to hoist based on the local metadata or assumptions. It fails to recognize that these local guarantees are tied to the original block's control flow and become invalid at the new insertion point. Consequently, the instruction is hoisted to a location where its safety guarantees no longer hold, leading to the unconditional execution of an unsafe operation and potential undefined behavior (e.g., a faulting memory access).
