# Issue 116668

## Incorrect Alias Analysis for Unescaped Heap Objects Across `returns_twice` Calls

**Description:**

The bug is triggered by a specific sequence involving a dynamically allocated object (e.g., heap memory) and a function call marked with the `returns_twice` attribute (such as `setjmp`). The strategy to trigger the miscompilation involves the following pattern at the LLVM IR level:

1. **Allocation and Initialization**: A dynamically allocated object is created and an initial value is stored into it. Crucially, this object is kept local and does not escape its current scope.
2. **First Return**: A call is made to a function with the `returns_twice` attribute.
3. **Intermediate Modification**: In the control flow path following the first return of this call, a new value is stored into the allocated object. Subsequently, a mechanism (like `longjmp`) is invoked to transfer control back to the `returns_twice` call, causing it to return a second time.
4. **Second Return and Load**: In the control flow path following the second return, the value is loaded from the allocated object.

The incorrect transformation logic stems from how Alias Analysis evaluates the `returns_twice` call against the unescaped object. The analysis incorrectly assumes that because the dynamically allocated object has not escaped prior to the call, the call cannot possibly access or clobber it. However, a `returns_twice` function effectively creates a complex control flow where modifications made after the first return must be preserved and visible after the second return.

Because Alias Analysis fails to model this implicit clobbering for unescaped non-stack objects, memory optimization passes (such as EarlyCSE or Global Value Numbering) incorrectly conclude that the memory location remains unchanged across the `returns_twice` call. As a result, these passes erroneously forward the initial value stored *before* the call directly to the load executed *after* the second return, completely bypassing and erasing the valid store that occurred between the two returns.

---

# Issue 120932

## Incorrect Memory Effect Inference for Volatile Memory Intrinsics

**Description**:
The bug is triggered by the following sequence of conditions and transformations:
1. A function is defined containing a volatile memory intrinsic (such as a volatile `memcpy`, `memset`, or `memmove`).
2. The explicit pointer arguments of this volatile intrinsic are constrained to memory locations that typically do not produce observable side effects from the caller's perspective. For example, the pointers might reference strictly local allocations (`alloca`) or constant global variables.
3. When the compiler's interprocedural analysis evaluates the function to infer its memory effects, it examines these explicit memory accesses. Because the accessed memory is purely local or constant, the analysis deduces that the operations do not affect any globally observable state.
4. However, the analysis fails to account for the inherent semantics of `volatile` operations. According to the language reference, volatile operations can implicitly read or modify state that is not accessible via regular memory operations (often modeled as "inaccessible memory").
5. As a result of ignoring the volatile qualifier, the compiler erroneously annotates the function with an attribute indicating it has no memory effects whatsoever (e.g., `memory(none)`).
6. This incorrect attribute allows subsequent optimization passes to treat calls to this function as having no side effects, potentially leading to the calls being incorrectly eliminated as dead code, reordered, or hoisted, which results in a miscompilation.

---

# Issue 52735

## Incorrect Alias Analysis for `callbr` Instructions Leading to Invalid Memory Optimization

**Description:**
The bug is triggered by a sequence of instructions involving a memory location, a `callbr` instruction (such as inline assembly with control-flow branches) that potentially modifies that memory, and a subsequent load from the same memory location.

At the LLVM IR level, Alias Analysis is responsible for determining whether instructions read or write to memory. However, it fails to recognize `callbr` as a memory-accessing instruction, falling back to a default assumption that it has no memory effects (`NoModRef`).

Because of this incorrect assumption, optimization passes that rely on Alias Analysis (such as Global Value Numbering or Dead Store Elimination) believe that the memory remains unmodified across the `callbr` instruction. As a result, these passes may incorrectly optimize away subsequent loads—for instance, by replacing the loaded value with a stale value, a constant, or an uninitialized value—leading to a miscompilation.

---

# Issue 55343

## Incorrect Partial Alias Offset for PHI and Select Pointers

**Description**:
The bug is triggered when the compiler evaluates the aliasing relationship between a pointer produced by a `phi` or `select` instruction and another memory location. To determine the alias result, the alias analysis recursively queries the aliasing between the incoming values (or true/false operands) of the `phi`/`select` instruction and the target memory location.

If the underlying relationship is a partial alias (where the memory locations overlap but start at different addresses), the offset of the overlap is recorded. However, the recursive alias queries are performed with the arguments in the reversed order compared to the original query. Because the partial alias offset is direction-dependent (representing the offset of one pointer relative to the other), this swapped argument order causes the analysis to compute and return a partial alias with a negated or incorrect offset.

Optimization passes that rely on precise alias offsets, such as Global Value Numbering (GVN), may use this incorrect offset to perform invalid memory optimizations, such as incorrectly forwarding loads or eliminating memory accesses, ultimately leading to a miscompilation.

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

---

# Issue 69096

