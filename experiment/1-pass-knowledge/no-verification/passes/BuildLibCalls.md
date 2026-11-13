# Issue 53645

## Missing Parameter Attributes During Libcall Simplification

**Description:**
The bug is triggered when an optimization pass performs standard library call simplification or replacement (e.g., replacing a call to one memory function with another equivalent function). The sequence of events leading to the miscompilation is as follows:

1. A module is compiled with specific calling convention configurations or metadata that dictate how arguments should be passed (e.g., specifying that a certain number of parameters must be passed in registers, represented by parameter attributes like `inreg`).
2. During optimization, the compiler decides to replace an existing library call with a different, more optimal library call.
3. To facilitate this replacement, the compiler generates a new function declaration for the target library function.
4. The incorrect transformation logic fails to infer or apply the necessary parameter attributes (such as `inreg`) to the newly created function declaration based on the module's calling convention metadata.
5. Consequently, the newly generated call site lacks the required parameter attributes. This results in a calling convention mismatch between the caller (which expects the arguments to be passed according to the new, incorrect declaration) and the actual callee (which expects the arguments in registers), ultimately leading to runtime crashes or undefined behavior.
