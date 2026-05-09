#!/usr/bin/env python3
"""Archer online review service with FastAPI."""

import json
import os
import queue
import re
import subprocess
import sys
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")


def utc_now_iso() -> str:
  return datetime.now(timezone.utc).isoformat()


def strip_ansi(text: str) -> str:
  return ANSI_ESCAPE_RE.sub("", text).rstrip("\n")


@dataclass
class Job:
  id: str
  pr_id: int
  status: str = "queued"
  phase: str = "queued"
  error: Optional[str] = None
  created_at: str = field(default_factory=utc_now_iso)
  updated_at: str = field(default_factory=utc_now_iso)
  started_at: Optional[str] = None
  finished_at: Optional[str] = None
  stats_path: Optional[str] = None
  history_path: Optional[str] = None
  review_path: Optional[str] = None
  log_path: Optional[str] = None
  logs: List[str] = field(default_factory=list)
  title: str = ""
  author: str = ""
  components: List[str] = field(default_factory=list)

  def append_log(self, line: str, max_logs: int = 400) -> None:
    self.logs.append(line)
    if len(self.logs) > max_logs:
      self.logs = self.logs[-max_logs:]


class ServiceConfig:
  def __init__(self):
    self.repo_root = Path(__file__).resolve().parent.parent
    self.data_dir = Path(
      os.environ.get("ARCHER_DATA_DIR", str(self.repo_root / "service_data"))
    )
    self.runs_dir = self.data_dir / "runs"
    self.state_file = self.data_dir / "state.json"

    self.model = os.environ.get(
      "ARCHER_MODEL", "google/gemini-3.1-pro-preview-customtools"
    )
    self.driver = os.environ.get("ARCHER_DRIVER", "openai")
    self.scan_interval_sec = int(os.environ.get("ARCHER_SCAN_INTERVAL_SEC", "300"))
    self.auto_scan = os.environ.get("ARCHER_AUTO_SCAN", "true").lower() == "true"
    self.include_draft = (
      os.environ.get("ARCHER_INCLUDE_DRAFT", "false").lower() == "true"
    )
    self.open_pr_limit = int(os.environ.get("ARCHER_OPEN_PR_LIMIT", "20"))
    self.max_logs_per_job = int(os.environ.get("ARCHER_MAX_LOGS_PER_JOB", "400"))
    self.max_queue_size = int(os.environ.get("ARCHER_MAX_QUEUE_SIZE", "200"))

    self.github_repo = os.environ.get("ARCHER_GITHUB_REPO", "llvm/llvm-project")
    self.github_token = os.environ.get("ARCHER_GITHUB_TOKEN") or os.environ.get(
      "LAB_GITHUB_TOKEN"
    )

    self.runs_dir.mkdir(parents=True, exist_ok=True)


class JobCreateRequest(BaseModel):
  pr_id: int = Field(gt=0)
  source: str = Field(default="manual")
  force: bool = False


