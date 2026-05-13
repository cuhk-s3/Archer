import json
import queue
import subprocess
import sys
import threading
import time
import zipfile
from dataclasses import asdict
from datetime import datetime, timezone
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
  "llvm/test/Transforms/AggressiveInstCombine",
  "llvm/test/Transforms/LoopVectorize",
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
  "llvm/lib/Transforms/AggressiveInstCombine",
  "llvm/lib/Transforms/Vectorize/LoopVectorize.cpp",
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
    self.lock = threading.Lock()
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
          pr_info = self._get_pr_info(j.pr_id)
          if isinstance(pr_info, dict):
            j.components = pr_info.get("components", []) or []
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
      for job_id in queued_jobs:
        try:
          self.queue.put(job_id, block=False)
        except queue.Full:
          break
      self._save_state()

  def _save_state(self) -> None:
    state = {"jobs": [asdict(j) for j in self.jobs.values()]}
    self.config.state_file.write_text(json.dumps(state, indent=2))

  def get_job(self, job_id: str) -> Optional[Job]:
    return self.jobs.get(job_id)

  def list_jobs(self) -> List[Job]:
    return sorted(self.jobs.values(), key=lambda j: j.created_at, reverse=True)

  def _get_pr_info(self, pr_id: int) -> Optional[dict]:
    dataset_dir = self.config.repo_root / "dataset"
    for sub in ["closed", "open"]:
      path = dataset_dir / sub / f"{pr_id}.json"
      if not path.exists():
        continue
      try:
        return json.loads(path.read_text())
      except Exception:
        continue
    return None

  def enqueue_pr(self, pr_id: int, source: str = "manual", force: bool = False) -> Job:
    with self.lock:
      existing_id = self.jobs_by_pr.get(pr_id)
      if existing_id and not force:
        return self.jobs[existing_id]
      ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
      job_id = f"{source}-{pr_id}-{ts}"
      job = Job(
        id=job_id,
        pr_id=pr_id,
        executor=self.config.executor,
        status="queued",
        created_at=utc_now_iso(),
        updated_at=utc_now_iso(),
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

  def _find_remote_run(self, session: requests.Session, job: Job) -> Optional[dict]:
    workflow_path = self._actions_api_path(
      f"actions/workflows/{self.config.actions_workflow}/runs"
    )

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
        if self._match_remote_run(run, job):
          return run

      if len(runs) < 100:
        break
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
    job.remote_run_id = int(run_id) if run_id is not None else None
    job.remote_run_url = str(run.get("html_url") or "") or None
    job.remote_run_status = str(run.get("status") or "") or None
    job.remote_run_conclusion = str(run.get("conclusion") or "") or None

    if job.remote_run_status == "completed":
      if job.remote_run_conclusion == "success":
        job.status = "succeeded"
        job.phase = "done"
      else:
        job.status = "failed"
        job.phase = job.remote_run_conclusion or "failed"
        if not job.error and job.remote_run_conclusion:
          job.error = f"GitHub Actions concluded with {job.remote_run_conclusion}"
      job.finished_at = utc_now_iso()
    elif job.remote_run_status:
      if job.remote_run_status in {"queued", "requested", "waiting", "pending"}:
        job.status = "queued"
      else:
        job.status = "running"
      job.phase = job.remote_run_status
    job.updated_at = utc_now_iso()

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
    return bool(job.stats_path or job.history_path or job.review_path)

  def _needs_remote_artifact_sync(self, job: Job) -> bool:
    return (
      job.executor == "github-actions"
      and job.remote_run_status == "completed"
      and not (job.stats_path and job.history_path and job.review_path)
    )

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
          try:
            downloaded = self._download_remote_artifacts(
              session, job, job.remote_run_id
            )
            if downloaded:
              self._save_state()
          except Exception as e:
            print(f"Artifact download error for {job.id}: {e}", file=sys.stderr)
      else:
        job.status = "queued"
        job.phase = "dispatched"
        job.updated_at = utc_now_iso()
      self._save_state()
    except Exception as e:
      job.status = "failed"
      job.phase = "failed"
      job.error = str(e)
      job.finished_at = utc_now_iso()
      job.updated_at = utc_now_iso()
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
      downloaded = False
      if (
        job.remote_run_id
        and job.remote_run_status == "completed"
        and not (job.stats_path and job.history_path and job.review_path)
      ):
        try:
          downloaded = self._download_remote_artifacts(session, job, job.remote_run_id)
        except Exception as e:
          print(f"Artifact sync download error for {job.id}: {e}", file=sys.stderr)
      after = (
        job.status,
        job.phase,
        job.error,
        job.remote_run_status,
        job.remote_run_conclusion,
      )
      if before != after or downloaded:
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
        with self.lock:
          if pr_number in self.jobs_by_pr:
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
          job = self.enqueue_pr(pr_number, source="auto")
        except queue.Full:
          errors += 1
          break
        pr_info = self._get_pr_info(pr_number)
        job.title = str(pr.get("title", ""))
        user = pr.get("user")
        job.author = str(user.get("login", "")) if isinstance(user, dict) else ""
        job.components = pr_info.get("components", []) if pr_info else []
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
        if job:
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
