# Issue 160912

## Incorrect No-Wrap Assumption for Conditionally Dereferenced Pointers in Loop Analysis

The bug occurs in loop analysis passes (such as memory dependence analysis, loop vectorization, or load elimination) when evaluating pointer arithmetic instructions that carry no-wrap flags (e.g., `inbounds` or `nusw`).

The compiler uses these no-wrap flags to infer that the pointer address computation does not wrap around the address space, which is a crucial property for calculating strides and proving the absence of memory dependences across loop iterations. However, this inference is only sound if the pointer is guaranteed to be dereferenced (via a load or store) in every iteration of the loop. If a pointer wraps but is never actually dereferenced, it merely yields a poison value without causing immediate undefined behavior.

The bug is triggered when a loop contains a memory access that is executed conditionally (e.g., guarded by a branch or an `if` statement inside the loop), but the pointer used for the access is derived from an instruction with a no-wrap flag. The compiler incorrectly applies the no-wrap assumption globally to the entire loop, failing to account for the fact that the pointer might wrap during iterations where the conditional memory access is bypassed.

By falsely assuming the pointer never wraps under any circumstance, the compiler's dependence analysis may incorrectly conclude that memory accesses do not overlap or have safe dependence distances. This flawed analysis subsequently allows the compiler to perform invalid loop transformations, such as unsafe vectorization or incorrect load forwarding, leading to miscompilations.

---

# Issue 47927

## Incorrect Type Shrinking of Instructions with Incompatible Operands During Vectorization

**Description:**
The bug is triggered by a pattern where an instruction's result is eventually truncated to a narrower type within a loop. During loop vectorization, the compiler analyzes the demanded bits and attempts to optimize the loop by shrinking the bit width of operations to match the narrower type.

However, the compiler's analysis fails to verify whether the operands of the instruction can be safely evaluated in this reduced bit width. This leads to miscompilations in cases where the operands require the original, wider type to maintain correct semantics.

A primary example of this is a shift operation where the constant shift amount is greater than or equal to the new, narrower bit width. When the compiler forces the operation into the smaller type, the shift amount exceeds the type's bit width, resulting in undefined behavior, poison values, or incorrect results (such as evaluating to zero instead of the correct value). More generally, if any operand demands more bits than the chosen minimum bit width, evaluating the instruction in the narrower type alters the program's semantics and leads to incorrect computation.

---

# Issue 63602

## Incorrect Hoisting of Interleaved Loads Across Conflicting Stores

The bug is triggered by a specific sequence of memory operations within a loop that are candidates for vectorization via interleaved memory accesses. The Loop Vectorizer analyzes memory accesses in a bottom-up program order to group strided loads into wide, interleaved vector loads.

The problematic pattern involves the following sequence of instructions in program order:
1. An earlier load instruction (`Load C`).
2. A store instruction (`Store A`).
3. A later load instruction (`Load B`) that has a read-after-write (RAW) memory dependence on the store (i.e., it reads from a memory location written to by the store).

During the bottom-up interleaved access analysis, the compiler tracks active load groups. When the analysis processes `Load B`, it becomes part of an active interleave group. As the analysis continues scanning upwards, it encounters `Store A` and correctly detects the memory dependence between `Store A` and `Load B`.

However, the flawed transformation logic fails to mark `Load B`'s interleave group as "complete" or closed to new members upon hitting this conflicting store. When the analysis continues further up and reaches `Load C`, it incorrectly determines that `Load C` shares a compatible stride with the active group containing `Load B` and adds it to the group.

This creates a critical issue during the actual vectorization phase. The compiler inserts the combined interleaved vector load instruction at the position of the earliest load in the group, which is `Load C`. Because `Load C` precedes `Store A` in program order, the entire interleaved load—including the read corresponding to `Load B`—is incorrectly hoisted above the conflicting `Store A`. This invalidates the read-after-write dependence, causing the vectorized load to read stale memory values (from before the store occurred) rather than the updated values, ultimately leading to a miscompilation.
