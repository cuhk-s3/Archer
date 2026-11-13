# Issue 102597

## Incorrect Constant Difference Computation for Wide Integers

**Description**:
The bug is triggered when the compiler's scalar evolution analysis attempts to compute the constant difference between two expressions involving integer types wider than 64 bits (e.g., `i128`).

During this analysis, the compiler decomposes the expressions and accumulates their constant components by multiplying them with a multiplicity factor (typically `1` or `-1`). However, when dealing with integers larger than 64 bits and a negative multiplicity factor (such as `-1`), the factor is incorrectly zero-extended instead of sign-extended to match the width of the wide integer.

This incorrect zero-extension causes the multiplication to produce a massive positive value rather than the intended negative value, leading to a completely wrong constant difference. As a result, downstream loop optimizations (like induction variable simplification) rely on this flawed analysis to incorrectly fold loop conditions or comparisons into constant boolean values (e.g., always `true`). This alters the control flow of the loop, causing the compiled program to skip intended logic and produce incorrect results.

---

# Issue 117133

## Incorrect Recurrence Formation from PHI Nodes with UB-Causing Backedge Values

**Description:**
The bug is triggered by a loop containing a PHI node whose initial value is well-defined, but whose backedge value involves an operation that can cause immediate undefined behavior (UB) or produce poison (such as a division by zero or a division by a potentially poison value).

When the compiler attempts to analyze the PHI node and model it as a scalar evolution recurrence, it tries to deduce the recurrence by shifting the backedge expression backwards by one iteration. It then evaluates this shifted expression to check if its starting value matches the PHI node's actual initial value.

If the shifted backedge expression evaluates to UB or poison (e.g., `0 / 0`), the compiler's simplification logic might incorrectly fold it into a valid constant that happens to match the PHI node's well-defined initial value. Because of this coincidental match, the compiler erroneously concludes that the entire PHI node can be represented by the shifted backedge expression.

This transformation is invalid because it replaces a well-defined initial value with an expression that evaluates to UB or poison. By doing so, the compiler effectively introduces UB into the first iteration of the loop where it did not originally exist (or refines a well-defined value into poison). This allows subsequent optimization passes to miscompile the program based on the false assumption of UB or poison.

---

# Issue 126012

## Incorrect Simplification of Loop-Variant Conditions at Merge Points

**Description**:
The bug is triggered when the compiler attempts to simplify a condition at a control flow merge point (such as a basic block with multiple predecessors or a PHI node) inside a loop.

1. **Loop-Variant Value**: The condition depends on a loop-variant value, specifically an induction variable or an expression that evolves predictably across loop iterations (e.g., a scalar evolution AddRec expression).
2. **Merge Point Analysis**: The compiler analyzes the incoming values to the merge point to determine if they can statically imply the condition. To do this safely, it checks whether the incoming values properly dominate the merge point, attempting to ensure they do not carry stale values from a previous loop iteration.
3. **Flawed Dominance Check**: The compiler's dominance check incorrectly considers induction variables (and expressions derived from them) as properly dominating the loop they are defined in. It fails to recognize that while the definition's location dominates, the actual value evaluated changes with each loop iteration.
4. **Miscompilation**: Because the compiler incorrectly assumes the loop-variant value is safe to use for implication across iterations, it erroneously proves the condition based on a specific iteration's state. This leads to the incorrect folding of a loop-variant condition into a constant (e.g., always `true` or always `false`), altering the program's control flow and causing a miscompilation.

---

# Issue 126409

## Incorrect Preservation of `samesign` Flag During Operand Truncation in Condition Implication

**Description**:
The bug is triggered when the compiler's analysis tries to prove a target integer comparison using a known dominating comparison (such as a branch condition) that carries the `samesign` flag.

