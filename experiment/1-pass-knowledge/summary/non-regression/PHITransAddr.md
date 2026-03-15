# Subsystem Knowledge for PHITransAddr
## Elements Frequently Missed

* **Dominance Constraints**: The optimization pass frequently misses strict dominance checks when searching for an existing instruction that computes a translated address. It fails to ensure that the selected instruction dominates the target basic block.
* **Control-Flow Context and Local Assumptions**: The pass overlooks the fact that instructions are bound to specific control-flow contexts. It misses the implications of block-specific metadata, branch conditions, or `llvm.assume` calls that apply only to the block where the instruction originally resides.
* **Instruction Validity Scope**: The pass misses the distinction between structural equivalence and semantic validity. It incorrectly assumes that because two instructions compute the same expression (e.g., identical `getelementptr` instructions), they are universally interchangeable regardless of their placement in the Control Flow Graph (CFG).

## High-Level Patterns Not Well Handled

### Pattern 1: Address Translation Resolving to Non-Dominating Blocks
During PHI translation (commonly in GVN or PRE passes), the compiler translates a memory address expression to a predecessor block and searches for an existing instruction that computes this translated address. The pass incorrectly selects a structurally equivalent instruction located in a parallel or non-dominating block (e.g., picking an instruction from an `if.else` branch when translating an address for an `if.then` branch).
**Why it is not well handled:** The search mechanism prioritizes value equivalence over structural correctness in the CFG. It lacks a strict filtering step to discard candidate instructions that do not dominate the target predecessor block, allowing out-of-scope instructions to be selected as valid translations.

### Pattern 2: Context-Leaking Alias Analysis
When a non-dominating instruction is selected during PHI translation, subsequent analyses (such as Alias Analysis) evaluate this instruction to determine memory dependencies. The analysis incorrectly applies local assumptions attached to the non-dominating instruction—such as `llvm.assume` constraints, specific loop induction variable values, or branch-implied conditions—to the target block where those assumptions do not hold true.
**Why it is not well handled:** Alias Analysis relies on the provided instruction pointer to gather contextual metadata and prove properties like `NoAlias`. Because `PHITransAddr` feeds it an instruction from an invalid context, the analysis blindly trusts the attached metadata without verifying if those assumptions are legally applicable to the block currently being optimized. This leads to flawed disambiguation and invalid transformations, such as incorrectly eliminating memory loads or replacing them with `undef`.
