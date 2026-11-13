# Issue 121745

## Incorrect Live-Out Extraction from Uniformly Scalarized Loop Instructions

**Description:**
The bug occurs during loop vectorization when handling instructions whose results are used outside the loop (live-out values), particularly those associated with induction variables or complex loop updates.

1. **Uniform Scalarization:** During vectorization planning, the vectorizer may identify certain instructions (such as specific induction variable updates or expressions involving loop-invariant loads) as "uniform." Consequently, it models them to be scalarized uniformly, meaning the instruction is only executed once per vector iteration to compute the value for the first vector lane, rather than computing the values for all lanes.
2. **Live-Out Extraction:** Because the result of this instruction is used outside the loop, the vectorizer must extract its final value from the last iteration of the loop. This requires retrieving the value corresponding to the last lane of the final vector iteration.
3. **Mismatch and Miscompilation:** Since the instruction was uniformly scalarized, the value for the last lane is never actually computed or made available. The extraction logic incorrectly retrieves the only available scalar value—which corresponds to the first lane of the last vector iteration.
4. **Result:** The program uses an incorrect live-out value (e.g., the value from the first lane instead of the last lane of the final vector block), leading to a miscompilation. This pattern is typically triggered when complex induction expressions are incorrectly assumed to be safe for uniform replication without accounting for the necessity of the final lane's value for live-out extraction.

---

# Issue 122496

## Incorrect Uniformity Analysis for Induction Variable Updates with Outside Users

**Description**:
To trigger this bug, the following pattern can be constructed at the LLVM IR level:

1. **Create a loop with an induction variable**: Define a loop controlled by an induction variable (IV).
2. **Use the IV update outside the loop**: Ensure that the instruction responsible for updating the induction variable (e.g., the increment operation) has at least one user outside the loop. This typically manifests as an LCSSA PHI node that captures the exit value of the IV for later use (e.g., when the IV corresponds to a global variable or is returned from a function).
3. **Keep internal uses uniform**: Constrain all uses of the IV update *inside* the loop to be uniform. For example, the update should only be used by the induction PHI node itself, the loop exit condition, or uniform memory accesses.
4. **Trigger the miscompilation**: During loop vectorization, the uniformity analysis evaluates the IV update. Because the analysis incorrectly ignores out-of-loop users when determining uniformity, it classifies the IV update as strictly uniform.
5. **Resulting behavior**: By treating the IV update as uniform, the vectorizer assumes it does not need to extract the final scalar value from the appropriate vector lane for the out-of-loop user. This results in the generation of incorrect code for the exit value (often just taking the value from the first lane or failing to compute the final chain of uniform instructions), leading to a miscompilation or runtime crash.

---

# Issue 122602

## Incorrect Uniformity Analysis for Induction Variables with Outside Users

**Description:**
The bug is triggered by a loop containing an induction variable where the induction update instruction (e.g., the increment operation) is used outside the loop.

The strategy to trigger this issue involves the following conditions:
1. **Uniform Inside Users**: All users of the induction update instruction *inside* the loop must be uniform (for example, the induction PHI node itself or other uniform operations).
2. **Outside Users**: The induction update instruction (or a chain of instructions derived from it) must have at least one user *outside* the loop, typically using it as an exit value.
3. **Flawed Uniformity Analysis**: The loop vectorizer's uniformity analysis incorrectly ignores users outside the loop when determining if an instruction is uniform. Because all inside-loop users are uniform, the vectorizer mistakenly classifies the induction update as uniform.
4. **Miscompilation**: During vectorization, uniform instructions are often optimized to only compute or preserve the scalar value for the first vector lane. However, the user outside the loop requires the value from the final loop iteration (which corresponds to the last active lane of the vector). Because the instruction was treated as uniform, the correct final value is not extracted, and the outside user receives an incorrect value (e.g., from the first lane), leading to a miscompilation.

By ensuring the induction update is used outside the loop while keeping its internal uses uniform, the vectorizer is tricked into applying an invalid scalarization/uniformity optimization, failing to provide the correct exit value.

---

# Issue 125374

## Loop-Variant Header Phi Replaced by Constant Breaking Cyclic Dependencies

**Description:**
The bug is triggered by creating a loop with a cyclic dependency, such as a reduction or recurrence, where the loop header phi node evaluates to a constant value across all iterations.

