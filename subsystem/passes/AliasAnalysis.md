# Issue 55343

## Incorrect Partial Alias Offset for PHI and Select Pointers

**Description**: 
The bug is triggered when the compiler evaluates the aliasing relationship between a pointer produced by a `phi` or `select` instruction and another memory location. To determine the alias result, the alias analysis recursively queries the aliasing between the incoming values (or true/false operands) of the `phi`/`select` instruction and the target memory location.

If the underlying relationship is a partial alias (where the memory locations overlap but start at different addresses), the offset of the overlap is recorded. However, the recursive alias queries are performed with the arguments in the reversed order compared to the original query. Because the partial alias offset is direction-dependent (representing the offset of one pointer relative to the other), this swapped argument order causes the analysis to compute and return a partial alias with a negated or incorrect offset.

Optimization passes that rely on precise alias offsets, such as Global Value Numbering (GVN), may use this incorrect offset to perform invalid memory optimizations, such as incorrectly forwarding loads or eliminating memory accesses, ultimately leading to a miscompilation.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"

define i8 @test(i1 %c) {
entry:
  %alloc = alloca i64, align 8
  store i64 0, ptr %alloc, align 8
  %p = getelementptr inbounds i8, ptr %alloc, i64 1
  %p_plus_1 = getelementptr inbounds i8, ptr %alloc, i64 2
  br label %loop

loop:
  %pn = phi ptr [ %p_plus_1, %entry ], [ %p_plus_1_loop, %loop ]
  store i32 16909060, ptr %pn, align 1
  %load = load i8, ptr %p, align 1
  %p_plus_1_loop = getelementptr inbounds i8, ptr %alloc, i64 2
  br i1 %c, label %loop, label %exit

exit:
  ret i8 %load
}
```
### Optimized IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"

define i8 @test(i1 %c) {
entry:
  %alloc = alloca i64, align 8
  store i64 0, ptr %alloc, align 8
  %p_plus_1 = getelementptr inbounds i8, ptr %alloc, i64 2
  br label %loop

loop:
  store i32 16909060, ptr %p_plus_1, align 1
  br i1 %c, label %loop, label %exit

exit:
  ret i8 3
}
```


---

# Issue 63266

## Incorrect `nsw` Flag Preservation on Negated GEP Scales

**Description**

The bug is triggered when the alias analysis evaluates two pointers derived from the same base pointer, where one involves a variable offset that can take the value of `INT_MIN` (the minimum representable signed integer for its bit width). 

The miscompilation occurs through the following sequence of high-level analysis steps:

1. **Pointer Derivation**: Two pointers are derived from a common base using `getelementptr` (GEP) instructions. One pointer has a constant offset, while the other has a large constant offset combined with a variable index (e.g., a `phi` node).
2. **Trivial `nsw` Assumption**: The variable index in the second GEP has a positive scale (e.g., `1`). Because multiplying any value by `1` cannot cause a signed overflow, the compiler internally flags this scaling operation as `nsw` (no signed wrap).
3. **Offset Subtraction**: To determine if the pointers alias, the alias analysis compares them by subtracting their decomposed offset expressions. This subtraction negates the scale of the variable index (e.g., changing the scale from `1` to `-1`).
4. **Incorrect Flag Preservation**: The compiler incorrectly preserves the `nsw` flag for the newly negated scale during the subtraction process. 
5. **Invalid Non-Wrapping Deduction**: While `X * 1` never wraps, `X * (-1)` will cause a signed overflow if `X` is exactly `INT_MIN`. Because the `nsw` flag is preserved on the negated scale, the compiler incorrectly assumes that the multiplication cannot overflow. Consequently, it deduces that the variable index can never be `INT_MIN`.
6. **Miscompilation**: By incorrectly excluding `INT_MIN` from the possible values of the variable index, the compiler concludes that the calculated offsets can never match. This results in an invalid `NoAlias` determination, even though the pointers perfectly alias when the variable index is `INT_MIN`.

## Example

