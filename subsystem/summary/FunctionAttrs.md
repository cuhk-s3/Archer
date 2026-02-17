# Subsystem Knowledge for FunctionAttrs

## Elements Frequently Missed

*   **The `inbounds` keyword on `getelementptr` instructions**: The analysis frequently overlooks the absence of the `inbounds` keyword. It assumes that pointer arithmetic based on a non-null pointer yields a non-null result, failing to account for the fact that standard (non-inbounds) pointer arithmetic can wrap or offset to null.
*   **Specific operands passed to recursive calls**: During interprocedural analysis of Strongly Connected Components (SCCs), the specific values passed as arguments to recursive calls are often missed. The analyzer tends to look at the function body's general behavior but ignores that passing a global variable or non-argument pointer to a recursive instance changes the memory footprint of the call.
*   **Distinction between "Callee Arguments" and "Caller Arguments"**: The optimization pass frequently conflates the abstract concept of "accessing arguments" with accessing the specific arguments of the entry function. It misses that when a function calls itself with a global variable, the callee is accessing *its* argument, but the caller is effectively accessing that global variable.

## Patterns Not Well Handled

### Pattern 1: Context-Insensitive Memory Effect Inference in Recursive SCCs
The optimization pass struggles with accurately deducing memory attributes (like `argmemonly`) for functions involved in recursion (SCCs). The pattern involves a function that generally only accesses its arguments but makes a recursive call passing a pointer that is *not* one of its own arguments (e.g., a global variable or a locally allocated pointer).
*   **Issue**: The analyzer optimistically ignores the recursive call, assuming the callee's behavior is consistent with the properties being deduced. It fails to realize that the recursive call acts as a transitive access. If `Function A` writes to its argument, and `Function A` calls `Function A(@Global)`, the execution results in a write to `@Global`.
*   **Why it is not well handled**: The logic assumes that if a function is `argmemonly`, recursive calls to it are safe. It fails to perform the necessary context-sensitive check to verify that the arguments passed to the recursive call are actually derived from the caller's arguments.

### Pattern 2: Unsafe Attribute Propagation through Pointer Arithmetic
The optimization pass exhibits flaws when propagating attributes (specifically `nonnull`) from operands to the results of pointer arithmetic instructions. This pattern involves a function taking a `nonnull` pointer and performing address calculations using `getelementptr` before returning the result.
*   **Issue**: The compiler infers that because the base is `nonnull`, the result is `nonnull`. This is only mathematically guaranteed if the `inbounds` keyword is present. Without `inbounds`, negative offsets or overflows can result in a null pointer.
*   **Why it is not well handled**: The analysis relies on a simplified model of pointer arithmetic that presumes validity and non-wrapping behavior, neglecting the strict semantic requirements (presence of `inbounds`) necessary to guarantee that the non-null property is preserved.