The strategy to trigger this miscompilation involves the following steps:
1. **Constant Cyclic Dependency**: Define a loop with a header phi node that is updated by an operation in the loop body (e.g., a reduction accumulator). Construct the operation such that the value remains unchanged throughout the loop's execution (e.g., adding `0`, multiplying by `1`, or bitwise ORing with `0`).
2. **SCEV Constant Evaluation**: Because the value never changes, the Scalar Evolution (SCEV) analysis correctly determines that the loop-variant phi node is mathematically equivalent to a constant.
3. **Operand Replacement**: During the vectorization process, the compiler queries SCEV to simplify operands. It incorrectly replaces the use of the loop-variant phi node in the loop body with the evaluated constant.
4. **Broken Dependency Chain**: This replacement severs the structural def-use chain of the cyclic dependency. The loop body operation no longer references the header phi, which destroys the expected reduction or recurrence pattern.
5. **Miscompilation**: Because the dependency chain is broken, the vectorizer fails to properly accumulate or propagate the value across vector lanes and iterations. It generates incorrect vectorized code that uses the constant directly instead of maintaining the accumulator, leading to an incorrect final result.

---

# Issue 142957

## Speculative Execution of Loads with Poison-Generating Address Computations

**Description:**
The bug is triggered when a loop contains a conditionally executed load whose address computation depends on an instruction that is not safe to speculatively execute (e.g., an operation that may trap, such as a division) or an operand that may be `poison`.

During loop vectorization, the compiler may decide to if-convert the loop and speculatively execute the load unconditionally. To prevent the unsafe instruction in the address computation from causing undefined behavior, the compiler predicates it. Consequently, when the execution condition is false, the predicated instruction is bypassed and produces a `poison` value.

This `poison` value propagates through the rest of the address computation, ultimately resulting in a `poison` pointer. Because the load has been speculated and executes unconditionally, it dereferences the `poison` pointer whenever the original condition is false. This introduces instant undefined behavior into a previously well-defined program. The underlying issue is that the compiler evaluated the load's safety for speculation without verifying whether the computations feeding its pointer could safely execute unconditionally without producing `poison`.

---

# Issue 149347

## Divergence in Loop-Invariant Analysis for Uniform Stores in Loop Vectorization

**Description:**
The bug is triggered by a mismatch in how different phases of the loop vectorizer determine if a value is loop-invariant, specifically when handling store instructions.

