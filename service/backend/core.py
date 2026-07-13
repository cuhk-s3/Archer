import json
import queue
import subprocess
import sys
import threading
import time
import zipfile
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests

from .config import ServiceConfig
from .models import Job, utc_now_iso

_TEST_PATH_PREFIXES: list[str] = [
  "llvm/test/Transforms/InstCombine",
  "llvm/test/Transforms/InstSimplify",
  "llvm/test/Analysis/ValueTracking",
  "llvm/test/Transforms/ConstraintElimination",
  "llvm/test/Transforms/EarlyCSE",
  "llvm/test/Transforms/GVN",
  "llvm/test/Transforms/NewGVN",
  "llvm/test/Transforms/Reassociate",
  "llvm/test/Transforms/SCCP",
  "llvm/test/Transforms/CorrelatedValuePropagation",
  "llvm/test/Transforms/SimplifyCFG",
  "llvm/test/Transforms/VectorCombine",
  "llvm/test/Transforms/SLPVectorizer",
  "llvm/test/Transforms/AggressiveInstCombine",
]

_SOURCE_PATH_PREFIXES: list[str] = [
  "llvm/lib/Transforms/InstCombine",
  "llvm/lib/Analysis/InstructionSimplify",
  "llvm/lib/Analysis/ValueTracking",
  "llvm/lib/Analysis/ConstantFolding",
  "llvm/lib/IR/ConstantFold",
  "llvm/lib/IR/ConstantRange",
  "llvm/lib/IR/ConstantFPRange",
  "llvm/lib/Support/KnownBits",
  "llvm/lib/Support/KnownFPClass",
  "llvm/include/llvm/Analysis/InstructionSimplify.h",
  "llvm/include/llvm/Analysis/ValueTracking.h",
  "llvm/include/llvm/Analysis/ConstantFolding.h",
  "llvm/include/llvm/Support/KnownBits.h",
  "llvm/include/llvm/Support/KnownFPClass.h",
  "llvm/lib/Transforms/ConstraintElimination",
  "llvm/lib/Transforms/Scalar/EarlyCSE",
  "llvm/lib/Transforms/Scalar/GVN",
  "llvm/lib/Transforms/Scalar/NewGVN",
  "llvm/lib/Transforms/Scalar/Reassociate",
  "llvm/lib/Transforms/Scalar/SCCP",
  "llvm/lib/Transforms/Scalar/CorrelatedValuePropagation",
  "llvm/lib/Transforms/Utils/SimplifyCFG.cpp",
  "llvm/lib/Transforms/Vectorize/VectorCombine",
  "llvm/lib/Transforms/Vectorize/SLPVectorizer.cpp",
  "llvm/lib/Transforms/AggressiveInstCombine",
]

ALL_KEYWORDS: list[str] = _TEST_PATH_PREFIXES + _SOURCE_PATH_PREFIXES

_EXCLUDED_TITLE_KEYWORDS: list[str] = [
  "NFC",
  "[DAG]",
  "[GISEL]",
  "GLOBALISEL",
  "SELECTIONDAG",
  "CODEGEN",
]

_EXCLUDED_FILE_SEGMENTS: list[str] = [
  "/AsmParser/",
  "/Bitcode/",
  "/CodeGen/",
  "/GlobalISel/",
  "/SelectionDAG/",
  "/Target/",
]


def is_excluded_pr_title(title: str) -> bool:
  upper_title = title.upper()
  return any(keyword in upper_title for keyword in _EXCLUDED_TITLE_KEYWORDS)


def is_excluded_pr_file(pr_file_path: str) -> bool:
  return any(segment in pr_file_path for segment in _EXCLUDED_FILE_SEGMENTS)


def has_excluded_pr_label(label_names: List[str]) -> bool:
  lowered = [label.lower() for label in label_names]
  return (
    any(label.startswith("backend:") for label in lowered)
    or any(label.startswith("compiler-rt:") for label in lowered)
    or any(label.startswith("pgo") for label in lowered)
  )


def is_relevant_pr_file(pr_file_path: str) -> bool:
  return any(pr_file_path.startswith(keyword) for keyword in ALL_KEYWORDS)


