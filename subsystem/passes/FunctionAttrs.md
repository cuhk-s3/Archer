# Issue 63936

## Incorrect Deduction of Memory Effects for Recursive Calls Passing Non-Argument Pointers

**Description**:
The bug occurs during the interprocedural analysis of memory effects for functions within a Strongly Connected Component (SCC), such as recursive functions. The optimizer attempts to deduce memory attributes (e.g., whether a function only accesses argument memory) by analyzing the function body.

When the analysis encounters a call to a function within the same SCC, it optimistically ignores the call, assuming that the memory effects of the callee are already accounted for by the SCC's aggregate properties. However, this assumption is flawed regarding argument memory accesses. If a function in the SCC is determined to access its arguments, a recursive call implies an access to the specific pointers passed as arguments at that call site.

If the recursive call passes a pointer that is not an argument of the caller (for example, a pointer loaded from memory or a global variable), the callee's access to its argument constitutes an access to arbitrary or non-argument memory from the caller's perspective. By ignoring the recursive call site, the optimizer fails to account for these transitive accesses. Consequently, it may incorrectly mark the function as only accessing argument memory, even though the recursion causes it to access other memory locations pointed to by the passed parameters.

## Example

### Original IR
```llvm
@G = global i32 0

define void @test(i32* %p) {
  store i32 0, i32* %p
  %cmp = icmp eq i32* %p, @G
  br i1 %cmp, label %exit, label %recurse

recurse:
  call void @test(i32* @G)
  br label %exit

exit:
  ret void
}
```
### Optimized IR
```llvm
@G = global i32 0

; Function Attrs: argmemonly
define void @test(i32* %p) #0 {
  store i32 0, i32* %p
  %cmp = icmp eq i32* %p, @G
  br i1 %cmp, label %exit, label %recurse

recurse:
  call void @test(i32* @G)
  br label %exit

exit:
  ret void
}

attributes #0 = { argmemonly }
```


---

# Issue 91177

## Incorrect Non-Null Inference for Non-Inbounds Pointer Arithmetic

**Description**: 
The bug is triggered when the compiler analyzes a function to infer whether its return value is guaranteed to be non-null. The analysis incorrectly propagates the `nonnull` property through `getelementptr` (GEP) instructions. Specifically, the logic assumes that if the base pointer of a GEP is non-null, the resulting pointer must also be non-null. This assumption is incorrect for GEP instructions that lack the `inbounds` keyword. Without `inbounds`, pointer arithmetic is permitted to result in a null address (for example, by applying a negative offset that effectively subtracts the pointer's address). Consequently, the compiler may incorrectly attach the `nonnull` attribute to a function returning the result of a non-inbounds GEP, leading to potential miscompilations if the resulting pointer is actually null.

## Example

### Original IR
```llvm
define i8* @test_gep_no_inbounds(i8* nonnull %base, i64 %idx) {
  %res = getelementptr i8, i8* %base, i64 %idx
  ret i8* %res
}
```
### Optimized IR
```llvm
define nonnull i8* @test_gep_no_inbounds(i8* nonnull %base, i64 %idx) {
  %res = getelementptr i8, i8* %base, i64 %idx
  ret i8* %res
}
```
