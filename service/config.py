import os
from pathlib import Path


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
