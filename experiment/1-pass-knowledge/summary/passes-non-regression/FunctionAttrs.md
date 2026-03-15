# Issue 91177

## Incorrect `nonnull` Return Attribute Inference for Non-Inbounds Pointer Arithmetic

**Description**:
The bug is triggered when a function returns a pointer computed via non-inbounds pointer arithmetic (such as a `getelementptr` instruction without the `inbounds` keyword) derived from a known `nonnull` base pointer.

The compiler's attribute inference analysis incorrectly assumes that any pointer derived from a `nonnull` source pointer will inherently remain `nonnull`. It traces the returned pointer back to its source and, upon seeing a `nonnull` base, erroneously attaches the `nonnull` attribute to the function's return value.

However, this logic is flawed for non-inbounds pointer arithmetic. Without the `inbounds` restriction, pointer arithmetic operations are allowed to wrap around the address space or use negative offsets that can explicitly compute the null address (address zero). By returning the result of a non-inbounds pointer calculation, the compiler is tricked into making a false `nonnull` guarantee, which can lead to severe miscompilations when downstream optimization passes rely on this incorrect assumption to remove null checks or perform other aggressive transformations.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-i64:64-f80:128-n8:16:32:64-S128"

define ptr @test(ptr nonnull %p, i64 %offset) {
entry:
  %gep = getelementptr i8, ptr %p, i64 %offset
  ret ptr %gep
}

```
### Optimized IR
```llvm
target datalayout = "e-m:e-i64:64-f80:128-n8:16:32:64-S128"

define nonnull ptr @test(ptr nonnull %p, i64 %offset) {
entry:
  %gep = getelementptr i8, ptr %p, i64 %offset
  ret ptr %gep
}

```