1. The program contains a known integer comparison with the `samesign` flag, which asserts that both of its operands have the same sign (both non-negative or both negative).
2. The compiler attempts to use this known comparison to imply the result of another comparison that operates on a narrower integer type (e.g., a loop exit condition).
3. To perform the implication and match the types, the compiler conceptually truncates the operands of the known comparison to the narrower type.
4. The compiler incorrectly assumes that the `samesign` property still holds for the truncated operands. However, truncating an integer can alter its sign bit (for example, a positive 32-bit integer like `0x000000FF` becomes a negative 8-bit integer `0xFF`), meaning the truncated values are not guaranteed to still share the same sign.
5. By improperly retaining the `samesign` flag on the truncated operands, the compiler makes invalid logical deductions—such as incorrectly converting between unsigned and signed predicates. This leads to severe miscompilations, such as erroneously evaluating a loop condition as always true or always false, which can result in an infinite loop.

---

# Issue 131465

## Incorrect Undefined Behavior Assumption for Zero-Stride Loop Recurrences

**Description:**
The bug occurs in the compiler's loop analysis framework when calculating the exit limit of a loop based on a recurrence expression (e.g., an induction variable) reaching zero. The triggering strategy involves the following sequence:

1. A loop is constructed where the exit condition depends on a recurrence expression reaching zero.
2. The loop is optimized or rotated such that the recurrence expression evaluated at the exit check has a step (stride) of zero, and a start value that evaluates to zero (or is not statically known to be non-zero).
3. The compiler observes the zero step and incorrectly assumes that the value will never change, meaning the loop would be infinite if the exit condition is not met.
4. For languages where loops are assumed to be finite (like C and C++), the compiler deduces that an infinite loop implies undefined behavior (UB). Consequently, it assumes that the loop must invoke UB if entered.
5. However, because the start value of the recurrence is already zero, the exit condition is satisfied immediately, and the loop terminates normally without infinite looping.
6. The compiler's failure to check if the start value is non-zero before assuming UB leads to miscompilation. The compiler incorrectly optimizes the control flow based on the false UB assumption, which can result in aggressively eliminating the loop, dropping subsequent instructions, or computing an incorrect loop trip count.

---

# Issue 135531

## Incorrect Shift of Negative Constant Multiplier in SCEV Factorization

**Description:**
The bug is triggered by a sequence of operations involving a multiplication by a negative constant with a no-signed-wrap (`nsw`) flag, followed by a bitwise `and` operation (or an operation that masks bits).

When the compiler's scalar evolution analysis attempts to simplify the bitwise `and` expression, it looks for common powers of two (trailing zeros) between the constant multiplier and the `and` mask to factor them out. To achieve this, it shifts the constant multiplier to the right by the common number of trailing zeros.

However, the compiler incorrectly applies a logical right shift instead of an arithmetic right shift. When the constant multiplier is negative, the logical shift fills the most significant bits with zeros, transforming the small negative constant into a large positive constant. The compiler then constructs a new multiplication expression with this large positive constant while incorrectly preserving the original `nsw` (and potentially `nuw`) flags. Because the new multiplier is excessively large, the multiplication easily overflows its type bounds during evaluation, yielding a poison value and leading to a miscompilation.

---

# Issue 156849

## Incorrect Elision of Unsigned Overflow Checks for Truncated Loop Exit Counts

**Description**:
The bug is triggered by a loop containing an induction variable that starts at zero and increments by a known positive step. Inside the loop, the induction variable is subjected to operations that cause it to wrap or be bounded, such as multiplication followed by a bitwise mask (e.g., `and`), or truncation to a narrower integer type.

When the compiler attempts to optimize or vectorize the loop, it computes runtime overflow checks to ensure the induction variable's progression remains valid across the loop iterations. During this process, if the loop's exit count is evaluated in a truncated type, the compiler may incorrectly assume that an unsigned overflow check is always false simply because the start value is zero and the step is positive.

This assumption is flawed because it fails to account for the fact that the step multiplied by the truncated exit count can still wrap around, or that the truncation of the exit count itself might strip significant leading bits. Consequently, the compiler erroneously elides the necessary overflow check. The absence of this check allows invalid loop transformations to proceed—such as vectorizing memory accesses using wide loads and shuffles—which completely ignore the wrapping or masking behavior of the original induction variable, leading to a miscompilation.

---

# Issue 56242

## Incorrect Context Usage for Loop PHI Node Incoming Values from Previous Iterations

