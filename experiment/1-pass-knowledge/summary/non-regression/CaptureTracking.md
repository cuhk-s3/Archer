# Subsystem Knowledge for CaptureTracking
## Elements Frequently Missed

* **Ephemeral Values and Instructions**: Instructions whose results are ultimately only used by assumption intrinsics (such as `llvm.assume`). They are frequently missed or ignored by the analysis under the flawed premise that they do not affect observable program behavior and will eventually be removed, causing the analysis to overlook their immediate side effects in the current IR.
* **Capturing Instructions within Ephemeral Chains**: Instructions that explicitly capture a pointer (e.g., `ptrtoint`, `store`, or `call`) but are bypassed by capture tracking because their data flow terminates at an assumption intrinsic.
* **Assumption Intrinsics (`llvm.assume`)**: The intrinsics themselves act as a trigger for the analysis to prematurely discount the data flow, liveness, and capture semantics of their entire operand trees.

## Patterns Not Well Handled

### Pattern 1: Premature Elision of Ephemeral Captures
Capture tracking traverses the uses of a pointer to determine if it escapes. In this pattern, the analysis encounters a pointer use that is part of an ephemeral chain (e.g., an instruction sequence that feeds into `llvm.assume`) and completely ignores it.

**Issues Caused:** Downstream optimization passes, such as Dead Store Elimination (DSE), heavily rely on capture tracking to determine if a memory location is strictly local and unobservable. If a capture is hidden inside an ephemeral chain, DSE incorrectly assumes the pointer does not escape and aggressively eliminates stores to that memory. Because the ephemeral instructions still exist in the IR at this stage, they (or related instructions) execute and read uninitialized or stale memory, leading to undefined behavior and miscompilations.

**Why it is not well handled:** The analysis incorrectly conflates "will eventually be removed and does not affect final observable output" with "does not capture the pointer in the current IR state." It fails to remain conservative. As long as ephemeral instructions exist in the IR, they must be treated as valid uses that can capture pointers and require valid memory states.

### Pattern 2: Pointer-to-Integer Conversions Feeding Assumptions
A pointer is allocated, stored to, and then converted to an integer (`ptrtoint`). This integer is subsequently converted back to a pointer (`inttoptr`), loaded from, and the result is used in a comparison (`icmp`) that feeds directly into an `llvm.assume`.

**Issues Caused:** The `ptrtoint` instruction fundamentally captures the pointer, as the pointer's value is exposed as an integer. When capture tracking ignores this capture because the ultimate user is an assumption, it breaks alias analysis. The compiler loses track of the memory provenance, failing to recognize that the subsequent `inttoptr` and `load` operations alias with the original allocation. Consequently, the compiler deletes the initial `store`, thinking it is dead.

**Why it is not well handled:** The capture tracking logic aggressively prunes its use-def graph traversal upon detecting an ephemeral use. It fails to account for the fact that operations like `ptrtoint` inherently break strict provenance tracking. The pass lacks the necessary safeguards to ensure that capturing operations are recorded regardless of whether their downstream consumers are ephemeral intrinsics.
