# Issue 70703

## Module Cloning Miscompilation with Block Addresses

**Description**:
The bug is triggered when a module containing `blockaddress` constants—typically used in conjunction with `indirectbr` instructions to implement indirect control flow (such as indirect gotos)—is duplicated using the compiler's module cloning infrastructure.

During the cloning process, the transformation logic fails to correctly remap the `blockaddress` references to the newly cloned basic blocks. Consequently, the cloned module retains invalid, unmapped, or corrupted label addresses. When the resulting code is executed, indirect branches jump to incorrect memory locations, leading to corrupted control flow, miscompilations, or runtime crashes (e.g., illegal instruction faults).
