# Subsystem Knowledge for PassManagerBuilder
## Elements
 Frequently Missed

*   **Step/Update Instructions of Induction Variables**: Optimization
 passes often focus on the PHI node as the definition point of an induction variable. They frequently miss that the increment/
step instruction (e.g., `add` or `ptrtoint`) often acts as a secondary definition point that
 holds the "next" value, which may be referenced by LCSSA PHI nodes at loop exit blocks.
*
   **External SSA Uses via LCSSA PHI Nodes**: Passes often verify if the loop-internal induction variable has uses
 outside the loop by only checking the PHI node's user list. They fail to identify that the loop exit'
s LCSSA PHI nodes may point to the step instruction, effectively creating a "hidden" dependency that escapes the loop scope.
*
**Induction Variable Liveness post-transformation**: When collapsing or flattening loops, passes often perform a simplified liveness check that assumes if
 the "induction variable" (the PHI) is not used, the induction variable is dead. This ignores the fact
 that other instructions in the update chain (the step instructions) might be required to reconstruct the final value in the flattened loop.

##
 High-Level Patterns Not Well Handled

### Pattern 1: Loop-Carried Dependency Escapes
This pattern occurs when a
 nested loop's inner induction variable is used outside the loop body after termination. In LLVM IR, the induction variable
 is defined by a PHI node at the header and updated by a step instruction. If an LCSSA PHI node at
 the exit block pulls the result from the *step instruction* instead of the *PHI node*, the optimization pass perceives the variable
 as local to the inner loop.

Because the pass only validates the PHI node's external use count, it falsely
 concludes that the inner loop's control logic is strictly internal. This leads to the aggressive removal of the backedge and
 the induction variable's logic. The failure to reconcile the data-flow dependency between the original step instruction and the new
 flattened induction variable results in the propagation of constant or incorrect initial values to the external use sites, causing silent miscompilation. The
 root cause is the pass's failure to perform a transitive closure analysis of all instructions involved in the loop-carried update chain before
 deciding that the loop metadata is safe to strip.
