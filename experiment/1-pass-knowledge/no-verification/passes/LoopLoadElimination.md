# Issue 160912

## Incorrect No-Wrap Assumption for Conditionally Dereferenced Pointers in Loop Analysis

The bug occurs in loop analysis passes (such as memory dependence analysis, loop vectorization, or load elimination) when evaluating pointer arithmetic instructions that carry no-wrap flags (e.g., `inbounds` or `nusw`).

The compiler uses these no-wrap flags to infer that the pointer address computation does not wrap around the address space, which is a crucial property for calculating strides and proving the absence of memory dependences across loop iterations. However, this inference is only sound if the pointer is guaranteed to be dereferenced (via a load or store) in every iteration of the loop. If a pointer wraps but is never actually dereferenced, it merely yields a poison value without causing immediate undefined behavior.

The bug is triggered when a loop contains a memory access that is executed conditionally (e.g., guarded by a branch or an `if` statement inside the loop), but the pointer used for the access is derived from an instruction with a no-wrap flag. The compiler incorrectly applies the no-wrap assumption globally to the entire loop, failing to account for the fact that the pointer might wrap during iterations where the conditional memory access is bypassed.

By falsely assuming the pointer never wraps under any circumstance, the compiler's dependence analysis may incorrectly conclude that memory accesses do not overlap or have safe dependence distances. This flawed analysis subsequently allows the compiler to perform invalid loop transformations, such as unsafe vectorization or incorrect load forwarding, leading to miscompilations.

---

# Issue 69744

## Incorrect Handling of Unknown Dependencies with Loop-Varying Underlying Objects

**Description**:
The bug is triggered when a loop contains indirect memory accesses where the base pointer or underlying object is loaded from memory inside the loop (i.e., the underlying object's address is loop-variant). Because the exact memory addresses accessed depend on values loaded during each iteration, the dependencies between these accesses across loop iterations are unknown at compile time.

When the compiler's loop access analysis encounters these unknown dependencies, it may attempt to resolve them by generating runtime memory dependence checks. However, generating runtime checks for memory accesses with loop-varying underlying objects is unsafe. The compiler cannot accurately determine the bounds of the accessed memory regions or the dependence distance, as the base pointers change dynamically across iterations. Consequently, the compiler either generates flawed runtime checks or incorrectly assumes the memory accesses are safe, leading to invalid loop optimizations such as erroneous vectorization or loop load elimination when the loop-varying pointers alias at runtime.
