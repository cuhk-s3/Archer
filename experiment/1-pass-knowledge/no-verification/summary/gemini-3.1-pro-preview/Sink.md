# Subsystem Knowledge for Sink
## Elements Frequently Missed

* **The `willreturn` Attribute**: The optimization pass frequently misses checking for the `willreturn` attribute on function calls. It assumes that if a call lacks memory write side effects or exception-throwing behavior, it is safe to move, ignoring whether the function is actually guaranteed to return to the caller.
* **Instruction Termination Behavior**: The pass fails to recognize that the potential for an instruction to not return (e.g., entering an infinite loop or trapping) is a critical side effect. Instructions lacking forward progress guarantees act as implicit control flow barriers that must be respected during code motion.

## Patterns Not Well Handled

### Pattern 1: Sinking Non-Returning Instructions Past Conditional Branches
This pattern occurs when an instruction that is not guaranteed to return (such as a function call without the `willreturn` attribute) is placed before a conditional branch. The instruction is otherwise side-effect-free (e.g., read-only), and its result is used exclusively within one of the conditional branch's successor blocks. The optimization pass incorrectly sinks this instruction out of the unconditional execution path and into the conditionally executed block.

**Issues Caused**:
This transformation invalidates the program's control flow and termination guarantees. If the original instruction was destined to hang or trap, sinking it allows the conditional branch and potentially other instructions to execute. This can lead to severe miscompilations, such as the program terminating normally when it should have hung, or triggering undefined behavior (e.g., branching on an `undef` or uninitialized value) that would have been safely preempted in the original code.

**Why it is not well handled**:
The Sink pass relies too heavily on traditional side-effect checks (such as memory writes, volatile accesses, or throwing exceptions) to determine if an instruction is safe to move. It does not adequately model non-termination as a side effect. Consequently, it treats read-only, non-returning instructions as freely movable, failing to realize that moving them past a branch fundamentally alters the conditions under which the branch itself is evaluated.
