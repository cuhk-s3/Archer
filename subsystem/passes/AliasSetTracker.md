# Issue 64897

## Summary Title
**Stale Access Size in MustAlias Set Representative Leading to Missed Aliasing**

## Description
The miscompilation is triggered when the `AliasSetTracker` manages a `MustAlias` set containing multiple distinct pointer values that refer to the same memory location. The issue arises from the following sequence of operations:

1.  **Initial Set Creation**: Two or more pointers (e.g., `P1` and `P2`) are identified as aliasing exactly (`MustAlias`) and are grouped into a single set. One of these pointers (e.g., `P1`) is chosen as the representative for the set. Initially, these pointers are accessed with a small memory size.
2.  **Size Expansion**: One of the non-representative pointers (e.g., `P2`) is subsequently accessed with a larger size that encompasses and extends beyond the original range. The tracker updates the size information for `P2` but fails to propagate this larger size to the set's representative pointer (`P1`).
3.  **Overlapping Access**: A new memory access occurs via a third pointer (`P3`) at an offset that falls within the extended range of `P2` but lies outside the original, smaller range of the representative `P1`.
4.  **Incorrect Alias Query**: When determining if `P3` aliases the existing set, the tracker compares it only against the representative pointer `P1`. Because `P1` retains the stale, smaller size, the tracker incorrectly concludes that the ranges do not overlap and returns `NoAlias`.
5.  **Invalid Optimization**: Consequently, the compiler treats the access to `P3` as independent of the access to `P2`. This incorrect independence allows optimization passes, such as Loop Invariant Code Motion (LICM), to illegally reorder memory operations (e.g., hoisting a load past a store that actually overwrites the loaded value), leading to incorrect program behavior.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

declare void @use(i8)
declare i1 @cond()

define void @test_alias_bug(i8* %base) {
entry:
  %p2 = bitcast i8* %base to i32*
  %p3 = getelementptr inbounds i8, i8* %base, i64 1
  br label %loop

loop:
  ; Access 1: Small size (1 byte). Establishes 'base' as representative.
  store i8 0, i8* %base

  ; Access 2: Large size (4 bytes). MustAlias with 'base'.
  ; The bug causes the representative's size to remain 1, ignoring this larger access.
  store i32 -1, i32* %p2

  ; Access 3: Offset 1.
  ; Should alias with Access 2 (bytes 0-3), but if checked against the stale representative (byte 0),
  ; it appears non-overlapping. LICM may incorrectly hoist this load.
  %val = load i8, i8* %p3

  call void @use(i8 %val)
  %c = call i1 @cond()
  br i1 %c, label %loop, label %exit

exit:
  ret void
}
```
### Optimized IR
```llvm
target datalayout = "e-m:e-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

declare void @use(i8)
declare i1 @cond()

define void @test_alias_bug(i8* %base) {
entry:
  %p2 = bitcast i8* %base to i32*
  %p3 = getelementptr inbounds i8, i8* %base, i64 1
  ; The load is incorrectly hoisted out of the loop because the alias check failed.
  %val = load i8, i8* %p3
  br label %loop

loop:
  store i8 0, i8* %base
  store i32 -1, i32* %p2
  call void @use(i8 %val)
  %c = call i1 @cond()
  br i1 %c, label %loop, label %exit

exit:
  ret void
}
```
