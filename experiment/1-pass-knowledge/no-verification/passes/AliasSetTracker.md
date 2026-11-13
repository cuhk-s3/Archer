# Issue 64897

## Incorrect Alias Analysis for MustAlias Sets with Varying Access Sizes

**Description**:
The bug is triggered by a sequence of memory operations that exploit a flaw in how alias tracking handles `MustAlias` sets when access sizes change. The strategy involves the following steps:

1. **Initial Access**: A memory operation accesses a pointer with a specific size. This establishes a `MustAlias` set in the alias tracker, and the tracker records this initial size for the set's representative pointer.
2. **Larger Access to the Same Pointer**: A subsequent memory operation accesses the exact same pointer (or a pointer that strictly must-alias with it) but with a *larger* size.
3. **Missing Size Update**: The alias tracking mechanism registers the new size for the specific pointer entry but fails to update the size of the `MustAlias` set's representative pointer. As a result, the alias set as a whole still appears to only cover the initial, smaller memory region.
4. **Overlapping Access**: Another memory operation accesses a memory region that falls within the bounds of the larger access size but strictly outside the bounds of the initial smaller size.
5. **Incorrect Alias Query**: When the compiler checks for aliasing between this new memory operation and the `MustAlias` set, it incorrectly concludes `NoAlias`. This happens because the tracker only checks against the representative pointer, which still holds the smaller size.
6. **Illegal Optimization**: Optimization passes that rely on this alias information, such as Loop Invariant Code Motion (LICM), use the flawed `NoAlias` result to perform invalid transformations. For example, the pass might incorrectly hoist a load or store out of a loop, bypassing an aliasing memory operation and leading to a miscompilation.
