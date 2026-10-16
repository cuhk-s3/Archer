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
import hashlib
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .schema import DDL, SCHEMA_VERSION

# This package directory (``<project_root>/dataset``); the DB lives here.
PACKAGE_DIR = Path(__file__).resolve().parent
KNOWLEDGE_FILE = PACKAGE_DIR / "knowledge" / "insights.jsonl"


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
    decoded = json.loads(value)
    return fallback if decoded is None else decoded
  except (TypeError, ValueError):
    return fallback


def _text(value: Any) -> Optional[str]:
  """Return SQLite-safe text while preserving structured tool diagnostics."""
  if value is None or isinstance(value, str):
    return value
  return json.dumps(value, ensure_ascii=False)


class ArcherStore:
  """Thread-safe SQLite wrapper around the Archer schema."""

  def __init__(self, db_path: Optional[os.PathLike] = None):
    self.db_path = Path(db_path) if db_path else default_db_path()
    self.db_path.parent.mkdir(parents=True, exist_ok=True)
    self._lock = threading.RLock()
    self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
    self._conn.row_factory = sqlite3.Row
    self._conn.execute("PRAGMA foreign_keys = ON;")
    self._init_schema()
    self._import_verified_knowledge()

  def _init_schema(self) -> None:
    with self._lock:
      self._conn.executescript(DDL)
      self._migrate_schema()
      self._conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
      )
      self._conn.commit()

  def _migrate_schema(self) -> None:
    """Add columns introduced after the initial SQLite schema."""
    bug_columns = {
      row["name"] for row in self._conn.execute("PRAGMA table_info(bugs)").fetchall()
    }
    migrations = {
      "github_issue_number": "INTEGER",
      "github_issue_url": "TEXT",
      "github_comment_id": "INTEGER",
      "published_at": "TEXT",
    }
    for column, column_type in migrations.items():
      if column not in bug_columns:
        self._conn.execute(f"ALTER TABLE bugs ADD COLUMN {column} {column_type}")

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

  def replace_pr_version(self, pr: Dict[str, Any]) -> int:
    """Overwrite the stored payload for an existing ``(pr_id, fix_commit)``.

    This is used by extraction ``--force`` to repair stale/incomplete version
    rows while preserving the version id and review/bug foreign keys.
    """
    self.upsert_pr(pr)
    pr_id = int(pr["pr_id"])
    fix_commit = str(pr.get("fix_commit", "") or "")
    now = _now()
    with self._lock:
      row = self._version_by_commit_locked(pr_id, fix_commit)
      if row is None:
        version_id, _ = self.upsert_pr_version(pr)
        return version_id

      version_id = int(row["id"])
      self._conn.execute(
        """UPDATE pr_versions SET base_commit=?, patch=?, tests=?,
           patch_location_lineno=?, patch_location_funcname=?, comments=?, state=?
           WHERE id=?""",
        (
          pr.get("base_commit", ""),
          pr.get("patch", ""),
          _dumps(pr.get("tests", [])),
          json.dumps(pr.get("patch_location_lineno", {}) or {}, ensure_ascii=False),
          json.dumps(pr.get("patch_location_funcname", {}) or {}, ensure_ascii=False),
          _dumps(pr.get("comments", [])),
          pr.get("state", ""),
          version_id,
        ),
      )
      self._conn.execute(
        "UPDATE prs SET latest_version_id=?, updated_at=? WHERE pr_id=?",
        (version_id, now, pr_id),
      )
      self._conn.commit()
      return version_id

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
      row = self._version_by_commit_locked(pr_id, fix_commit)
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
      return self._version_by_commit_locked(pr_id, fix_commit)

  def _version_by_commit_locked(
    self, pr_id: int, fix_commit: str
  ) -> Optional[sqlite3.Row]:
    fix_commit = str(fix_commit or "")
    if not fix_commit:
      return None
    row = self._conn.execute(
      "SELECT * FROM pr_versions WHERE pr_id=? AND fix_commit=?",
      (int(pr_id), fix_commit),
    ).fetchone()
    if row is not None or len(fix_commit) < 10:
      return row
    return self._conn.execute(
      """SELECT * FROM pr_versions
         WHERE pr_id=?
           AND length(fix_commit) >= 10
           AND (? LIKE fix_commit || '%' OR fix_commit LIKE ? || '%')
         ORDER BY length(fix_commit) DESC
         LIMIT 1""",
      (int(pr_id), fix_commit, fix_commit),
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
    """Return the review row id for a ``(pr_id, version_id)`` pair, idempotently.

    The schema enforces at most one review per commit version (a commit is
    reviewed exactly once). If a row already exists we return that row's id
    instead of inserting a duplicate; callers can then decide whether to
    overwrite the run (``finish_review``) or leave the previous result intact.
    Returning the existing id -- rather than raising -- keeps the write paths
    (local CLI run, remote-runner ingest, scanner replay) uniformly safe to
    invoke on a commit that has already been handled.
    """
    now = _now()
    with self._lock:
      row = self._conn.execute(
        "SELECT id FROM reviews WHERE pr_id=? AND version_id=?",
        (int(pr_id), int(version_id)),
      ).fetchone()
      if row is not None:
        return int(row["id"])
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

  def reset_review(self, review_id: int) -> None:
    """Reset an unpublished review before an explicit ``--force`` rerun."""
    with self._lock:
      published = self._conn.execute(
        """SELECT COUNT(*) FROM bugs WHERE review_id=? AND
           (github_issue_number IS NOT NULL OR github_comment_id IS NOT NULL OR
            published_at IS NOT NULL)""",
        (int(review_id),),
      ).fetchone()[0]
      if published:
        raise RuntimeError(
          f"review {review_id} has published findings and cannot be reset"
        )
      self._conn.execute("DELETE FROM bugs WHERE review_id=?", (int(review_id),))
      self._conn.execute(
        """UPDATE reviews SET status='running', skipped_reason=NULL,
           strategies='[]', reason_thou=NULL, report=NULL, chat_rounds=0,
           phase1_round=0, phase2_round=0, input_tokens=0, output_tokens=0,
           cached_tokens=0, total_tokens=0, chat_cost=0.0, total_time_sec=0.0,
           error=NULL, errmsg=NULL, traceback=NULL, history=NULL,
           finished_at=NULL WHERE id=?""",
        (int(review_id),),
      )
      self._conn.commit()

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

  def record_dispatch_failure(
    self,
    pr_id: int,
    fix_commit: str,
    error: str,
    errmsg: str = "",
    title: str = "",
    author: str = "",
    components: Optional[List[str]] = None,
  ) -> Tuple[int, int]:
    """Record a failed dispatch as a permanent marker in the DB.

    Used when a remote run finished but never produced a usable snapshot (for
    example ``main.py`` panicked in extract/build before ever writing a review
    row of its own), or when the local dispatch request itself failed. Writes:

    1. a ``pr_versions`` row for ``(pr_id, fix_commit)`` (mostly-empty payload;
       we only need the row to exist so ``get_version_by_commit`` finds it),
    2. a ``reviews`` row with ``status='failed'``, carrying ``error`` /
       ``errmsg`` for later diagnosis.

    Returns ``(version_id, review_id)``.

    Once this marker is in place, ``ArcherService._commit_already_reviewed``
    will return True on the next scan and the scanner will refuse to re-enqueue
    the same ``(pr, sha)`` -- enforcing "failed dispatches stay failed" without
    re-triggering GitHub Actions every scan interval.
    """
    pr_stub: Dict[str, Any] = {
      "pr_id": int(pr_id),
      "pr_url": f"https://github.com/opencompl/veir/pull/{int(pr_id)}",
      "title": title or "",
      "author": author or "",
      "components": list(components or []),
      "labels": [],
      "description": "",
      "knowledge_cutoff": "",
      "state": "open",
      "base_commit": "",
      "fix_commit": str(fix_commit),
      "patch": "",
      "tests": [],
      "comments": [],
      "patch_location_lineno": {},
      "patch_location_funcname": {},
    }
    version_id, _created = self.upsert_pr_version(pr_stub)
    review_id = self.create_review(int(pr_id), version_id, str(fix_commit))
    now = _now()
    with self._lock:
      self._conn.execute(
        """UPDATE reviews SET status='failed', error=?, errmsg=?, finished_at=?
           WHERE id=?""",
        (str(error), str(errmsg or ""), now, int(review_id)),
      )
      self._conn.commit()
    return version_id, review_id

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
          _text(bug.get("call_instr")),
          _text(bug.get("log")),
          bug.get("thoughts"),
          now,
        ),
      )
      self._conn.commit()
      return int(cur.lastrowid)

  def get_bug(self, bug_id: int) -> Optional[sqlite3.Row]:
    with self._lock:
      return self._conn.execute(
        "SELECT * FROM bugs WHERE id=?", (int(bug_id),)
      ).fetchone()

  def list_bugs_pending_publication(self) -> List[sqlite3.Row]:
    """Patch-specific active bugs whose issue or analysis comment is missing."""
    with self._lock:
      return list(
        self._conn.execute(
          """SELECT b.* FROM bugs b
             JOIN reviews r ON r.id=b.review_id
             WHERE b.status='active'
               AND b.baseline_checked=1
               AND b.baseline_triggered=0
               AND b.non_patch_specific=0
               AND r.status IN ('succeeded', 'tokenlimit')
               AND (b.github_issue_number IS NULL OR b.github_comment_id IS NULL)
             ORDER BY b.created_at ASC, b.id ASC"""
        ).fetchall()
      )

  def list_publishable_bugs_for_pr(self, pr_id: int) -> List[sqlite3.Row]:
    """All active, patch-specific bugs for a PR, oldest first."""
    with self._lock:
      return list(
        self._conn.execute(
          """SELECT b.* FROM bugs b
             JOIN reviews r ON r.id=b.review_id
             WHERE b.pr_id=?
               AND b.status='active'
               AND b.baseline_checked=1
               AND b.baseline_triggered=0
               AND b.non_patch_specific=0
               AND r.status IN ('succeeded', 'tokenlimit')
             ORDER BY b.created_at ASC, b.id ASC""",
          (int(pr_id),),
        ).fetchall()
      )

  def set_bug_github_issue(
    self, bug_id: int, issue_number: int, issue_url: str
  ) -> None:
    with self._lock:
      self._conn.execute(
        "UPDATE bugs SET github_issue_number=?, github_issue_url=? WHERE id=?",
        (int(issue_number), str(issue_url), int(bug_id)),
      )
      self._conn.commit()

  def set_bug_github_comment(self, bug_id: int, comment_id: int) -> None:
    with self._lock:
      self._conn.execute(
        "UPDATE bugs SET github_comment_id=?, published_at=? WHERE id=?",
        (int(comment_id), _now(), int(bug_id)),
      )
      self._conn.commit()

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

  # ---------------------------------------------------------------------------
  # Durable review knowledge
  # ---------------------------------------------------------------------------
  def upsert_insight(
    self,
    *,
    components: List[str],
    topic: str,
    kind: str,
    content: str,
    verified: bool = False,
    evidence_tool: Optional[str] = None,
    evidence: Any = None,
    pr_id: Optional[int] = None,
    version_id: Optional[int] = None,
    review_id: Optional[int] = None,
    fix_commit: str = "",
  ) -> int:
    normalized_components = sorted({str(c).strip() for c in components if str(c).strip()})
    normalized = "\n".join([
      ",".join(c.casefold() for c in normalized_components),
      topic.strip().casefold(), kind.strip().casefold(), content.strip(),
    ])
    fingerprint = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    now = _now()
    with self._lock:
      self._conn.execute(
        """INSERT INTO insights(
             fingerprint, components, topic, kind, content, verified,
             evidence_tool, evidence, pr_id, version_id, review_id, fix_commit,
             created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(fingerprint) DO UPDATE SET
             verified=MAX(insights.verified, excluded.verified),
             evidence_tool=COALESCE(excluded.evidence_tool, insights.evidence_tool),
             evidence=COALESCE(excluded.evidence, insights.evidence),
             pr_id=COALESCE(excluded.pr_id, insights.pr_id),
             version_id=COALESCE(excluded.version_id, insights.version_id),
             review_id=COALESCE(excluded.review_id, insights.review_id),
             fix_commit=CASE WHEN excluded.fix_commit != '' THEN excluded.fix_commit
                             ELSE insights.fix_commit END,
             updated_at=excluded.updated_at""",
        (
          fingerprint, _dumps(normalized_components), topic.strip(), kind.strip(),
          content.strip(), 1 if verified else 0, evidence_tool,
          _text(evidence), pr_id, version_id, review_id, str(fix_commit or ""),
          now, now,
        ),
      )
      row = self._conn.execute(
        "SELECT id FROM insights WHERE fingerprint=?", (fingerprint,)
      ).fetchone()
      self._conn.commit()
      insight_id = int(row["id"])
    if verified:
      self.export_verified_knowledge()
    return insight_id

  def _import_verified_knowledge(self) -> None:
    """Seed a fresh/local DB from the repository's reviewable knowledge file."""
    if not KNOWLEDGE_FILE.is_file():
      return
    try:
      records = [json.loads(line) for line in KNOWLEDGE_FILE.read_text(
        encoding="utf-8").splitlines() if line.strip()]
    except (OSError, ValueError):
      return
    for record in records:
      self.upsert_insight(
        components=record.get("components", []),
        topic=record.get("topic", ""), kind=record.get("kind", "observation"),
        content=record.get("content", ""), verified=True,
        evidence_tool=record.get("evidence_tool"), evidence=record.get("evidence"),
        pr_id=record.get("pr_id"), fix_commit=record.get("fix_commit", ""),
      )

  def export_verified_knowledge(self) -> None:
    """Write verified knowledge as stable JSONL suitable for code review/versioning."""
    with self._lock:
      rows = self._conn.execute(
        "SELECT * FROM insights WHERE verified=1 ORDER BY fingerprint"
      ).fetchall()
    records = []
    for row in rows:
      item = dict(row)
      records.append({
        "fingerprint": item["fingerprint"],
        "components": _loads(item["components"], []),
        "topic": item["topic"], "kind": item["kind"],
        "content": item["content"], "evidence_tool": item["evidence_tool"],
        "evidence": _loads(item["evidence"], item["evidence"]),
        "pr_id": item["pr_id"], "fix_commit": item["fix_commit"],
      })
    KNOWLEDGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
      for record in records)
    tmp = KNOWLEDGE_FILE.with_suffix(".jsonl.tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(KNOWLEDGE_FILE)

  def search_insights(
    self,
    *,
    components: Optional[List[str]] = None,
    query: str = "",
    verified_only: bool = False,
    limit: int = 20,
  ) -> List[Dict[str, Any]]:
    clauses = []
    params: List[Any] = []
    if verified_only:
      clauses.append("verified=1")
    if query.strip():
      clauses.append("(topic LIKE ? OR content LIKE ?)")
      needle = f"%{query.strip()}%"
      params.extend([needle, needle])
    sql = "SELECT * FROM insights"
    if clauses:
      sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY verified DESC, updated_at DESC"
    wanted = {c.casefold() for c in (components or []) if c}
    with self._lock:
      rows = self._conn.execute(sql, params).fetchall()
    result = []
    for row in rows:
      item = dict(row)
      item["components"] = _loads(item.get("components"), [])
      if wanted and not wanted.intersection(c.casefold() for c in item["components"]):
        continue
      item["verified"] = bool(item["verified"])
      result.append(item)
      if len(result) >= max(1, min(int(limit), 100)):
        break
    return result

  def list_insights_for_review(self, review_id: int) -> List[Dict[str, Any]]:
    with self._lock:
      rows = self._conn.execute(
        "SELECT * FROM insights WHERE review_id=? ORDER BY created_at, id",
        (int(review_id),),
      ).fetchall()
    result = []
    for row in rows:
      item = dict(row)
      item["components"] = _loads(item.get("components"), [])
      item["verified"] = bool(item["verified"])
      result.append(item)
    return result

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
