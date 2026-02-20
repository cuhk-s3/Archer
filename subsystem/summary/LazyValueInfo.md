# Subsystem Knowledge for LazyValueInfo

## Elements Frequently Missed

* **`undef` Values**: The analysis frequently misses the semantic implication of `undef` values during constant range computation. Instead of treating `undef` as a full, unrestricted range (since it can represent any possible value of the given type at runtime), the analysis incorrectly ignores it or assumes it conforms to the ranges of other known values.
* **PHI Nodes with Mixed Incoming Values**: PHI nodes that merge strictly bounded values (e.g., zero-extended variables) with `undef` values are not handled safely. The analysis misses the need to conservatively expand the resulting range to the maximum possible bounds (a full range) when an `undef` operand is present.

## Patterns Not Well Handled

### Pattern 1: Incorrect Constant Range Union in PHI Nodes
When a PHI node merges control flow paths where one path provides a bounded value (such as a value produced by a `zext` instruction) and another path provides an `undef` value, LazyValueInfo attempts to compute the overall constant range of the PHI node. The analysis fails to properly union the bounded range with the unrestricted range of the `undef` value. Consequently, it infers an artificially narrow constant range for the PHI node, incorrectly assuming the `undef` value will safely fall within the bounds of the other incoming value.

### Pattern 2: Erroneous Elimination of Range-Dependent Operations
Because LazyValueInfo propagates an artificially narrow range for values derived from `undef`, subsequent optimization passes (such as Correlated Value Propagation) operate under false assumptions. When the optimized code contains range-dependent operations—such as bitwise masking (`and` instructions to clear upper bits), absolute value calculations, or bounds checks—the optimizer queries LazyValueInfo and determines these operations are redundant. The pattern of relying on flawed LVI ranges leads to the erroneous removal of these critical instructions, resulting in miscompilations since the `undef` value could evaluate to an out-of-bounds value at runtime.