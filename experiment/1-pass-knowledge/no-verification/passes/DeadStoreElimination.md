# Issue 115976

## Incorrect Preservation of Pointer Attributes when Shortening Memory Intrinsics

**Description**:
The bug can be triggered by constructing a specific sequence of memory operations that causes the compiler to shorten a memory intrinsic, while failing to update the associated pointer attributes. The strategy involves the following steps:

1. **Emit a Memory Intrinsic with Pointer Attributes**: Create a memory intrinsic (such as `llvm.memset`, `llvm.memcpy`, or `llvm.memmove`) where the destination pointer argument is decorated with attributes that provide specific memory guarantees, such as `dereferenceable`, `dereferenceable_or_null`, or `align`.
2. **Overwrite the Prefix of the Memory Region**: Immediately follow the memory intrinsic with one or more store instructions that completely overwrite the beginning (the prefix) of the memory region just modified by the intrinsic.
3. **Trigger Dead Store Elimination**: This pattern triggers dead store elimination (DSE) optimizations. Recognizing that the initial bytes written by the intrinsic are dead (since they are overwritten by the subsequent stores), the compiler optimizes the intrinsic by shortening it. This involves advancing the intrinsic's base pointer forward by a certain offset and reducing the total length of the memory operation.
4. **Attribute Miscompilation**: The bug manifests during this transformation. The optimization incorrectly preserves the original pointer attributes on the newly offset pointer. For example, if the original pointer was marked as `dereferenceable(100)`, the new pointer (which has been advanced by an offset) will also be marked as `dereferenceable(100)`. This over-promises the safe memory bounds or violates alignment guarantees, introducing undefined behavior into the IR.

---

# Issue 126181

## Incorrect Dead Store Elimination due to `initializes` Attribute on `byval` Arguments

**Description**:
The bug is triggered by a specific interaction between the `byval` and `initializes` attributes during the Dead Store Elimination (DSE) pass. The pattern involves the following sequence:

1. A caller function performs a store operation to a specific memory location.
2. The caller then passes a pointer to this memory location as an argument to a callee function.
3. The corresponding parameter in the callee function is marked with both the `byval` attribute (indicating that the callee receives a private copy of the memory) and the `initializes` attribute (indicating that the callee writes to the specified memory range).

The miscompilation occurs because DSE misinterprets the scope of the `initializes` attribute. While `byval` guarantees that the callee only modifies its own local copy of the memory, DSE incorrectly assumes that the `initializes` attribute implies the callee will overwrite the caller's original memory. Consequently, DSE erroneously determines that the preceding store in the caller is dead (since it believes the call will overwrite it) and removes the store instruction. This leaves the caller's memory uninitialized or holding an incorrect value, leading to incorrect program behavior.

---

# Issue 52774

## Incorrect Dead Store Elimination for Loop-Variant Memory Allocations

**Description**:
The bug is triggered by a specific sequence of memory allocations and store instructions involving a loop. The pattern consists of the following elements:
1. A loop that contains a memory allocation instruction (such as `malloc` or other alloc-like functions), meaning a new memory location is allocated in each iteration.
2. A store instruction inside the loop that writes to the newly allocated memory.
3. A subsequent store instruction located outside (after) the loop, which writes to the memory allocated during the *final* iteration of the loop.

The compiler's Dead Store Elimination (DSE) pass incorrectly identifies the memory allocation as loop-invariant. It does this by merely checking if the base pointer comes from an allocation instruction, without verifying if the allocation actually resides outside the loop (e.g., in the function's entry block).

Because the compiler assumes the pointer refers to the exact same memory location across all loop iterations, it erroneously concludes that the post-loop store completely overwrites the in-loop store for *every* iteration. As a result, the compiler incorrectly eliminates the store inside the loop as a dead store. This leads to a miscompilation where the memory allocated in all but the last iteration remains uninitialized or retains incorrect values.

---

# Issue 70547

## Prematurely Ignoring Ephemeral Values in Pointer Capture Tracking

**Description:**
The bug occurs in the compiler's pointer capture tracking and alias analysis logic. When determining whether a pointer escapes (is captured), the analysis explores the uses of the pointer. Previously, the analysis was designed to ignore "ephemeral" values—instructions whose results are ultimately only used by assumption intrinsics (like `llvm.assume`)—under the premise that these instructions do not affect observable program behavior and will eventually be removed.

However, ignoring these ephemeral values prematurely leads to miscompilations. If an ephemeral instruction captures a pointer (for example, by passing it to a function call or storing it), ignoring it causes the capture tracking analysis to incorrectly conclude that the pointer does not escape.

Optimization passes, such as Dead Store Elimination (DSE), heavily rely on this analysis. If DSE is incorrectly informed that a pointer does not escape, it may aggressively eliminate stores to that memory location, assuming the memory is strictly local and the stores are dead. Because the ephemeral instructions are still present in the Intermediate Representation (IR) at this stage, they or other related instructions might still execute and access the memory. Since the necessary stores were incorrectly removed, this results in the program reading uninitialized or stale memory, leading to incorrect runtime behavior.

The core issue is that capture tracking must remain conservative and account for all uses of a pointer, including those in ephemeral instructions, as long as those instructions still exist in the IR.
