# Rust MIR pass knowledge

Historical merge dates: **2024-01-01 through 2025-12-31**.

833 selected PRs processed: **168** retained concrete counterexamples, 467 source-backed exclusions, 198 cases without a validated counterexample.
41 actual passes, **193** summarized patterns.

A describes the historical wrong transformation. B generates and executes original/transformed program pairs with fixed Rust/Miri; defined repeatable differences retain a case. C summarizes every retained description for its pass and cannot reject cases. These are concrete-input examples, not universal proofs or current rustc bug claims.

## Contents

- `passes/`: the knowledge read by review; one file per actual pass.
- `catalog/`: pass classification definitions and pinned source snapshots used to rebuild them.
- `cases.json`: retained case index, upstream PR links, triggering conditions, tested outputs and evidence hashes.
- `metadata/`: one JSON file for each validated or inconclusive case, with upstream metadata, source references, analysis and unresolved reasons. Source-backed exclusions remain only in runtime caches.
- `cases/`: ignored local artifacts: retained validation records, Rust programs and compiler-emitted MIR. These are not committed; `localCase` links require a local export.
- `history.json` / `selection.json`: validated and inconclusive PRs with links to their metadata; excluded PRs are omitted.
- `manifest.json`: corpus scope, counts, compiler versions and summary content hashes.

Validated and inconclusive case metadata, descriptions and pass summaries are versioned. Inconclusive cases are retained for follow-up but do not enter pass summaries. Program pairs and detailed validation artifacts stay local in the ignored `cases/` directory; full raw patches, intermediate attempts and verbose logs remain in `service_data/reviews/knowledge/history/`.

## Pass index

| Pass | Cases | Patterns |
| --- | ---: | ---: |
| [AbortUnwindingCalls](passes/AbortUnwindingCalls.md) | 5 | 5 |
| [AddCallGuards](passes/AddCallGuards.md) | 1 | 3 |
| [CheckAlignment](passes/CheckAlignment.md) | 3 | 3 |
| [CheckEnums](passes/CheckEnums.md) | 1 | 1 |
| [CheckInlineAlwaysTargetFeature](passes/CheckInlineAlwaysTargetFeature.md) | 1 | 3 |
| [CheckNull](passes/CheckNull.md) | 1 | 3 |
| [CheckUnnecessaryTransmutes](passes/CheckUnnecessaryTransmutes.md) | 2 | 2 |
| [CleanupPostBorrowck](passes/CleanupPostBorrowck.md) | 6 | 5 |
| [ConstPropLint](passes/ConstPropLint.md) | 3 | 3 |
| [CopyProp](passes/CopyProp.md) | 3 | 3 |
| [CtfeLimit](passes/CtfeLimit.md) | 1 | 1 |
| [DataflowConstProp](passes/DataflowConstProp.md) | 5 | 5 |
| [DeadStoreElimination](passes/DeadStoreElimination.md) | 1 | 2 |
| [Derefer](passes/Derefer.md) | 1 | 3 |
| [DestinationPropagation](passes/DestinationPropagation.md) | 4 | 5 |
| [EarlyOtherwiseBranch](passes/EarlyOtherwiseBranch.md) | 5 | 5 |
| [ElaborateBoxDerefs](passes/ElaborateBoxDerefs.md) | 1 | 2 |
| [ElaborateDrops](passes/ElaborateDrops.md) | 10 | 9 |
| [EraseDerefTemps](passes/EraseDerefTemps.md) | 1 | 3 |
| [ForceInline](passes/ForceInline.md) | 2 | 3 |
| [GVN](passes/GVN.md) | 23 | 14 |
| [ImpossiblePredicates](passes/ImpossiblePredicates.md) | 2 | 3 |
| [Inline](passes/Inline.md) | 20 | 14 |
| [InstrumentCoverage](passes/InstrumentCoverage.md) | 30 | 18 |
| [InstSimplify](passes/InstSimplify.md) | 4 | 4 |
| [JumpThreading](passes/JumpThreading.md) | 10 | 7 |
| [KnownPanicsLint](passes/KnownPanicsLint.md) | 6 | 5 |
| [LowerIntrinsics](passes/LowerIntrinsics.md) | 4 | 4 |
| [MatchBranchSimplification](passes/MatchBranchSimplification.md) | 3 | 6 |
| [MentionedItems](passes/MentionedItems.md) | 1 | 4 |
| [PromoteTemps](passes/PromoteTemps.md) | 3 | 4 |
| [ReferencePropagation](passes/ReferencePropagation.md) | 1 | 1 |
| [RemoveNoopLandingPads](passes/RemoveNoopLandingPads.md) | 1 | 2 |
| [RemoveZsts](passes/RemoveZsts.md) | 1 | 3 |
| [RenameReturnPlace](passes/RenameReturnPlace.md) | 3 | 5 |
| [ScalarReplacementOfAggregates](passes/ScalarReplacementOfAggregates.md) | 1 | 4 |
| [SimplifyCfg](passes/SimplifyCfg.md) | 6 | 6 |
| [SimplifyLocals](passes/SimplifyLocals.md) | 2 | 3 |
| [StateTransform](passes/StateTransform.md) | 14 | 8 |
| [UnreachablePropagation](passes/UnreachablePropagation.md) | 1 | 3 |
| [Validator](passes/Validator.md) | 6 | 6 |
