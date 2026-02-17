## Elements Frequently Missed

*   **Alignment Constraints during Speculation**: The optimization pass frequently misses the verification of alignment attributes (`align N`) when hoisting memory access instructions (like `store`). It correctly identifies that the pointer is dereferenceable based on prior accesses but fails to check if the prior access guarantees the *same or stricter* alignment required by the instruction being hoisted.
*   **Attribute Compatibility between Dominating and Hoisted Instructions**: When using a dominating instruction (e.g., a `load` in a predecessor) to prove the safety of a speculative instruction (e.g., a `store` in a successor), the pass often misses checking if the attributes of the speculative instruction are compatible with the dominating one. It assumes existence implies total safety, ignoring specific constraints like alignment width.

## Patterns Not Well Handled

### Pattern 1: Speculative Hoisting of Stores with Strict Alignment
This pattern occurs when SimplifyCFG attempts to flatten control flow by hoisting a `store` instruction from a conditional block (e.g., `if.then`) into an unconditional predecessor block. The optimizer attempts to justify this speculation by finding a prior memory access to the same pointer in the predecessor.
*   **The Issue**: The optimizer treats "proof of dereferenceability" (the pointer is valid) as sufficient for "proof of safety" for the specific instruction being hoisted.
*   **Why it is not well handled**: The logic fails to account for the fact that the conditional store might have a stricter alignment requirement (e.g., `align 4`) than the proving instruction (e.g., `align 1`). By hoisting the stricter store unconditionally, the optimizer introduces Undefined Behavior on paths where the pointer is valid but not sufficiently aligned, a constraint that was originally protected by the control flow.