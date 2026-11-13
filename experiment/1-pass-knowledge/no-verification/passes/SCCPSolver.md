# Issue 63380

## Incorrect Scalarization of Vector Constants

The bug is triggered when a compiler optimization pass evaluates a vector instruction and determines that its result can be reduced to a constant. During the analysis, the pass tracks the possible values of the vector's elements using a constant range based on the scalar element type.

When the analysis concludes that the range contains only a single value (meaning all elements of the vector will have the same constant value), it attempts to replace the original vector instruction with a materialized constant. However, the pass incorrectly generates a scalar constant of the element type instead of a vector splat constant of the original vector type.

This replacement of a vector value with a scalar value introduces a severe type mismatch in the LLVM IR, leading to invalid intermediate representation and subsequent compiler crashes or assertion failures. The issue is not specific to any single intrinsic or operation, but rather applies generally to vector operations that the pass can successfully reduce to a single-element constant range.
