# Issue 115976

## Incorrect Preservation of Pointer Attributes when Shortening Memory Intrinsics

**Description**:
The bug can be triggered by constructing a specific sequence of memory operations that causes the compiler to shorten a memory intrinsic, while failing to update the associated pointer attributes. The strategy involves the following steps:

1. **Emit a Memory Intrinsic with Pointer Attributes**: Create a memory intrinsic (such as `llvm.memset`, `llvm.memcpy`, or `llvm.memmove`) where the destination pointer argument is decorated with attributes that provide specific memory guarantees, such as `dereferenceable`, `dereferenceable_or_null`, or `align`.
2. **Overwrite the Prefix of the Memory Region**: Immediately follow the memory intrinsic with one or more store instructions that completely overwrite the beginning (the prefix) of the memory region just modified by the intrinsic.
3. **Trigger Dead Store Elimination**: This pattern triggers dead store elimination (DSE) optimizations. Recognizing that the initial bytes written by the intrinsic are dead (since they are overwritten by the subsequent stores), the compiler optimizes the intrinsic by shortening it. This involves advancing the intrinsic's base pointer forward by a certain offset and reducing the total length of the memory operation.
4. **Attribute Miscompilation**: The bug manifests during this transformation. The optimization incorrectly preserves the original pointer attributes on the newly offset pointer. For example, if the original pointer was marked as `dereferenceable(100)`, the new pointer (which has been advanced by an offset) will also be marked as `dereferenceable(100)`. This over-promises the safe memory bounds or violates alignment guarantees, introducing undefined behavior into the IR.

## Example

### Original IR
```llvm
declare void @llvm.memset.p0.i64(ptr nocapture writeonly, i8, i64, i1 immarg)

define void @test_shorten_memset(ptr %p) {
entry:
  call void @llvm.memset.p0.i64(ptr align 32 dereferenceable(100) %p, i8 0, i64 100, i1 false)
  store i64 1, ptr %p, align 32
  ret void
}

```
### Optimized IR
```llvm
declare void @llvm.memset.p0.i64(ptr nocapture writeonly, i8, i64, i1 immarg)

define void @test_shorten_memset(ptr %p) {
entry:
  %0 = getelementptr inbounds i8, ptr %p, i64 8
  call void @llvm.memset.p0.i64(ptr align 32 dereferenceable(100) %0, i8 0, i64 92, i1 false)
  store i64 1, ptr %p, align 32
  ret void
}

```

---

# Issue 126181

## Incorrect Dead Store Elimination due to `initializes` Attribute on `byval` Arguments

**Description**:
The bug is triggered by a specific interaction between the `byval` and `initializes` attributes during the Dead Store Elimination (DSE) pass. The pattern involves the following sequence:

1. A caller function performs a store operation to a specific memory location.
2. The caller then passes a pointer to this memory location as an argument to a callee function.
3. The corresponding parameter in the callee function is marked with both the `byval` attribute (indicating that the callee receives a private copy of the memory) and the `initializes` attribute (indicating that the callee writes to the specified memory range).

The miscompilation occurs because DSE misinterprets the scope of the `initializes` attribute. While `byval` guarantees that the callee only modifies its own local copy of the memory, DSE incorrectly assumes that the `initializes` attribute implies the callee will overwrite the caller's original memory. Consequently, DSE erroneously determines that the preceding store in the caller is dead (since it believes the call will overwrite it) and removes the store instruction. This leaves the caller's memory uninitialized or holding an incorrect value, leading to incorrect program behavior.

## Example

### Original IR
```llvm
declare void @callee(ptr byval(i32) initializes((0, 4)) %p)

define i32 @caller() {
entry:
  %a = alloca i32, align 4
  store i32 42, ptr %a, align 4
  call void @callee(ptr byval(i32) initializes((0, 4)) %a)
  %res = load i32, ptr %a, align 4
  ret i32 %res
}
```
### Optimized IR
```llvm
declare void @callee(ptr byval(i32) initializes((0, 4)) %p)

define i32 @caller() {
entry:
  %a = alloca i32, align 4
  call void @callee(ptr byval(i32) initializes((0, 4)) %a)
  %res = load i32, ptr %a, align 4
  ret i32 %res
}
```

---

# Issue 70547

## Prematurely Ignoring Ephemeral Values in Pointer Capture Tracking

**Description:**
The bug occurs in the compiler's pointer capture tracking and alias analysis logic. When determining whether a pointer escapes (is captured), the analysis explores the uses of the pointer. Previously, the analysis was designed to ignore "ephemeral" values—instructions whose results are ultimately only used by assumption intrinsics (like `llvm.assume`)—under the premise that these instructions do not affect observable program behavior and will eventually be removed.

However, ignoring these ephemeral values prematurely leads to miscompilations. If an ephemeral instruction captures a pointer (for example, by passing it to a function call or storing it), ignoring it causes the capture tracking analysis to incorrectly conclude that the pointer does not escape.

Optimization passes, such as Dead Store Elimination (DSE), heavily rely on this analysis. If DSE is incorrectly informed that a pointer does not escape, it may aggressively eliminate stores to that memory location, assuming the memory is strictly local and the stores are dead. Because the ephemeral instructions are still present in the Intermediate Representation (IR) at this stage, they or other related instructions might still execute and access the memory. Since the necessary stores were incorrectly removed, this results in the program reading uninitialized or stale memory, leading to incorrect runtime behavior.

The core issue is that capture tracking must remain conservative and account for all uses of a pointer, including those in ephemeral instructions, as long as those instructions still exist in the IR.

## Example

### Original IR
```llvm
declare void @llvm.assume(i1)

define void @test() {
  %p = alloca i32
  store i32 42, ptr %p
  %int = ptrtoint ptr %p to i64
  %ptr = inttoptr i64 %int to ptr
  %val = load i32, ptr %ptr
  %cmp = icmp eq i32 %val, 42
  call void @llvm.assume(i1 %cmp)
  ret void
}
```
### Optimized IR
```llvm
declare void @llvm.assume(i1)

define void @test() {
  %p = alloca i32
  %int = ptrtoint ptr %p to i64
  %ptr = inttoptr i64 %int to ptr
  %val = load i32, ptr %ptr
  %cmp = icmp eq i32 %val, 42
  call void @llvm.assume(i1 %cmp)
  ret void
}
```
