# Issue 139202

## Incorrect Vectorization due to 32-bit Truncation of 64-bit Pointer Offsets

**Description**:
The bug is triggered by a sequence of memory operations (such as loads or stores) that access memory using large offsets from a common base pointer. These offsets are large enough to require a 64-bit representation, exceeding the capacity of a standard 32-bit integer.

To trigger the miscompilation, the offsets are constructed such that their lower 32 bits form a contiguous sequence of memory addresses, spaced exactly by the size of the accessed elements (e.g., 0, 8, 16, 24 for 8-byte elements). However, the upper 32 bits of some offsets are non-zero, meaning the actual memory locations are widely separated and strictly non-contiguous.

When the compiler's vectorization analysis calculates the distances between these pointers to check for consecutive accesses, it incorrectly truncates the 64-bit pointer differences into 32-bit integers. Because of this truncation, the large, non-contiguous offsets are masked, and the compiler only sees the contiguous lower 32 bits. Deceived into believing that the memory accesses are strictly adjacent, the compiler erroneously combines the separate scalar memory operations into a single vector memory operation (e.g., a contiguous vector load or store). This results in a miscompilation where data is read from or written to incorrect memory locations.

---

# Issue 160912

## Incorrect No-Wrap Assumption for Conditionally Dereferenced Pointers in Loop Analysis

The bug occurs in loop analysis passes (such as memory dependence analysis, loop vectorization, or load elimination) when evaluating pointer arithmetic instructions that carry no-wrap flags (e.g., `inbounds` or `nusw`).

The compiler uses these no-wrap flags to infer that the pointer address computation does not wrap around the address space, which is a crucial property for calculating strides and proving the absence of memory dependences across loop iterations. However, this inference is only sound if the pointer is guaranteed to be dereferenced (via a load or store) in every iteration of the loop. If a pointer wraps but is never actually dereferenced, it merely yields a poison value without causing immediate undefined behavior.

The bug is triggered when a loop contains a memory access that is executed conditionally (e.g., guarded by a branch or an `if` statement inside the loop), but the pointer used for the access is derived from an instruction with a no-wrap flag. The compiler incorrectly applies the no-wrap assumption globally to the entire loop, failing to account for the fact that the pointer might wrap during iterations where the conditional memory access is bypassed.

By falsely assuming the pointer never wraps under any circumstance, the compiler's dependence analysis may incorrectly conclude that memory accesses do not overlap or have safe dependence distances. This flawed analysis subsequently allows the compiler to perform invalid loop transformations, such as unsafe vectorization or incorrect load forwarding, leading to miscompilations.

---

# Issue 57315

## Missing Loop Verification in Difference-Based Runtime Pointer Checks for Nested Loops

**Description**:
The bug is triggered by a specific pattern of memory accesses within nested loops, which leads to incorrect dependency analysis and missing runtime alias checks during loop optimizations like vectorization.

1. **IR Pattern**: Construct a nested loop structure containing multiple memory accesses in the innermost loop.
2. **Address Recurrence**: Configure the memory accesses such that one pointer's address is derived from the outer loop's induction variable (making it loop-invariant with respect to the inner loop), while another pointer's address is derived from the inner loop's induction variable. Ensure that these two memory regions can potentially alias or overlap at runtime.
3. **Optimization Trigger**: Invoke an optimization pass that relies on loop access analysis to generate runtime pointer checks (e.g., the Loop Vectorizer) on the innermost loop.
4. **Incorrect Transformation Logic**: During the analysis, the compiler attempts to create a difference-based runtime pointer check to ensure the memory accesses do not overlap. The logic assumes that the scalar evolution add-recurrence expressions for both pointers belong to the innermost loop being analyzed. However, it fails to explicitly verify this property.
5. **Miscompilation**: Because one pointer's recurrence actually belongs to the outer loop, the difference check logic evaluates the relationship between the pointers incorrectly. This flaw causes the compiler to silently drop or miscalculate the required runtime alias checks. Consequently, the optimization pass unsafely transforms the loop (e.g., by vectorizing it) without the necessary runtime guards, leading to incorrect program behavior when the memory regions actually overlap.

---

# Issue 69744

## Incorrect Handling of Unknown Dependencies with Loop-Varying Underlying Objects

**Description**:
The bug is triggered when a loop contains indirect memory accesses where the base pointer or underlying object is loaded from memory inside the loop (i.e., the underlying object's address is loop-variant). Because the exact memory addresses accessed depend on values loaded during each iteration, the dependencies between these accesses across loop iterations are unknown at compile time.

When the compiler's loop access analysis encounters these unknown dependencies, it may attempt to resolve them by generating runtime memory dependence checks. However, generating runtime checks for memory accesses with loop-varying underlying objects is unsafe. The compiler cannot accurately determine the bounds of the accessed memory regions or the dependence distance, as the base pointers change dynamically across iterations. Consequently, the compiler either generates flawed runtime checks or incorrectly assumes the memory accesses are safe, leading to invalid loop optimizations such as erroneous vectorization or loop load elimination when the loop-varying pointers alias at runtime.

---

# Issue 79137

## Iteration-Local Scoped Alias Metadata Used for Cross-Iteration Dependence Analysis

**Description:**
The bug is triggered when a loop contains memory accesses (loads or stores) annotated with scoped alias metadata (such as `!alias.scope` and `!noalias`), and the corresponding alias scopes are explicitly declared *inside* the loop body (e.g., via scope declaration intrinsics).

Because these alias scopes are declared within the loop, their non-aliasing guarantees are strictly iteration-local; they only assert that the annotated memory accesses do not alias within the execution of a *single* loop iteration.

The incorrect transformation logic occurs during loop dependence analysis. The compiler attempts to analyze memory dependencies *across* different loop iterations (which is necessary for optimizations like loop vectorization). In doing so, it erroneously applies the iteration-local scoped alias metadata to cross-iteration memory accesses. This causes the compiler to incorrectly conclude that memory locations accessed in different iterations do not alias, masking true loop-carried dependencies and ultimately leading to illegal and unsafe loop transformations.
