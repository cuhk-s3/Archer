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

# Issue 159918

## Mishandling of Memory-Defining Intrinsics Returning Arguments in Value Numbering

**Description**
The bug is triggered when the Global Value Numbering (GVN) optimization encounters an intrinsic function call that possesses two specific characteristics: it modifies memory (acting as a memory-defining instruction) and it returns one of its input arguments (e.g., via a `returned` attribute).

The optimization logic incorrectly simplifies such calls by immediately equating the result of the intrinsic to the input argument during symbolic evaluation. This aggressive simplification treats the instruction merely as a value pass-through, ignoring its role as a distinct memory operation. Consequently, the instruction is not properly tracked within the memory congruence system. This leads to an inconsistent internal state where the memory access associated with the intrinsic is mishandled, causing assertion failures when the compiler attempts to update memory dependency classes.

## Example

### Original IR
```llvm
define i32 @test(i32* %p) {
  store i32 42, i32* %p
  %call = call i32* @llvm.foo(i32* %p)
  %val = load i32, i32* %call
  ret i32 %val
}

declare i32* @llvm.foo(i32* returned)
```
### Optimized IR
```llvm
define i32 @test(i32* %p) {
  store i32 42, i32* %p
  %call = call i32* @llvm.foo(i32* %p)
  ret i32 42
}

declare i32* @llvm.foo(i32* returned)
```
