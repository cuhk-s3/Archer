## Elements Frequently Missed

*   **Parameter Attributes Validation**: Specifically, the `readonly` attribute on function parameters. The optimization pass frequently misses the need to validate and strip restrictive memory attributes when the underlying memory usage pattern changes from read-only to mutable.
*   **`byval` Argument Semantics**: The pass overlooks the semantic contract implied by `byval` combined with `readonly`, assuming that because `byval` implies a local copy, it is always safe to write to it, ignoring the explicit immutability constraint provided by `readonly`.

## Patterns Not Well Handled

### Pattern 1: Reuse of Read-Only Stack Slots for Iterative Parameter Passing
When converting a tail-recursive function that accepts `byval` arguments into a loop, the optimization strategy involves reusing the stack memory allocated for the incoming argument to store the values for the next iteration. This pattern is not well handled when the argument is marked `readonly`. The optimization introduces explicit `store` instructions to the argument pointer to update the loop state, directly violating the `readonly` attribute. The pass fails to detect this conflict and does not remove the attribute, resulting in invalid IR where a pointer is defined as immutable but is modified within the function body.