**Description**:
To trigger this bug, construct a loop containing a PHI node at the loop header that receives a value from the loop backedge. This backedge value must be defined inside the loop body, meaning the PHI node holds the value computed in the *previous* iteration. Next, introduce a condition inside the loop that constrains the newly computed value in the *current* iteration. Finally, use the PHI node in a comparison or operation that is evaluated in a context where the condition on the current iteration's value is known to be true.

When the compiler attempts to simplify the comparison involving the PHI node, it analyzes the PHI node's incoming values to see if the condition holds for all of them. For the backedge incoming value, the compiler incorrectly verifies whether the value dominates the incoming block (e.g., the loop latch) rather than the PHI block (the loop header). Since the value defined inside the loop naturally dominates the loop latch, the compiler erroneously assumes it is safe to apply the contextual constraints from the current iteration to the value originating from the previous iteration. This mismatch in loop iteration contexts leads to an invalid simplification, such as incorrectly folding a conditional check to a constant.

---

# Issue 57187

## Hoisting Instructions with Context-Dependent Poison-Generating Flags

**Description**:
The bug is triggered by a transformation that moves an instruction without properly adjusting its context-dependent optimization flags. The strategy involves the following sequence:

1. **Context-Specific Flag Inference**: An instruction (such as an induction variable increment or a binary operator) is located in a specific basic block. Based on local facts or conditions dominating this block, the compiler correctly infers poison-generating flags (e.g., `nuw` or `nsw` for no-wrap guarantees).
2. **Instruction Hoisting**: A compiler transformation hoists this instruction to a new location earlier in the control flow (for example, to replace a congruent instruction or eliminate redundancy).
3. **Introduction of New Uses**: The transformation introduces new uses of the hoisted instruction in the new location that did not exist in the original program.
4. **Retention of Invalid Flags**: The transformation fails to drop or recompute the poison-generating flags for the hoisted instruction. It retains the flags that were only proven valid in the original, more restricted context.
5. **Poison Generation and Propagation**: Because the instruction is now executed in a broader context where the original guarantees no longer hold, the operation may violate the retained flags at runtime, generating a `poison` value.
6. **Undefined Behavior**: The generated `poison` value is consumed by the newly introduced uses (such as a conditional branch), leading to undefined behavior and a miscompiled program.

---

# Issue 59777

## Failure to Recompute Poison-Generating Flags When Reusing Dominating Instructions

**Description**:
When an optimization pass (such as induction variable simplification) attempts to hoist or reuse an existing instruction (e.g., a binary operator) to replace or merge with another instruction, it checks if the existing instruction already dominates the target insertion point. If it does, the compiler may short-circuit the hoisting process, leaving the instruction in its original position.

However, by short-circuiting, the compiler fails to strip or recompute the poison-generating flags (such as `nsw` or `nuw`) on the reused instruction. Because the instruction is now being used in a broader or different context to serve additional uses, the original flags might no longer be valid. This oversight causes the reused instruction to incorrectly produce a poison value during execution when the operation overflows in the new context, leading to a miscompilation.

---

# Issue 60944

## Incorrect No-Wrap Flags on Expressions from Finite Loop Non-Strict Predicate Simplification

**Description**:
The bug is triggered when a finite loop's exit condition is controlled by a non-strict comparison predicate, such as signed/unsigned less-than-or-equal (`sle`, `ule`) or greater-than-or-equal (`sge`, `uge`).

To optimize the loop, the compiler attempts to canonicalize the non-strict comparison into a strict one. For example, it converts `X <= Y` into `X < Y + 1`. The compiler justifies this transformation by assuming that because the loop is known to be finite, the boundary value `Y` cannot be the maximum (or minimum) possible value of its type; otherwise, the loop would iterate infinitely.

