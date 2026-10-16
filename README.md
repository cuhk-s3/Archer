# Archer for VeIR

Archer for VeIR reviews pull requests in [`opencompl/veir`](https://github.com/opencompl/veir). It keeps Archer's two-phase analysis and evidence-backed reporting, but uses VeIR's own tools:

- `veir-opt` for pass execution and crash detection;
- `veir-interpret` for before/after semantic differential testing;
- VeIR MLIR/FileCheck tests as mutation seeds;
- Lean source, verifier, interpreter and dialect definitions as review context.

## Setup

Run the setup script once to prepare the VeIR review environment. Subsequent
runs reuse the existing setup.

```bash
bash scripts/setup.sh
cp environments.example environments
```

Fill in `ARCHER_LM_API_ENDPOINT`, `ARCHER_LM_API_KEY`, and `LAB_GITHUB_TOKEN`, then load them:

```bash
source environments
source scripts/upenv.sh
```

Run `source scripts/upenv.sh` in each new terminal before using Archer.

## Review a PR

```bash
python main.py --pr 1634 --model <model> \
  --review review.md --history history.json --stats stats.json
```

The PR extractor targets `opencompl/veir`, checks out the PR base in the private VeIR clone, applies its code patch, builds VeIR, and stores the version and MLIR tests in `dataset/archer.db`.

## Durable review knowledge

The `insight` reviewer tool records reusable hypotheses and observations in SQLite. Only observations backed by an actual `verify`, `difftest`, or `rwenum` result can be marked verified. Verified records are automatically synchronized to `dataset/knowledge/insights.jsonl`, so knowledge is reviewable in Git and is imported into a fresh database on startup. Later PRs automatically receive only component-relevant verified insights; unverified hypotheses require an explicit search.
