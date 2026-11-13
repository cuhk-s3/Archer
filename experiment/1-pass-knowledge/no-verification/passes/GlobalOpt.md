# Issue 58718

## Incorrect Removal of `inalloca` Attribute from Variadic Functions

**Description**:
The bug is triggered when an interprocedural optimization pass processes a variadic function (a function that accepts variable arguments) that uses the `inalloca` attribute on one of its parameters.

If the function's address is not taken and it lacks `musttail` callers, the optimization pass incorrectly assumes it is safe to strip the `inalloca` attribute from the function and its call sites. However, for variadic functions, variable arguments are inherently passed via the `inalloca` allocation. Removing the `inalloca` attribute breaks the calling convention because the variable arguments are not subsequently passed as separate, individual arguments. This leads to a miscompilation during the lowering phase, where the backend generates incorrect assembly (e.g., pushing the pointer as a standard argument instead of treating it as the pre-allocated argument block).

To trigger this issue at the LLVM IR level:
1. Define a variadic function (`...`) that takes an `inalloca` parameter.
2. Ensure the function's address is never taken and it is not called by any `musttail` call sites.
3. Call the function, passing an `inalloca` allocated value.
4. Run the interprocedural optimization pass (e.g., GlobalOpt). The pass will incorrectly remove the `inalloca` attribute, corrupting the varargs passing mechanism.

---

# Issue 81793

## Constant Folding of Loads from Memory with Padded Types

**Description**:
The bug is triggered when the compiler attempts to constant-fold a load instruction that reads from a memory location initialized or stored with a uniform constant (e.g., all ones) of a type that requires padding in memory. This occurs when a type's bit size is not equal to its store size (for example, an `i9` type which occupies 16 bits in memory).

In such cases, the padding bits are technically undefined or zero-extended by the backend. However, the optimization logic incorrectly assumes that the entire memory representation, including the padding bits, shares the same uniform pattern as the valid bits of the constant. Consequently, when a value is loaded from this memory location—especially on big-endian targets where the load might directly read the padding bits—the compiler erroneously folds the load into a uniform constant.

The strategy to trigger this miscompilation involves storing a uniform constant of a non-byte-aligned (padded) type and subsequently loading a value from that same memory location, causing the compiler to incorrectly evaluate the load based on the uninitialized or zeroed padding bits.
