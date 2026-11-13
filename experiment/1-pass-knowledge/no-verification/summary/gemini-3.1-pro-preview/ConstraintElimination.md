# Subsystem Knowledge for ConstraintElimination
## Elements
 Frequently Missed

*   **Instruction Flags (e.g., `dis
joint`, `nuw`, `nsw`)**: The pass often ignores the semantic requirements imposed by these flags. It treats operations
 as if they were simple mathematical operators, forgetting that these flags introduce conditions (like "no common bits" or "no overflow
") that can be violated if operands are replaced or simplified in isolation.
*   **Contextual Poison Sensitivity**: The pass fails to check
 whether an instruction's result is "poison" before incorporating it into the constraint system. It assumes that if an instruction
 exists, its result is valid, ignoring that optimization flags can convert otherwise valid values into poison.
*   **Bit
-Width Discrepancies**: The pass uses a fixed-width internal representation (usually 64-bit)
 for linear algebra decomposition. It misses the necessity of checking whether the bit-width of the actual IR values exceeds this internal
 capacity, leading to silent overflows and invalid mathematical models.
*   **Loop Invariance of Bounds**: The pass often assumes that
 once a constraint (like `i < N`) is established for a loop, it remains valid for all iterations, failing to verify that `N
` is actually loop-invariant.

## High-Level Patterns Not Well Handled

### Pattern 1: Optimistic Constraint
 Modeling via Mathematical Decomposition
The pass attempts to map complex IR sequences into a linear system of equations. This pattern fails when the source IR
 contains operations whose algebraic properties (overflow, wrapping) do not map 1:1 to the internal linear model. Because
 the pass prioritizes global constraint solving over local validity, it builds models that "work" mathematically but are semantically incorrect due
 to integer truncation or wrapping that the compiler's internal solver does not account for.

### Pattern 2: Context-
Unaware Operand Substitution
This pattern occurs when the pass identifies an implied relationship between two operands of a logical or arithmetic instruction and attempts to simplify one
 based on the other. It fails because it performs "short-circuit" style simplifications in place without re-evaluating the parent instruction
's flags. This violates the "contract" established by flags like `disjoint`, creating a state where the instruction
's semantics are fundamentally altered in a way that generates poison or undefined behavior under specific input conditions.

### Pattern 3
: Unconditional Fact Inference from Potentially Poisonous Intrinsics
The pass treats intrinsics (like `smin
`/`umax`) as pure mathematical operators. It unconditionally adds constraints (e.g., `result <= operand`) to its
 system. This is a flaw because the pass fails to perform a "poison-reachability" check. By introducing these facts,
 the pass forces the constraint solver to assume properties about inputs that might never have been executed or observed in the original program, effectively
 "inventing" constraints that lead to erroneous branch elimination or constant folding.
