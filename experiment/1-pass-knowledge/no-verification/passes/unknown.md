# Issue 122537

## Bug Triggering Strategy: Incorrect `undef` Replacement due to TBAA Mismatch

### Description
The bug is triggered by a sequence of memory operations where Type-Based Alias Analysis (TBAA) incorrectly determines that a load and a store do not alias, leading to an invalid optimization by Global Value Numbering (GVN) or similar passes. The strategy involves the following high-level pattern:

1. **Uninitialized Memory Allocation**: A memory region is allocated using a function or instruction that provides uninitialized memory (e.g., `malloc` with an `allockind("uninitialized")` attribute).
2. **Store with Specific TBAA Tag**: A value is stored into the allocated memory. This store instruction is annotated with a specific TBAA metadata tag (e.g., representing a pointer to a generic type like `void*` or `omnipotent char`).
3. **Load with Mismatched TBAA Tag**: A value is subsequently loaded from the same memory location, but the load instruction is annotated with a different TBAA metadata tag (e.g., representing a pointer to a specific type like `float*`).
4. **Incorrect Alias Analysis**: Because the TBAA type descriptor graphs for the load and store differ, the alias analysis incorrectly concludes that the two memory accesses do not alias (`NoAlias`), failing to recognize that they might clobber each other (which should return `MayAlias`).
5. **Invalid Dependency Resolution**: When an optimization pass (such as GVN using Memory Dependence Analysis) attempts to find the defining access for the load, it bypasses the intervening store due to the incorrect `NoAlias` result.
6. **Miscompilation to `undef`**: The analysis resolves the load's dependency directly to the initial memory allocation. Since the allocation is known to return uninitialized memory, the optimization pass incorrectly assumes the loaded value is undefined and replaces the load instruction's result with an `undef` value, leading to a miscompilation.

---

# Issue 160112

## Dynamic Archive Format Upgrade with Precomputed Metadata

**Description:**
The bug is triggered when generating a static archive (library) from multiple object files under the following conditions:
1. The object files contain symbols with long names, which necessitates the creation of a string table within the archive.
2. The total size of the archive exceeds the maximum threshold for 32-bit offsets (or the threshold is artificially lowered during testing), which forces the archive writer to dynamically upgrade the archive format from a 32-bit format (such as COFF) to a 64-bit format (such as GNU64) to support larger file offsets.

The incorrect logic occurs because the archive writer computes structural metadata—such as headers, symbol maps, and string table offsets—based on the initial 32-bit format. When the size threshold is crossed later in the process, the format is dynamically switched to 64-bit, but the previously computed metadata is not recalculated. As a result, the archive is written using a mix of 32-bit metadata and 64-bit formatting, leading to malformed structures (e.g., unterminated string tables or incorrect offsets) that corrupt the final archive file.

---

# Issue 53218

## Incorrect Value Numbering of Instructions with Poison-Generating Flags

**Description**:
The bug is triggered when two identical instructions—differing only in their poison-generating flags (such as `nuw`, `nsw`, or `exact`)—are present in the same function. The optimization pass (like Global Value Numbering) hashes and compares these instructions while ignoring their flags, incorrectly determining that they are equivalent.

If the instruction with the poison-generating flags is selected as the leader and replaces the instruction without the flags, it effectively introduces these restrictive flags into a computation path where they did not originally exist. Subsequent optimization passes (such as instruction simplification) may then exploit these newly introduced flags to perform aggressive simplifications. This leads to a miscompilation because the simplifications are based on the false assumption that the operation will not trigger the poison condition (e.g., assuming no overflow occurs), altering the program's semantics for inputs that would violate those conditions.

---

# Issue 55291

## Miscompilation in Unsigned Remainder with All-Ones Divisor due to Undefined Value Duplication

**Description**:
The bug is triggered when an unsigned remainder operation (`urem`) is performed with a constant divisor consisting of all ones (the maximum unsigned value for the given integer type). The compiler attempts to optimize this operation by transforming it into a comparison and a select instruction: it checks if the numerator equals the all-ones value, returning 0 if true, and returning the numerator itself if false.

However, this transformation duplicates the numerator, using it as an operand in both the new comparison and the select instruction. If the numerator is an undefined value (`undef`), these duplicated uses can evaluate to different concrete values. For example, the comparison might evaluate to false, causing the select to return the undefined numerator, which could then be independently evaluated as the all-ones value. This violates the semantics of the original remainder operation, which mathematically can never return a value equal to or greater than the divisor. To prevent this miscompilation, the numerator must be explicitly frozen before being duplicated, ensuring it resolves to a single, consistent value across all its uses.