However, the transformation logic contains two critical flaws that lead to miscompilations:
1. **Invalid Global No-Wrap Flags**: When constructing the new arithmetic expression (e.g., `Y + 1`), the compiler incorrectly attaches no-wrap flags (such as `nsw` or `nuw`) to it. Because scalar evolution expressions are cached and shared globally across the entire function, this expression might be reused by other instructions outside the context of the loop exit. The no-wrap guarantee may not hold in those other contexts, causing the compiler to incorrectly deduce value ranges or generate poison values.
2. **Missing Loop-Invariance Check**: The compiler applies this simplification without verifying that the right-hand side of the comparison (`Y`) is loop-invariant. If `Y` varies across loop iterations, the assumption that it cannot reach the boundary value is invalid, making the transformation unsafe.

---

# Issue 63727

## Incorrect Instruction Reuse During Scalar Evolution Expansion Due to Poison Semantics Mismatch

**Description:**
The bug is triggered during the expansion of Scalar Evolution (SCEV) expressions when the compiler attempts to optimize by reusing an existing instruction that evaluates to the same mathematical SCEV expression.

The core issue arises from a mismatch in poison semantics between the simplified SCEV expression and the actual IR instruction being reused. An existing instruction can be "more poisonous" than its corresponding SCEV expression. This typically happens when the instruction's computation graph includes operands or operations that can generate or propagate poison, but these poison contributors are mathematically simplified or abstracted away in the SCEV representation (for example, an operation like `0 * %var` simplifies to `0` in SCEV, but can still produce poison if `%var` is poison).

Previously, the compiler attempted to mitigate this by dropping poison-generating flags directly on the reused instruction. However, this was insufficient because poison could still be introduced by the instruction's operands or from deeper within its computation tree, which do not rely on flags attached to the root instruction itself.

When the compiler blindly reuses such an instruction to materialize a SCEV expression, it inadvertently injects unexpected poison into the program. If the expanded value is then used in a context where the original, simplified SCEV expression would have been well-defined, the leaked poison propagates and leads to miscompilation.

---

# Issue 63763

## Incorrect Instruction Reuse During SCEV Expansion Due to Poison Semantics Mismatch

**Description:**

The bug is triggered by a mismatch in poison semantics between a mathematical Scalar Evolution (SCEV) expression and the existing LLVM IR instructions chosen to represent it.

During loop optimizations and SCEV expansion, the compiler attempts to minimize redundant computations by reusing existing IR instructions that mathematically evaluate to the same SCEV expression. However, this reuse strategy can be unsafe if the existing instruction is "more poisonous" than the abstract SCEV expression it replaces.

The compiler previously attempted to mitigate this by dropping poison-generating flags (such as `nsw`, `nuw`, or `exact`) strictly on the root instruction being reused. This approach was insufficient and allowed the bug to be triggered through two primary patterns:

1.  **Deep Poison-Generating Flags:** The poison-generating flags might not reside on the directly reused root instruction, but rather on its operands or deeper within its instruction tree. Because the compiler only stripped flags from the root, the reused instruction tree could still produce poison.
2.  **Folded Poison Dependencies:** The existing instruction tree might depend on a potentially poisonous value that was mathematically simplified away in the SCEV representation. For example, an IR sequence computing `0 * %var` evaluates to poison if `%var` is poison. However, the SCEV analysis simplifies this expression to the constant `0`, which is never poison. If the compiler reuses the `0 * %var` IR sequence to represent the SCEV constant `0`, it inadvertently introduces poison into the program.

When these patterns occur, the compiler blindly replaces a well-defined SCEV expansion with an existing instruction tree that evaluates to poison at runtime. This injected poison then propagates through subsequent operations, ultimately leading to incorrect program execution and miscompilations.

---

# Issue 63926

## Incorrect Reuse of Poisonous Instructions During SCEV Expansion

**Description:**

The bug is triggered during the expansion of Scalar Evolution (SCEV) expressions back into LLVM IR. To optimize the generated code and avoid redundancy, the expander attempts to reuse existing instructions in the program that evaluate to the same mathematical SCEV expression.

The vulnerability arises when the expander reuses an existing instruction that is "more poisonous" than the SCEV expression it is meant to replace. While the compiler previously attempted to mitigate this by dropping poison-generating flags (such as `nsw` or `nuw`) directly on the reused instruction, it failed to account for poison introduced through other structural means.

