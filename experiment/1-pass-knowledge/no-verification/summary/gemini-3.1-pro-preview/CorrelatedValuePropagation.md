# Subsystem Knowledge for CorrelatedValuePropagation
## Elements Frequently Missed

* **`undef` Values in Range Analysis**: The optimization pass frequently misses the deferred evaluation nature of `undef`. Value tracking optimistically assigns a constrained value to `undef` to satisfy a predicate (e.g., assuming it is non-negative). However, it misses that if the constraining instruction is removed, the `undef` can later evaluate to any arbitrary value, violating the assumed constraint.
* **Intrinsic-Specific Semantic Flags (e.g., `is_int_min_poison`)**: The pass misses the implications of flags that define edge-case behaviors in intrinsics. For example, when `is_int_min_poison` is `false` on `llvm.abs`, the intrinsic has strict, well-defined behavior for all inputs. The pass fails to check these flags before making optimistic replacements based on `undef`.
* **PHI Nodes Merging `undef` with Constrained Values**: The pass frequently misses the unconstrained nature of `undef` when it is merged with known values (e.g., known non-negative integers) via a PHI node. The analysis improperly propagates the constrained range of the known incoming values to the entire PHI node result.

## Patterns Not Well Handled

### Pattern 1: Optimistic Simplification of Bounding Intrinsics with `undef` Operands
The optimization pass encounters an intrinsic that inherently bounds its output (such as `llvm.abs`, which guarantees a non-negative result or exactly `INT_MIN`). The operand provided to this intrinsic is a combination of known-range values and `undef` (often constructed via a PHI node). The pass optimistically assumes that the `undef` value will fall within the known, favorable range (e.g., non-negative) and decides to replace the intrinsic directly with its operand.

This pattern causes severe miscompilations because removing the intrinsic removes the structural guarantee of the bound. Once the intrinsic is replaced by the raw operand, subsequent compiler passes are free to evaluate the exposed `undef` to an arbitrary value outside the previously assumed range (e.g., a negative number). It is not well handled because the value tracking analysis is designed to treat `undef` optimistically to enable optimizations, but CVP fails to recognize that completely removing the bounding instruction expands the domain of possible future evaluations for the `undef` value.

### Pattern 2: Ignoring Poison-Generating Flags During Intrinsic Replacement
The pass attempts to replace an intrinsic with its operand (or a negated operand) based on inferred value ranges, but it fails to properly account for the intrinsic's poison-generating flags, such as `is_int_min_poison = false` on `llvm.abs`.

This causes issues because the flag dictates that the intrinsic has well-defined fallback behavior for edge cases (like returning `INT_MIN` instead of yielding poison). When the intrinsic is bypassed based on optimistic `undef` assumptions, these strict semantic guarantees are lost. This pattern is not well handled because the optimization logic focuses too heavily on the inferred range of the operand and neglects to validate whether the intrinsic's specific configuration permits a direct replacement. The pass fails to realize that when these strict semantic flags are present, it must conservatively treat `undef` as a full range rather than optimistically assigning it a constrained value.