## Incorrect Preservation of No-Signed-Wrap (NSW) Flags During Index Expression Merging

**Description**:
The bug is triggered when the compiler's alias analysis evaluates memory access instructions (such as `getelementptr`) by decomposing their index computations into linear expressions. When multiple index expressions share the same underlying variable, the analysis attempts to simplify the computation by merging their scales (e.g., combining `A * x` and `B * x` into `(A + B) * x`).

If the original, separate index computations were marked with "no signed wrap" (NSW) flags, the analysis incorrectly preserved this flag for the newly merged expression. However, the combined scale can cause the merged expression to undergo signed overflow, even if the individual components were guaranteed not to wrap.

By improperly retaining the NSW flag on the merged expression, the compiler incorrectly assumes the combined index computation cannot wrap. This leads to flawed alias analysis results, where the compiler might incorrectly deduce that two memory locations do not overlap. Consequently, this false assumption allows downstream optimization passes to perform invalid transformations, such as improperly reordering, vectorizing, or eliminating memory accesses.

---

# Issue 70547

## Prematurely Ignoring Ephemeral Values in Pointer Capture Tracking

**Description:**
The bug occurs in the compiler's pointer capture tracking and alias analysis logic. When determining whether a pointer escapes (is captured), the analysis explores the uses of the pointer. Previously, the analysis was designed to ignore "ephemeral" values—instructions whose results are ultimately only used by assumption intrinsics (like `llvm.assume`)—under the premise that these instructions do not affect observable program behavior and will eventually be removed.

However, ignoring these ephemeral values prematurely leads to miscompilations. If an ephemeral instruction captures a pointer (for example, by passing it to a function call or storing it), ignoring it causes the capture tracking analysis to incorrectly conclude that the pointer does not escape.

Optimization passes, such as Dead Store Elimination (DSE), heavily rely on this analysis. If DSE is incorrectly informed that a pointer does not escape, it may aggressively eliminate stores to that memory location, assuming the memory is strictly local and the stores are dead. Because the ephemeral instructions are still present in the Intermediate Representation (IR) at this stage, they or other related instructions might still execute and access the memory. Since the necessary stores were incorrectly removed, this results in the program reading uninitialized or stale memory, leading to incorrect runtime behavior.

The core issue is that capture tracking must remain conservative and account for all uses of a pointer, including those in ephemeral instructions, as long as those instructions still exist in the IR.

---

# Issue 72831

## Incorrect Alias Analysis for GEPs with Wrapping Scaled Non-Zero Indices

### Description
The bug is triggered when the compiler's alias analysis evaluates two `getelementptr` (GEP) instructions to determine if their memory accesses overlap. Specifically, the issue occurs when one of the GEPs uses a variable index that the compiler can prove is strictly non-zero (e.g., due to loop bounds, dominating branch conditions, or range metadata).

The alias analysis incorrectly assumes that if the variable index is non-zero, the resulting scaled offset (the variable index multiplied by its scale, such as the type's element size) must also have an absolute value of at least 1. However, this assumption fails to account for integer overflow. If the multiplication of the variable index and the scale wraps around the integer bitwidth, the resulting offset added to the pointer can actually be zero.

Because the analysis ignores the possibility of wrapping math resulting in a zero offset, it incorrectly concludes that the two pointers cannot point to the same memory location and returns a `NoAlias` result. This flawed alias information is subsequently used by memory optimization passes (such as Dead Store Elimination, Global Value Numbering, or instruction scheduling) to perform invalid transformations, like incorrectly reordering dependent memory operations or eliminating necessary stores, ultimately leading to a miscompilation.

---

# Issue 76789

## Incorrect NoAlias Deduction Between Constant Pointers and Escaped Local Objects

**Description**:
The bug is triggered by a flaw in the alias analysis logic regarding constant pointers and identified local objects (such as stack allocations). The strategy to trigger this issue involves the following steps:

1. **Create an Identified Local Object**: Define a local memory object, such as an `alloca`, within a function.
2. **Escape the Local Object**: Allow the address of this local object to escape its immediate scope. This can be done by converting the pointer to an integer, storing it in a global variable, or passing it to an external function.
3. **Construct a Constant Pointer**: Create a constant pointer using a constant expression (specifically, an integer-to-pointer conversion) that evaluates to the address of the escaped local object.
4. **Perform Memory Operations**: Execute memory accesses (loads or stores) using both the original local object (or a pointer derived from it) and the newly constructed constant pointer.

The alias analysis incorrectly assumes as a hard rule that a constant pointer can never alias with a non-constant identified local object. It fails to account for the fact that if the local object has escaped, its address can be legitimately reconstructed and accessed via a constant expression. As a result, the compiler incorrectly returns a `NoAlias` result for the two pointers. This false deduction can lead to invalid memory optimizations, such as improperly reordering or eliminating dependent load and store instructions, ultimately causing a miscompilation.

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