Specifically, the bug is triggered when the extra poison in the reused instruction originates from:
1. **Operands:** The poison-generating flags or poison values might exist deeper in the operand tree of the reused instruction, rather than on the instruction itself.
2. **Folded Operations:** The reused instruction might involve operations that mathematically fold away in the SCEV model (for example, multiplying a potentially poisonous variable by zero, which SCEV evaluates as simply zero) but still propagate poison during actual IR execution.

By reusing such an instruction, the compiler inadvertently introduces `poison` into a code path where the original expression would have been well-defined. When this newly introduced poison propagates to operations that invoke undefined behavior (like memory accesses or branches), it results in a miscompilation.

---

# Issue 64333

## Incorrect Reuse of Instructions with Hidden Poison Dependencies in SCEV Expansion

**Description**:
The bug occurs when the compiler's scalar evolution expander reuses an existing instruction sequence to materialize a mathematical expression, but the existing sequence is "more poisonous" than the abstract expression it represents.

To trigger this issue, an instruction sequence must compute a value that the scalar evolution analysis simplifies away. For example, an operation where one operand mathematically cancels out another (such as a multiplication by zero or a masking operation). If the canceled-out operand is a poison value, the actual IR instruction sequence will evaluate to poison at runtime. However, the scalar evolution analysis models the result as a simpler expression (e.g., a constant zero), effectively ignoring the poison contribution of the canceled-out operand.

When the expander later needs to generate code for this simpler expression, it searches for existing instructions that match the same mathematical model. It finds and reuses the previously mentioned instruction sequence. The flaw in the transformation logic was that it only stripped poison-generating flags from the *directly* reused instruction. It failed to account for poison introduced by the instruction's operands or deeper instructions in its computation graph.

As a result, the reused sequence retains its hidden poison dependencies. By substituting a safe expression with an instruction graph that can produce poison, the compiler introduces poison into a new context where a well-defined value was expected, ultimately leading to a miscompilation.

---

# Issue 66616

## Stale SCEV Cache due to Incomplete Invalidation of LCSSA Phi Nodes

**Description:**
The bug is triggered by a sequence of loop transformations and analysis queries that leave stale data in the Scalar Evolution (SCEV) cache. The strategy to trigger this issue involves the following steps:

1. **Trivial LCSSA PHI Node:** A loop is structured such that its exit block contains a trivial LCSSA PHI node (e.g., a PHI node with a single incoming edge from the loop, or where all incoming values are identical).
2. **SCEV Analysis and Caching:** SCEV analyzes the loop and evaluates the trivial LCSSA PHI node. Because the PHI is trivial, SCEV looks right through it and directly caches expressions (such as `SCEVUnknown` or `SCEVAddRecExpr`) based on the underlying values defined inside the loop. These cached expressions may be stored in internal SCEV structures, such as backedge-taken counts, which do not maintain explicit IR-level use-def chains.
3. **Control Flow Modification:** A loop transformation pass (such as loop vectorization, unrolling, or peeling) modifies the control flow graph by adding a new predecessor to the loop's exit block. This modification turns the previously trivial LCSSA PHI node into a non-trivial one.
4. **Incomplete Invalidation:** The transformation pass notifies SCEV to invalidate the modified PHI node. However, the standard invalidation logic only walks the explicit IR use-def chains. It successfully invalidates the PHI node itself but fails to track down and invalidate the underlying loop-defined SCEV expressions that were cached earlier. Since these internal expressions lack direct IR use-def links to the PHI node, they remain in the cache.
5. **Crash or Miscompilation:** Subsequent optimization passes or utilities (like SCEVExpander) query SCEV and retrieve the stale, now-invalid expressions. Attempting to use or expand these stale expressions results in incorrect transformations, assertion failures, or compiler crashes.

---

# Issue 68260

## Stale Scalar Evolution Cache due to Truncated Invalidation Propagation

The bug occurs when the compiler's scalar evolution analysis fails to properly invalidate cached results for instructions that depend on memory operations or other typically "unanalyzable" instructions.

