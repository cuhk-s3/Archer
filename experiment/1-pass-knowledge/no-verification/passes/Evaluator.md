# Issue 55859

## Incorrect Redundancy Check for Memory-Setting Intrinsics in Global Evaluation

**Description**:
To trigger this bug, construct a scenario where a global variable is initialized with a mix of values, such that its first byte or element matches a specific value (e.g., zero), but subsequent bytes or elements contain different, non-matching values. Then, introduce a memory-setting intrinsic (such as `memset`) within a global constructor or initialization function, which is intended to overwrite the entire global variable with that specific value.

When the compiler evaluates the initialization at compile time, it attempts to optimize away redundant memory operations. However, the redundancy check is flawed: it only inspects the first byte or element of the destination memory. Finding that the first byte already matches the value being set, the compiler erroneously concludes that the entire memory-setting operation is a no-op and removes it. As a result, the global variable is not fully updated, and the subsequent bytes retain their original values instead of being overwritten, leading to a miscompilation.
