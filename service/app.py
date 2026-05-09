#!/usr/bin/env python3
"""Archer online review service with FastAPI."""

import queue
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse

from .config import ServiceConfig
from .core import ArcherService
from .dashboard import build_dashboard_html, detect_bug_found
from .models import JobCreateRequest
from .renderers import render_artifact_viewer

config = ServiceConfig()
service = ArcherService(config)

app = FastAPI()


@app.on_event("startup")
def startup_event() -> None:
  service.start()


@app.on_event("shutdown")
def shutdown_event() -> None:
  service.stop()


@app.get("/", response_class=HTMLResponse)
def home() -> str:
  return build_dashboard_html()


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
