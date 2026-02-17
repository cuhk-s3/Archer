# Subsystem Knowledge for BDCE

## Elements Frequently Missed

*   **Poison-Generating Flags (`nsw`, `nuw`, `exact`)**: The optimization pass frequently fails to identify that these flags must be dropped when the input operands of an instruction are simplified or modified, even if the instruction's opcode remains the same.
*   **Fully-Demanded Instructions**: Instructions where all output bits are required by downstream users are often skipped during the update phase. The analyzer incorrectly assumes that if no output bits are dead, the instruction itself requires no modification, missing the necessity to sanitize flags based on changed inputs.
*   **Users of Simplified Operands**: When an instruction is simplified (e.g., constant folding or bit masking) based on limited demand, the users of that instruction are not always correctly revisited to check for validity constraints, specifically regarding undefined behavior triggers.

## Patterns Not Well Handled

### Pattern 1: Flag Retention on Fully-Demanded Users of Simplified Operands
This pattern occurs when the BDCE pass identifies that an operand (Instruction A) can be simplified because its user (Instruction B) does not demand all of its bits. However, Instruction B is a "fully-demanded" user (all its output bits are used elsewhere) and carries poison-generating flags like `nsw` (No Signed Wrap), `nuw` (No Unsigned Wrap), or `exact`.

The issue arises because the optimization logic treats the "fully-demanded" status of Instruction B as a signal that Instruction B does not need to be modified. Consequently, Instruction A is simplified (e.g., high bits are zeroed out), but Instruction B retains its flags. The simplification of A changes the input values to B such that the flags are no longer valid (e.g., a sign change occurs that violates `nsw`), causing the instruction to produce a poison value instead of a valid result. The optimizer fails to couple the simplification of an operand with the necessary sanitization of the user's flags when that user is not otherwise being dead-code eliminated.