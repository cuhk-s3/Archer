from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional


def utc_now_iso() -> str:
  return datetime.now(timezone.utc).isoformat()


@dataclass
class Job:
  id: str
  pr_id: int
  # Head commit SHA this job reviews. The dedup identity is (pr_id, head_sha),
  # matching the commit-based store (a PR pushing a new commit is a new job),
  # not merely the PR id. May be None for legacy/manual jobs that did not
  # capture a commit; those fall back to a gentler per-PR active-job guard.
  head_sha: Optional[str] = None
  executor: str = "local"
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
  # Structured DB snapshot produced by a remote runner (run.db.json), and
  # whether its contents have already been ingested into the local store.
  db_path: Optional[str] = None
  ingested: bool = False
  logs: List[str] = field(default_factory=list)
  title: str = ""
  author: str = ""
  components: List[str] = field(default_factory=list)
  remote_run_id: Optional[int] = None
  remote_run_url: Optional[str] = None
  remote_run_status: Optional[str] = None
  remote_run_conclusion: Optional[str] = None

  def append_log(self, line: str, max_logs: int = 400) -> None:
    self.logs.append(line)
    if len(self.logs) > max_logs:
      self.logs = self.logs[-max_logs:]

  # Terminal states: the job has finished all work the dispatcher owes it.
  # ``succeeded/failed/tokenlimit/skipped`` are the possible outcomes; a remote
  # job additionally needs its DB snapshot ingested before it is truly done.
  # In-flight states (``queued/running``) are always non-terminal.
  _FINAL_STATUSES = frozenset({"succeeded", "failed", "tokenlimit", "skipped"})

  def is_terminal(self) -> bool:
    """True iff the dispatcher has nothing left to do for this job.

    Terminal jobs are the ones that can safely be evicted from the on-disk
    state file: they carry no runtime state the orchestrator needs to recover
    on restart. Anything the UI needs to display long-term about a finished
    review lives in the SQLite store, not here.
    """
    if self.status not in Job._FINAL_STATUSES:
      return False
    # Remote runs still need their snapshot ingested before we drop them.
    if self.executor == "github-actions" and self.db_path and not self.ingested:
      return False
    return True
