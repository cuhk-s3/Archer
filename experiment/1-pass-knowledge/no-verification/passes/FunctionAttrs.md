# Issue 63936

## Incorrect Memory Attribute Deduction for Intra-SCC Calls with Non-Argument Pointers

**Description**:
The bug is triggered by a specific pattern involving recursive functions or functions within the same Strongly Connected Component (SCC) that manipulate memory through pointer arguments. The strategy to trigger this issue involves the following steps:

1. **Define an SCC with Argument Memory Accesses**: Create a function (or a group of mutually recursive functions) that reads or writes memory through its pointer arguments.
2. **Perform an Intra-SCC Call**: Inside this function, insert a call to a function within the same SCC (e.g., a direct recursive call).
3. **Pass a Non-Argument Pointer**: Pass a pointer to this intra-SCC call that does *not* originate from the caller's own arguments. For example, pass a pointer that was loaded from memory, derived from a global variable, or created via a local allocation.
4. **Trigger the Analysis Flaw**: The interprocedural memory attribute analysis optimistically ignores the memory effects of calls within the same SCC, assuming their effects are strictly bounded by the overall effects of the SCC being computed.
5. **Miscompilation**: Because the analysis ignores the intra-SCC call, it fails to account for the translation of memory locations between the caller and callee. Specifically, it misses the fact that an "argument memory" access in the callee actually corresponds to a "non-argument memory" access in the caller (since the passed pointer is not an argument of the caller). As a result, the compiler incorrectly deduces overly restrictive memory attributes (such as assuming the function *only* accesses argument memory), which can lead to aggressive and invalid optimizations later in the compilation pipeline.

---

# Issue 91177

## Incorrect `nonnull` Return Attribute Inference for Non-Inbounds Pointer Arithmetic

**Description**:
The bug is triggered when a function returns a pointer computed via non-inbounds pointer arithmetic (such as a `getelementptr` instruction without the `inbounds` keyword) derived from a known `nonnull` base pointer.

The compiler's attribute inference analysis incorrectly assumes that any pointer derived from a `nonnull` source pointer will inherently remain `nonnull`. It traces the returned pointer back to its source and, upon seeing a `nonnull` base, erroneously attaches the `nonnull` attribute to the function's return value.

However, this logic is flawed for non-inbounds pointer arithmetic. Without the `inbounds` restriction, pointer arithmetic operations are allowed to wrap around the address space or use negative offsets that can explicitly compute the null address (address zero). By returning the result of a non-inbounds pointer calculation, the compiler is tricked into making a false `nonnull` guarantee, which can lead to severe miscompilations when downstream optimization passes rely on this incorrect assumption to remove null checks or perform other aggressive transformations.
