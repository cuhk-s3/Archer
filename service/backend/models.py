from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field


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


class JobCreateRequest(BaseModel):
  pr_id: int = Field(gt=0)
  source: str = Field(default="manual")
  force: bool = False
