# Subsystem Knowledge for SCCPSolver
## Elements Frequently Missed

* **Original Instruction Types (Vector Types)**: The optimization pass frequently misses the distinction between the original instruction's vector type and the scalar element type. While it correctly tracks the constant range of the scalar elements, it forgets to enforce the original vector type when materializing the final constant.
* **Vector Splat Materialization**: The pass misses the requirement to generate a vector splat constant (e.g., `ConstantVector` or `ConstantDataVector`) when replacing a vector instruction. It incorrectly assumes a scalar constant is sufficient if the constant range resolves to a single value.

## Patterns Not Well Handled

### Pattern 1: Materialization of Vector Constants from Scalar Ranges
When the SCCPSolver evaluates a vector instruction and determines that all of its elements will evaluate to the exact same constant value, it tracks this state using a constant range based on the scalar element type. However, when the analysis concludes that the range contains only a single value, the transformation phase attempts to replace the original vector instruction with a materialized scalar constant instead of a vector splat constant.

This pattern is not well handled because the solver's lattice and constant range evaluation abstracts away the vector shape to analyze the underlying element values. When transitioning from the analysis phase (which correctly identifies the single scalar value) to the transformation phase (replacing the instruction), the pass fails to reconstruct the original vector shape. This causes a severe type mismatch in the LLVM IR (replacing a vector value with a scalar value), leading to invalid intermediate representation and subsequent compiler crashes or assertion failures.
