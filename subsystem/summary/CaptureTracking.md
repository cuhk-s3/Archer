# Subsystem Knowledge for CaptureTracking

## Elements Frequently Missed

* **Ephemeral Instructions**: Instructions whose results are ultimately only used by assumption intrinsics (e.g., `llvm.assume`). They are frequently missed because CaptureTracking prematurely ignores them under the assumption that they do not affect observable program behavior and will eventually be removed.
* **Pointer-to-Integer Conversions (`ptrtoint`)**: When a `ptrtoint` instruction is part of an ephemeral chain, its inherent behavior of capturing a pointer is overlooked by the analysis.
* **Assumption Intrinsics (`llvm.assume`)**: The presence of these intrinsics triggers the flawed logic that hides the capturing behavior of their operand chains, causing the analysis to drop tracking on any pointers involved in computing the assumption.

## Patterns Not Well Handled

### Pattern 1: Ephemeral Pointer Captures Triggering Invalid Dead Store Elimination
This pattern occurs when a local pointer (e.g., from an `alloca`) is initialized with a store, and then the pointer is captured (such as being cast via `ptrtoint` or passed to a function) to compute a condition that is exclusively used by an `llvm.assume` intrinsic. 

**The Issue:** CaptureTracking incorrectly classifies the capturing instruction as "ephemeral" and ignores it. When an optimization pass like Dead Store Elimination (DSE) queries CaptureTracking, it is falsely informed that the pointer never escapes. DSE then aggressively deletes the initial store, assuming the memory is strictly local and the store is dead. However, the ephemeral instructions (which may include `inttoptr` casts and `load` instructions) still exist in the IR at this stage. When they execute, they read uninitialized or stale memory, leading to miscompilations.

**Why it is not well handled:** The optimization pass fails to maintain a conservative approach regarding the current state of the IR. It operates on the flawed premise that ephemeral instructions can be treated as if they have already been removed. Capture tracking must account for all uses of a pointer—including those in ephemeral instructions—as long as those instructions physically remain in the Intermediate Representation.