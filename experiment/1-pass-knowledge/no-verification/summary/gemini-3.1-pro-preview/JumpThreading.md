# Subsystem Knowledge for JumpThreading
## Elements Frequently Missed

* **Dominator Tree Synchronization**: The optimization pass frequently misses updating or recalculating the Dominator Tree immediately after altering the Control Flow Graph (CFG). It proceeds to make further analysis queries while the dominance information is temporarily out of sync with the actual CFG.
* **Implicit Analysis Dependencies**: The pass misses the implicit dependency that Alias Analysis (AA) has on an up-to-date Dominator Tree. It fails to account for the fact that AA uses dominance relationships to evaluate contextual assumptions, check cycles, and decompose pointer expressions.
* **Intervening Clobbering Stores**: Memory writes (stores) that should invalidate previously loaded values are missed. Because the underlying alias queries return false negatives (`NoAlias`) due to stale dominance data, the pass fails to recognize that a memory location has been clobbered.

## Patterns Not Well Handled

### Pattern 1: Interleaving CFG Transformations with Memory Optimization Queries
This pattern occurs when the optimization pass performs structural changes to the CFG (such as threading jumps or duplicating basic blocks) and subsequently attempts to perform memory optimizations (like redundant load elimination) within the same pass iteration, without updating intermediate analysis structures.
**Why it is not well handled:** The pass assumes that analysis passes like Alias Analysis are safe to query at any point. However, because the CFG has changed, the cached Dominator Tree is stale. When the pass queries Alias Analysis to ensure memory safety, AA relies on this stale DomTree, leading to incorrect aliasing deductions and unsafe transformations.

### Pattern 2: Partially Redundant Load Elimination via Stale Value Routing
This pattern involves the pass attempting to eliminate a load instruction by proving it is partially redundant. The pass tries to reuse a previously loaded value by routing it through a PHI node to bypass the redundant load.
**Why it is not well handled:** To ensure this transformation is safe, the pass must verify that no intervening stores clobber the memory location. It relies on Alias Analysis for this verification. If the Dominator Tree is stale, Alias Analysis may incorrectly deduce that an intervening store does not alias the load's target address (`NoAlias`). Trusting this flawed result, the pass incorrectly eliminates the load and wires the PHI node to an outdated value, bypassing the actual memory update and causing a miscompilation.