---

# Issue 59888

## Incorrect Metadata Inference When Pushing `freeze` Through Instructions

**Description**:
The bug is triggered by a transformation that moves a `freeze` instruction from the result of an operation to its operand(s). During or after this movement, the compiler infers value-restricting metadata (such as `!range`, `!nonnull`, etc.) for the operation.

The incorrect transformation logic stems from assuming that the newly frozen operand retains the same value properties (e.g., known bits or bounded ranges) as the original un-frozen operand. However, if the original operand evaluates to `poison` (for example, due to an out-of-bounds shift or other poison-generating behaviors), the `freeze` instruction will convert it into an arbitrary, non-poison value of the given type.

When the operation is executed with this arbitrary value, the result can easily fall outside the strict bounds specified by the inferred metadata. In LLVM IR, violating value-restricting metadata results in `poison`. Consequently, the transformed code may produce `poison` in cases where the original code guaranteed a frozen, well-defined value, leading to a miscompilation.

This pattern applies generally to any operation where `freeze` is pushed to the operands and the compiler overly constrains the operation's output with metadata based on the properties of potentially poison-generating inputs.

---

# Issue 63019

## Incorrect Merging of Partial Alias Results with Different Offsets

**Description**:
The bug is triggered when the compiler performs alias analysis on memory operations involving pointers that partially alias a memory location at different offsets. During the analysis, the compiler often needs to merge multiple alias results (for example, when analyzing pointers derived from control flow merges like PHI nodes or `select` instructions, or when aggregating alias information from different sources).

When merging these results, the compiler incorrectly evaluates two partial alias results with different offsets as equivalent. This happens because the comparison logic only checks the alias kind (i.e., whether they are both partial aliases) and completely ignores the specific offset values associated with them. As a result, the merged alias result loses crucial offset information.

Consequently, downstream memory optimization passes (such as Dead Store Elimination, Global Value Numbering, or Instruction Combining) rely on this inaccurate and overly broad alias information. This leads to invalid transformations, such as improper reordering of memory accesses, incorrect load/store forwarding, or the erroneous elimination of necessary memory operations.

---

# Issue 63885

## Incorrect Relocation Value for Local-Exec Thread-Local Storage (TLS) Accesses

**Description**:
The bug is triggered when a program defines and accesses multiple thread-local global variables using the `local-exec` Thread-Local Storage (TLS) model. At the LLVM IR level, this is represented by global variables marked with the `thread_local(localexec)` attribute.

During the compilation process, specifically in the object file emission phase, the compiler must generate appropriate relocations to resolve the addresses of these thread-local variables. However, the transformation logic fails to properly account for the specific relocation type associated with the `local-exec` model. Instead of calculating and writing the correct virtual address or offset for the symbol, the compiler writes a default or incorrect value (such as zero) to the relocation target.

As a result, the generated executable contains incorrect memory offsets for the thread-local variables. At runtime, accesses to a specific thread-local variable may incorrectly resolve to the address of a different thread-local variable, leading to silent miscompilations and incorrect program behavior.

---

# Issue 66984

## Incorrect Stack Slot Merging for SEH Catch Objects due to Unmodeled Implicit Writes

**Description**:
The bug is triggered by a miscompilation in the stack coloring optimization when handling Windows Structured Exception Handling (SEH). The strategy to trigger this issue involves the following pattern:

1. A function utilizes SEH and contains at least two stack allocations (allocas).
2. The first stack allocation is used exclusively within a cleanup block (`cleanuppad`).
3. The second stack allocation is used as the catch object within a catch block (`catchpad`), where the exception object is written.
4. Crucially, the catch object allocation has no explicit uses in the IR prior to the catch block.

The stack coloring pass attempts to minimize stack usage by merging stack slots whose lifetimes do not overlap. By default, it relies on a "first-use" analysis to determine when a stack slot's lifetime begins. Because the catch object's first explicit IR use is inside the catch block, the analysis incorrectly assumes its lifetime starts at that point.

However, in SEH, the personality function implicitly writes the exception object to the catch object's stack slot *before* any cleanup blocks are executed during the unwinding process. Since this implicit write is not explicitly modeled in the LLVM IR, the first-use analysis fails to account for it.

As a result, the compiler incorrectly concludes that the lifetime of the cleanup block's allocation ends before the catch object's lifetime begins. It then assigns both allocations to the same stack slot. During execution, the personality function writes the exception object to the shared slot, but the subsequent execution of the cleanup block overwrites it, leading to corrupted exception data and a miscompilation.
