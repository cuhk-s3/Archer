# Subsystem Knowledge for FunctionAttrs
## Elements Frequently Missed

* **The `inbounds` Flag on `getelementptr` (GEP) Instructions**: The optimization pass frequently misses checking for the presence of the `inbounds` keyword during pointer arithmetic analysis. Without this flag, there is no guarantee that the resulting pointer remains within the bounds of the allocated object.
* **Pointer Wrap-Around Semantics**: The analysis overlooks the mathematical possibility that non-inbounds pointer arithmetic can use negative offsets or large positive offsets that wrap around the address space, explicitly computing the null address (address zero).
* **Loss of Pointer Attributes During Derivation**: The pass misses the principle that certain pointer attributes (like `nonnull`) are not strictly transitive through all forms of arithmetic. It fails to drop the `nonnull` assumption when the derivation path includes unsafe or unbounded operations.

## Patterns Not Well Handled

### Pattern 1: Attribute Propagation Through Non-Inbounds Pointer Arithmetic

**Description**:
The `FunctionAttrs` pass attempts to infer return attributes (such as `nonnull`) by tracing the data flow of a returned value back to its source. When the returned value is a pointer derived from a known `nonnull` base pointer (e.g., a function argument marked `nonnull`) via a `getelementptr` instruction, the pass assumes the derived pointer inherently retains the `nonnull` property.

**Issues Caused**:
Because the pass propagates the `nonnull` attribute without verifying the safety of the intermediate arithmetic, it can attach a `nonnull` return attribute to a function that might actually return a null pointer. This creates a false guarantee in the IR. Downstream optimization passes rely on this incorrect attribute to perform aggressive transformations, such as eliminating valid null checks, which ultimately leads to severe miscompilations and runtime crashes.

**Why it is Not Well Handled**:
The attribute inference logic is overly reliant on the properties of the base pointer and does not adequately evaluate the semantic-altering flags of the intermediate instructions. Specifically, it treats all `getelementptr` derivations as safe for `nonnull` propagation, failing to recognize that the absence of the `inbounds` keyword fundamentally changes the semantics of the operation, allowing for address space wrap-around and the computation of a null pointer.
