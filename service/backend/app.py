#!/usr/bin/env python3
"""Archer online review service with FastAPI."""

import queue
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

from .config import ServiceConfig
from .core import ArcherService
from .dashboard import build_dashboard_html, detect_bug_found
from .models import JobCreateRequest
from .renderers import render_artifact_viewer

config = ServiceConfig()
service = ArcherService(config)

app = FastAPI()


def _resolve_run_file(run_id: str, file_path: str) -> Path:
  runs_path = config.runs_dir / run_id
  if not runs_path.exists() or not runs_path.is_dir():
    raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

  target_name = Path(file_path).name
  artifact_attr_by_name = {
    "run.review.md": "review_path",
    "run.history.json": "history_path",
    "run.stats.json": "stats_path",
  }
  artifact_attr = artifact_attr_by_name.get(target_name)
  allowed_root = config.data_dir.resolve()

  if artifact_attr and run_id.isdigit():
    pr_id = int(run_id)
    pr_jobs = [job for job in service.list_jobs() if job.pr_id == pr_id]
    for job in pr_jobs:
      artifact_path = getattr(job, artifact_attr, None)
      if not artifact_path:
        continue
      target = Path(artifact_path).resolve()
      if (
        str(target).startswith(str(allowed_root))
        and target.exists()
        and target.is_file()
      ):
        return target

  candidates: list[Path] = []

  # Support both layouts:
  # 1) runs/<run_id>/<subdir>/<file>
  # 2) runs/<run_id>/<file>
  direct = (runs_path / file_path).resolve()
  candidates.append(direct)

  for child in runs_path.iterdir():
    if child.is_dir():
      candidates.append((child / file_path).resolve())
      if file_path == target_name:
        candidates.append((child / target_name).resolve())

  for target in candidates:
    if (
      str(target).startswith(str(allowed_root)) and target.exists() and target.is_file()
    ):
      return target

  raise HTTPException(status_code=404, detail=f"File not found: {file_path}")


app.add_middleware(
  CORSMiddleware,
  allow_origins=config.cors_origins,
  allow_credentials=False,
  allow_methods=["*"],
  allow_headers=["*"],
)


@app.on_event("startup")
def startup_event() -> None:
  service.start()


@app.on_event("shutdown")
def shutdown_event() -> None:
  service.stop()


@app.get("/", response_class=HTMLResponse)
def home() -> str:
  return build_dashboard_html()


@app.get("/logo.png", include_in_schema=False)
def logo() -> FileResponse:
  logo_path = config.repo_root / "Archer.png"
  if not logo_path.exists():
    raise HTTPException(status_code=404, detail="Logo not found")
  return FileResponse(logo_path, media_type="image/png")


@app.get("/healthz")
def healthz() -> dict:
  return {
    "ok": True,
    "repo": config.github_repo,
    "auto_scan": config.auto_scan,
  }


@app.get("/api/jobs")
def api_jobs() -> dict:
  jobs = []
  for j in service.list_jobs():
    item = asdict(j)
    item["bug_found"] = detect_bug_found(j.stats_path)
    jobs.append(item)
  return {"jobs": jobs}


@app.get("/api/jobs/{job_id}")
def api_job(job_id: str) -> dict:
  job = service.get_job(job_id)
  if not job:
    raise HTTPException(status_code=404, detail="Not found")
  item = asdict(job)
  item["bug_found"] = detect_bug_found(job.stats_path)
  return item


@app.post("/api/jobs")
def api_create_job(req: JobCreateRequest) -> dict:
  try:
    job = service.enqueue_pr(pr_id=req.pr_id, source=req.source, force=req.force)
  except queue.Full:
    raise HTTPException(status_code=503, detail="Queue full")
  return asdict(job)


@app.post("/api/scan")
def api_scan() -> dict:
  result = service.scan_open_prs()
  if not result.get("ok"):
    raise HTTPException(status_code=400, detail=result.get("reason", "failed"))
  return result


@app.get("/api/artifacts")
def api_artifact(path: str):
  target = Path(path).resolve()
  allowed_root = config.data_dir.resolve()
  if not str(target).startswith(str(allowed_root)):
    raise HTTPException(status_code=403, detail="Access denied")
  if not target.exists():
    raise HTTPException(status_code=404, detail="Not found")
  return PlainTextResponse(target.read_text())


@app.get("/artifact", response_class=HTMLResponse)
def artifact_viewer(path: str) -> str:
  target = Path(path).resolve()
  allowed_root = config.data_dir.resolve()
  if not str(target).startswith(str(allowed_root)):
    raise HTTPException(status_code=403, detail="Access denied")
  if not target.exists():
    raise HTTPException(status_code=404, detail="Not found")
  return render_artifact_viewer(target)


@app.get("/artifact/", response_class=HTMLResponse, include_in_schema=False)
def artifact_viewer_slash(path: str) -> str:
  return artifact_viewer(path)


@app.get("/artifact/run/{run_id}/{file_path:path}", response_class=HTMLResponse)
def artifact_viewer_path(run_id: str, file_path: str) -> str:
  target = _resolve_run_file(run_id, file_path)
  return render_artifact_viewer(target)


@app.get(
  "/artifact/run/{run_id}/{file_path:path}/",
  response_class=HTMLResponse,
  include_in_schema=False,
)
def artifact_viewer_path_slash(run_id: str, file_path: str) -> str:
  return artifact_viewer_path(run_id, file_path)


@app.get("/api/artifacts/run/{run_id}/{file_path:path}")
def api_artifact_path(run_id: str, file_path: str):
  target = _resolve_run_file(run_id, file_path)
  return PlainTextResponse(target.read_text())


@app.get("/api/artifacts/run/{run_id}/{file_path:path}/", include_in_schema=False)
def api_artifact_path_slash(run_id: str, file_path: str):
  return api_artifact_path(run_id, file_path)
