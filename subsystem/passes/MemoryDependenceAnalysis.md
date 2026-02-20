# Issue 111585

## Incorrect Reuse of Memory Dependence Cache for Different Access Sizes

**Description**: 
The bug is triggered when the compiler's memory dependence analysis processes multiple memory accesses to the same base pointer but with different sizes. The strategy to trigger this issue involves the following sequence:

1. **Initial Large Access**: The compiler analyzes a memory access (such as a load or store) with a larger size. This larger access might read or write past the valid bounds of the underlying object, potentially invoking undefined behavior (UB). The analysis caches the dependence results based on this larger size.
2. **Subsequent Small Access**: The compiler then analyzes a second memory access to the exact same pointer, but with a smaller, strictly valid size.
3. **Flawed Cache Reuse**: When querying the dependence for the smaller access, the analysis notices that a cached entry exists for the same pointer. Instead of invalidating the cache or evaluating the smaller access independently, the analysis conservatively restarts the query using the *larger* size from the cache.
4. **Miscompilation**: Because the larger size encompasses out-of-bounds memory, the compiler may apply UB-based reasoning (e.g., assuming certain execution paths are unreachable or that specific aliases cannot exist) to the smaller, valid access. 
5. Optimization passes that rely on this dependence information (such as Global Value Numbering) receive incorrect aliasing or clobbering results. This leads to invalid transformations, such as incorrectly forwarding values, eliminating necessary memory operations, or improperly reordering instructions.

## Example

### Original IR
```llvm
@g = global i8 0, align 2

define i8 @test(i8* %p, i1 %c) {
entry:
  store i8 1, i8* @g, align 2
  br label %bb1

bb1:
  store i8 2, i8* %p, align 1
  br i1 %c, label %bb2, label %bb3

bb2:
  %large = load i16, i16* bitcast (i8* @g to i16*), align 2
  %trunc = trunc i16 %large to i8
  ret i8 %trunc

bb3:
  %small = load i8, i8* @g, align 2
  ret i8 %small
}
```
### Optimized IR
```llvm
@g = global i8 0, align 2

define i8 @test(i8* %p, i1 %c) {
entry:
  store i8 1, i8* @g, align 2
  br label %bb1

bb1:
  store i8 2, i8* %p, align 1
  br i1 %c, label %bb2, label %bb3

bb2:
  %large = load i16, i16* bitcast (i8* @g to i16*), align 2
  %trunc = trunc i16 %large to i8
  ret i8 %trunc

bb3:
  ret i8 1
}
```
