# Issue 174045

## Incorrect Replacement of Pointer Vectors Due to Missing Provenance Checks

**Description**: 
The bug is triggered when an optimization pass attempts to replace one vector of pointers with another based on an equality condition (for example, folding a `select` instruction driven by an `icmp eq` between two pointer vectors). 

While replacing values based on equality is generally safe for simple types like integers, it is not always valid for pointers due to strict provenance rules—two pointers may hold the same memory address but originate from different allocations (different provenances). 

The issue arises because the compiler's safety validation logic for pointer replacement only checks for scalar pointer types. When it encounters a vector of pointers, it incorrectly classifies it as a non-pointer type. As a result, the compiler bypasses the necessary provenance checks and unconditionally allows the replacement. This leads to a miscompilation where the original pointer provenance is lost or incorrectly altered, potentially causing invalid memory accesses later in the compilation pipeline.

## Example

### Original IR
```llvm
define <2 x ptr> @test_select_eq(<2 x ptr> %p, <2 x ptr> %q) {
  %cmp = icmp eq <2 x ptr> %p, %q
  %sel = select <2 x i1> %cmp, <2 x ptr> %p, <2 x ptr> %q
  ret <2 x ptr> %sel
}
```
### Optimized IR
```llvm
define <2 x ptr> @test_select_eq(<2 x ptr> %p, <2 x ptr> %q) {
  ret <2 x ptr> %q
}
```
