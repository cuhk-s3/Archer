# TypeScript review service

Archer uses Node.js and the Pi SDK for review execution. The browser dashboard reads the same JSON records written by the CLI.

```bash
bash scripts/install.sh
bash scripts/web.sh
```

The service listens on `127.0.0.1:8080` with `npm start`, or `0.0.0.0:8080` with `scripts/web.sh`. Set `ARCHER_HOST` and `ARCHER_PORT` to override these values. Use `ARCHER_OUTPUT_DIR` to select the artifact store (default `service_data/reviews`).

Run reviews on the host:

```bash
npm run review -- review 162593 --model deepseek-flash
```

The CLI builds base and patched Rust stage1 compilers, runs Pi with TypeScript source inspection and validation tools, and writes review JSON/Markdown and extracted knowledge. It requires `submit_report`, a saved test strategy, and at least one completed differential test before accepting a successful review. Set `ARCHER_AGENT_TIMEOUT` to change the agent timeout in seconds (default 1200).

Read-only endpoints:

- `/healthz`: runtime health.
- `/api/prs`: PR summaries for the dashboard.
- `/api/prs/:id`: PR metadata and its review versions.
- `/api/reviews/:id`: full report, test sources, evidence and knowledge.
- `/pr/:id`: review history page.
- `/review/:id`: human-readable report and test evidence.

GitHub Actions can also run the CLI on the configured self-hosted runner. Configure `ARCHER_REPO_ROOT`, model endpoint/key and GitHub token as workflow variables/secrets. Artifacts are uploaded from the shared output directory. Scanning, dispatching and remote artifact ingestion from the previous Python service are not implemented in this TypeScript service.
