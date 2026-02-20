# Issue 113997

## Miscompilation due to Improper Handling of Call Attributes during CSE/GVN

**Description:**
The bug occurs when Common Subexpression Elimination (CSE) or Global Value Numbering (GVN) optimizations replace a function call with a dominating equivalent call without properly reconciling their return attributes. 

The bug triggering strategy involves the following sequence:
1. The program contains two identical function calls (or intrinsics) with the same arguments, making the dominated call a candidate for elimination.
2. The dominating call possesses more restrictive return attributes (such as `range` or `nonnull`) compared to the dominated call.
3. For specific inputs, the dominating call evaluates to `poison` because its restrictive attributes are violated. However, in the original program, this `poison` value is safely ignored or masked by the control flow.
4. The dominated call, which lacks these restrictive attributes (or has more relaxed ones), evaluates to a well-defined value for the same inputs.
5. The optimization pass replaces the dominated call with the dominating call but fails to intersect or strip the incompatible attributes.
6. As a result, the uses of the dominated call incorrectly receive the `poison` value from the dominating call, leading to a miscompilation where the optimized program is more poisonous than the original source.

## Example

### Original IR
```llvm
declare ptr @foo(ptr) memory(none)

define ptr @test(ptr %p, i1 %c) {
entry:
  %call1 = call nonnull ptr @foo(ptr %p)
  br i1 %c, label %then, label %else

then:
  ret ptr %call1

else:
  %call2 = call ptr @foo(ptr %p)
  ret ptr %call2
}

```
### Optimized IR
```llvm
declare ptr @foo(ptr) memory(none)

define ptr @test(ptr %p, i1 %c) {
entry:
  %call1 = call nonnull ptr @foo(ptr %p)
  br i1 %c, label %then, label %else

then:
  ret ptr %call1

else:
  ret ptr %call1
}

```