1. **Target Pattern**: A loop contains a store instruction that writes to a loop-invariant memory address. The value being stored is also loop-invariant, but this invariance is not structurally obvious. For example, the value might be a PHI node where the only active incoming edge provides a constant, while other edges come from dead or unreachable control flow blocks.
2. **Advanced Analysis vs. Structural Analysis**: The vectorizer's cost model and predication logic use an advanced analysis framework (like Scalar Evolution) to evaluate the stored value. This analysis successfully proves that the value is loop-invariant despite the complex control flow.
3. **Bypassing Predication**: Because both the pointer and the stored value are deemed invariant by the advanced analysis, the vectorizer decides that the store does not need to be predicated. It optimizes it into a uniform store that can execute unconditionally.
4. **Code Generation Divergence**: During the actual vector code generation (e.g., via VPlan), the system relies on a simpler, structural invariance check (such as verifying if the value's definition physically resides outside the loop). Under this stricter check, the value is not recognized as invariant.
5. **Incorrect Lane Extraction**: Since the code generator treats the value as a varying vector rather than a uniform scalar, it attempts to perform the uniform store by extracting the value from the last lane of the vector.
6. **Miscompilation**: Because the store was originally part of conditional control flow or a PHI node with dead paths, the last lane might correspond to a masked-out or inactive execution path. Extracting from this lane yields an incorrect value (e.g., a default or garbage value from the dead branch), which is then stored to memory, resulting in a miscompilation.

This strategy highlights the danger of using a powerful analysis in the optimization decision phase while relying on a weaker analysis during code generation, leading to inconsistent handling of uniform stores and incorrect lane extractions.

---

# Issue 153946

## Poison Propagation in Early-Exit Loop Vectorization via Unfrozen Boolean Reductions

**Description**:
The bug is triggered by vectorizing a loop that contains an early exit, where the exit condition can evaluate to `poison` for certain iterations. The strategy involves the following steps at the LLVM IR level:

1. **Construct a loop with an early exit**: Create a loop where a specific condition causes the loop to terminate before reaching its maximum trip count.
2. **Introduce a poison-generating operation**: Formulate the early exit condition using an instruction that will produce a `poison` value for iterations that would normally be skipped in a scalar execution. Examples include oversized bitwise shifts, out-of-bounds memory accesses, or operations with `nsw`/`nuw` flags that overflow in later iterations.
3. **Trigger early-exit vectorization**: Force the compiler to vectorize the loop. During this transformation, the vectorizer evaluates the loop body and the early exit condition for multiple lanes (and potentially unrolled iterations) simultaneously.
4. **Reduce the exit condition**: The vectorizer combines the boolean exit conditions from all vector lanes into a single scalar boolean value using a reduction operation (such as an OR reduction) to determine if any lane triggered the early exit.
5. **Propagate poison**: Because the vectorizer fails to freeze the inputs before feeding them into the boolean reduction, a `poison` value originating from a lane that would not have been executed in the scalar loop propagates through the reduction.
6. **Resulting Miscompilation**: The entire reduced boolean result becomes `poison`. When this `poison` value is used for subsequent control flow or arithmetic operations outside the loop, it leads to undefined behavior, such as incorrect branching or floating-point exceptions (e.g., division by zero).

---

# Issue 155162

## Poison Propagation in Early-Exit Loop Vectorization

**Description**:
When a loop containing an early exit is vectorized, the compiler evaluates the exit condition across multiple lanes simultaneously. To determine if the early exit should be taken, the compiler reduces the boolean results of the condition from all lanes into a single scalar boolean value (typically using a sequence of bitwise OR operations or a vector reduction).

If the exit condition evaluates to `poison` for any lane—which can happen due to operations like out-of-bounds shifts, invalid memory accesses, or other undefined behaviors in lanes that would normally be unreachable or skipped in the scalar execution—the `poison` value propagates through the boolean reduction. Because bitwise operations with `poison` yield `poison`, the entire reduced scalar result becomes `poison` if even a single lane is `poison`.

Subsequently, using this `poison` value as the branch condition for the early exit leads to undefined behavior and miscompilation. To trigger this issue, one can construct a vectorizable loop with an early exit where the condition involves an operation that naturally produces `poison` for certain iterations (e.g., a shift amount exceeding the type's bit-width). When vectorized, the evaluation of these iterations in parallel lanes injects `poison` into the reduction tree, corrupting the control flow.

---

# Issue 156190

## Repeated Narrowing of Interleaved Memory Accesses During Loop Vectorization

**Description**

The bug is triggered by a loop containing interleaved memory accesses, such as loading elements from an array of structures or complex numbers. During loop vectorization, the compiler may decide to simplify or "narrow" these interleave groups to optimize the memory access pattern.

The issue arises from a flaw in the transformation logic where the compiler fails to track which operations have already been narrowed. Consequently, an interleaved load operation is subjected to the narrowing process multiple times. It is first narrowed from an interleave group to a wide vector load, which is the correct intermediate step. However, because the newly created wide load is not marked as processed, it is erroneously narrowed again into a single-scalar load.

As a result of this repeated narrowing, the compiler generates instructions that load only a single scalar value (e.g., the first element of the structure, such as the real part of a complex number) from memory. This single value is then incorrectly broadcasted or reused for all other elements in the interleaved structure (e.g., using the real component for both the real and imaginary parts). This leads to a miscompilation where the vectorized loop produces incorrect results by duplicating the first element across the entire vector or structure.

---

# Issue 160912

## Incorrect No-Wrap Assumption for Conditionally Dereferenced Pointers in Loop Analysis

The bug occurs in loop analysis passes (such as memory dependence analysis, loop vectorization, or load elimination) when evaluating pointer arithmetic instructions that carry no-wrap flags (e.g., `inbounds` or `nusw`).

The compiler uses these no-wrap flags to infer that the pointer address computation does not wrap around the address space, which is a crucial property for calculating strides and proving the absence of memory dependences across loop iterations. However, this inference is only sound if the pointer is guaranteed to be dereferenced (via a load or store) in every iteration of the loop. If a pointer wraps but is never actually dereferenced, it merely yields a poison value without causing immediate undefined behavior.

The bug is triggered when a loop contains a memory access that is executed conditionally (e.g., guarded by a branch or an `if` statement inside the loop), but the pointer used for the access is derived from an instruction with a no-wrap flag. The compiler incorrectly applies the no-wrap assumption globally to the entire loop, failing to account for the fact that the pointer might wrap during iterations where the conditional memory access is bypassed.

By falsely assuming the pointer never wraps under any circumstance, the compiler's dependence analysis may incorrectly conclude that memory accesses do not overlap or have safe dependence distances. This flawed analysis subsequently allows the compiler to perform invalid loop transformations, such as unsafe vectorization or incorrect load forwarding, leading to miscompilations.

---

# Issue 162498

## Incorrect Value Extraction for Stores with Per-Part Uniform Addresses During Loop Unrolling

**Description:**

The bug is triggered when the loop vectorizer processes a loop containing a memory store operation with the following characteristics:
1. **Per-Part Uniform Address:** The destination address of the store evaluates to the same location within a single vector part (i.e., across the vectorization factor) but varies across different unrolled parts (i.e., across the unroll factor). This pattern frequently occurs when the memory address is computed using operations like right shifts or integer divisions on the loop induction variable.
2. **Varying Stored Value:** The actual data value being stored is not uniform and changes across consecutive loop iterations (e.g., it is directly derived from the induction variable).

During vectorization and unrolling, the compiler attempts to optimize these memory writes. Because the destination address is uniform within a given vector part, the compiler correctly deduces that it only needs to perform a single scalar store per unrolled part, writing only the final value that would be stored in that part's sequence of iterations.

However, the transformation logic contains a flaw in how it selects the scalar value to store. Instead of extracting the last lane's value specific to *each individual unrolled part*, the compiler incorrectly extracts the last lane's value across *all* unrolled parts (i.e., the value corresponding to the very last iteration of the entire unrolled block).

Consequently, the generated code performs multiple scalar stores to different addresses (one for each unrolled part), but incorrectly writes the exact same value—the one from the final unrolled iteration—to all of them. This leads to a miscompilation where memory locations corresponding to earlier parts are erroneously overwritten with future values.

---

# Issue 162512

## Incorrect LCSSA Preservation During Expression Expansion in Temporarily Disconnected Blocks

**Description**:
During loop vectorization, the compiler often generates runtime checks (such as memory dependence or bounds checks) early in the transformation process and places them in basic blocks that are temporarily disconnected from the main Control Flow Graph (CFG). Later, the compiler expands loop-invariant expressions (e.g., Scalar Evolution expressions) required for the vectorized loop.

If the expression expansion process is configured to preserve Loop-Closed SSA (LCSSA) form, it will attempt to identify and rewrite uses of loop-defined values outside the loop by inserting LCSSA PHI nodes. However, because the basic blocks containing the runtime checks are temporarily unreachable at this stage, the LCSSA preservation logic can incorrectly replace uses or insert malformed references within these disconnected blocks. When these blocks are eventually reconnected to the CFG, the improperly updated uses persist, leading to a miscompilation.

To trigger this issue, a loop must require runtime checks (e.g., due to potential memory aliasing) and contain loop-invariant expressions whose expansion invokes LCSSA updates while the check blocks are in a detached state.

---

# Issue 168902

## Incorrect Preservation of No-Wrap Flags on Truncated Induction Variables During Vectorization

**Description:**
The bug is triggered by the loop vectorizer when it processes an integer induction variable that is truncated to a narrower type inside a loop. The strategy to trigger this issue involves the following pattern:

1. A loop contains an integer induction variable whose increment operation is marked with no-wrap flags (such as `nsw` for no signed wrap or `nuw` for no unsigned wrap).
2. Within the loop body, this induction variable is truncated to a narrower integer type.
3. When the loop is vectorized, the vectorizer attempts to optimize this pattern by creating a new widened vector induction variable directly in the narrower type, rather than widening the original type and then truncating it.
4. During this transformation, the vectorizer incorrectly propagates the no-wrap flags from the original, wider induction variable to the new, narrower vector induction variable.
5. Because the narrower type has a much smaller representable range, its increment operations may legitimately overflow during loop execution, even if the original wider induction variable does not.
6. The incorrectly retained no-wrap flags on the narrower induction variable cause these legitimate overflows to generate `poison` values. This leads to miscompilations in subsequent optimization passes, such as incorrect constant folding or invalid simplifications based on the false assumption that the narrower induction variable will never wrap.

---

# Issue 180781

## Incorrect Uniformity Assumption for Sunk Instructions in Loop Vectorization

**Description**:
During loop vectorization and interleaving (unrolling), the compiler analyzes whether values are uniform across different vector lanes (Vectorization Factor, VF) and unroll parts (Unroll Factor, UF). A bug is triggered when an instruction originally inside the loop is sunk out of the loop body into a post-loop block (such as the loop exit block).

The vectorizer's uniformity analysis incorrectly assumes that any instruction located outside the loop region is inherently uniform across all VFs and UFs. While this assumption is valid for instructions in the loop preheader or entry blocks (which are defined before the loop executes and are truly loop-invariant), it is invalid for instructions sunk to exit blocks. These sunk instructions often compute final values (like inductions, reductions, or loop-variant expressions used outside the loop) and their results may still depend on the specific vector lane or unroll part computed during the loop's execution.

Because the compiler mistakenly treats these sunk instructions as uniform, it may fail to properly replicate the instruction for different unroll parts or fail to extract the correct lane values. This leads to miscompilations where the final sunk value is incorrectly generated, often using the wrong unroll part or a single scalar instance instead of accounting for the vectorized/interleaved state.

---

# Issue 51677

## Loop Vectorization Miscompilation with Tail Folding and Escaping Induction Variables

**Description**
The bug is triggered by a specific combination of loop vectorization, tail folding by masking, and an induction variable that escapes the loop. The triggering strategy involves the following pattern:

1. **Induction Variable with Outside Users**: A loop is defined with an induction variable (IV), and the value of this IV is used outside the loop body (e.g., it escapes the loop and is consumed by an instruction in the exit block).
2. **Tail Folding by Masking**: The loop is vectorized, and the compiler applies an optimization known as "tail folding by masking." This optimization eliminates the need for a separate scalar epilogue loop by rounding up the loop's trip count to a multiple of the vectorization factor.
3. **Execution of Padded Iterations**: To handle the rounded-up trip count safely, the vectorizer masks the operations in the final vector iteration, preventing out-of-bounds memory accesses or side effects for the extra "padded" elements.

**The Core Issue**:
While memory operations and other side effects are correctly masked during the padded iterations, the induction variable itself continues to be incremented. Because the loop executes additional logical iterations to fill the final vector, the induction variable reaches a value greater than its original scalar final value. When the IV is used outside the loop, the escaping value reflects these extra padded iterations rather than the correct final value dictated by the original loop bounds. This results in the outside user consuming an incorrect, out-of-bounds value, leading to a miscompilation.

---

# Issue 57712

## Pointer Induction Widening Mismatch in Epilogue Vectorization

**Description**
The bug is triggered during loop vectorization when epilogue vectorization is applied to a loop containing a pointer induction variable.

The issue arises from a discrepancy between the vectorizer's cost model and the actual vectorization plan's execution logic. Specifically, the cost model evaluates the loop and determines that the pointer induction variable should remain scalar after vectorization. The epilogue vectorization phase relies on this cost model decision, assuming that no widened vector versions of the induction variable need to be generated, and therefore does not prepare the necessary widened start values.

However, during the execution of the vectorization plan, the logic that determines whether to generate only scalar values for the pointer induction evaluates the variable's users independently, rather than strictly adhering to the cost model's prior decision. This can result in the vectorization plan incorrectly deciding to widen the pointer induction variable.

Because the epilogue vectorizer did not prepare for this widening, the newly created widened PHI nodes for the pointer induction in the epilogue vector loop are initialized with incorrect start values. This leads to incorrect memory address calculations during the loop's execution, resulting in miscompilations such as reading from or writing to the wrong memory locations.

---

# Issue 59459

## Incorrect Start Value for Widened Induction Variables in Epilogue Vector Loops

When a loop is vectorized and an epilogue vector loop is generated, the start value for widened induction variables (such as integer, floating-point, or pointer inductions) in the epilogue vector loop is incorrectly initialized.

Instead of using the proper resume value calculated after the execution of the main vector loop, the epilogue vector loop erroneously reuses the initial start value of the original scalar loop. This causes the epilogue loop to process the wrong sequence of induction values, leading to incorrect computations and miscompilations when the induction variable is used in vector operations (e.g., being multiplied and stored to memory).

To trigger this bug, a loop containing an induction variable must be vectorized such that it produces both a main vector loop and an epilogue vector loop (for instance, when the trip count is not a perfect multiple of the vectorization factor), and the induction variable must be widened within the vector loop body.

---

# Issue 61396

## Loop Vectorizer Miscompilation on Store Instructions with Identical Pointer and Value Operands

**Description**

The bug is triggered when a loop contains a store instruction where the value being stored is exactly the same as the destination memory address (the pointer operand).

During loop vectorization, the compiler analyzes the uniformity of values across vector lanes to optimize the generated code. For contiguous memory accesses, the vectorizer typically considers the base pointer of the access as uniform, because a single widened vector memory operation only requires the base address to perform the operation for all lanes.

However, when the pointer is also the value being stored, its value must vary across the vector lanes (i.e., each lane should store its own specific memory address). The uniformity analysis fails to account for this dual use of the pointer. It merely checks if the pointer is used as the destination address of a vectorized memory access and, if so, incorrectly marks the pointer as uniform.

As a result, the vectorizer assumes the stored value is also uniform and broadcasts the base address of the first vector lane to all lanes in the vector, rather than generating a vector of varying addresses. This leads to incorrect code generation where multiple consecutive memory locations are erroneously initialized with the same base address instead of pointing to their respective individual addresses.

---

# Issue 62565

## Miscompilation of "AnyOf" Reductions with Undef/Poison Initial Values

**Description**:
The bug is triggered when the loop vectorizer processes an "AnyOf" reduction pattern. In this pattern, a loop conditionally selects a new loop-invariant value if a specific condition is met; otherwise, it retains the initial reduction value (start value).

During vectorization, the compiler's transformation logic tracks the reduction state by repeatedly comparing the current reduction vector against the initial start value to determine if the new value has been selected in any lane. This approach introduces multiple new uses of the initial start value across the vectorized loop body and the reduction epilogue.

If the initial start value is `undef`, `poison`, or an input that causes the comparison to yield `poison`, these multiple uses become problematic. Subsequent optimization passes can evaluate each use of `undef` or `poison` independently and inconsistently. Because the generated vector code relies on the assumption that all comparisons against the start value will yield consistent results, the independent evaluation of these undefined values breaks the reduction logic. This leads to conflicting selections between the initial value and the new value, ultimately resulting in a miscompilation.

---

# Issue 62954

## Incorrect Elimination of First-Order Recurrence Used Only Outside the Loop

**Description**:
To trigger this bug, the following conditions must be met at the LLVM IR level:
1. **First-Order Recurrence**: Define a loop that computes a first-order recurrence (a value computed in one iteration that is used in the next).
2. **Live-Out Only Usage**: Ensure that the result of the recurrence is not used anywhere inside the loop body, but is only used outside the loop (i.e., it is a live-out value).
3. **Scalar Epilogue Requirement**: Trigger loop vectorization in a way that requires a scalar epilogue loop to be generated (for example, by having a loop trip count that is not a multiple of the vectorization factor).

When these conditions are met, the vectorizer's dead code elimination logic incorrectly identifies the recurrence instructions as dead. This happens because the recurrence's only use—providing the resume value for the scalar epilogue loop—is implicit and not explicitly modeled in the internal vectorization plan. Consequently, the recurrence instructions are erroneously removed, leading to a miscompilation where the scalar epilogue loop is left without its correct resume value.

---

# Issue 64047

## Incorrect Ordering of Sunk Invariant Stores in Multiple Reductions

**Description**:
The bug is triggered by a loop that contains multiple reduction operations, where these reductions also involve intermediate stores to loop-invariant memory locations (e.g., storing the intermediate reduction value to a global variable or an invariant pointer).

During loop vectorization, the compiler optimizes these intermediate invariant stores by sinking them out of the loop and into the loop's exit block, so that the memory location is only updated once with the final reduced value after the loop finishes.

The incorrect transformation logic occurs when the vectorizer processes these multiple reductions. It iterates through the reduction PHI nodes and sinks their corresponding invariant stores without considering the original execution order (dominance relationship) of those stores within the loop body. Consequently, the sunk stores are emitted in the exit block in an arbitrary order (typically the order of the PHI nodes). If the original stores had a specific sequential dependency or updated the same/aliasing memory locations, altering their final execution order in the exit block results in the wrong value persisting in memory, leading to a miscompilation.

To trigger this, one needs to construct a loop with multiple reductions that store their intermediate results to loop-invariant addresses, ensuring that the final program state depends on the strict original ordering of these stores.

---

# Issue 65212

## Loop Vectorizer Fails to Preserve Alignment for Reduction Intermediate Stores

**Description**:
The bug is triggered when a loop performs a reduction operation and continuously stores the intermediate reduction value to a memory location within the loop. Crucially, this intermediate store instruction must have an explicit alignment that is smaller than the default ABI alignment for the stored data type (for example, an alignment of 1 for a 16-bit integer).

When the loop vectorizer processes this loop, it optimizes the reduction and generates a final store instruction outside the vectorized loop to write the fully reduced value to memory. However, the transformation logic fails to propagate the explicit alignment from the original intermediate store to the newly created final store. As a result, the new store is generated using the target's default alignment for that type, which is larger than the original alignment. This incorrectly increases the alignment requirement of the memory access, potentially leading to memory access violations or undefined behavior if the actual memory address does not meet the stricter default alignment boundary.

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

# Issue 75298

## Incorrect Elimination of Conditional Operations in Tail-Folded Loop Reductions

**Description:**
When a loop containing a reduction is vectorized using tail-folding, the compiler often inserts conditional operations (such as `select` instructions) to correctly handle the reduction of elements in the final, partial iteration (the "tail").

If the final result of this reduction is only used outside the main vector loop (for example, stored to memory after the loop terminates), the compiler's internal representation may fail to properly track these external users. If the conditional operation is simultaneously classified as having no side effects, the compiler may incorrectly determine that the operation is unused within the loop and eliminate it as dead code. This results in a miscompilation where the reduction is not properly updated for the tail elements, leading to incorrect final values being computed and stored.

---

# Issue 76069

## Loop Vectorization Miscompilation with Tail-Folding and Outside Induction Variable Users

**Description**:
The bug is triggered when a loop is vectorized using tail-folding by masking, and an induction variable from the loop is used outside of the loop body (i.e., it is a live-out value).

Tail-folding by masking is an optimization where the vectorizer avoids generating a separate scalar epilogue loop by padding the vector loop's iteration count to a multiple of the vectorization factor. It uses active lane masks to prevent out-of-bounds memory accesses or side effects during the final, partially filled vector iteration.

However, a miscompilation occurs if an induction variable is used outside the loop (for example, in an exit block). The final value of the induction variable for outside users is computed based on the total number of iterations executed by the vector loop. Because tail-folding artificially inflates the iteration count to match the vectorization factor, the computed final value of the induction variable reflects these padded iterations rather than the exact original scalar loop bounds. Consequently, the outside user consumes an incorrect, over-incremented value, which can lead to downstream errors such as out-of-bounds array accesses or incorrect subsequent computations.

---

# Issue 81872

## Incorrect Dropping of Poison-Generating Flags in Vectorized Address Computation

## Description
The bug is triggered by a mismatch between how loop analyses and the loop vectorizer handle poison-generating flags during the vectorization of conditional memory accesses. The strategy to trigger this issue involves the following steps:

1. **Conditional Address Computation**: Construct a loop containing a conditionally executed block. Inside this block, perform a memory operation where the address computation relies on an instruction with a poison-generating flag. A prime example is an `or` instruction with a `disjoint` flag, which is mathematically equivalent to an `add` instruction because the operands are known to have no overlapping bits when the dominating condition is true.
2. **Analysis Assumption**: Loop analyses (such as Scalar Evolution used for dependence analysis) analyze the memory access and model the address computation based on the strict arithmetic equivalence implied by the flag (e.g., treating the `or disjoint` exactly as an `add`).
3. **Unconditional Execution and Flag Dropping**: When the loop vectorizer transforms the loop, it converts the conditional control flow into a masked vector operation. The address computation is hoisted and executed unconditionally across all vector lanes. To prevent generating poison values in inactive lanes (where the condition is false and the operands might overlap), the vectorizer drops the poison-generating flag (e.g., converting `or disjoint` back to a regular `or`).
4. **Incorrect Base Address Calculation**: For contiguous vector memory operations, the vectorizer computes a single base address, often using the address evaluated for one specific lane (which might happen to be an inactive lane). Because the flag was dropped, the instruction no longer behaves like the assumed arithmetic operation for inactive lanes (e.g., a regular `or` does not carry over bits like an `add` does when operands overlap).
5. **Miscompilation**: Consequently, the base address for the vector memory operation is computed incorrectly. Even though the memory operation is properly masked, the wrong base address shifts the memory accesses for the active lanes, leading to incorrect memory reads or writes.
