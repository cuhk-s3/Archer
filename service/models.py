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


class JobCreateRequest(BaseModel):
  pr_id: int = Field(gt=0)
  source: str = Field(default="manual")
  force: bool = False
