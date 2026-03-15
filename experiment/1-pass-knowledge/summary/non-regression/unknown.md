# Subsystem Knowledge for unknown
## Elements Frequently Missed

*   **Poison-Generating Flags (`nsw`, `nuw`, `exact`)**: These flags are frequently missed during instruction hashing and equivalence comparisons. The optimization pass focuses on the opcode and operands but ignores these restrictive flags, incorrectly treating a safe instruction and a poison-generating instruction as identical.
*   **Memory Alias Offsets**: Specific offset values associated with partial aliases are frequently missed or dropped when merging alias analysis results. The compiler checks the alias kind (e.g., `PartialAlias`) but fails to retain or compare the exact byte offsets, treating distinct memory locations as the same.
*   **Secondary Instruction Attributes in Equivalence Checks**: Broadly, the optimization passes frequently miss secondary metadata or qualifiers when determining if two values or analysis results are equivalent, leading to a loss of crucial semantic precision.

## Patterns Not Well Handled

### Pattern 1: Incomplete Equivalence Checking and Hashing
The optimization pass frequently employs hashing and comparison logic that is too shallow. When evaluating whether two instructions or analysis results are equivalent, the compiler groups them based on primary characteristics (like opcodes, operands, or alias kinds) while completely ignoring secondary, yet semantically critical, attributes (like poison-generating flags or memory offsets). This pattern causes the compiler to incorrectly fold distinct operations into a single equivalence class, laying the groundwork for invalid transformations.

### Pattern 2: Unsafe Leader Selection and State Merging
When the compiler identifies a set of "equivalent" instructions or merges analysis results from different control flow paths (such as through `select` instructions or `phi` nodes), it fails to compute a safe intersection of their properties. Instead of conservatively dropping restrictive flags (e.g., stripping `nsw` when replacing an instruction without it) or downgrading alias precision (e.g., falling back to `MayAlias` when offsets differ), the compiler arbitrarily selects one as the "leader" or merges them while retaining overly specific information. This effectively forces restrictive conditions or incorrect offsets onto execution paths where they do not belong.

### Pattern 3: Invalid Propagation to Downstream Optimizations
The optimization pass does not well handle the downstream consequences of its equivalence and merging decisions. By incorrectly propagating restrictive flags or inaccurate alias offsets, it creates a false semantic foundation for subsequent passes. This pattern directly leads to aggressive miscompilations, such as Global Value Numbering (GVN) incorrectly forwarding loads from the wrong memory offset across a `select` instruction, or instruction simplification passes exploiting newly introduced poison flags to erroneously eliminate necessary computations.