### Original IR
```llvm
define i8 @test(ptr %base, i64 %x) {
entry:
  %ptr2 = getelementptr i8, ptr %base, i64 %x
  %ptr3 = getelementptr i8, ptr %ptr2, i64 -9223372036854775808
  store i8 1, ptr %base, align 1
  store i8 2, ptr %ptr3, align 1
  %val = load i8, ptr %base, align 1
  ret i8 %val
}
```
### Optimized IR
```llvm
define i8 @test(ptr %base, i64 %x) {
entry:
  %ptr2 = getelementptr i8, ptr %base, i64 %x
  %ptr3 = getelementptr i8, ptr %ptr2, i64 -9223372036854775808
  store i8 1, ptr %base, align 1
  store i8 2, ptr %ptr3, align 1
  ret i8 1
}
```


---

# Issue 69096

## Incorrect Preservation of No-Signed-Wrap (NSW) Flags During Index Expression Merging

**Description**: 
The bug is triggered when the compiler's alias analysis evaluates memory access instructions (such as `getelementptr`) by decomposing their index computations into linear expressions. When multiple index expressions share the same underlying variable, the analysis attempts to simplify the computation by merging their scales (e.g., combining `A * x` and `B * x` into `(A + B) * x`). 

If the original, separate index computations were marked with "no signed wrap" (NSW) flags, the analysis incorrectly preserved this flag for the newly merged expression. However, the combined scale can cause the merged expression to undergo signed overflow, even if the individual components were guaranteed not to wrap. 

By improperly retaining the NSW flag on the merged expression, the compiler incorrectly assumes the combined index computation cannot wrap. This leads to flawed alias analysis results, where the compiler might incorrectly deduce that two memory locations do not overlap. Consequently, this false assumption allows downstream optimization passes to perform invalid transformations, such as improperly reordering, vectorizing, or eliminating memory accesses.

## Example

### Original IR
```llvm
define i8 @test(ptr %p, i64 %x) {
entry:
  %mul1 = mul nsw i64 %x, 2
  %mul2 = mul nsw i64 %x, 3
  %gep.C = getelementptr i8, ptr %p, i64 -9223372036854775806
  %gep1 = getelementptr i8, ptr %p, i64 %mul1
  %gep2 = getelementptr i8, ptr %gep1, i64 %mul2
  store i8 1, ptr %gep.C, align 1
  store i8 2, ptr %gep2, align 1
  %val = load i8, ptr %gep.C, align 1
  ret i8 %val
}
```
### Optimized IR
```llvm
define i8 @test(ptr %p, i64 %x) {
entry:
  %mul1 = mul nsw i64 %x, 2
  %mul2 = mul nsw i64 %x, 3
  %gep.C = getelementptr i8, ptr %p, i64 -9223372036854775806
  %gep1 = getelementptr i8, ptr %p, i64 %mul1
  %gep2 = getelementptr i8, ptr %gep1, i64 %mul2
  store i8 1, ptr %gep.C, align 1
  store i8 2, ptr %gep2, align 1
  ret i8 1
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


---

# Issue 72831

## Incorrect Alias Analysis for GEPs with Wrapping Scaled Non-Zero Indices

### Description
The bug is triggered when the compiler's alias analysis evaluates two `getelementptr` (GEP) instructions to determine if their memory accesses overlap. Specifically, the issue occurs when one of the GEPs uses a variable index that the compiler can prove is strictly non-zero (e.g., due to loop bounds, dominating branch conditions, or range metadata). 

The alias analysis incorrectly assumes that if the variable index is non-zero, the resulting scaled offset (the variable index multiplied by its scale, such as the type's element size) must also have an absolute value of at least 1. However, this assumption fails to account for integer overflow. If the multiplication of the variable index and the scale wraps around the integer bitwidth, the resulting offset added to the pointer can actually be zero. 

Because the analysis ignores the possibility of wrapping math resulting in a zero offset, it incorrectly concludes that the two pointers cannot point to the same memory location and returns a `NoAlias` result. This flawed alias information is subsequently used by memory optimization passes (such as Dead Store Elimination, Global Value Numbering, or instruction scheduling) to perform invalid transformations, like incorrectly reordering dependent memory operations or eliminating necessary stores, ultimately leading to a miscompilation.

## Example

### Original IR
```llvm
define i32 @test(ptr %p, i64 %idx) {
entry:
  %cmp = icmp ne i64 %idx, 0
  br i1 %cmp, label %then, label %else

then:
  ; GEP without 'inbounds'. If %idx is (1 << 62), %idx * 4 wraps to 0 in i64.
  ; Thus, %gep can be equal to %p even if %idx != 0.
  %gep = getelementptr i32, ptr %p, i64 %idx
  store i32 1, ptr %p, align 4
  store i32 2, ptr %gep, align 4
  %val = load i32, ptr %p, align 4
  ret i32 %val

else:
  ret i32 0
}