class ArcherService:
  def __init__(self, config: ServiceConfig):
    self.config = config
    self.jobs: Dict[str, Job] = {}
    self.jobs_by_pr: Dict[int, str] = {}
    self.queue: "queue.Queue[str]" = queue.Queue(maxsize=config.max_queue_size)
    # RLock (not Lock) so that ``_save_state`` -- which needs to iterate the
    # jobs dict atomically -- can be safely called from a code path that
    # already holds the lock (e.g. ``enqueue_pr``).
    self.lock = threading.RLock()
    self.stop_flag = False
    self.worker_thread: Optional[threading.Thread] = None
    self.scanner_thread: Optional[threading.Thread] = None
    self.remote_thread: Optional[threading.Thread] = None
    self._last_scan_at: Optional[str] = None
    self._load_state()

  def _load_state(self) -> None:
    queued_jobs: List[str] = []
    if self.config.state_file.exists():
      with open(self.config.state_file) as f:
        state = json.load(f)
      for job_data in state.get("jobs", []):
        j = Job(
          id=job_data["id"],
          pr_id=job_data["pr_id"],
          head_sha=job_data.get("head_sha"),
          executor=job_data.get("executor", "local"),
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
          db_path=job_data.get("db_path"),
          ingested=job_data.get("ingested", False),
          logs=job_data.get("logs", []),
          title=job_data.get("title", ""),
          author=job_data.get("author", ""),
          components=job_data.get("components", []),
          remote_run_id=job_data.get("remote_run_id"),
          remote_run_url=job_data.get("remote_run_url"),
          remote_run_status=job_data.get("remote_run_status"),
          remote_run_conclusion=job_data.get("remote_run_conclusion"),
        )
        if not j.components:
          j.components = self._resolve_components(j.pr_id)
        if j.status == "running":
          if j.executor == "github-actions":
            j.status = "running"
            j.phase = j.remote_run_status or "running"
          else:
            j.status = "failed"
            j.error = "Service interrupted"
        if j.status == "queued":
          # For remote executor, "dispatched" jobs should be tracked by poller,
          # not re-enqueued for a second workflow dispatch after restart.
          if (
            j.executor == "github-actions"
            and j.phase in {"dispatching", "dispatched"}
            and j.started_at
          ):
            pass
          else:
            queued_jobs.append(j.id)
        self.jobs[j.id] = j
        self.jobs_by_pr[j.pr_id] = j.id
      # Enforce the "only newest commit per PR is queued" invariant on the
      # loaded snapshot. If two queued jobs from before the last shutdown share
      # a PR but sit on different commits, keep only the newest (by created_at)
      # and supersede the rest -- the older ones were never worth running once
      # the author pushed the newer commit.
      by_pr_queued: Dict[int, List[Job]] = {}
      for jid in queued_jobs:
        j = self.jobs[jid]
        by_pr_queued.setdefault(j.pr_id, []).append(j)
      still_queued: List[str] = []
      for pr_id, group in by_pr_queued.items():
        group.sort(key=lambda x: x.created_at)
        newest = group[-1]
        for older in group[:-1]:
          if older.head_sha and older.head_sha == newest.head_sha:
            # Same sha, different job id -- keep the newest and drop the older
            # one silently (this is a duplicate, not a supersede).
            older.status = "skipped"
            older.phase = "duplicate"
            older.error = None
          else:
            older.status = "skipped"
            older.phase = "superseded"
            older.error = f"Superseded by newer commit {(newest.head_sha or '')[:10]}"
          older.finished_at = utc_now_iso()
          older.updated_at = older.finished_at
        still_queued.append(newest.id)

      for job_id in still_queued:
        try:
          self.queue.put(job_id, block=False)
        except queue.Full:
          break
      self._save_state()

  def _save_state(self) -> None:
    """Persist the dispatcher's in-flight jobs to disk.

    Only non-terminal jobs are written: a job whose lifecycle is complete
    (``succeeded``/``failed``/``tokenlimit``/``skipped`` with any snapshot
    already ingested) carries no runtime state we need to recover on restart.
    The UI's long-term view of finished reviews comes from the SQLite store,
    not from this file, so evicting terminal jobs keeps state.json bounded to
    "what the orchestrator is currently working on".

    As a side effect, terminal jobs are also removed from the in-memory ``jobs``
    dict here, which prevents the process from accumulating hundreds of
    thousands of finished-job records over long uptimes.
    """
    with self.lock:
      to_evict = [jid for jid, j in self.jobs.items() if j.is_terminal()]
      for jid in to_evict:
        j = self.jobs.pop(jid)
        if self.jobs_by_pr.get(j.pr_id) == jid:
          # Only drop the reverse index entry if it was pointing at this job.
          self.jobs_by_pr.pop(j.pr_id, None)
      state = {"jobs": [asdict(j) for j in self.jobs.values()]}
    self.config.state_file.write_text(json.dumps(state, indent=2))

  def get_job(self, job_id: str) -> Optional[Job]:
    return self.jobs.get(job_id)

  def list_jobs(self) -> List[Job]:
    return sorted(self.jobs.values(), key=lambda j: j.created_at, reverse=True)

  def _get_pr_info(self, pr_id: int) -> Optional[dict]:
    """Fetch stored PR info from the SQLite store (the single source of truth)."""
    project_root = self.config.repo_root.parent
    if str(project_root) not in sys.path:
      sys.path.insert(0, str(project_root))
    try:
      from dataset import get_store

      return get_store().to_pr_info(pr_id)
    except Exception:
      return None

  def _infer_components_from_files(self, diff_files: List[str]) -> List[str]:
    # Keep this behavior aligned with llvm/llvm_helper.py::infer_related_components.
    prefixes = [
      "llvm/lib/Analysis/",
      "llvm/lib/Transforms/Scalar/",
      "llvm/lib/Transforms/Vectorize/",
      "llvm/lib/Transforms/Utils/",
      "llvm/lib/Transforms/IPO/",
      "llvm/lib/Transforms/",
      "llvm/lib/IR/",
    ]
    components: List[str] = []
    seen = set()
    for file in diff_files:
      for prefix in prefixes:
        if not file.startswith(prefix):
          continue
        component_name = (
          file.removeprefix(prefix)
          .split("/")[0]
          .removesuffix(".cpp")
          .removesuffix(".h")
        )
        if component_name == "":
          break
        if (
          component_name.startswith("VPlan")
          or component_name.startswith("LoopVectoriz")
          or component_name.startswith("VPRecipe")
        ):
          component_name = "LoopVectorize"
        if component_name.startswith("ScalarEvolution"):
          component_name = "ScalarEvolution"
        if component_name.startswith("ConstantFold"):
          component_name = "ConstantFold"
        if "AliasAnalysis" in component_name:
          component_name = "AliasAnalysis"
        if component_name.startswith("Attributor"):
          component_name = "Attributor"
        if file.startswith("llvm/lib/IR"):
          component_name = "IR"
        if component_name not in seen:
          seen.add(component_name)
          components.append(component_name)
        break
    return components

  def _resolve_components(
    self,
    pr_id: int,
    files: Optional[List[str]] = None,
    session: Optional[requests.Session] = None,
  ) -> List[str]:
    pr_info = self._get_pr_info(pr_id)
    if isinstance(pr_info, dict):
      stored_components = pr_info.get("components", []) or []
      if stored_components:
        return stored_components

    if files is not None:
      return self._infer_components_from_files(files)

    if not self.config.github_token:
      return []

    own_session = False
    active_session = session
    if active_session is None:
      active_session = self._github_session()
      own_session = True
    try:
      pr_files = self._fetch_pull_files(active_session, pr_id)
      return self._infer_components_from_files(pr_files)
    except Exception:
      return []
    finally:
      if own_session:
        active_session.close()

  # --- Commit-level dedup helpers -------------------------------------------
  # The review identity is (pr_id, head_sha): a PR pushing a new commit must be
  # reviewed again, whereas the same commit must never be reviewed twice. This
  # mirrors the store's (pr_id, fix_commit) versioning.
  #
  # NOTE: an earlier version treated ``failed`` as "retry on next scan", which
  # caused the scanner to re-enqueue the same commit every scan interval (up to
  # dozens of times per commit) when a remote Actions run hit a transient
  # infrastructure error. That both wasted CI budget and starved new commits'
  # jobs behind an ever-growing retry backlog. We now consider *every* prior
  # attempt (including ``failed``) as "already handled" for the automatic
  # scanner: a failed commit stays failed until an operator retries it manually
  # from the host process (there is no HTTP surface for this, see ``app.py``).
  _REDO_STATUSES: set[str] = set()

  def _jobs_for_pr(self, pr_id: int) -> List[Job]:
    return sorted(
      (j for j in self.jobs.values() if j.pr_id == pr_id),
      key=lambda j: j.created_at,
      reverse=True,
    )

  def _find_active_job_for_commit(self, pr_id: int, head_sha: str) -> Optional[Job]:
    """Return an existing job for this exact (pr, commit), if any.

    Checks the in-memory job table first; if nothing matches, falls back to
    the SQLite store: a committed ``pr_versions`` row for this ``(pr, commit)``
    means the commit was already handled by an earlier run whose job record
    has since been evicted from state.json. In that case we return a synthetic
    "sentinel" Job (status=succeeded, ingested=True) purely to signal
    "already handled" to callers -- the dispatcher no longer needs the full
    runtime record, only the yes/no answer.
    """
    for j in self._jobs_for_pr(pr_id):
      if j.head_sha == head_sha and j.status not in self._REDO_STATUSES:
        return j
    # DB fallback: authoritative "was this commit ever reviewed?" record.
    if head_sha and self._commit_already_reviewed(pr_id, head_sha):
      return Job(
        id=f"db-sentinel-{pr_id}-{head_sha[:10]}",
        pr_id=pr_id,
        head_sha=head_sha,
        status="succeeded",
        phase="done",
        ingested=True,
      )
    return None

  def _find_inflight_job_for_pr(self, pr_id: int) -> Optional[Job]:
    """Return an in-flight (queued/running) job for the PR, ignoring commit.

    Only a gentle guard for manual enqueues that carry no head_sha, so repeated
    manual clicks do not stack duplicate jobs for the same PR.
    """
    for j in self._jobs_for_pr(pr_id):
      if j.status in {"queued", "running"}:
        return j
    return None

  def _commit_already_reviewed(self, pr_id: int, head_sha: str) -> bool:
    """Restart-proof authoritative check: does this commit have a version row?

    The store dedups on (pr_id, fix_commit); a present version means the commit
    was already reviewed (or gate-skipped), even if local job state was lost.
    Best-effort: any error is treated as "not reviewed" so scanning proceeds.
    """
    try:
      store = self._store()
      return store.get_version_by_commit(int(pr_id), str(head_sha)) is not None
    except Exception:
      return False

  def enqueue_pr(
    self,
    pr_id: int,
    source: str = "manual",
    force: bool = False,
    head_sha: Optional[str] = None,
  ) -> Job:
    with self.lock:
      if not force:
        existing = (
          self._find_active_job_for_commit(pr_id, head_sha)
          if head_sha
          else self._find_inflight_job_for_pr(pr_id)
        )
        if existing is not None:
          return existing
      existing_id = self.jobs_by_pr.get(pr_id)
      existing_job = self.jobs.get(existing_id) if existing_id else None
      prior_jobs = sorted(
        (j for j in self.jobs.values() if j.pr_id == pr_id),
        key=lambda j: j.created_at,
        reverse=True,
      )
      metadata_job = next(
        (j for j in prior_jobs if j.title or j.author or j.components),
        existing_job,
      )
      # Supersede any older queued jobs of the same PR that were sitting on a
      # *different* commit: only the newest head_sha is worth reviewing, so any
      # intermediate commit still waiting to run gets skipped rather than run
      # through the full review pipeline. We deliberately leave ``running``
      # jobs alone: they are already burning CI time on the remote side and
      # cancelling them would just orphan those runs without saving anything;
      # they will finish naturally, ingest their commit's version + review, and
      # the newer job we are about to enqueue will still be reviewed after.
      if head_sha:
        for j in prior_jobs:
          if j.status == "queued" and j.head_sha and j.head_sha != head_sha:
            j.status = "skipped"
            j.phase = "superseded"
            j.error = f"Superseded by newer commit {head_sha[:10]}"
            j.finished_at = utc_now_iso()
            j.updated_at = j.finished_at
      pr_info = self._get_pr_info(pr_id) or {}
      ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
      job_id = f"{source}-{pr_id}-{ts}"
      job = Job(
        id=job_id,
        pr_id=pr_id,
        head_sha=head_sha,
        executor=self.config.executor,
        status="queued",
        created_at=utc_now_iso(),
        updated_at=utc_now_iso(),
        title=(
          metadata_job.title
          if metadata_job and metadata_job.title
          else str(pr_info.get("title", ""))
        ),
        author=(
          metadata_job.author
          if metadata_job and metadata_job.author
          else str(pr_info.get("author", ""))
        ),
        components=(
          list(metadata_job.components)
          if metadata_job and metadata_job.components
          else self._resolve_components(pr_id)
        ),
      )
      self.jobs[job_id] = job
      self.jobs_by_pr[pr_id] = job_id
      self.queue.put(job_id, block=False)
      self._save_state()
      return job

  def _github_session(self) -> requests.Session:
    session = requests.Session()
    session.headers.update(
      {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "archer-review-service",
      }
    )
    if self.config.github_token:
      session.headers["Authorization"] = f"Bearer {self.config.github_token}"
    return session

  def _is_review_candidate(self, pr_data: dict, files: List[str]) -> bool:
    if not isinstance(pr_data, dict):
      return False
    if pr_data.get("draft", False):
      return False

    title = str(pr_data.get("title", ""))
    if is_excluded_pr_title(title):
      return False

    labels = pr_data.get("labels", [])
    label_names = [
      str(label.get("name", "")) for label in labels if isinstance(label, dict)
    ]
    if has_excluded_pr_label(label_names):
      return False

    base = pr_data.get("base")
    if not (isinstance(base, dict) and base.get("ref") == "main"):
      return False

    if not files:
      return False
    if any(is_excluded_pr_file(path) for path in files):
      return False
    return any(is_relevant_pr_file(path) for path in files)

  def _fetch_open_pr_candidates(self) -> List[dict]:
    session = self._github_session()
    candidates: List[dict] = []
    page = 1
    while len(candidates) < self.config.open_pr_limit:
      response = session.get(
        f"https://api.github.com/repos/{self.config.github_repo}/pulls",
        params={
          "state": "open",
          "sort": "updated",
          "direction": "desc",
          "per_page": 100,
          "page": page,
        },
        timeout=30,
      )
      response.raise_for_status()
      payload = response.json()
      if not isinstance(payload, list) or not payload:
        break
      for item in payload:
        if not isinstance(item, dict):
          continue
        candidates.append(item)
        if len(candidates) >= self.config.open_pr_limit:
          break
      if len(payload) < 100:
        break
      page += 1
    session.close()
    return candidates

  def _fetch_pull_files(self, session: requests.Session, pr_number: int) -> List[str]:
    files: List[str] = []
    page = 1
    while True:
      response = session.get(
        f"https://api.github.com/repos/{self.config.github_repo}/pulls/{pr_number}/files",
        params={"per_page": 100, "page": page},
        timeout=30,
      )
      response.raise_for_status()
      payload = response.json()
      if not isinstance(payload, list) or not payload:
        break
      for item in payload:
        if isinstance(item, dict) and item.get("filename"):
          files.append(str(item["filename"]))
      if len(payload) < 100:
        break
      page += 1
    return files

  def _actions_api_path(self, suffix: str) -> str:
    return (
      f"https://api.github.com/repos/{self.config.actions_repo}/{suffix.lstrip('/')}"
    )

  def _match_remote_run(self, run: dict, job: Job) -> bool:
    if not isinstance(run, dict):
      return False
    haystack = " ".join(
      str(run.get(key, "")) for key in ["display_title", "name", "path"]
    ).lower()
    # Use exact service_job_id matching to avoid binding multiple jobs
    # to the same workflow run when many runs exist.
    return job.id.lower() in haystack

  def _parse_github_datetime(self, value: str) -> Optional[datetime]:
    if not value:
      return None
    try:
      return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
      return None

  def _github_timestamp_iso(self, run: dict, *keys: str) -> Optional[str]:
    for key in keys:
      parsed = self._parse_github_datetime(str(run.get(key) or ""))
      if parsed:
        return parsed.astimezone(timezone.utc).isoformat()
    return None

  def _is_remote_run_taken(self, run_id: Optional[int], exclude_job_id: str) -> bool:
    if run_id is None:
      return False
    for j in self.jobs.values():
      if j.id == exclude_job_id:
        continue
      if j.remote_run_id == run_id:
        return True
    return False

  def _find_remote_run(self, session: requests.Session, job: Job) -> Optional[dict]:
    workflow_path = self._actions_api_path(
      f"actions/workflows/{self.config.actions_workflow}/runs"
    )
    collected_runs: List[dict] = []

    for page in range(1, 6):
      response = session.get(
        workflow_path,
        params={
          "event": "workflow_dispatch",
          "per_page": 100,
          "page": page,
        },
        timeout=30,
      )
      response.raise_for_status()
      payload = response.json()
      runs = payload.get("workflow_runs", []) if isinstance(payload, dict) else []
      if not isinstance(runs, list) or not runs:
        break

      for run in runs:
        run_id = run.get("id") if isinstance(run, dict) else None
        parsed_run_id = int(run_id) if isinstance(run_id, int) else None
        if self._match_remote_run(run, job) and not self._is_remote_run_taken(
          parsed_run_id, job.id
        ):
          return run
        if isinstance(run, dict):
          collected_runs.append(run)

      if len(runs) < 100:
        break

    started_at = self._parse_github_datetime(str(job.started_at or ""))
    if not started_at:
      return None

    candidates: List[tuple[float, dict]] = []
    for run in collected_runs:
      run_id = run.get("id")
      parsed_run_id = int(run_id) if isinstance(run_id, int) else None
      if self._is_remote_run_taken(parsed_run_id, job.id):
        continue
      created_at = self._parse_github_datetime(str(run.get("created_at") or ""))
      if not created_at:
        continue
      # Fallback only within a narrow time window around dispatch.
      if created_at < started_at - timedelta(minutes=3):
        continue
      delta_sec = abs((created_at - started_at).total_seconds())
      candidates.append((delta_sec, run))

    if len(candidates) == 1:
      return candidates[0][1]
    return None

  def _wait_for_remote_run(
    self, session: requests.Session, job: Job, timeout_sec: int = 90
  ) -> Optional[dict]:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
      run = self._find_remote_run(session, job)
      if run:
        return run
      time.sleep(3)
    return None

  def _apply_remote_run_state(self, job: Job, run: dict) -> None:
    run_id = run.get("id")
    previous_state = (
      job.remote_run_id,
      job.remote_run_status,
      job.remote_run_conclusion,
      job.status,
      job.phase,
    )
    job.remote_run_id = int(run_id) if run_id is not None else None
    job.remote_run_url = str(run.get("html_url") or "") or None
    job.remote_run_status = str(run.get("status") or "") or None
    job.remote_run_conclusion = str(run.get("conclusion") or "") or None

    if job.remote_run_status == "completed":
      completed_at = self._github_timestamp_iso(run, "completed_at", "updated_at")
      if job.remote_run_conclusion == "success":
        job.status = "succeeded"
        job.phase = "done"
      else:
        job.status = "failed"
        job.phase = job.remote_run_conclusion or "failed"
        if not job.error and job.remote_run_conclusion:
          job.error = f"GitHub Actions concluded with {job.remote_run_conclusion}"
      if completed_at:
        job.finished_at = completed_at
        job.updated_at = completed_at
      elif not job.finished_at:
        job.finished_at = utc_now_iso()
        job.updated_at = job.finished_at
    elif job.remote_run_status:
      if job.remote_run_status in {"queued", "requested", "waiting", "pending"}:
        job.status = "queued"
      else:
        job.status = "running"
      job.phase = job.remote_run_status
      current_state = (
        job.remote_run_id,
        job.remote_run_status,
        job.remote_run_conclusion,
        job.status,
        job.phase,
      )
      if current_state != previous_state:
        job.updated_at = (
          self._github_timestamp_iso(run, "updated_at", "created_at") or utc_now_iso()
        )

  def _download_remote_artifacts(
    self, session: requests.Session, job: Job, run_id: int
  ) -> bool:
    """Download uploaded GitHub Actions artifacts and map local file paths."""
    response = session.get(
      self._actions_api_path(f"actions/runs/{run_id}/artifacts"),
      timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    artifacts = payload.get("artifacts", []) if isinstance(payload, dict) else []
    if not isinstance(artifacts, list) or not artifacts:
      return False

    run_dir = self.config.runs_dir / str(job.pr_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    extracted = False

    for artifact in artifacts:
      if not isinstance(artifact, dict):
        continue
      if artifact.get("expired"):
        continue
      archive_url = artifact.get("archive_download_url")
      if not archive_url:
        continue

      artifact_name = str(artifact.get("name") or f"run-{run_id}")
      zip_path = run_dir / f"{artifact_name}.zip"
      extract_dir = run_dir / artifact_name
      extract_dir.mkdir(parents=True, exist_ok=True)

      download_resp = session.get(str(archive_url), timeout=120, stream=True)
      download_resp.raise_for_status()
      with open(zip_path, "wb") as f:
        for chunk in download_resp.iter_content(chunk_size=8192):
          if chunk:
            f.write(chunk)

      with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)
      zip_path.unlink(missing_ok=True)
      extracted = True

    if not extracted:
      return False

    def pick_file(filename: str) -> Optional[str]:
      candidates = sorted(run_dir.rglob(filename), key=lambda p: p.stat().st_mtime)
      if not candidates:
        return None
      return str(candidates[-1])

    job.stats_path = pick_file("run.stats.json")
    job.history_path = pick_file("run.history.json")
    job.review_path = pick_file("run.review.md")
    job.db_path = pick_file("run.db.json")
    return bool(job.stats_path or job.history_path or job.review_path or job.db_path)

  def _needs_remote_artifact_sync(self, job: Job) -> bool:
    return (
      job.executor == "github-actions"
      and job.remote_run_status == "completed"
      and not job.ingested
    )

  def _store(self):
    """Return the local (front-end) SQLite store: the authoritative source."""
    project_root = self.config.repo_root.parent
    if str(project_root) not in sys.path:
      sys.path.insert(0, str(project_root))
    from dataset import get_store

    return get_store()

  def _ingest_db_snapshot(self, job: Job) -> bool:
    """Replay a remote runner's ``run.db.json`` into the local store.

    The snapshot is machine-independent (it carries PR/version/review/bug data,
    not this-machine row ids), so we re-create the rows locally via the store's
    normal write path. Idempotent: guarded by ``job.ingested`` so repeated polls
    do not duplicate reviews.
    """
    if job.ingested:
      return False
    if not job.db_path or not Path(job.db_path).exists():
      return False

    try:
      with open(job.db_path, encoding="utf-8") as f:
        snapshot = json.load(f)
    except Exception as e:
      print(f"DB snapshot parse error for {job.id}: {e}", file=sys.stderr)
      return False

    pr_info = snapshot.get("pr_info") or {}
    review = snapshot.get("review")
    bugs = snapshot.get("bugs") or []
    fixed_prev_commit = snapshot.get("fixed_prev_commit")
    if not pr_info or not pr_info.get("pr_id"):
      # Nothing structured to ingest (e.g. the run crashed before export).
      # Mark ingested so we stop retrying this completed run.
      job.ingested = True
      return True

    store = self._store()
    # Re-create (or reuse) the PR + commit version in the local store.
    version_id, _ = store.upsert_pr_version(pr_info)
    fix_commit = str(pr_info.get("fix_commit", "") or "")
    # Align the job's recorded head with the commit the runner actually ran, so
    # commit-level dedup keys off the real reviewed commit (guards against a
    # stale scan value if the PR advanced between scan and execution).
    if fix_commit and job.head_sha != fix_commit:
      job.head_sha = fix_commit
    review_id = store.create_review(int(pr_info["pr_id"]), version_id, fix_commit)

    # A commit is reviewed exactly once. ``create_review`` is now idempotent per
    # ``(pr_id, version_id)``: if a review row for this commit already exists
    # (e.g. from an earlier successful ingest of the same run, or from a prior
    # job on the same commit) we get its id back and MUST NOT overwrite it --
    # otherwise a re-ingest would double-write bugs and clobber a good result
    # with a later re-run's failure. We only fill in fields when the review is
    # still fresh (never finished). ``job.ingested`` will get set below so the
    # remote poller stops touching this run either way.
    existing = store.get_review(review_id)
    already_finished = existing is not None and existing["finished_at"] is not None

    if already_finished:
      job.ingested = True
      return True

    status = str((review or {}).get("status") or "succeeded")
    if status == "skipped":
      store.skip_review(review_id, (review or {}).get("skipped_reason") or "")
    elif review is not None:
      stats_payload = dict(review)
      # ``strategies`` / ``history`` are stored as JSON text in the source DB;
      # the write path re-serializes them, so hand back parsed objects.
      stats_payload["strategies"] = self._loads_json(review.get("strategies"), [])
      stats_payload["history"] = self._loads_json(review.get("history"), None)
      store.finish_review(review_id, stats_payload)

    for bug in bugs:
      bug_id = store.add_bug(
        int(pr_info["pr_id"]),
        version_id,
        review_id,
        {
          "repro_kind": bug.get("repro_kind", "verify"),
          "original_ir": bug.get("original_ir"),
          "transformed_ir": bug.get("transformed_ir"),
          "args": bug.get("args"),
          "call_instr": bug.get("call_instr"),
          "log": bug.get("log"),
          "thoughts": bug.get("thoughts"),
        },
      )
      if bug.get("baseline_checked") and bug.get("baseline_triggered") is not None:
        store.set_bug_baseline(bug_id, bool(bug.get("baseline_triggered")))

    # If the remote run's regression gate passed, this version fixed the
    # previous version's active bugs. Replay that on the local store so the
    # front-end can show the older bugs as "fixed in a later version". We locate
    # the previous version by its commit sha (machine-independent) rather than a
    # row id. Best-effort: if the front-end has not ingested that earlier version
    # yet, we simply skip -- no earlier bugs to update here.
    if fixed_prev_commit:
      prev_ver = store.get_version_by_commit(
        int(pr_info["pr_id"]), str(fixed_prev_commit)
      )
      if prev_ver is not None:
        for prev_bug in store.list_active_bugs(int(prev_ver["id"])):
          store.mark_bug_fixed(int(prev_bug["id"]), version_id)

    job.ingested = True
    return True

  @staticmethod
  def _loads_json(value, fallback):
    if value is None:
      return fallback
    if not isinstance(value, str):
      return value
    try:
      return json.loads(value)
    except Exception:
      return fallback

  def _collect_and_ingest_remote(self, session: requests.Session, job: Job) -> bool:
    """After a remote run completes: download artifacts + ingest the snapshot.

    Returns True if any local state changed (so the caller can persist). This is
    idempotent and self-terminating: once the snapshot is ingested -- or we have
    confirmed a completed run produced no snapshot (e.g. it crashed before the
    export step) -- the job is marked ``ingested`` and drops out of the poll set.
    """
    if job.ingested or job.remote_run_status != "completed" or not job.remote_run_id:
      return False

    changed = False
    download_ok = True
    if not (job.stats_path and job.history_path and job.review_path and job.db_path):
      try:
        if self._download_remote_artifacts(session, job, job.remote_run_id):
          changed = True
      except Exception as e:
        download_ok = False
        print(f"Artifact download error for {job.id}: {e}", file=sys.stderr)

    try:
      if self._ingest_db_snapshot(job):
        changed = True
    except Exception as e:
      print(f"DB snapshot ingest error for {job.id}: {e}", file=sys.stderr)

    # Download succeeded but the completed run has no structured snapshot to
    # ingest -- i.e. ``main.py`` on the remote runner exited before writing
    # ``run.db.json`` (extract failed, build failed, --fix-commit mismatch,
    # anything else that hits ``panic()`` before the review body runs). In
    # that case we still want a permanent record so the scanner never
    # re-enqueues this (pr, sha) again: write a ``failed`` review marker into
    # the local store keyed by the sha the dispatcher was trying to review.
    if download_ok and not job.ingested and not job.db_path:
      if job.head_sha:
        try:
          conclusion = job.remote_run_conclusion or "no snapshot"
          error_label = "RemoteRunNoSnapshot"
          errmsg = (
            f"Remote workflow run {job.remote_run_id} finished with "
            f"conclusion={conclusion} but produced no run.db.json. The archer "
            f"process on the runner likely aborted before the review body ran "
            f"(e.g. PR extract or build failure). Recorded as a failed marker "
            f"so this commit is not retried."
          )
          self._store().record_dispatch_failure(
            pr_id=int(job.pr_id),
            fix_commit=str(job.head_sha),
            error=error_label,
            errmsg=errmsg,
            title=str(job.title or ""),
            author=str(job.author or ""),
            components=list(job.components or []),
          )
        except Exception as e:
          print(f"failed to record dispatch marker for {job.id}: {e}", file=sys.stderr)
      job.ingested = True
      changed = True
    return changed

  def _has_inflight_remote_job(self, exclude_job_id: Optional[str] = None) -> bool:
    for j in self.jobs.values():
      if j.executor != "github-actions":
        continue
      if exclude_job_id and j.id == exclude_job_id:
        continue
      if j.status == "running":
        return True
      if (
        j.status == "queued"
        and j.phase in {"dispatching", "dispatched"}
        and j.started_at
        and not j.finished_at
      ):
        return True
    return False

  def _dispatch_job_via_github_actions(self, job: Job) -> None:
    if not self.config.github_token:
      job.status = "failed"
      job.phase = "failed"
      job.error = "Missing GitHub token for Actions dispatch"
      job.updated_at = utc_now_iso()
      self._save_state()
      return

    job.status = "running"
    job.phase = "dispatching"
    job.started_at = utc_now_iso()
    job.updated_at = utc_now_iso()
    self._save_state()

    session = self._github_session()
    try:
      response = session.post(
        self._actions_api_path(
          f"actions/workflows/{self.config.actions_workflow}/dispatches"
        ),
        json={
          "ref": self.config.actions_ref,
          "inputs": {
            "service_job_id": job.id,
            "pr_id": str(job.pr_id),
            # Pin the exact head sha the scanner enqueued. Without this input
            # the runner falls back to "whatever version is currently latest in
            # the DB", which can be weeks stale for a PR that has pushed new
            # commits since the last successful ingest (see main.py's
            # ``--fix-commit`` handling).
            "head_sha": str(job.head_sha or ""),
            "model": self.config.model,
            "driver": self.config.driver,
            "archer_ref": self.config.actions_ref,
          },
        },
        timeout=30,
      )
      response.raise_for_status()
      run = self._wait_for_remote_run(session, job)
      if run:
        self._apply_remote_run_state(job, run)
        if job.remote_run_id and job.remote_run_status == "completed":
          self._collect_and_ingest_remote(session, job)
      else:
        # Dispatch request already succeeded, but run is not visible yet.
        # Keep this as running so dashboard reflects in-flight remote work.
        job.status = "running"
        job.phase = "dispatched"
        job.updated_at = utc_now_iso()
      self._save_state()
    except Exception as e:
      job.status = "failed"
      job.phase = "failed"
      job.error = str(e)
      job.finished_at = utc_now_iso()
      job.updated_at = utc_now_iso()
      # Persist a DB marker so the scanner does not re-enqueue this same sha
      # on its next tick just because the local job record is about to be
      # GC'd from state.json (terminal jobs are evicted on _save_state).
      if job.head_sha:
        try:
          self._store().record_dispatch_failure(
            pr_id=int(job.pr_id),
            fix_commit=str(job.head_sha),
            error="DispatchFailed",
            errmsg=f"workflow_dispatch request failed: {e}",
            title=str(job.title or ""),
            author=str(job.author or ""),
            components=list(job.components or []),
          )
        except Exception as marker_err:
          print(
            f"failed to record dispatch marker for {job.id}: {marker_err}",
            file=sys.stderr,
          )
      self._save_state()
    finally:
      session.close()

  def _sync_remote_job(self, session: requests.Session, job: Job) -> None:
    if job.remote_run_id is None:
      run = self._find_remote_run(session, job)
      if run:
        self._apply_remote_run_state(job, run)
        self._save_state()
      return

    response = session.get(
      self._actions_api_path(f"actions/runs/{job.remote_run_id}"),
      timeout=30,
    )
    response.raise_for_status()
    run = response.json()
    if isinstance(run, dict):
      before = (
        job.status,
        job.phase,
        job.error,
        job.remote_run_status,
        job.remote_run_conclusion,
      )
      self._apply_remote_run_state(job, run)
      changed = self._collect_and_ingest_remote(session, job)
      after = (
        job.status,
        job.phase,
        job.error,
        job.remote_run_status,
        job.remote_run_conclusion,
      )
      if before != after or changed:
        self._save_state()

  def _enqueue_new_reviews(self) -> dict:
    if not self.config.github_token:
      return {"ok": False, "reason": "No GitHub token"}

    session = self._github_session()
    created = 0
    skipped_existing = 0
    skipped_filtered = 0
    errors = 0
    prs: List[dict] = []

    try:
      prs = self._fetch_open_pr_candidates()
      for pr in prs:
        pr_number = int(pr.get("number", 0))
        if pr_number <= 0:
          continue
        head = pr.get("head") if isinstance(pr, dict) else None
        head_sha = str(head.get("sha", "") or "") if isinstance(head, dict) else ""
        # Dedup on the exact commit, not the PR: a new commit pushed onto an
        # already-seen PR is a new version and must be reviewed again.
        with self.lock:
          already_local = (
            self._find_active_job_for_commit(pr_number, head_sha) is not None
            if head_sha
            else pr_number in self.jobs_by_pr
          )
        if already_local:
          skipped_existing += 1
          continue
        # Authoritative, restart-proof: this commit already has a version row
        # in the store (reviewed or gate-skipped), so nothing to do.
        if head_sha and self._commit_already_reviewed(pr_number, head_sha):
          skipped_existing += 1
          continue
        try:
          files = self._fetch_pull_files(session, pr_number)
        except Exception:
          errors += 1
          continue
        if not self._is_review_candidate(pr, files):
          skipped_filtered += 1
          continue
        try:
          job = self.enqueue_pr(pr_number, source="auto", head_sha=head_sha or None)
        except queue.Full:
          errors += 1
          break
        job.title = str(pr.get("title", ""))
        user = pr.get("user")
        job.author = str(user.get("login", "")) if isinstance(user, dict) else ""
        job.components = self._resolve_components(
          pr_number, files=files, session=session
        )
        job.updated_at = utc_now_iso()
        self._save_state()
        created += 1
    except Exception as e:
      return {"ok": False, "reason": str(e)}
    finally:
      session.close()

    self._last_scan_at = utc_now_iso()
    return {
      "ok": True,
      "scanned": len(prs),
      "created": created,
      "skipped_existing": skipped_existing,
      "skipped_filtered": skipped_filtered,
      "errors": errors,
      "last_scan_at": self._last_scan_at,
    }

  def _run_job_local(self, job: Job) -> None:
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
      "--model",
      self.config.model,
      "--stats",
      str(stats_path),
      "--history",
      str(history_path),
      "--review",
      str(review_path),
    ]
    # Pin the exact head sha this job was enqueued for; without it main.py
    # falls back to "latest DB version", which may be days/weeks stale.
    if job.head_sha:
      cmd.extend(["--fix-commit", job.head_sha])

    env = {
      **subprocess.os.environ,
      "ARCHER_MODEL": self.config.model,
      "ARCHER_DRIVER": self.config.driver,
    }

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

    reach_token_limit = False
    if stats_path.exists():
      try:
        with open(stats_path) as f:
          stats = json.load(f)
        if stats.get("error") == "ReachTokenLimit":
          reach_token_limit = True
      except Exception:
        pass

    if reach_token_limit:
      job.status = "tokenlimit"
      job.phase = "stopped"
      if review_path.exists():
        try:
          with open(review_path, "r+") as f:
            content = f.read()
            if "Due to reaching token limit." not in content:
              if content.strip().endswith("\n"):
                content += "Due to reaching token limit.\n"
              else:
                content += "\nDue to reaching token limit.\n"
              f.seek(0)
              f.write(content)
              f.truncate()
        except Exception:
          pass
    elif returncode == 0:
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

  def _run_job(self, job: Job) -> None:
    if job.executor == "github-actions":
      while not self.stop_flag and self._has_inflight_remote_job(exclude_job_id=job.id):
        if job.status != "queued" or job.phase != "waiting-slot":
          job.status = "queued"
          job.phase = "waiting-slot"
          job.updated_at = utc_now_iso()
          self._save_state()
        time.sleep(2)
      if self.stop_flag:
        return
      self._dispatch_job_via_github_actions(job)
      return
    self._run_job_local(job)

  def _worker(self) -> None:
    while not self.stop_flag:
      try:
        job_id = self.queue.get(timeout=1)
        job = self.jobs.get(job_id)
        # A job may have been superseded (a newer commit arrived while it was
        # waiting) between being pushed onto the FIFO queue and being pulled
        # off. We cannot remove entries from the middle of ``queue.Queue``, so
        # the worker double-checks the current status here and silently drops
        # anything that is no longer ``queued``.
        if job is None or job.status != "queued":
          continue
        self._run_job(job)
      except queue.Empty:
        continue
      except Exception as e:
        print(f"Worker error: {e}", file=sys.stderr)

  def _scanner(self) -> None:
    while not self.stop_flag:
      if self.config.auto_scan:
        try:
          result = self._enqueue_new_reviews()
          if not result.get("ok"):
            print(
              f"Auto scan failed: {result.get('reason', 'failed')}", file=sys.stderr
            )
        except Exception as e:
          print(f"Auto scan error: {e}", file=sys.stderr)
      for _ in range(max(self.config.scan_interval_sec, 1)):
        if self.stop_flag:
          return
        time.sleep(1)

  def _remote_status_poller(self) -> None:
    while not self.stop_flag:
      if self.config.executor != "github-actions":
        time.sleep(1)
        continue

      jobs = [
        job
        for job in self.jobs.values()
        if job.executor == "github-actions"
        and (
          job.status in {"queued", "running"} or self._needs_remote_artifact_sync(job)
        )
      ]
      if not jobs:
        time.sleep(max(self.config.actions_poll_interval_sec, 1))
        continue

      session = self._github_session()
      try:
        for job in jobs:
          self._sync_remote_job(session, job)
      except Exception as e:
        print(f"Remote poll error: {e}", file=sys.stderr)
      finally:
        session.close()

      for _ in range(max(self.config.actions_poll_interval_sec, 1)):
        if self.stop_flag:
          return
        time.sleep(1)

  def start(self) -> None:
    if self.worker_thread is None or not self.worker_thread.is_alive():
      self.worker_thread = threading.Thread(target=self._worker, daemon=True)
      self.worker_thread.start()
    if self.config.auto_scan and (
      self.scanner_thread is None or not self.scanner_thread.is_alive()
    ):
      self.scanner_thread = threading.Thread(target=self._scanner, daemon=True)
      self.scanner_thread.start()
    if self.config.executor == "github-actions" and (
      self.remote_thread is None or not self.remote_thread.is_alive()
    ):
      self.remote_thread = threading.Thread(
        target=self._remote_status_poller, daemon=True
      )
      self.remote_thread.start()

  def stop(self) -> None:
    self.stop_flag = True

  def scan_open_prs(self) -> dict:
    return self._enqueue_new_reviews()
