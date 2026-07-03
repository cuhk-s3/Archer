"""Data-access layer for the Archer review store (SQLite).

The store is the single source of truth for extracted PR data, per-commit
versions, review runs and the bugs they find. It replaces the previous
``dataset/{closed,open}/{pr_id}.json`` layout.

Typical usage:

    from dataset import get_store
    store = get_store()
    version_id, created = store.upsert_pr_version(pr_info_dict)
"""

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .schema import DDL, SCHEMA_VERSION

# This package directory (``<project_root>/dataset``); the DB lives here.
PACKAGE_DIR = Path(__file__).resolve().parent


def _now() -> str:
  return datetime.now(timezone.utc).isoformat()


def default_db_path() -> Path:
  """Resolve the database file location.

  Priority:
    1. ``LAB_ARCHER_DB`` env var (explicit path).
    2. ``${LAB_DATASET_DIR}/archer.db`` if the dataset dir env is set.
    3. ``<project_root>/dataset/archer.db`` (this package directory).
  """
  explicit = os.environ.get("LAB_ARCHER_DB")
  if explicit:
    return Path(explicit)
  dataset_dir = os.environ.get("LAB_DATASET_DIR")
  if dataset_dir:
    return Path(dataset_dir) / "archer.db"
  return PACKAGE_DIR / "archer.db"


def _dumps(value: Any) -> str:
  return json.dumps(value if value is not None else [], ensure_ascii=False)


def _loads(value: Any, fallback: Any) -> Any:
  if value is None:
    return fallback
  try:
    return json.loads(value)
  except Exception:
    return fallback


