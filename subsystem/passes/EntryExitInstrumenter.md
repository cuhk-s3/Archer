# Issue 50742

## Instrumentation of Functions with `available_externally` Linkage

**Description**: 
The bug is triggered when an instrumentation pass incorrectly processes functions that have `available_externally` linkage. In LLVM IR, the `available_externally` linkage type indicates that the function definition is provided for inlining and optimization purposes within the current module, but the compiler will not emit the function's body into the final object file. 

When the transformation logic applies instrumentation (such as inserting entry and exit hooks) to these functions, it often introduces references to the function itself, such as taking the function's address to pass as an argument to the instrumentation callbacks. Because the function is instrumented and its address is taken, it may not be completely optimized out or inlined. However, adhering to the `available_externally` linkage semantics, the compiler still discards the function definition during code generation. Consequently, the generated object file contains unresolved references to the function, which ultimately leads to undefined reference errors during the linking phase. The core issue lies in the transformation pass failing to skip functions with `available_externally` linkage before applying modifications.

## Example

### Original IR
```llvm
define available_externally void @foo() {
entry:
  ret void
}

define void @bar() {
entry:
  call void @foo()
  ret void
}

```
### Optimized IR
```llvm
declare void @__cyg_profile_func_enter(ptr, ptr)

declare void @__cyg_profile_func_exit(ptr, ptr)

define available_externally void @foo() {
entry:
  call void @__cyg_profile_func_enter(ptr @foo, ptr null)
  call void @__cyg_profile_func_exit(ptr @foo, ptr null)
  ret void
}

define void @bar() {
entry:
  call void @__cyg_profile_func_enter(ptr @bar, ptr null)
  call void @foo()
  call void @__cyg_profile_func_exit(ptr @bar, ptr null)
  ret void
}

```