class ArcherService:
  def __init__(self, config: ServiceConfig):
    self.config = config
    self.jobs: Dict[str, Job] = {}
    self.jobs_by_pr: Dict[int, str] = {}
    self.queue: "queue.Queue[str]" = queue.Queue(maxsize=config.max_queue_size)
    self.lock = threading.Lock()
    self.stop_flag = False
    self._load_state()

  def _load_state(self) -> None:
    if self.config.state_file.exists():
      with open(self.config.state_file) as f:
        state = json.load(f)
      for job_data in state.get("jobs", []):
        j = Job(
          id=job_data["id"],
          pr_id=job_data["pr_id"],
          status=job_data.get("status", "queued"),
          phase=job_data.get("phase", "queued"),
          error=job_data.get("error"),
          created_at=job_data.get("created_at", utc_now_iso()),
          updated_at=job_data.get("updated_at", utc_now_iso()),
          started_at=job_data.get("started_at"),
          finished_at=job_data.get("finished_at"),
          stats_path=job_data.get("stats_path"),
          history_path=job_data.get("history_path"),
          review_path=job_data.get("review_path"),
          log_path=job_data.get("log_path"),
          logs=job_data.get("logs", []),
          title=job_data.get("title", ""),
          author=job_data.get("author", ""),
          components=job_data.get("components", []),
        )
        if j.status == "running":
          j.status = "failed"
          j.error = "Service interrupted"
        self.jobs[j.id] = j
        self.jobs_by_pr[j.pr_id] = j.id
      self._save_state()

  def _save_state(self) -> None:
    state = {"jobs": [asdict(j) for j in self.jobs.values()]}
    self.config.state_file.write_text(json.dumps(state, indent=2))

  def get_job(self, job_id: str) -> Optional[Job]:
    return self.jobs.get(job_id)

  def list_jobs(self) -> List[Job]:
    return sorted(self.jobs.values(), key=lambda j: j.created_at, reverse=True)

  def enqueue_pr(self, pr_id: int, source: str = "manual", force: bool = False) -> Job:
    with self.lock:
      existing_id = self.jobs_by_pr.get(pr_id)
      if existing_id and not force:
        return self.jobs[existing_id]
      job_id = f"{source}-{pr_id}"
      job = Job(
        id=job_id,
        pr_id=pr_id,
        status="queued",
        created_at=utc_now_iso(),
        updated_at=utc_now_iso(),
      )
      self.jobs[job_id] = job
      self.jobs_by_pr[pr_id] = job_id
      self.queue.put(job_id, block=False)
      self._save_state()
      return job

  def _run_job(self, job: Job) -> None:
    job.status = "running"
    job.started_at = utc_now_iso()
    job.updated_at = utc_now_iso()
    self._save_state()

    run_dir = self.config.runs_dir / str(job.pr_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    stats_path = run_dir / f"{timestamp}.stats.json"
    history_path = run_dir / f"{timestamp}.history.json"
    review_path = run_dir / f"{timestamp}.review.md"
    log_path = run_dir / f"{timestamp}.log"

    cmd = [
      sys.executable,
      str(self.config.repo_root / "main.py"),
      "--pr",
      str(job.pr_id),
      "--stats",
      str(stats_path),
      "--history",
      str(history_path),
      "--review",
      str(review_path),
    ]

    env = os.environ.copy()
    env.update(
      {
        "ARCHER_MODEL": self.config.model,
        "ARCHER_DRIVER": self.config.driver,
      }
    )

    try:
      with open(log_path, "w") as log_file:
        proc = subprocess.Popen(
          cmd,
          stdout=log_file,
          stderr=subprocess.STDOUT,
          text=True,
          env=env,
          cwd=str(self.config.repo_root),
        )
        proc.wait(timeout=3600)
        returncode = proc.returncode
    except subprocess.TimeoutExpired:
      proc.kill()
      job.status = "failed"
      job.error = "Timeout after 1 hour"
      returncode = -1
    except Exception as e:
      job.status = "failed"
      job.error = str(e)
      returncode = -1

    if returncode == 0:
      job.status = "succeeded"
      job.phase = "done"
    else:
      if not job.error:
        job.status = "failed"
        job.phase = "failed"

    job.stats_path = str(stats_path) if stats_path.exists() else None
    job.history_path = str(history_path) if history_path.exists() else None
    job.review_path = str(review_path) if review_path.exists() else None
    job.log_path = str(log_path) if log_path.exists() else None
    job.finished_at = utc_now_iso()
    job.updated_at = utc_now_iso()
    self._save_state()

  def _worker(self) -> None:
    while not self.stop_flag:
      try:
        job_id = self.queue.get(timeout=1)
        job = self.jobs.get(job_id)
        if job:
          self._run_job(job)
      except queue.Empty:
        continue
      except Exception as e:
        print(f"Worker error: {e}", file=sys.stderr)

  def start(self) -> None:
    worker_thread = threading.Thread(target=self._worker, daemon=True)
    worker_thread.start()

  def stop(self) -> None:
    self.stop_flag = True

  def scan_open_prs(self) -> dict:
    if not self.config.github_token:
      return {"ok": False, "reason": "No GitHub token"}
    # Placeholder for GitHub scanning
    return {"ok": True, "scanned": 0}


def build_dashboard_html() -> str:
  return """<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Archer Live Review Board</title>
  <style>
    :root {
      --ink: #1f2d3d;
      --sub: #60758d;
      --line: #eaf0f7;
      --brand-1: #2f6fad;
      --brand-2: #6aa6d6;
      --ok: #1f9956;
      --err: #d64545;
      --run: #c7821f;
      --queue: #6e7d8c;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      background: #ffffff;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif;
      padding: 12px 14px;
    }
    .shell { max-width: 900px; margin: 0 auto; }
    .brand-strip { height: 4px; background: linear-gradient(90deg, var(--brand-1), var(--brand-2)); border-radius: 0; margin-bottom: 8px; }
    .head { padding: 10px 12px; display: flex; justify-content: space-between; align-items: flex-end; gap: 10px; }
    .head-main { min-width: 0; }
    .head-badge { font-size: 11px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: #35516c; background: #eef5fc; padding: 4px 8px; border-radius: 0; }
    .title { margin: 0; font-size: clamp(24px, 3vw, 36px); font-weight: 700; line-height: 1; }
    .sub { margin-top: 8px; color: var(--sub); font-size: 13px; }
    .toolbar { padding: 8px 12px; }
    .query-wrap { width: 100%; overflow-x: auto; }
    .query-row { display: grid; grid-template-columns: auto minmax(360px, 1fr); gap: 8px; align-items: center; min-width: 750px; }
    .search-box { display: flex; align-items: center; border: 1px solid #e6eef7; border-radius: 0; background: #f7fbff; height: 34px; overflow: hidden; }
    .search-input { min-width: 0; width: 100%; border: none; height: 32px; padding: 0 10px; background: transparent; font-size: 14px; color: var(--ink); }
    .search-input:focus { outline: none; }
    .input-clear { border: none; border-left: 1px solid #e6eef7; background: #f7fbff; width: 34px; height: 100%; padding: 0; color: #5e7388; font-size: 16px; line-height: 1; cursor: pointer; }
    .input-clear:hover { background: #eef6ff; }
    .status-tabs { display: inline-flex; border: 1px solid #e6eef7; border-radius: 0; overflow: hidden; background: #f7fbff; height: 34px; }
    .status-tab { border: none; border-right: 1px solid #e6eef7; background: transparent; color: #4f667d; padding: 0 12px; font-size: 12px; font-weight: 600; height: 100%; cursor: pointer; }
    .status-tab:last-child { border-right: none; }
    .status-tab.active { background: #eaf3fd; color: #2c5071; }
    .status { color: var(--sub); min-height: 20px; font-size: 12px; padding: 4px 12px; }
    .table-wrap { overflow: auto; }
    table { width: 100%; border-collapse: collapse; min-width: 750px; table-layout: fixed; }
    th, td { border-bottom: 1px solid var(--line); padding: 6px 10px; text-align: left; vertical-align: top; font-size: 13px; }
    th { color: #2a435a; font-weight: 700; font-size: 13px; position: sticky; top: 0; background: #f7fbff; letter-spacing: 0.02em; }
    th:nth-child(1), td:nth-child(1) { width: 40%; }
    th:nth-child(2), td:nth-child(2) { width: 10%; }
    th:nth-child(3), td:nth-child(3) { width: 8%; }
    th:nth-child(4), td:nth-child(4) { width: 8%; }
    th:nth-child(5), td:nth-child(5) { width: 8%; }
    th:nth-child(6), td:nth-child(6) { width: 16%; }
    tbody tr:hover { background: #fbfdff; }
    .pagination-wrap { display: flex; justify-content: center; align-items: center; gap: 12px; padding: 12px 12px; min-height: 40px; }
    .pagination-btn { border: 1px solid #e6eef7; background: #f7fbff; color: #4f667d; padding: 6px 12px; font-size: 12px; font-weight: 600; border-radius: 0; cursor: pointer; }
    .pagination-btn:hover:not(:disabled) { background: #eef6ff; }
    .pagination-btn:disabled { opacity: 0.4; cursor: not-allowed; }
    .page-info { font-size: 12px; color: #60758d; font-weight: 600; min-width: 60px; text-align: center; }
    .pill { border-radius: 0; padding: 3px 8px; display: inline-flex; font-weight: 700; font-size: 13px; gap: 4px; align-items: center; text-transform: lowercase; }
    .pill::before { content: '#'; width: auto; height: auto; border-radius: 0; font-weight: 800; }
    .queued { color: #6e7d8c; }
    .running { color: #c7821f; }
    .done { color: #1f9956; }
    .failed { color: #d64545; }
    .bug-pill { border-radius: 0; padding: 2px 6px; font-size: 13px; font-weight: 700; display: inline-block; }
    .bug-yes { background: #fdeaea; color: #bb2f2f; }
    .bug-no { background: #e9f7ef; color: #1f9956; }
    .bug-unknown { background: #f2f5f8; color: #6e7d8c; }
    .tags { margin-top: 2px; display: flex; gap: 4px; flex-wrap: wrap; }
    .tag { background: #eef5fc; color: #2f6fad; padding: 2px 6px; font-size: 12px; border-radius: 0; }
    .date-chip { display: inline-block; padding: 2px 8px; background: #f2f6fb; color: #4e657b; border-radius: 0; font-size: 12px; white-space: nowrap; }
    .pr-header { line-height: 1.4; }
    .pr-title-text { color: #1f2d3d; font-size: 13px; font-weight: 600; }

    .pr-link { color: #1750a6; font-size: 13px; font-weight: 700; display: inline; margin-right: 8px; }
    a { color: #1750a6; text-decoration: none; font-weight: 700; }
    a:hover { text-decoration: underline; }
    @media (max-width: 750px) { .query-row { min-width: 750px; } }
  </style>
</head>
<body>
  <div class="shell">
    <div class="brand-strip"></div>
    <div class="head">
      <div class="head-main">
        <h1 class="title">Archer Review Board</h1>
        <div class="sub">Live tracking for PR review progress.</div>
      </div>
      <div class="head-badge">Archer</div>
    </div>

    <div class="toolbar">
      <div class="query-wrap">
        <div class="query-row">
          <div id="statusTabs" class="status-tabs">
            <button class="status-tab active" data-status="all">All</button>
            <button class="status-tab" data-status="running">Running</button>
            <button class="status-tab" data-status="queued">Queued</button>
            <button class="status-tab" data-status="succeeded">Done</button>
            <button class="status-tab" data-status="failed">Failed</button>
          </div>
          <div class="search-box">
            <input id="searchInput" class="search-input" type="text" placeholder="Search PR, title, components..." />
            <button id="clearBtn" class="input-clear" type="button">×</button>
          </div>
        </div>
      </div>
    </div>

    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>PR</th>
            <th>State</th>
            <th>Bug</th>
            <th>Review</th>
            <th>History</th>
            <th>Date</th>
          </tr>
        </thead>
        <tbody id="tbody"></tbody>
      </table>
    </div>

    <div class="pagination-wrap">
      <button id="firstBtn" class="pagination-btn" type="button">« First</button>
      <button id="prevBtn" class="pagination-btn" type="button">← Previous</button>
      <span id="pageInfo" class="page-info"></span>
      <button id="nextBtn" class="pagination-btn" type="button">Next →</button>
      <button id="lastBtn" class="pagination-btn" type="button">Last »</button>
    </div>
  </div>

  <script>
    let allJobs = [];
    let currentStatus = 'all';
    let currentPage = 1;
    const ITEMS_PER_PAGE = 15;
    let currentFiltered = [];

    function esc(v) {
      return (v || '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
    }

    function formatDate(isoStr) {
      if (!isoStr) return '';
      const d = new Date(isoStr);
      const y = d.getFullYear();
      const m = String(d.getMonth() + 1).padStart(2, '0');
      const day = String(d.getDate()).padStart(2, '0');
      const h = String(d.getHours()).padStart(2, '0');
      const min = String(d.getMinutes()).padStart(2, '0');
      return y + '-' + m + '-' + day + ' ' + h + ':' + min;
    }

    function stateMeta(status) {
      if (status === 'succeeded') return { label: 'done', cls: 'done' };
      if (status === 'running') return { label: 'running', cls: 'running' };
      if (status === 'failed') return { label: 'failed', cls: 'failed' };
      if (status === 'queued') return { label: 'queued', cls: 'queued' };
      return { label: 'unknown', cls: 'queued' };
    }

    function applyFilters(options = {}) {
      const resetPage = options.resetPage !== false;
      const query = (document.getElementById('searchInput').value || '').trim().toLowerCase();
      currentFiltered = allJobs.filter(j => {
        if (currentStatus !== 'all' && (j.status || '') !== currentStatus) return false;
        if (!query) return true;
        const bugText = j.bug_found === true ? 'bug yes found' : (j.bug_found === false ? 'bug no not found' : 'bug unknown');
        const hay = [String(j.pr_id || ''), j.title || '', (j.components || []).join(' '), bugText].join(' ').toLowerCase();
        return hay.includes(query);
      });
      const totalPages = Math.ceil(currentFiltered.length / ITEMS_PER_PAGE) || 1;
      if (resetPage) {
        currentPage = 1;
      } else if (currentPage > totalPages) {
        currentPage = totalPages;
      }
      renderRows();
      updatePaginationControls();
    }

    function setStatusFilter(status) {
      currentStatus = status;
      document.querySelectorAll('.status-tab').forEach(el => el.classList.toggle('active', el.dataset.status === status));
      applyFilters({ resetPage: true });
    }

    function renderRows() {
      const tbody = document.getElementById('tbody');
      const start = (currentPage - 1) * ITEMS_PER_PAGE;
      const end = start + ITEMS_PER_PAGE;
      const pageJobs = currentFiltered.slice(start, end);

      tbody.innerHTML = pageJobs.map(j => {
        const state = stateMeta(j.status);
        const prCell = '<div class="pr-header"><a class="pr-link" href="https://github.com/llvm/llvm-project/pull/' + j.pr_id + '" target="_blank">#' + j.pr_id + '</a><span class="pr-title-text">' + esc(j.title || '(no title)') + '</span></div>'
          + (j.components && j.components.length ? '<div class="tags">' + j.components.map(c => '<span class="tag">' + esc(c) + '</span>').join('') + '</div>' : '');
        const stateCell = '<span class="pill ' + esc(state.cls) + '">' + esc(state.label) + '</span>';
        const bugCell = j.bug_found === true
          ? '<span class="bug-pill bug-yes">found</span>'
          : (j.bug_found === false
            ? '<span class="bug-pill bug-no">none</span>'
            : '<span class="bug-pill bug-unknown">unknown</span>');
        const reviewLink = j.review_path ? '<a href="/artifact?path=' + encodeURIComponent(j.review_path) + '" target="_blank">view</a>' : '—';
        const historyLink = j.history_path ? '<a href="/artifact?path=' + encodeURIComponent(j.history_path) + '" target="_blank">view</a>' : '—';
        const dateStr = formatDate(j.updated_at);
        return '<tr><td>' + prCell + '</td><td>' + stateCell + '</td><td>' + bugCell + '</td><td>' + reviewLink + '</td><td>' + historyLink + '</td><td><span class="date-chip">' + dateStr + '</span></td></tr>';
      }).join('');
    }

    function updatePaginationControls() {
      const totalPages = Math.ceil(currentFiltered.length / ITEMS_PER_PAGE) || 1;
      const firstBtn = document.getElementById('firstBtn');
      const prevBtn = document.getElementById('prevBtn');
      const nextBtn = document.getElementById('nextBtn');
      const lastBtn = document.getElementById('lastBtn');
      const pageInfo = document.getElementById('pageInfo');

      pageInfo.textContent = 'Page ' + currentPage + ' / ' + totalPages;
      firstBtn.disabled = currentPage <= 1;
      prevBtn.disabled = currentPage <= 1;
      nextBtn.disabled = currentPage >= totalPages;
      lastBtn.disabled = currentPage >= totalPages;
    }

    async function refreshJobs() {
      try {
        const resp = await fetch('/api/jobs');
        if (!resp.ok) throw new Error('Failed');
        allJobs = (await resp.json()).jobs || [];
        applyFilters({ resetPage: false });
      } catch (err) {
        document.getElementById('pageInfo').textContent = 'Error: ' + err;
      }
    }

    document.getElementById('searchInput').addEventListener('input', () => applyFilters({ resetPage: true }));
    document.getElementById('statusTabs').addEventListener('click', ev => {
      if (ev.target.classList.contains('status-tab')) setStatusFilter(ev.target.dataset.status || 'all');
    });
    document.getElementById('clearBtn').addEventListener('click', () => {
      document.getElementById('searchInput').value = '';
      setStatusFilter('all');
      document.getElementById('searchInput').focus();
    });
    document.getElementById('firstBtn').addEventListener('click', () => {
      if (currentPage > 1) {
        currentPage = 1;
        renderRows();
        updatePaginationControls();
      }
    });
    document.getElementById('prevBtn').addEventListener('click', () => {
      if (currentPage > 1) {
        currentPage--;
        renderRows();
        updatePaginationControls();
      }
    });
    document.getElementById('nextBtn').addEventListener('click', () => {
      const totalPages = Math.ceil(currentFiltered.length / ITEMS_PER_PAGE) || 1;
      if (currentPage < totalPages) {
        currentPage++;
        renderRows();
        updatePaginationControls();
      }
    });
    document.getElementById('lastBtn').addEventListener('click', () => {
      const totalPages = Math.ceil(currentFiltered.length / ITEMS_PER_PAGE) || 1;
      if (currentPage < totalPages) {
        currentPage = totalPages;
        renderRows();
        updatePaginationControls();
      }
    });

    setInterval(() => refreshJobs(), 5000);
    refreshJobs();
  </script>
</body>
</html>"""


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


def detect_bug_found(stats_path: Optional[str]) -> Optional[bool]:
  if not stats_path:
    return None
  try:
    data = json.loads(Path(stats_path).read_text())
  except Exception:
    return None

  bugs = data.get("bugs") if isinstance(data, dict) else None
  if isinstance(bugs, list):
    return len(bugs) > 0
  return None


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


def markdown_to_html(md_text: str) -> str:
  """Convert a small markdown subset to stable HTML for review rendering."""
  if not md_text:
    return "<p><em>(no content)</em></p>"

  def format_inline(text: str) -> str:
    placeholders = []

    def stash_code(match: re.Match[str]) -> str:
      placeholders.append(f"<code>{esc(match.group(1))}</code>")
      return f"@@CODE{len(placeholders) - 1}@@"

    escaped = re.sub(r"`([^`]+)`", stash_code, text)
    escaped = esc(escaped)
    escaped = re.sub(
      r"\[([^\]]+)\]\(([^)]+)\)",
      lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>',
      escaped,
    )
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"__(.+?)__", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", escaped)
    escaped = re.sub(r"_([^_]+)_", r"<em>\1</em>", escaped)
    for idx, value in enumerate(placeholders):
      escaped = escaped.replace(f"@@CODE{idx}@@", value)
    return escaped

  lines = md_text.splitlines()
  blocks = []
  paragraph_lines = []
  list_items = []
  code_lines = []
  code_lang = ""
  in_code_block = False

  def flush_paragraph() -> None:
    nonlocal paragraph_lines
    if not paragraph_lines:
      return
    text = "<br>".join(format_inline(line) for line in paragraph_lines)
    blocks.append(f"<p>{text}</p>")
    paragraph_lines = []

  def flush_list() -> None:
    nonlocal list_items
    if not list_items:
      return
    items = "".join(f"<li>{format_inline(item)}</li>" for item in list_items)
    blocks.append(f"<ul>{items}</ul>")
    list_items = []

  def flush_code() -> None:
    nonlocal code_lines, code_lang
    if not code_lines and not code_lang:
      return
    label = f'<div class="md-code-lang">{esc(code_lang)}</div>' if code_lang else ""
    code_html = esc("\n".join(code_lines))
    blocks.append(
      f'<div class="md-code-block">{label}<pre><code>{code_html}</code></pre></div>'
    )
    code_lines = []
    code_lang = ""

  for raw_line in lines:
    line = raw_line.rstrip()

    if line.startswith("```"):
      flush_paragraph()
      flush_list()
      if in_code_block:
        flush_code()
        in_code_block = False
      else:
        in_code_block = True
        code_lang = line[3:].strip()
        code_lines = []
      continue

    if in_code_block:
      code_lines.append(raw_line)
      continue

    stripped = line.strip()
    if not stripped:
      flush_paragraph()
      flush_list()
      continue

    heading = re.match(r"^(#{1,3})\s+(.+)$", stripped)
    if heading:
      flush_paragraph()
      flush_list()
      level = len(heading.group(1))
      blocks.append(f"<h{level}>{format_inline(heading.group(2))}</h{level}>")
      continue

    list_match = re.match(r"^-\s+(.+)$", stripped)
    if list_match:
      flush_paragraph()
      list_items.append(list_match.group(1))
      continue

    paragraph_lines.append(stripped)

  if in_code_block:
    flush_code()
  flush_paragraph()
  flush_list()
  return "".join(blocks) if blocks else "<p><em>(no content)</em></p>"


def build_review_html_from_stats(stats_data: dict) -> str:
  """Build review page from stats.json data."""
  strategies = stats_data.get("strategies", [])
  bugs = stats_data.get("bugs", [])
  report_raw = stats_data.get("report", {})

  # Parse report if it's a JSON string
  report = report_raw
  if isinstance(report_raw, str):
    try:
      report = json.loads(report_raw)
    except Exception:
      report = {}

  # Format strategies section - add numbered list
  strategies_html = ""
  for i, strat in enumerate(strategies, 1):
    name = strat.get("name", "")
    target = strat.get("target", "")
    rationale = strat.get("rationale", "")
    expected = strat.get("expected_issue", "")
    strategy_id = f"strategy_{i}"

    strategies_html += f"""
    <div class="strategy-card">
      <div class="strategy-fold" id="{strategy_id}">
        <div class="strategy-head">
          <h4 class="strategy-title"><span style="font-weight: 700;">{i}.</span> {esc(name)}</h4>
          <button type="button" class="fold-toggle" data-target="{strategy_id}" title="展开/收起">
            <span class="fold-icon" aria-hidden="true"></span>
          </button>
        </div>
        <div class="strategy-body">
          <div style="margin: 8px 0; font-size: 13px; line-height: 1.5;">
            <strong style="color: #424a53;">Target:</strong><br>{esc(target)}
          </div>
          <div style="margin: 8px 0; font-size: 13px; line-height: 1.5;">
            <strong style="color: #424a53;">Rationale:</strong><br>{esc(rationale)}
          </div>
          <div style="margin: 8px 0; font-size: 13px; line-height: 1.5;">
            <strong style="color: #424a53;">Expected Issue:</strong><br>{esc(expected)}
          </div>
        </div>
      </div>
    </div>"""

  # Format bugs section - include full log with collapsible UI
  bugs_html = ""
  for i, bug in enumerate(bugs, 1):
    orig_ir = bug.get("original_ir", "")
    trans_ir = bug.get("transformed_ir", "")
    log = bug.get("log", "")

    unique_id = f"bug_{i}_log"
    orig_ir_html = f'<div class="bug-ir-body">{esc(orig_ir)}</div>'
    trans_ir_html = f'<div class="bug-ir-body">{esc(trans_ir)}</div>'
    log_html = (
      (
        f'<div class="bug-log-fold" id="{unique_id}">'
        f'<div class="bug-log-body">{esc(log)}</div>'
        f'<button type="button" class="fold-toggle" data-target="{unique_id}" title="展开/收起">'
        f'<span class="fold-icon" aria-hidden="true"></span>'
        "</button>"
        "</div>"
      )
      if len(log) > 320
      else (f'<div class="bug-log-body bug-log-body-static">{esc(log)}</div>')
    )

    bugs_html += f"""
    <div style="margin-bottom: 24px; padding: 14px 16px; background: #fef3c7; border-left: 3px solid #d97706; border-radius: 4px;">
      <h4 style="margin: 0 0 12px 0; color: #92400e; font-size: 15px;">Bug #{i}</h4>
      <div style="margin: 12px 0; font-size: 12px;">
        <strong style="color: #92400e; display: block; margin-bottom: 6px;">Original IR:</strong>
        {orig_ir_html}
      </div>
      <div style="margin: 12px 0; font-size: 12px;">
        <strong style="color: #92400e; display: block; margin-bottom: 6px;">Transformed IR:</strong>
        {trans_ir_html}
      </div>
      <div style="margin: 12px 0; font-size: 12px;">
        <strong style="color: #92400e; display: block; margin-bottom: 6px;">Error/Output Log:</strong>
        {log_html}
      </div>
    </div>"""

  if not bugs_html:
    bugs_html = '<p style="color: #999; font-size: 13px;"><em>No bugs found</em></p>'

  # Format analysis section - use report['thoughts'] field
  report_text = ""
  if isinstance(report, dict) and "thoughts" in report:
    report_text = report["thoughts"]
  else:
    report_text = "No analysis available"

  analysis_html = (
    '<div class="analysis-card">'
    f'<div class="analysis-body">{markdown_to_html(report_text)}</div>'
    "</div>"
  )

  html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Review</title>
  <style>
    :root {{
      --ink: #1f2d3d;
      --sub: #60758d;
      --line: #eaf0f7;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: var(--ink); background: #ffffff; }}
    .review-container {{ max-width: 1000px; margin: 0 auto; padding: 24px 32px; }}
    .head {{ margin-bottom: 20px; padding-bottom: 0; }}
    .title {{ margin: 0; font-size: 28px; font-weight: 700; }}
    .subtitle {{ margin-top: 8px; color: var(--sub); font-size: 13px; }}
    .section {{ margin: 28px 0; }}
    .section-title {{ font-size: 16px; font-weight: 700; margin-bottom: 16px; color: var(--ink); }}
    code {{ background: #f5f5f5; padding: 2px 6px; border-radius: 3px; font-family: 'Monaco', 'Menlo', monospace; font-size: 12px; }}
    pre {{ background: #f5f5f5; padding: 12px; border-radius: 4px; overflow-x: auto; line-height: 1.4; font-size: 12px; }}
    strong {{ font-weight: 600; }}
    a {{ color: #2f6fad; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .analysis-card {{ padding: 14px 16px; background: #eef5fc; border-left: 3px solid #2f6fad; border-radius: 4px; }}
    .strategy-card {{ margin-bottom: 20px; padding: 14px 16px; background: #fafbfc; border-left: 3px solid #6e7681; border-radius: 4px; }}
    .strategy-fold {{ position: relative; }}
    .strategy-head {{ position: relative; padding-right: 34px; }}
    .strategy-title {{ margin: 0; color: #1f2d3d; font-size: 15px; }}
    .strategy-body {{ display: none; margin-top: 10px; }}
    .strategy-fold.expanded .strategy-body {{ display: block; }}
    .strategy-card .fold-icon {{ border-color: #cdd9e6; }}
    .strategy-card .fold-icon::before, .strategy-card .fold-icon::after {{
      border-right-color: #546b83;
      border-bottom-color: #546b83;
    }}
    .strategy-card .fold-toggle:hover .fold-icon {{ background: #eef5fc; }}
    .analysis-body {{ line-height: 1.6; font-size: 13px; color: #333; }}
    .analysis-body h1, .analysis-body h2, .analysis-body h3 {{
      margin: 0 0 12px 0;
      color: #1f2d3d;
      line-height: 1.35;
    }}
    .analysis-body h1 {{ font-size: 22px; }}
    .analysis-body h2 {{ font-size: 16px; margin-top: 22px; }}
    .analysis-body h3 {{ font-size: 14px; margin-top: 18px; }}
    .analysis-body p {{ margin: 0 0 14px 0; }}
    .analysis-body ul {{ margin: 0 0 14px 18px; padding: 0; }}
    .analysis-body li {{ margin: 0 0 6px 0; }}
    .analysis-body .md-code-block {{ margin: 0 0 14px 0; background: #f5f5f5; border-radius: 4px; overflow: hidden; }}
    .analysis-body .md-code-lang {{ padding: 8px 12px 0 12px; font-size: 12px; color: #60758d; text-transform: lowercase; }}
    .analysis-body .md-code-block pre {{ margin: 0; border-radius: 0; }}
    .bug-ir-body {{
      background: #fff7e6;
      padding: 10px;
      border-radius: 3px;
      font-family: monospace;
      overflow-x: auto;
      overflow-y: auto;
      max-height: 400px;
      line-height: 1.4;
      color: #333;
      white-space: pre-wrap;
      word-break: normal;
      overflow-wrap: anywhere;
    }}
    .bug-log-fold {{ margin-top: 6px; position: relative; }}
    .bug-log-body {{
      background: #fff7e6;
      padding: 10px;
      border-radius: 3px;
      font-family: monospace;
      overflow-x: auto;
      line-height: 1.4;
      color: #555;
      white-space: pre-wrap;
      word-break: break-all;
    }}
    .bug-log-fold .bug-log-body {{
      margin-top: 0;
      max-height: 9.5em;
      overflow: hidden;
      position: relative;
      transition: max-height 0.18s ease;
      padding-right: 34px;
    }}
    .bug-log-fold .bug-log-body::after {{
      content: "";
      position: absolute;
      left: 0;
      right: 0;
      bottom: 0;
      height: 2.6em;
      background: linear-gradient(to bottom, rgba(255, 247, 230, 0), #fff7e6 75%);
      pointer-events: none;
    }}
    .bug-log-fold.expanded .bug-log-body {{
      max-height: 400px;
      overflow-y: auto;
      overflow-x: auto;
    }}
    .bug-log-fold.expanded .bug-log-body::after {{
      display: none;
    }}
    .bug-log-body-static {{ max-height: 400px; overflow-y: auto; }}
    .fold-toggle {{
      position: absolute;
      right: 2px;
      bottom: 2px;
      width: 24px;
      height: 24px;
      border: none;
      background: transparent;
      padding: 0;
      cursor: pointer;
      z-index: 2;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }}
    .fold-icon {{
      position: relative;
      width: 22px;
      height: 22px;
      border: 1px solid #e3c8a8;
      border-radius: 11px;
      background: #ffffff;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }}
    .fold-icon::before, .fold-icon::after {{
      content: "";
      position: absolute;
      left: 50%;
      width: 6px;
      height: 6px;
      border-right: 2px solid #8a5a21;
      border-bottom: 2px solid #8a5a21;
      transform: translateX(-50%) rotate(45deg);
    }}
    .fold-icon::before {{ top: 4px; }}
    .fold-icon::after {{ top: 9px; }}
    .bug-log-fold.expanded .fold-icon::before, .bug-log-fold.expanded .fold-icon::after {{
      transform: translateX(-50%) rotate(225deg);
    }}
    .fold-toggle:hover .fold-icon {{ background: #fff7e6; }}
  </style>
</head>
<body>
  <div class="review-container">
    <div class="head">
      <h1 class="title">Review Report</h1>
      <div class="subtitle">Agent analysis and findings from PR review</div>
    </div>

    <div class="section">
      <h2 class="section-title">Test Strategies (Phase 1)</h2>
      {strategies_html}
    </div>

    <div class="section">
      <h2 class="section-title">Bugs Found (Phase 2)</h2>
      {bugs_html}
    </div>

    <div class="section">
      <h2 class="section-title">Analysis & Findings</h2>
      {analysis_html}
    </div>
  </div>
  <script>
    document.querySelectorAll('.bug-log-fold, .strategy-fold').forEach(function (box) {{
      box.classList.remove('expanded');
    }});

    document.addEventListener('click', function (ev) {{
      const btn = ev.target.closest('.fold-toggle');
      if (!btn) return;
      const id = btn.getAttribute('data-target');
      if (!id) return;
      const box = document.getElementById(id);
      if (!box) return;
      box.classList.toggle('expanded');
    }});
  </script>
</body>
</html>"""

  return html


@app.get("/artifact", response_class=HTMLResponse)
def artifact_viewer(path: str) -> str:
  target = Path(path).resolve()
  allowed_root = config.data_dir.resolve()
  if not str(target).startswith(str(allowed_root)):
    raise HTTPException(status_code=403, detail="Access denied")
  if not target.exists():
    raise HTTPException(status_code=404, detail="Not found")

  content = target.read_text()

  # Check if it's a stats.json file - build review from it
  if str(target).endswith(".stats.json"):
    try:
      stats_data = json.loads(content)
      return build_review_html_from_stats(stats_data)
    except Exception as e:
      return f"<pre>Error parsing stats.json: {str(e)}</pre>"

  # Check if it's a review markdown file - try to find corresponding stats.json
  if str(target).endswith(".review.md"):
    # Derive stats.json path from review.md path
    base_path = str(target).rsplit(".", 2)[0]  # Remove .review.md
    stats_path = Path(base_path + ".stats.json")

    if stats_path.exists():
      try:
        stats_data = json.loads(stats_path.read_text())
        return build_review_html_from_stats(stats_data)
      except Exception:
        pass  # Fall back to old behavior

  try:
    data = json.loads(content)
    is_json = True
  except Exception:
    is_json = False
    data = content

  html = """<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Agent Trajectory</title>
  <style>
    :root {
      --ink: #1f2d3d;
      --sub: #60758d;
      --line: #eaf0f7;
      --blue-soft: #f4f9ff;
    }
    body { margin: 0; padding: 16px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: var(--ink); background: #ffffff; }
    .viewer { max-width: 1100px; margin: 0 auto; padding: 8px 10px 24px; }
    .head { margin-bottom: 12px; }
    .title { margin: 0; font-size: 26px; line-height: 1.2; font-weight: 700; }
    .sub { margin-top: 6px; color: var(--sub); font-size: 13px; word-break: break-all; }
    .summary-grid { display: grid; grid-template-columns: repeat(4, minmax(120px, 1fr)); gap: 8px; margin: 12px 0; }
    .stat { border: 1px solid var(--line); background: #f9fcff; padding: 8px 10px; }
    .stat-label { font-size: 11px; color: var(--sub); text-transform: uppercase; letter-spacing: 0.04em; }
    .stat-value { margin-top: 4px; font-size: 18px; font-weight: 700; color: var(--ink); }
    .tools { border: 1px solid var(--line); background: #f9fcff; padding: 10px; margin-bottom: 12px; }
    .tools-title { font-size: 12px; color: var(--sub); margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.04em; }
    .tool-badges { display: flex; flex-wrap: wrap; gap: 6px; }
    .tool-badge { border: 1px solid #d5e4f2; background: #ffffff; color: #35516c; padding: 3px 8px; font-size: 12px; }
    pre { background: #f7fbff; padding: 12px; overflow-x: auto; border: 1px solid #eaf0f7; }
    .msg { position: relative; margin: 10px 0; padding: 10px; border-left: 3px solid #2f6fad; background: var(--blue-soft); }
    .msg.user { border-left-color: #c7821f; background: #fff9e6; }
    .msg.assistant { border-left-color: #1f9956; background: #f0f9f0; }
    .msg.system { border-left-color: #2f6fad; background: #eef5fc; }
    .msg.tool { border-left-color: #7a8694; background: #f2f5f8; }
    .msg-body { margin-top: 10px; white-space: pre-wrap; word-break: break-word; }
    .msg-fold { margin-top: 8px; position: relative; }
    .msg-fold .msg-body {
      margin-top: 0;
      max-height: 9.5em;
      overflow: hidden;
      position: relative;
      transition: max-height 0.18s ease;
    }
    .msg-fold .msg-body::after {
      content: "";
      position: absolute;
      left: 0;
      right: 0;
      bottom: 0;
      height: 2.6em;
      background: linear-gradient(to bottom, rgba(247, 251, 255, 0), #f7fbff 75%);
      pointer-events: none;
    }
    .msg-fold.expanded .msg-body {
      max-height: none;
      overflow: visible;
    }
    .msg-fold.expanded .msg-body::after {
      display: none;
    }
    .fold-toggle {
      position: absolute;
      right: 2px;
      bottom: 2px;
      width: 24px;
      height: 24px;
      border: none;
      background: transparent;
      padding: 0;
      cursor: pointer;
      z-index: 2;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }
    .fold-icon {
      position: relative;
      width: 22px;
      height: 22px;
      border: 1px solid #cdd9e6;
      border-radius: 11px;
      background: #ffffff;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }
    .fold-icon::before, .fold-icon::after {
      content: "";
      position: absolute;
      left: 50%;
      width: 6px;
      height: 6px;
      border-right: 2px solid #546b83;
      border-bottom: 2px solid #546b83;
      transform: translateX(-50%) rotate(45deg);
    }
    .fold-icon::before { top: 4px; }
    .fold-icon::after { top: 9px; }
    .msg-fold.expanded .fold-icon::before, .msg-fold.expanded .fold-icon::after {
      transform: translateX(-50%) rotate(225deg);
    }
    .fold-toggle:hover .fold-icon { background: #eef5fc; }
    h3 { margin: 0; font-size: 12px; color: #60758d; }
  </style>
</head>
<body>
  <div class="viewer">
    <div class="head">
      <h1 class="title">Agent Trajectory</h1>
      <div class="sub">Conversation timeline with tool traces and model turns</div>
    </div>
"""

  if is_json and isinstance(data, list):
    allowed_roles = {"user", "assistant", "system", "tool"}

    def content_to_text(value):
      if isinstance(value, str):
        return value
      if isinstance(value, list):
        parts = []
        for item in value:
          if isinstance(item, str):
            parts.append(item)
          elif isinstance(item, dict):
            if isinstance(item.get("text"), str):
              parts.append(item["text"])
            elif isinstance(item.get("content"), str):
              parts.append(item["content"])
            else:
              parts.append(json.dumps(item, ensure_ascii=False))
          else:
            parts.append(str(item))
        return "\n".join(p for p in parts if p)
      if isinstance(value, dict):
        if isinstance(value.get("text"), str):
          return value["text"]
        return json.dumps(value, ensure_ascii=False, indent=2)
      return str(value)

    def entry_to_view(msg):
      role = str(msg.get("role", "")).strip().lower()
      if role in allowed_roles:
        return role, role.upper(), content_to_text(msg.get("content", ""))

      msg_type = str(msg.get("type", "")).strip().lower()
      if msg_type == "function_call":
        name = str(msg.get("name", "tool"))
        args_text = content_to_text(msg.get("arguments", ""))
        return "tool", f"TOOL CALL: {name}", args_text
      if msg_type == "function_call_output":
        output_text = content_to_text(msg.get("output", ""))
        return "tool", "TOOL OUTPUT", output_text
      if msg_type:
        content_text = content_to_text(msg.get("content", msg))
        return "tool", f"EVENT: {msg_type}", content_text

      return None

    shown = 0
    trajectory_html = []
    fold_id = 0
    preview_limit = 320
    user_turns = 0
    message_entries = 0
    tool_calls_total = 0
    tool_events_total = 0
    tool_name_counts = {}
    phase_rounds = {}
    current_phase = None
    token_input = 0
    token_output = 0
    token_total = 0
    has_tokens = False

    def read_int(dct, key):
      val = dct.get(key)
      return val if isinstance(val, int) else None

    def ingest_tokens(msg):
      nonlocal token_input, token_output, token_total, has_tokens
      in_tok = None
      out_tok = None
      total_tok = None

      if isinstance(msg.get("usage"), dict):
        u = msg["usage"]
        in_tok = read_int(u, "input_tokens")
        if in_tok is None:
          in_tok = read_int(u, "prompt_tokens")
        out_tok = read_int(u, "output_tokens")
        if out_tok is None:
          out_tok = read_int(u, "completion_tokens")
        total_tok = read_int(u, "total_tokens")

      if in_tok is None:
        in_tok = read_int(msg, "input_tokens")
      if in_tok is None:
        in_tok = read_int(msg, "prompt_tokens")
      if out_tok is None:
        out_tok = read_int(msg, "output_tokens")
      if out_tok is None:
        out_tok = read_int(msg, "completion_tokens")
      if total_tok is None:
        total_tok = read_int(msg, "total_tokens")

      if in_tok is None and out_tok is None and total_tok is None:
        return

      has_tokens = True
      if in_tok is not None:
        token_input += in_tok
      if out_tok is not None:
        token_output += out_tok
      if total_tok is not None:
        token_total += total_tok
      else:
        token_total += (in_tok or 0) + (out_tok or 0)

    def detect_phase_number(msg):
      if str(msg.get("role", "")).strip().lower() != "user":
        return None
      txt = content_to_text(msg.get("content", ""))
      m = re.search(r"#\s*phase\s*(\d+)", txt, re.I)
      if not m:
        return None
      try:
        return int(m.group(1))
      except Exception:
        return None

    for msg in data:
      if not isinstance(msg, dict):
        continue

      if msg.get("type") == "message":
        message_entries += 1

      phase_no = detect_phase_number(msg)
      if phase_no is not None:
        current_phase = phase_no

      view = entry_to_view(msg)
      if view is None:
        continue

      role_raw = str(msg.get("role", "")).strip().lower()
      if role_raw == "user":
        user_turns += 1

      msg_type = str(msg.get("type", "")).strip().lower()
      if msg_type == "function_call":
        tool_calls_total += 1
        if current_phase is not None:
          phase_rounds[current_phase] = phase_rounds.get(current_phase, 0) + 1
        tname = str(msg.get("name", "tool"))
        tool_name_counts[tname] = tool_name_counts.get(tname, 0) + 1
      if msg_type in {"function_call", "function_call_output"}:
        tool_events_total += 1

      ingest_tokens(msg)

      css_role, label, txt = view
      display_txt = txt.strip()
      if not display_txt:
        display_txt = "(empty output)" if label == "TOOL OUTPUT" else "(empty content)"

      if len(display_txt) > preview_limit:
        fold_id += 1
        fold_dom_id = f"fold-{fold_id}"
        trajectory_html.append(
          f'<div class="msg {css_role}">'
          f"<h3>{esc(label)}</h3>"
          f'<div class="msg-fold" id="{fold_dom_id}">'
          f'<pre class="msg-body">{esc(display_txt)}</pre>'
          f'<button type="button" class="fold-toggle" data-target="{fold_dom_id}" title="展开/收起">'
          f'<span class="fold-icon" aria-hidden="true"></span>'
          f"</button>"
          f"</div>"
          f"</div>"
        )
      else:
        trajectory_html.append(
          f'<div class="msg {css_role}"><h3>{esc(label)}</h3><pre class="msg-body">{esc(display_txt)}</pre></div>'
        )
      shown += 1

    token_text = f"{token_total:,}" if has_tokens else "-"
    total_rounds_text = str(tool_calls_total)
    phase1_rounds_text = str(phase_rounds.get(1, 0))
    phase2_rounds_text = str(phase_rounds.get(2, 0))
    if tool_name_counts:
      sorted_tools = sorted(tool_name_counts.items(), key=lambda kv: (-kv[1], kv[0]))
      badges = "".join(
        f'<span class="tool-badge">{esc(name)} x {count}</span>'
        for name, count in sorted_tools[:24]
      )
    else:
      badges = '<span class="tool-badge">(no tool calls)</span>'

    summary_html = (
      '<div class="summary-grid">'
      f'<div class="stat"><div class="stat-label">Total Rounds</div><div class="stat-value">{total_rounds_text}</div></div>'
      f'<div class="stat"><div class="stat-label">Phase 1 Analyze</div><div class="stat-value">{phase1_rounds_text}</div></div>'
      f'<div class="stat"><div class="stat-label">Phase 2 Validate</div><div class="stat-value">{phase2_rounds_text}</div></div>'
      f'<div class="stat"><div class="stat-label">Total Tokens</div><div class="stat-value">{token_text}</div></div>'
      "</div>"
      '<div class="tools">'
      '<div class="tools-title">Tool Call Distribution</div>'
      f'<div class="tool-badges">{badges}</div>'
      "</div>"
    )
    html += summary_html
    html += "".join(trajectory_html)

    if shown == 0:
      html += "<p>No visible history entries found.</p>"
  else:
    html += f"<pre>{esc(str(data))}</pre>"

  html += """
  <script>
    document.addEventListener('click', function (ev) {
      const btn = ev.target.closest('.fold-toggle');
      if (!btn) return;
      const id = btn.getAttribute('data-target');
      if (!id) return;
      const box = document.getElementById(id);
      if (!box) return;
      box.classList.toggle('expanded');
    });
  </script>
"""

  html += "</div></body></html>"
  return html


def esc(v):
  return (v or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
