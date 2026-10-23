# Archer for Rust

Archer reviews `rust-lang/rust` pull requests with an embedded [Pi](https://github.com/earendil-works/pi) TypeScript agent. It uses Archer's two-phase workflow: Phase 1 loads pass-specific knowledge and inspects source, ending with `stop` and structured strategies; Phase 2 freezes those strategies and enables compilation, Miri, differential testing, and reporting. The host enforces tool boundaries, checks strategy coverage, and records separate phase statistics.

## Setup

Install Node.js 22.19 or newer, Git, rustup, and the native prerequisites used by the [Rust compiler build](https://rustc-dev-guide.rust-lang.org/building/how-to-build-and-run.html). Then run:

```bash
git clone https://github.com/cuhk-s3/Archer.git
cd Archer
cp environments.example environments
```

Set `ARCHER_LM_API_ENDPOINT` and `ARCHER_LM_API_KEY` in `environments`; optionally set `LAB_GITHUB_TOKEN` to raise GitHub API limits. Install the runtime and Miri with:

```bash
source scripts/upenv.sh
bash scripts/install.sh
```

The first review downloads Rust source and builds stage1 rustc for the PR base and patched tree.

Source checkouts remain isolated under `build/rust/source/<PR>/<revision>/`. Compilers are shared across PRs under `build/rust/cache/rustc/<key>/`, keyed by revision, local patch, host, build configuration and native tool versions. LLVM has its own shared cache under `build/rust/cache/llvm/<key>/`, keyed by its pinned revision, bootstrap recipe, host and configuration. Completed cache hits validate the compiler and standard library and skip rebuilding; interrupted builds retain incremental output. Process locks serialize cache writers and protect source checkout preparation. Existing builds using the old directories can finish normally; they are not moved into the new cache automatically.

Set `LAB_RUST_BUILD_TIMEOUT` (seconds) and `LAB_RUST_BUILD_DIR` to tune build caching. The model defaults to `deepseek-flash` and can be changed with `ARCHER_MODEL`. The validated endpoint uses DeepSeek thinking mode; Pi preserves `reasoning_content` across tool calls. `ARCHER_AGENT_TIMEOUT` defaults to 1200 seconds. On Node 24+, the CLI automatically honors environment proxy variables.

## Use

```bash
npm run review -- review <RUST_PR_ID>
npm run review -- fetch <RUST_PR_ID>
npm run review -- serve
```

`fetch` prints PR metadata without building. `review` runs the full Pi tool workflow and stores review JSON/Markdown under `service_data/reviews/reviews/<PR>/`, with evidence-backed reusable notes in `service_data/reviews/knowledge/rust.jsonl`. The `serve` command hosts the review board at `http://127.0.0.1:8080` and provides `/api/prs`, `/api/prs/:id`, and `/api/reviews/:id`.

Miri rejects candidate tests that execute undefined behavior. A passing Miri run does not prove compiler correctness; a finding requires a reproducible difference from the base compiler on defined behavior.

Runtime code is organized by workflow: `src/knowledge/` (acquisition, analysis, verification and pass synthesis), `src/review/` (the two review phases and tools), `src/rust/` (passes and toolchains), `src/infra/` (GitHub, Pi and subprocesses), and `src/service/` (HTTP service and storage). The root keeps only the CLI, configuration and shared types. Tests live beside their modules.

Maintenance scripts are grouped under `scripts/knowledge/` and `scripts/review/`. Run `npm run format:check`, `npm run typecheck`, `npm test`, and `npm run build` to validate changes. Deployment and API details are in [service/SERVICE.md](service/SERVICE.md).

## Historical pass knowledge (2024–2025)

The active selection contains **833 independent PRs** merged from 2024-01-01 through 2025-12-31, verified with GitHub metadata. It combines MIR transform/dataflow implementation files and MIR optimization tests with MIR optimization label matches. Aggregate rollups, external subtree merge numbers and out-of-period changes are excluded. The selection is capped at 1,000 PRs in `history/selection.json`. Wider cached records are preserved but do not enter this run.

`knowledge:prescreen` is an advanced importer for the existing local Git file index (`build/rust/historical-merge-files.txt`) and cached GitHub label searches (`build/rust/prescreen/label-*.json`). These runtime caches are not committed. Ordinary review uses the published knowledge and does not require them.

```bash
npm run knowledge:prescreen
npm run review -- knowledge --collect-only
npm run review -- knowledge-build --model deepseek-flash --follow
```

Final knowledge is versioned under [`knowledge/rust/`](knowledge/rust/README.md). `passes/` contains the summaries read directly by review, `catalog/` contains pass definitions and pinned sources, `metadata/` records 168 validated cases and 198 inconclusive cases with their descriptions; the 467 source-backed exclusions are omitted, and the ignored local `cases/` directory preserves retained Rust/MIR programs and validation observations. `history.json`, `cases.json` and `manifest.json` index those records and their provenance. The metadata, indexes and summaries are versioned; `cases/` is not committed. `localCase` references are available only after a local export. To export a completed runtime corpus, run `npm run knowledge:publish`; complete pipeline runs also publish automatically.

Review supports both behavioral-difference checks and compiler ICE/crash checks. `ice_test` compiles each frozen Phase 1 strategy with base and patched rustc at O0 and O3, separating compiler ICEs/crashes from ordinary source errors and timeouts. It marks a failure as introduced only when patched rustc fails and base rustc succeeds at the same optimization level. Confirm the input is valid and deterministic before treating an ICE as a finding; Miri is available as a UB check, not an equivalence oracle.

The three roles follow Archer's original knowledge workflow:

1. **A** analyzes the historical issue/patch into a transformation description, triggering conditions and testing strategy.
2. **B** generates original and incorrectly transformed Rust/MIR program pairs from that description. The host uses one fixed modern Rust/Miri runtime: two Miri executions per variant and two native executions per variant at O0/O3. Defined, repeatable differences retain the case under its actual pass. Historical compiler builds are optional extra evidence.
3. **C** summarizes **all retained descriptions for each pass**, identifying frequently missed elements and common patterns. C has no rejection role. Every retained case must be referenced; a summary failure never deletes B's validated case.

This is concrete-input transformation testing, not universal equivalence proof or a claim that current rustc contains the historical bug. Tool errors, UB, timeouts and unstable outputs do not certify differences. Inconclusive cases retain their reasons. A source-backed exclusion must identify unrelated or mechanical changes; missing labels or automatic pass matches alone are not exclusion reasons.

Pass classification uses actual MIR registrations and implementation modules from pinned sources, plus exact MIR dump/EMIT_MIR names. GVN, CopyProp, JumpThreading, DataflowConstProp, DestinationPropagation, SimplifyCfg, SimplifyLocals, Inline and other actual passes have separate knowledge files. Shared helpers and ownership labels are not invented passes. Unresolved cases receive source inspection.

The corpus lives under `service_data/reviews/knowledge/history/`:

- `selection.json`, `selected-metadata/`, `inventory/`, `raw/`: bounded selection and complete source provenance.
- `records/`, `classification/`, `skipped/`, `pending/`: A's descriptions and source-backed decisions.
- `program-pairs/deepseek-flash/`: B's programs, execution matrices and certificates.
- `synthesis/deepseek-flash/`, `synthesized-passes/deepseek-flash/`: C's summaries and one Markdown file per pass.
- `collection.json`, `pipeline-status.json`: collection status and selected-case coverage.

The pipeline resumes completed work and retries infrastructure failures. On Node 24+ it honors proxy environment variables. Native macOS subprocesses select installed Command Line Tools and their SDK per process. For local Git acceleration, configure `ARCHER_HISTORY_GIT_REPO` and retain `build/rust/historical-merge-files.txt`; GitHub diff and full Git-object fallback handle missing partial-clone objects.

Phase 1 of review loads the identified passes' summarized knowledge, inspects the patch/source and finishes with `stop` plus structured strategies. Phase 2 freezes those strategies, runs defined differential tests and submits a report. The host enforces phase boundaries and strategy coverage.

`validate-knowledge` remains an optional validation against historical before/after compiler builds.

For an independent two-phase evaluation, run `npm run review:blind -- <PR>`. This exports a source snapshot at the actual PR merge, freezes the published knowledge input, and stores inputs, event traces and results under `service_data/blind-review/<PR>/`. The review tools cannot access later Git history or external selection notes. Keep known issue reports, fixes and reproducers outside that snapshot.

