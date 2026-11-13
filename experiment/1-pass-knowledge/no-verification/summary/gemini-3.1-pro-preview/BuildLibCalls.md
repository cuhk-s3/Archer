# Subsystem Knowledge for BuildLibCalls
## Elements Frequently Missed

* **Parameter Attributes (e.g., `inreg`, `signext`, `zeroext`)**: When synthesizing new library calls, the optimization pass frequently misses applying target-specific or ABI-required parameter attributes to the newly created function declarations and call sites. This happens because the IR builder defaults to creating standard, unannotated function signatures, ignoring the strict ABI requirements of the target architecture.
* **Module-Level Calling Convention Metadata**: The pass often overlooks module-level flags or metadata that dictate specific calling conventions (such as passing a certain number of parameters in registers). The logic focuses on the high-level semantics of the C standard library rather than the low-level ABI configurations embedded in the module.
* **Call Site Attribute Synchronization**: When replacing an existing call with a new one, the pass misses the step of synchronizing or transferring relevant attributes from the original call site (or inferring them from the target data layout) to the newly generated `CallInst`.

## Patterns Not Well Handled

### Pattern 1: Libcall Replacement and Declaration Generation
When the compiler decides to replace an existing library call with a more optimal one (e.g., replacing a specific memory function with an equivalent one), it must generate a new function declaration if one does not already exist in the module. The optimization pass handles the semantic mapping well but fails to properly construct the ABI-compliant signature. By generating a bare-bones function declaration without the necessary parameter attributes (like `inreg`), it creates a calling convention mismatch between the newly generated call site and the actual compiled library function, leading to undefined behavior or runtime crashes.

### Pattern 2: ABI-Oblivious IR Synthesis
The optimization logic in `BuildLibCalls` operates primarily on the abstract semantics of standard C library functions. When it synthesizes new instructions and function prototypes, it assumes a default, generic calling convention. This pattern of "ABI-oblivious" IR generation is not well handled because it bypasses the target-specific ABI lowering rules. The pass fails to cross-reference the module's calling convention configurations or target data layout before finalizing the new `CallInst`, resulting in miscompiled code on architectures that require explicit parameter attributes for correct register allocation and argument passing.
