# Subsystem Knowledge for ConstantFold
## Elements Frequently Missed

* **Instruction Contexts**: The specific instruction context (e.g., the instruction pointer) is frequently missing or null during certain optimization passes. Without this context, the constant folder cannot access function-level attributes to determine the correct execution environment.
* **Vector Constants**: Edge-case handling logic (such as flushing denormal values) is often implemented exclusively for scalar floating-point types. Vector constants containing the exact same edge-case values frequently bypass these checks entirely.
* **Function-Level Floating-Point Attributes**: Attributes that dictate non-standard floating-point behavior, such as `"denormal-fp-math"="preserve-sign"` or flush-to-zero modes, are missed when evaluating vector types or when the instruction context is unavailable.
* **Denormal Floating-Point Values**: These specific floating-point values are frequently misclassified as standard non-zero values under strict IEEE 754 rules, missing the required target-specific or attribute-specific flush-to-zero runtime behaviors.

## Patterns Not Well Handled

### Pattern 1: Context-Free Constant Folding of Environment-Dependent Operations
Constant folding often attempts to evaluate floating-point operations without a valid instruction context. When the context is missing, the compiler cannot query function-specific attributes (like denormal handling modes). Instead of conservatively aborting the fold when the environment is unknown, the optimization pass incorrectly defaults to assuming strict IEEE behavior. This leads to a critical mismatch where the compiler preserves denormal values at compile-time, but the target hardware flushes them to zero at runtime, fundamentally altering the results of comparisons and binary operations.

### Pattern 2: Discrepancy Between Scalar and Vector Constant Handling
The optimization pass frequently fails to apply scalar edge-case logic to vector types. While the compiler correctly identifies and handles denormal flushing for scalar floating-point constants based on function attributes, it lacks the corresponding logic for vector constants. When an operation involves a vector of denormal values, the compiler bypasses the flush-to-zero logic and falls back to strict IEEE semantics. This results in vector operations being folded incorrectly (e.g., evaluating a denormal vector element as "not equal" to zero) even when the instruction context is fully available and explicitly specifies a non-IEEE denormal mode.