```
### Optimized IR
```llvm
define i32 @test(ptr %p, i64 %idx) {
entry:
  %cmp = icmp ne i64 %idx, 0
  br i1 %cmp, label %then, label %else

then:
  %gep = getelementptr i32, ptr %p, i64 %idx
  store i32 1, ptr %p, align 4
  store i32 2, ptr %gep, align 4
  ; The load is incorrectly optimized to 1 because Alias Analysis wrongly
  ; assumes %p and %gep cannot alias since %idx != 0, ignoring the wrap.
  ret i32 1

else:
  ret i32 0
}

```


---

# Issue 79175

## Incorrect Load Elimination Due to Stale Dominator Tree in Alias Analysis

**Description:**

The bug is triggered by an unsafe interaction between control flow transformations and memory optimization queries relying on outdated analysis data. The strategy unfolds as follows:

1. **Control Flow Modification:** A compiler pass (such as jump threading) performs transformations that alter the Control Flow Graph (CFG). These changes can leave the Dominator Tree temporarily stale or out of sync with the actual CFG.
2. **Redundant Load Optimization:** While the Dominator Tree is in this stale state, the pass attempts to optimize memory accesses, specifically looking to eliminate partially redundant loads by reusing previously loaded values.
3. **Flawed Alias Analysis Query:** To ensure the optimization is safe, the pass queries Alias Analysis to check if any intervening memory writes (e.g., stores) clobber the memory location before the load occurs. 
4. **Incorrect Non-Aliasing Deduction:** Alias Analysis internally utilizes the Dominator Tree to make advanced aliasing deductions (such as evaluating contextual assumptions, checking cycles, or decomposing pointer expressions). Because the Dominator Tree is outdated, Alias Analysis evaluates the dominance relationships incorrectly. This leads it to mistakenly conclude that an intervening memory write does *not* alias the load's target address (`NoAlias`), when in reality, it does.
5. **Miscompilation:** Trusting the incorrect Alias Analysis result, the optimization pass assumes the previously loaded value is still valid. It incorrectly eliminates the load instruction, replacing it with a stale value (often by routing an older value through a PHI node). This bypasses the actual memory update performed by the clobbering write, resulting in a miscompilation where the program uses an outdated value.

## Example

### Original IR
```llvm
define i8 @test(i8* %p, i8* %q, i1 %c1) {
entry:
  %load1 = load i8, i8* %p
  br i1 %c1, label %bb1, label %bb2

bb1:
  store i8 42, i8* %q
  br label %bb3

bb2:
  br label %bb3

bb3:
  %phi = phi i1 [ true, %bb1 ], [ false, %bb2 ]
  br i1 %phi, label %bb4, label %bb5

bb4:
  %load2 = load i8, i8* %p
  ret i8 %load2

bb5:
  ret i8 0
}

```
### Optimized IR
```llvm
define i8 @test(i8* %p, i8* %q, i1 %c1) {
entry:
  %load1 = load i8, i8* %p
  br i1 %c1, label %bb1, label %bb5

bb1:
  store i8 42, i8* %q
  ret i8 %load1

bb5:
  ret i8 0
}

```
