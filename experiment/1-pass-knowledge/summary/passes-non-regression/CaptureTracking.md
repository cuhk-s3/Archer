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
