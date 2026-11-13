# Subsystem Knowledge for PromoteMemoryToRegister
## Elements
 Frequently Missed

*   **Undef vs. Poison Distinction**: The pass fails to account
 for the semantic difference between reading uninitialized memory (`undef`) and propagating a `poison` value. It treats all "
missing" or "not yet defined" data as interchangeable, failing to recognize that `poison` triggers undefined behavior more aggressively than
`undef`.
*   **Path-Sensitivity in Control Flow**: The pass frequently assumes a global view of "single-
store" status without verifying that the store dominates all possible paths leading to a load. It overlooks the fact that a load may occur on a
 path that bypasses the single store entirely.
*   **Initialization Status of Allocations**: The promotion logic assumes that
 if an allocation has only one store, that store is the *defining* definition for all loads. It ignores the scenario
 where the memory might never be initialized on a specific execution path.

## Patterns Not Well Handled

### Pattern 1: Control
-Flow-Dependent Initialization Bypassing
This pattern occurs when an `alloca` is conditionally initialized. The promotion logic detects
 a single store (or a limited set of stores) and incorrectly assumes that this store reaches all subsequent loads. If the logic ignores control
-flow constraints, it replaces a load that might have executed on a non-initialized path with the value from the initialization
 path. This incorrectly elevates the semantics of uninitialized memory (which behaves as `undef`) to the semantics of the stored
 value (e.g., `poison`). The pass fails because it optimizes based on the *existence* of a store instruction
 rather than the *reachability* of that store from all entry points of the load.
