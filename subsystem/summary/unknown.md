## Elements Frequently Missed

*   **Poison-Generating Flags (`nuw`, `nsw`, `exact`)**: Optimizers frequently overlook these flags during equivalence analysis (e.g., GVN). Treating instructions as congruent based solely on opcode and operands, while ignoring stricter wrap-around or exactness constraints, leads to the substitution of defined behavior with undefined behavior.
*   **`undef` Value Instability**: The semantic property of `undef`—that it can resolve to different concrete values for every distinct use—is often missed. Optimizations that duplicate operands (such as arithmetic expansions) without first `freeze`-ing the operand allow inconsistent values to propagate, breaking logical invariants.
*   **Instruction Metadata Constraints (`!range`)**: The dependency of metadata on specific input properties is frequently missed. Optimizers assume that metadata attached to an instruction (like value ranges) remains valid even if the instruction's operands are modified (e.g., by sinking a `freeze` instruction), leading to violations of the metadata's assertions.
*   **Lossy Operation Semantics**: The fact that certain intrinsics (like `fabs`) discard information is missed during value analysis. Optimizers incorrectly infer properties of the original operand (e.g., sign) based on the result of the lossy operation, leading to unsound simplifications downstream.

## Patterns Not Well Handled

### Pattern 1: Incorrect Congruence Identification in GVN
The optimization pass struggles to correctly handle congruence between instructions that differ only by poison-generating flags. When the optimizer identifies a "strict" instruction (one with `nuw` or `nsw`) as equivalent to a "loose" instruction (one without flags) and replaces the loose one with the strict one, it introduces undefined behavior in cases where the operation would originally have wrapped safely. The pattern of hashing or comparing instructions often fails to include these flags as differentiating factors.

### Pattern 2: Unsound Expansion of Operations with `undef` Operands
When expanding complex arithmetic operations (like `urem` with a constant divisor) into sequences of simpler instructions (like `icmp` and `select`), the optimizer fails to handle `undef` operands correctly. By duplicating the operand in the expanded code—using it once for the condition and once for the value—the optimizer creates a scenario where `undef` resolves differently in each branch. This pattern requires explicit `freeze` instructions to ensure consistency, which are currently omitted.

### Pattern 3: Reverse Property Inference through Non-Invertible Intrinsics
The optimizer incorrectly attempts to infer properties of an input operand based on comparisons involving the output of a non-invertible intrinsic. Specifically, seeing a condition like `fabs(x) > 0` leads the compiler to assume `x > 0`. This pattern fails because the intrinsic (`fabs`) destroys the sign bit, making it impossible to deduce the specific sign of the input. This false inference propagates through the IR, causing valid code (handling negative numbers) to be optimized away.

### Pattern 4: Invalid Code Motion of `freeze` Relative to Metadata
The optimization pass mishandles the movement of `freeze` instructions across operations that carry range metadata. Transforming `freeze(op(x))` into `op(freeze(x))` is treated as a valid sink, but it ignores that `op` may have `!range` metadata derived from the assumption that `x` is not poison. When `freeze(x)` converts poison into an arbitrary concrete value, that value may produce a result in `op` that violates the original metadata, leading to immediate undefined behavior.