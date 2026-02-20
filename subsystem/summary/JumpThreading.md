# Subsystem Knowledge for JumpThreading

## Elements Frequently Missed

* **Dominator Tree (DT) Synchronization**: The optimization pass frequently misses synchronizing or updating the Dominator Tree immediately after modifying the Control Flow Graph (CFG). This leaves the DT in a stale state during subsequent analysis queries.
* **Alias Analysis (AA) Context Validity**: The pass misses the fact that Alias Analysis internally relies on accurate dominance relationships for contextual deductions (e.g., evaluating assumptions, checking cycles). Querying AA with a stale DT leads to invalid results.
* **Clobbering Stores on Threaded Paths**: Memory writes (stores) that occur along newly threaded control flow paths are frequently missed as clobbers because the underlying alias queries return false `NoAlias` results due to outdated structural information.
* **Safety Checks for Partially Redundant Loads**: When attempting to eliminate partially redundant loads and replace them with previously loaded values (often via PHI nodes), the pass misses strict safety validations that ensure intervening memory states haven't been altered by newly formed control flow edges.

## High-Level Patterns Not Well Handled

### Pattern 1: Interleaving CFG Modifications with Memory Optimization Queries
**Description:** The JumpThreading pass performs control flow transformations (such as threading jumps, bypassing blocks, and altering branch conditions) and subsequently attempts to optimize memory accesses (e.g., eliminating partially redundant loads) within the same pass iteration, without first updating the Dominator Tree.
**Issues Caused:** Because the Dominator Tree is out of sync with the actual CFG, analyses that rely on dominance (like Alias Analysis) return incorrect results. Specifically, the analysis might mistakenly conclude that an intervening store does not alias with a load's target address. Trusting this flawed result, the pass eliminates the load and replaces it with a stale value, leading to a miscompilation.
**Why it is not well handled:** JumpThreading is primarily a control-flow optimization pass, but it opportunistically performs load elimination to expose further threading opportunities. The pass infrastructure fails to enforce strict Dominator Tree updates or restrict DT-dependent analysis queries during these opportunistic memory optimizations, assuming the structural changes won't impact localized memory queries.

### Pattern 2: Context-Sensitive Alias Analysis on Stale Control Flow
**Description:** Evaluating the aliasing relationship between a memory write (store) and a memory read (load) along a newly threaded path where the dominance relationships of the pointers, instructions, or contextual assumptions have recently changed.
**Issues Caused:** Alias Analysis uses the Dominator Tree to evaluate contextual assumptions, check instruction cycles, or decompose pointer expressions. When JumpThreading alters the CFG, the dominance relation between a store, a load, and their pointer definitions changes. If AA uses the stale DT, it deduces incorrect non-aliasing (`NoAlias`). This causes the pass to bypass the actual memory update performed by the clobbering write and route an older, invalid value to the load's users.
**Why it is not well handled:** The optimization pass treats Alias Analysis as a black box and assumes that alias queries are either purely localized or resilient to pending CFG updates. It does not account for the deep dependency of modern AA implementations on global structural correctness, failing to recognize that a stale DT completely invalidates advanced aliasing deductions.