1. **Unanalyzable Instruction with Loop-Dependent Operands**: An instruction that is generally considered to produce an unknown scalar evolution (such as a memory load) takes an operand whose value depends on a loop (e.g., a pointer derived from an induction variable).
2. **Scope-Specific Evaluation**: The result of this instruction is used in further computations. When evaluated at a specific scope, such as outside the loop, the loop-dependent operands may resolve to constant loop exit values.
3. **Constant Folding at Scope**: Because the operands resolve to constants at that scope, the normally "unknown" instruction can be constant-folded or evaluated to a predictable value (e.g., a load from a constant address).
4. **Truncated Invalidation**: The compiler's cache invalidation logic incorrectly assumes that the unanalyzable instruction will *always* remain unknown, and therefore stops propagating invalidation updates to its users.
5. **Stale Cache Usage**: When the scalar evolution of the instruction's operands changes or is invalidated, the users of the unanalyzable instruction do not get their cached results invalidated. The compiler then uses these stale cached values for subsequent optimizations, leading to miscompilations such as incorrect constant folding or erroneous loop transformations.

This strategy highlights the danger of assuming certain instruction types act as opaque barriers for analysis dependencies, especially when scope-specific evaluations can resolve their operands to constants and create hidden dependencies.

---

# Issue 69097

## Incomplete Invalidation of SCEV Expressions for LCSSA Phi Nodes During Loop Transformations

**Description**:
The bug is triggered by a sequence of events involving Scalar Evolution (SCEV) and loop transformations that modify the Control Flow Graph (CFG):

1. **Trivial LCSSA Phi Node**: A loop has an exit block containing a trivial LCSSA phi node (e.g., a phi node with a single predecessor from the loop, or where all incoming values are identical).
2. **SCEV Caching**: When SCEV analyzes this trivial phi node, it looks through the phi and caches a SCEV expression (such as an AddRec or an Unknown value) that is defined inside the loop.
3. **CFG Modification**: A loop transformation (such as loop vectorization, unrolling, or peeling) adds a new predecessor to the loop's exit block. This structural change makes the previously trivial LCSSA phi node non-trivial.
4. **Incomplete Invalidation**: The transformation attempts to invalidate the SCEV cache for the modified phi node. However, the standard invalidation mechanism only traverses the IR use-def chains. It fails to catch and invalidate internal SCEV references (such as those used in Backedge Taken Counts) that directly use the loop-defined expressions.
5. **Miscompilation**: Because the internal SCEV uses are not thoroughly invalidated, SCEV retains stale, invalid expressions for the LCSSA phi node. Subsequent analyses or optimizations that query SCEV will receive incorrect information, leading to miscompilations such as incorrect loop trip counts or infinite loops.

---

# Issue 89958

## Unsafe Expansion of Potentially Faulting Operations in Sequential Expressions

**Description:**
The bug is triggered by the incorrect handling of conditionally executed operations that can cause undefined behavior (such as division by zero) when they are modeled and subsequently expanded by the compiler's scalar evolution analysis. The triggering strategy involves the following pattern:

1. **Guarded Faulting Operation:** A program contains a loop with an operation that can trigger undefined behavior if given certain operands (e.g., an integer division). In the original IR, this operation is protected by a conditional guard (such as a loop entry check or a branch) that ensures the faulting condition (e.g., a zero divisor) is never met.
2. **Modeling with Sequential Expressions:** The compiler analyzes the loop to compute properties like its trip count or exit values. It models the conditionally executed logic using sequential expressions (such as sequential min/max operations) that incorporate the potentially faulting operation.
3. **Unsafe IR Expansion:** When the compiler expands these sequential expressions back into LLVM IR (for example, during loop vectorization or unrolling), it evaluates the operands of the expression. However, the expansion process fails to preserve the original short-circuiting semantics or guarding conditions for the potentially faulting operation.
4. **Introduction of Undefined Behavior:** As a result, the potentially faulting operation is emitted unconditionally or without adequate protection in the optimized IR. If the program is executed with inputs that trigger the faulting condition, the operation is evaluated unsafely, leading to undefined behavior (such as a floating-point exception or trap) that did not exist in the original program.