class ArcherStore:
  """Thread-safe SQLite wrapper around the Archer schema."""

  def __init__(self, db_path: Optional[os.PathLike] = None):
    self.db_path = Path(db_path) if db_path else default_db_path()
    self.db_path.parent.mkdir(parents=True, exist_ok=True)
    self._lock = threading.Lock()
    self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
    self._conn.row_factory = sqlite3.Row
    self._conn.execute("PRAGMA foreign_keys = ON;")
    self._init_schema()

  def _init_schema(self) -> None:
    with self._lock:
      self._conn.executescript(DDL)
      self._conn.execute(
        "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
      )
      self._conn.commit()

  def close(self) -> None:
    with self._lock:
      self._conn.close()

  # ---------------------------------------------------------------------------
  # PR + version write path
  # ---------------------------------------------------------------------------
  def upsert_pr(self, pr: Dict[str, Any]) -> int:
    """Insert/update the PR-level metadata row. Returns ``pr_id``."""
    pr_id = int(pr["pr_id"])
    now = _now()
    with self._lock:
      cur = self._conn.execute("SELECT pr_id FROM prs WHERE pr_id = ?", (pr_id,))
      exists = cur.fetchone() is not None
      if exists:
        self._conn.execute(
          """UPDATE prs SET pr_url=?, title=?, author=?, components=?, labels=?,
             description=?, knowledge_cutoff=?, state=?, updated_at=?
             WHERE pr_id=?""",
          (
            pr.get("pr_url", ""),
            pr.get("title", ""),
            pr.get("author", ""),
            _dumps(pr.get("components", [])),
            _dumps(pr.get("labels", [])),
            pr.get("description", "") or "",
            pr.get("knowledge_cutoff", ""),
            pr.get("state", ""),
            now,
            pr_id,
          ),
        )
      else:
        self._conn.execute(
          """INSERT INTO prs(pr_id, pr_url, title, author, components, labels,
             description, knowledge_cutoff, state, created_at, updated_at)
             VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
          (
            pr_id,
            pr.get("pr_url", ""),
            pr.get("title", ""),
            pr.get("author", ""),
            _dumps(pr.get("components", [])),
            _dumps(pr.get("labels", [])),
            pr.get("description", "") or "",
            pr.get("knowledge_cutoff", ""),
            pr.get("state", ""),
            now,
            now,
          ),
        )
      self._conn.commit()
    return pr_id

  def upsert_pr_version(self, pr: Dict[str, Any]) -> Tuple[int, bool]:
    """Insert a PR + a commit version keyed by ``(pr_id, fix_commit)``.

    This realizes the "只看 commit sha" dedup rule: a repeated fix_commit is a
    no-op (returns the existing version); a new fix_commit for a known PR is
    appended as a new version.

    Returns ``(version_id, created)`` where ``created`` is True for a new version.
    """
    self.upsert_pr(pr)
    pr_id = int(pr["pr_id"])
    fix_commit = str(pr.get("fix_commit", "") or "")
    now = _now()
    with self._lock:
      row = self._conn.execute(
        "SELECT id FROM pr_versions WHERE pr_id=? AND fix_commit=?",
        (pr_id, fix_commit),
      ).fetchone()
      if row is not None:
        return int(row["id"]), False

      seq_row = self._conn.execute(
        "SELECT COALESCE(MAX(seq), 0) AS m FROM pr_versions WHERE pr_id=?",
        (pr_id,),
      ).fetchone()
      seq = int(seq_row["m"]) + 1

      cur = self._conn.execute(
        """INSERT INTO pr_versions(pr_id, fix_commit, base_commit, patch, tests,
           patch_location_lineno, patch_location_funcname, comments, state, seq,
           created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
          pr_id,
          fix_commit,
          pr.get("base_commit", ""),
          pr.get("patch", ""),
          _dumps(pr.get("tests", [])),
          json.dumps(pr.get("patch_location_lineno", {}) or {}, ensure_ascii=False),
          json.dumps(pr.get("patch_location_funcname", {}) or {}, ensure_ascii=False),
          _dumps(pr.get("comments", [])),
          pr.get("state", ""),
          seq,
          now,
        ),
      )
      version_id = int(cur.lastrowid)
      self._conn.execute(
        "UPDATE prs SET latest_version_id=?, updated_at=? WHERE pr_id=?",
        (version_id, now, pr_id),
      )
      self._conn.commit()
    return version_id, True

  # ---------------------------------------------------------------------------
  # PR + version read path
  # ---------------------------------------------------------------------------
  def get_pr(self, pr_id: int) -> Optional[sqlite3.Row]:
    with self._lock:
      return self._conn.execute(
        "SELECT * FROM prs WHERE pr_id=?", (int(pr_id),)
      ).fetchone()

  def list_prs(self) -> List[sqlite3.Row]:
    """All PRs, most recently updated first."""
    with self._lock:
      return list(
        self._conn.execute(
          "SELECT * FROM prs ORDER BY updated_at DESC, pr_id DESC"
        ).fetchall()
      )

  def has_version(self, pr_id: int, fix_commit: str) -> bool:
    with self._lock:
      row = self._conn.execute(
        "SELECT 1 FROM pr_versions WHERE pr_id=? AND fix_commit=?",
        (int(pr_id), str(fix_commit)),
      ).fetchone()
    return row is not None

  def get_version(self, version_id: int) -> Optional[sqlite3.Row]:
    with self._lock:
      return self._conn.execute(
        "SELECT * FROM pr_versions WHERE id=?", (int(version_id),)
      ).fetchone()

  def get_latest_version(self, pr_id: int) -> Optional[sqlite3.Row]:
    with self._lock:
      return self._conn.execute(
        "SELECT * FROM pr_versions WHERE pr_id=? ORDER BY seq DESC LIMIT 1",
        (int(pr_id),),
      ).fetchone()

  def get_version_by_commit(self, pr_id: int, fix_commit: str) -> Optional[sqlite3.Row]:
    with self._lock:
      return self._conn.execute(
        "SELECT * FROM pr_versions WHERE pr_id=? AND fix_commit=?",
        (int(pr_id), str(fix_commit)),
      ).fetchone()

  def get_previous_version(self, version_id: int) -> Optional[sqlite3.Row]:
    """Return the immediately preceding version (by seq) of the same PR."""
    ver = self.get_version(version_id)
    if ver is None:
      return None
    with self._lock:
      return self._conn.execute(
        "SELECT * FROM pr_versions WHERE pr_id=? AND seq < ? ORDER BY seq DESC LIMIT 1",
        (int(ver["pr_id"]), int(ver["seq"])),
      ).fetchone()

  def list_versions(self, pr_id: int) -> List[sqlite3.Row]:
    with self._lock:
      return list(
        self._conn.execute(
          "SELECT * FROM pr_versions WHERE pr_id=? ORDER BY seq ASC",
          (int(pr_id),),
        ).fetchall()
      )

  def to_pr_info(
    self, pr_id: int, version_id: Optional[int] = None
  ) -> Optional[Dict[str, Any]]:
    """Assemble a ``PRInfo``-compatible dict from PR + version rows."""
    pr = self.get_pr(pr_id)
    if pr is None:
      return None
    ver = (
      self.get_version(version_id)
      if version_id is not None
      else self.get_latest_version(pr_id)
    )
    if ver is None:
      return None
    return {
      "pr_id": int(pr["pr_id"]),
      "pr_url": pr["pr_url"],
      "title": pr["title"],
      "author": pr["author"],
      "components": _loads(pr["components"], []),
      "labels": _loads(pr["labels"], []),
      "description": pr["description"],
      "knowledge_cutoff": pr["knowledge_cutoff"],
      "state": ver["state"] or pr["state"],
      "base_commit": ver["base_commit"],
      "fix_commit": ver["fix_commit"],
      "patch": ver["patch"],
      "tests": _loads(ver["tests"], []),
      "comments": _loads(ver["comments"], []),
      "patch_location_lineno": _loads(ver["patch_location_lineno"], {}),
      "patch_location_funcname": _loads(ver["patch_location_funcname"], {}),
    }

  # ---------------------------------------------------------------------------
  # Reviews
  # ---------------------------------------------------------------------------
  def create_review(self, pr_id: int, version_id: int, fix_commit: str = "") -> int:
    now = _now()
    with self._lock:
      cur = self._conn.execute(
        """INSERT INTO reviews(pr_id, version_id, fix_commit, status, created_at)
           VALUES (?,?,?, 'running', ?)""",
        (int(pr_id), int(version_id), str(fix_commit), now),
      )
      self._conn.commit()
      return int(cur.lastrowid)

  def get_review(self, review_id: int) -> Optional[sqlite3.Row]:
    with self._lock:
      return self._conn.execute(
        "SELECT * FROM reviews WHERE id=?", (int(review_id),)
      ).fetchone()

  def list_reviews_for_version(self, version_id: int) -> List[sqlite3.Row]:
    """Reviews of a single version, newest first."""
    with self._lock:
      return list(
        self._conn.execute(
          "SELECT * FROM reviews WHERE version_id=? ORDER BY created_at DESC, id DESC",
          (int(version_id),),
        ).fetchall()
      )

  def list_reviews_for_pr(self, pr_id: int) -> List[sqlite3.Row]:
    """All reviews of a PR across every version, newest first."""
    with self._lock:
      return list(
        self._conn.execute(
          "SELECT * FROM reviews WHERE pr_id=? ORDER BY created_at DESC, id DESC",
          (int(pr_id),),
        ).fetchall()
      )

  def skip_review(self, review_id: int, reason: str) -> None:
    with self._lock:
      self._conn.execute(
        "UPDATE reviews SET status='skipped', skipped_reason=?, finished_at=? WHERE id=?",
        (reason, _now(), int(review_id)),
      )
      self._conn.commit()

  def finish_review(self, review_id: int, stats: Dict[str, Any]) -> None:
    """Persist final run stats onto a review row."""
    with self._lock:
      self._conn.execute(
        """UPDATE reviews SET status=?, strategies=?, reason_thou=?, report=?,
           chat_rounds=?, phase1_round=?, phase2_round=?, input_tokens=?,
           output_tokens=?, cached_tokens=?, total_tokens=?, chat_cost=?,
           total_time_sec=?, error=?, errmsg=?, traceback=?, history=?,
           finished_at=? WHERE id=?""",
        (
          stats.get("status", "succeeded"),
          _dumps(stats.get("strategies", [])),
          stats.get("reason_thou"),
          stats.get("report"),
          int(stats.get("chat_rounds", 0) or 0),
          int(stats.get("phase1_round", 0) or 0),
          int(stats.get("phase2_round", 0) or 0),
          int(stats.get("input_tokens", 0) or 0),
          int(stats.get("output_tokens", 0) or 0),
          int(stats.get("cached_tokens", 0) or 0),
          int(stats.get("total_tokens", 0) or 0),
          float(stats.get("chat_cost", 0.0) or 0.0),
          float(stats.get("total_time_sec", 0.0) or 0.0),
          stats.get("error"),
          stats.get("errmsg"),
          stats.get("traceback"),
          json.dumps(stats["history"], ensure_ascii=False)
          if stats.get("history") is not None
          else None,
          _now(),
          int(review_id),
        ),
      )
      self._conn.commit()

  # ---------------------------------------------------------------------------
  # Bugs
  # ---------------------------------------------------------------------------
  def add_bug(
    self,
    pr_id: int,
    version_id: int,
    review_id: Optional[int],
    bug: Dict[str, Any],
  ) -> int:
    now = _now()
    with self._lock:
      cur = self._conn.execute(
        """INSERT INTO bugs(pr_id, version_id, review_id, repro_kind, original_ir,
           transformed_ir, args, call_instr, log, thoughts, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
          int(pr_id),
          int(version_id),
          int(review_id) if review_id is not None else None,
          bug.get("repro_kind", "verify"),
          bug.get("original_ir"),
          bug.get("transformed_ir"),
          bug.get("args"),
          bug.get("call_instr"),
          bug.get("log"),
          bug.get("thoughts"),
          now,
        ),
      )
      self._conn.commit()
      return int(cur.lastrowid)

  def set_bug_baseline(self, bug_id: int, triggered: bool) -> None:
    with self._lock:
      self._conn.execute(
        """UPDATE bugs SET baseline_checked=1, baseline_triggered=?,
           non_patch_specific=? WHERE id=?""",
        (1 if triggered else 0, 1 if triggered else 0, int(bug_id)),
      )
      self._conn.commit()

  def mark_bug_fixed(self, bug_id: int, fixed_in_version_id: int) -> None:
    with self._lock:
      self._conn.execute(
        "UPDATE bugs SET status='fixed', fixed_in_version_id=? WHERE id=?",
        (int(fixed_in_version_id), int(bug_id)),
      )
      self._conn.commit()

  def list_active_bugs(self, version_id: int) -> List[sqlite3.Row]:
    with self._lock:
      return list(
        self._conn.execute(
          "SELECT * FROM bugs WHERE version_id=? AND status='active'",
          (int(version_id),),
        ).fetchall()
      )

  def list_bugs_for_review(self, review_id: int) -> List[sqlite3.Row]:
    with self._lock:
      return list(
        self._conn.execute(
          "SELECT * FROM bugs WHERE review_id=?", (int(review_id),)
        ).fetchall()
      )

  def list_bugs_for_version(self, version_id: int) -> List[sqlite3.Row]:
    with self._lock:
      return list(
        self._conn.execute(
          "SELECT * FROM bugs WHERE version_id=? ORDER BY created_at ASC, id ASC",
          (int(version_id),),
        ).fetchall()
      )

  def list_bugs_for_pr(self, pr_id: int) -> List[sqlite3.Row]:
    with self._lock:
      return list(
        self._conn.execute(
          "SELECT * FROM bugs WHERE pr_id=? ORDER BY created_at ASC, id ASC",
          (int(pr_id),),
        ).fetchall()
      )


# ------------------------------------------------------------------------------
# Module-level singleton helper
# ------------------------------------------------------------------------------
_store_singleton: Optional[ArcherStore] = None
_singleton_lock = threading.Lock()


def get_store(db_path: Optional[os.PathLike] = None) -> ArcherStore:
  """Return a process-wide ``ArcherStore`` singleton (created on first call)."""
  global _store_singleton
  with _singleton_lock:
    if _store_singleton is None:
      _store_singleton = ArcherStore(db_path)
    return _store_singleton
