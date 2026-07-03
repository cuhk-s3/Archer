# Archer Dispatcher + Worker Deployment

This deployment mode separates responsibilities into two roles:

1. Dispatcher (Aliyun): scan PRs, dispatch jobs, poll job status, and serve UI.
2. Worker (School machine): execute `main.py` through GitHub Actions self-hosted runner.

## Responsibilities

### Dispatcher

1. Runs FastAPI service (`service.backend.app`) for the dashboard API and DB-backed PR/review pages.
2. Runs static UI from `service/frontend/`.
3. Scans LLVM PRs with existing filtering logic.
4. Dispatches work to GitHub Actions workflow.
5. Polls workflow run status, downloads artifacts, and ingests `run.db.json` into the local `dataset/archer.db`.
6. Serves the review board from the local SQLite DB.

### Worker

1. Runs GitHub Actions self-hosted runner with label `archer-school`.
2. Executes workflow job by running `main.py`.
3. Uploads `run.stats.json`, `run.history.json`, `run.review.md`, and `run.db.json` to GitHub Actions.

## One-Command Startup

### Dispatcher machine (Aliyun)

```bash
export ARCHER_GITHUB_TOKEN=<github-token-with-actions-and-repo-scope>
export ARCHER_CORS_ORIGINS=https://<your-public-frontend-domain>
export BACKEND_BASE_URL=https://<your-dispatcher-domain-or-ip>:8080
bash scripts/run_dispatcher.sh
```

`run_dispatcher.sh` is self-contained: it starts backend API + scanner, writes `service/frontend/runtime-config.js`, and serves the frontend static UI.

Default ports:

1. Dispatcher API: `ARCHER_SERVICE_PORT` (default `8080`)
2. Dispatcher UI: `FRONTEND_PORT` (default `8090`)

Common overrides:

```bash
export ARCHER_SERVICE_PORT=8080
export FRONTEND_PORT=8090
export ARCHER_ACTIONS_REPO=cuhk-s3/Archer
export ARCHER_ACTIONS_WORKFLOW=archer-review-dispatch.yml
export ARCHER_ACTIONS_REF=main
export ARCHER_ACTIONS_POLL_INTERVAL_SEC=20
```

### Worker machine (School)

```bash
export ACTIONS_RUNNER_DIR=/path/to/actions-runner
bash scripts/run_worker.sh
```

`run_worker.sh` starts `run.sh` in the self-hosted runner directory.

## GitHub Actions Setup

1. Workflow file: `.github/workflows/archer-review-dispatch.yml`
2. Runner label on worker machine: `archer-school`
3. Repository variable: `ARCHER_REPO_ROOT` (absolute Archer path on worker machine)
4. Worker environment must already have model credentials and dependencies (`scripts/upenv.sh`)

## Runtime Sequence

1. Dispatcher scans PRs and enqueues jobs.
2. Dispatcher dispatches workflow runs.
3. Worker runner pulls the workflow job and runs `main.py`.
4. `main.py` writes local stats/history/review files and exports a structured `run.db.json` snapshot.
5. Workflow uploads the files to GitHub Actions artifacts.
6. Dispatcher downloads the artifacts and replays `run.db.json` into its authoritative `dataset/archer.db`.
7. Dashboard reads from `/api/prs`, `/pr/{pr_id}`, `/review/{review_id}`, and `/trace/{review_id}`.

## Data Model

- `dataset/archer.db` on the dispatcher is the authoritative dashboard store.
- `run.db.json` is the machine-independent result snapshot sent from worker to dispatcher.
- `run.stats.json`, `run.history.json`, and `run.review.md` are still saved as run artifacts for debugging and inspection.
- With a single runner, copy the dispatcher's `dataset/archer.db` to the runner before starting if regression-gate history is needed there.

## Network Requirements

1. Dispatcher can access GitHub API.
2. Worker can access GitHub Actions service.
3. Browser can access Dispatcher UI/API.
4. Worker does not need public inbound access.
