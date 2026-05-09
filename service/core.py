import json
import queue
import subprocess
import sys
import threading
import time
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
    self._last_scan_at: Optional[str] = None
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
        if not j.components:
          pr_info = self._get_pr_info(j.pr_id)
          if isinstance(pr_info, dict):
            j.components = pr_info.get("components", []) or []
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

  def start(self) -> None:
    if self.worker_thread is None or not self.worker_thread.is_alive():
      self.worker_thread = threading.Thread(target=self._worker, daemon=True)
      self.worker_thread.start()
    if self.config.auto_scan and (
      self.scanner_thread is None or not self.scanner_thread.is_alive()
    ):
      self.scanner_thread = threading.Thread(target=self._scanner, daemon=True)
      self.scanner_thread.start()

  def stop(self) -> None:
    self.stop_flag = True

  def scan_open_prs(self) -> dict:
    return self._enqueue_new_reviews()
