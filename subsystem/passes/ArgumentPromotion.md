# Issue 84807

## Incorrect Caching of Block Transparency for Pointer Argument Promotion

### Description
The bug occurs during the argument promotion optimization, which attempts to replace pointer arguments with the values they point to (pass-by-value) if the pointed-to memory is not modified within the function before being loaded. 

To verify that it is safe to promote a pointer, the optimization checks whether any basic block on the control flow paths leading to the loads modifies the specific memory locations accessed by those loads. However, a flaw exists in how the analysis caches the "transparent" (non-modifying) status of basic blocks across multiple loads from the same pointer argument.

Because different loads can access different offsets (sub-locations) of the same underlying pointer, a basic block might be transparent for one load's specific memory location but modify another load's memory location. The bug is triggered under the following conditions:
1. A function takes a pointer argument and performs multiple loads from it at different offsets.
2. A basic block within the function modifies the memory at one of these offsets, but leaves another offset untouched.
3. The optimization analyzes the loads to ensure no modifications occur before them. 
4. If the optimization first analyzes a load whose corresponding memory offset is *not* modified by the block, it caches that block as "transparent."
5. When the optimization subsequently analyzes another load from a different offset—whose memory *is* actually modified by that same block—it incorrectly reuses the cached transparent status and skips the alias check.

As a result, the compiler erroneously concludes that the memory accessed by the second load is never modified. It then invalidly promotes the pointer argument, leading to a miscompilation where the function uses stale, pre-loaded values instead of the correctly modified memory contents.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-i64:64-f80:128-n8:16:32:64-S128"

@g = global [2 x i32] zeroinitializer

define internal i32 @test(ptr %p) {
entry:
  br label %block

block:
  ; Modifies the memory at offset 1 (the second element)
  store i32 1, ptr getelementptr inbounds ([2 x i32], ptr @g, i64 0, i64 1), align 4
  br label %exit

exit:
  ; Load from offset 0. Analyzed first, block is cached as "transparent" because offset 0 is not modified.
  %p.0 = getelementptr inbounds i32, ptr %p, i64 0
  %v0 = load i32, ptr %p.0, align 4
  
  ; Load from offset 1. Analyzed second, incorrectly reuses the "transparent" cache for block, missing the store.
  %p.1 = getelementptr inbounds i32, ptr %p, i64 1
  %v1 = load i32, ptr %p.1, align 4
  
  %add = add i32 %v0, %v1
  ret i32 %add
}

define i32 @caller() {
entry:
  %call = call i32 @test(ptr @g)
  ret i32 %call
}
```
### Optimized IR
```llvm
target datalayout = "e-m:e-i64:64-f80:128-n8:16:32:64-S128"

@g = global [2 x i32] zeroinitializer

; The pointer argument %p is incorrectly promoted to pass-by-value.
define internal i32 @test(i32 %p.0.val, i32 %p.1.val) {
entry:
  br label %block

block:
  store i32 1, ptr getelementptr inbounds ([2 x i32], ptr @g, i64 0, i64 1), align 4
  br label %exit

exit:
  ; Uses the stale, pre-loaded values instead of the correctly modified memory contents.
  %add = add i32 %p.0.val, %p.1.val
  ret i32 %add
}

define i32 @caller() {
entry:
  %p.0 = getelementptr inbounds i32, ptr @g, i64 0
  %p.0.val = load i32, ptr %p.0, align 4
  %p.1 = getelementptr inbounds i32, ptr @g, i64 1
  %p.1.val = load i32, ptr %p.1, align 4
  %call = call i32 @test(i32 %p.0.val, i32 %p.1.val)
  ret i32 %call
}
```
