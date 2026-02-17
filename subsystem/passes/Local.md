# Issue 113997

## Unsafe Common Subexpression Elimination of Function Calls with Incompatible Attributes

**Description**
The bug is triggered when the optimizer performs Common Subexpression Elimination (CSE) or Global Value Numbering (GVN) on function calls or intrinsics. The optimization logic identifies two calls as equivalent solely because they invoke the same function with identical operands, ignoring differences in attributes or metadata attached to the specific call sites (such as `range`, `nonnull`, or `noundef`).

The issue arises when the earlier call (used as the replacement value) has stricter attributes than the later call (the instruction being replaced). The stricter attributes may cause the earlier call to yield `poison` or undefined behavior for specific inputs, whereas the later call—having looser or no attributes—would produce a well-defined result for those same inputs. When the optimizer replaces the later call with the earlier one without intersecting or verifying the attributes, it introduces `poison` into a program path where the value was originally well-defined. This leads to miscompilation if the inputs violate the strict attributes of the replacement value but are valid for the original instruction.

## Example

### Original IR
```llvm
define i32 @test_unsafe_cse(i32 %x) {
  ; Call 1: Has strict range metadata [0, 10). If @fn returns 20, this is poison.
  %v1 = call i32 @fn(i32 %x) #0, !range !0
  ; Call 2: No range metadata. If @fn returns 20, this is 20.
  %v2 = call i32 @fn(i32 %x) #0
  ; The program should return the well-defined value from %v2.
  ret i32 %v2
}

declare i32 @fn(i32) #0

attributes #0 = { readnone nounwind }
!0 = !{i32 0, i32 10}
```
### Optimized IR
```llvm
define i32 @test_unsafe_cse(i32 %x) {
  ; The optimizer incorrectly CSEs %v2 to %v1, ignoring the stricter metadata on %v1.
  ; If @fn returns 20, the return value is now poison instead of 20.
  %v1 = call i32 @fn(i32 %x) #0, !range !0
  ret i32 %v1
}

declare i32 @fn(i32) #0

attributes #0 = { readnone nounwind }
!0 = !{i32 0, i32 10}
```


---

# Issue 64598

## Stale Analysis Cache via Address Reuse in PHI Deduplication

**Description**
The bug is triggered during the Global Value Numbering (GVN) optimization pass when it attempts to eliminate duplicate PHI nodes within a basic block. The pass utilizes a helper routine to identify and remove these redundant PHI nodes. However, this helper routine deallocates the instructions immediately without notifying the GVN pass or invalidating its associated analysis caches (specifically, Memory Dependence Analysis).

The critical failure occurs when the memory address of a just-deleted PHI node is reallocated for a new instruction. Because the analysis cache was not cleared, it retains an entry keyed by that memory address containing information about the old, deleted PHI node. When GVN subsequently analyzes the new instruction, it queries the cache and retrieves the stale data. This leads the optimizer to apply transformations to the new instruction based on the properties of the deleted one, resulting in invalid code generation.

## Example

### Original IR
```llvm
define i32 @test(i1 %c, i32* %p) {
entry:
  store i32 42, i32* %p
  br i1 %c, label %if, label %else

if:
  br label %merge

else:
  br label %merge

merge:
  ; Two identical PHI nodes to trigger deduplication logic in GVN
  %phi1 = phi i32 [ 0, %if ], [ 0, %else ]
  %phi2 = phi i32 [ 0, %if ], [ 0, %else ]
  
  ; A load instruction that depends on the store in entry.
  ; If the bug triggers, the address of the deleted %phi2 might be reused for a new instruction
  ; or confuse the analysis cache for this load, causing it to return stale data (e.g., 0 from the PHI).
  %load = load i32, i32* %p
  
  ; Computation to use the values
  %sum = add i32 %phi1, %phi2
  %res = add i32 %sum, %load
  ret i32 %res
}
```
### Optimized IR
```llvm
define i32 @test(i1 %c, i32* %p) {
entry:
  store i32 42, i32* %p
  br i1 %c, label %if, label %else

if:                                               ; preds = %entry
  br label %merge

else:                                             ; preds = %entry
  br label %merge

merge:                                            ; preds = %else, %if
  ; INCORRECT TRANSFORMATION:
  ; The load was incorrectly folded to 0 (the value of the deleted PHI) due to stale analysis cache.
  ; The correct return value should be 42.
  ret i32 0
}
```


---

# Issue 82884

## Improper Preservation of No-Wrap Flags During Replacement of Overflow Intrinsics

**Description**
The bug is triggered when an optimization pass (such as Global Value Numbering) identifies that the arithmetic result of an overflow-checking intrinsic (e.g., `llvm.sadd.with.overflow`) is equivalent to an existing standard binary operator (e.g., `add` or `sub`). The optimizer replaces the instruction extracting the intrinsic's result with the standard binary operator.

The issue arises because the standard binary operator may carry optimization flags like `nsw` (No Signed Wrap) or `nuw` (No Unsigned Wrap), which define overflow as producing a poison value (undefined behavior). In contrast, the `with.overflow` intrinsics are well-defined to return a wrapped result even when overflow occurs. By replacing the intrinsic's result with a flagged instruction without dropping the flags, the compiler incorrectly narrows the program's defined behavior. If the operation overflows at runtime, the replacement instruction generates poison instead of the expected wrapped value, leading to miscompilation.

## Example

### Original IR
```llvm
define i32 @bug_trigger(i32 %a, i32 %b) {
  %1 = add nsw i32 %a, %b
  call void @use(i32 %1)
  %2 = call {i32, i1} @llvm.sadd.with.overflow.i32(i32 %a, i32 %b)
  %3 = extractvalue {i32, i1} %2, 0
  ret i32 %3
}

declare void @use(i32)
declare {i32, i1} @llvm.sadd.with.overflow.i32(i32, i32)
```
### Optimized IR
```llvm
define i32 @bug_trigger(i32 %a, i32 %b) {
  %1 = add nsw i32 %a, %b
  call void @use(i32 %1)
  %2 = call {i32, i1} @llvm.sadd.with.overflow.i32(i32 %a, i32 %b)
  ret i32 %1
}

declare void @use(i32)
declare {i32, i1} @llvm.sadd.with.overflow.i32(i32, i32)
```
