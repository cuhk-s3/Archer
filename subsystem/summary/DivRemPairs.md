# Subsystem Knowledge for DivRemPairs

## Elements Frequently Missed

* **Poison-Generating Flags (e.g., `exact`)**: The optimization pass frequently misses the presence of poison-generating flags on division instructions (`sdiv`, `udiv`). When these instructions are reused to compute other values, the pass fails to recognize that these flags restrict the domain of valid inputs.
* **Instruction Flag Sanitization (Stripping)**: The pass misses the necessary step of dropping flags (like `exact`) from an instruction when its result is repurposed for a new computation. Because the new computation (the remainder) does not guarantee the same strict conditions as the original division, failing to sanitize the reused instruction leads to poison propagation.
* **Execution Context and Definedness**: The pass misses the semantic difference in definedness between independent instructions. It assumes that if a division and remainder share the same operands, the division's result is always safe to use for the remainder, missing the fact that the division might be conditionally executed or conditionally valid based on later control flow or `select` instructions.

## Patterns Not Well Handled

### Pattern 1: Dependency Injection with Poison-Generating Flags
When the pass optimizes a remainder operation (`srem` or `urem`) by decomposing it into a sequence of arithmetic operations (`X - (X / Y) * Y`), it reuses an existing division instruction in the same basic block or function. If the original division instruction possesses poison-generating flags (such as `exact`), the pass fails to strip these flags during the transformation. Consequently, if the division is not exact at runtime, it evaluates to poison. Because the remainder computation is now artificially dependent on this division result, the poison propagates, improperly poisoning a previously well-defined remainder value.

### Pattern 2: Poison Propagation in Conditional Execution (Selects)
The pass does not well handle patterns where the division and remainder are used in mutually exclusive conditional contexts, such as within `select` instructions. In the original IR, a division might be safely marked `exact` because the program logic ensures it is only selected or used when the exactness condition holds. However, the remainder might be selected when the exactness condition does *not* hold. By making the remainder structurally dependent on the conditionally-exact division without stripping the flags, the pass forces the remainder to evaluate to poison under conditions where it should have been perfectly valid. This leads to miscompilations when the `select` instruction chooses the now-poisoned remainder path.