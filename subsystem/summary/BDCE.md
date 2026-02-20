# Subsystem Knowledge for BDCE

## Elements Frequently Missed

* **Poison-Generating Flags (`nsw`, `nuw`, `exact`) on User Instructions**: The optimization pass frequently misses the need to clear these flags on instructions when their operands are modified. When a parent instruction is simplified based on demanded bits, the altered input can cause the user instruction to violate these flags, but the pass fails to strip them.
* **Fully Demanded User Instructions**: The pruning logic in the pass incorrectly assumes that if an instruction has 100% of its bits demanded by its own users, it does not need to be processed or updated. This causes the pass to completely skip evaluating these instructions for necessary flag removals.
* **Def-Use Chain Dependency Updates**: The pass misses the implicit dependency between altering the undemanded bits of a definition and the validity of the assumptions (flags) on its subsequent users in the def-use chain.

## Patterns Not Well Handled

### Pattern 1: Simplification of Partially Demanded Definitions with Fully Demanded Poison-Generating Users
This pattern occurs when a definition instruction is only partially demanded by its users, allowing BDCE to simplify it (e.g., by zeroing out the undemanded bits). This simplified definition is then used as an operand in a subsequent instruction that carries poison-generating flags (such as `nsw`, `nuw`, or `exact`). 

The issue arises when this user instruction is *fully demanded* by its own subsequent users. BDCE's pruning logic is designed to skip processing instructions that are fully demanded, under the flawed assumption that no simplification or update is needed for them. As a result, the pass alters the input to the user instruction (by simplifying the parent definition) but skips the user instruction entirely, failing to drop its poison-generating flags. 

This pattern is not well handled because the pruning logic relies solely on the demanded bits of the current instruction, ignoring the fact that changes to a parent instruction's undemanded bits can invalidate the current instruction's flags. At runtime, the modified input can cause the user instruction to trigger an overflow or exactness violation, producing a poison value that propagates and leads to miscompilation.