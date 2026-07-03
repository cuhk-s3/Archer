"""DB-backed read views for the web dashboard.

The web layer used to display per-run file artifacts (state.json + on-disk
stats/history/review). The single source of truth is now the SQLite store
(``dataset/archer.db``). This module reads that store and shapes it for the UI
along the natural hierarchy:

    PR  ->  commit version (pr_versions)  ->  review run (reviews)  ->  bugs

Live orchestration state (queued / dispatching) still lives in the in-memory
job system; those jobs are overlaid on top of the DB-derived summaries so a PR
that is currently being reviewed (but has no finished review row yet) still
shows up.
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# service/backend/db_view.py -> parents[2] == project root (Archer).
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _get_store():
  if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
  from dataset import get_store

  return get_store()


def _loads(value: Any, fallback: Any) -> Any:
  if value is None:
    return fallback
  if not isinstance(value, str):
    return value
  try:
    return json.loads(value)
  except Exception:
    return fallback


# ------------------------------------------------------------------------------
# Bug / review shaping
# ------------------------------------------------------------------------------
def patch_specificity(bug_row) -> str:
  """Classify a bug's patch-specificity from its baseline-check flags.

  Returns one of: ``patch_specific`` / ``non_patch_specific`` / ``not_checked``.
  """
  checked = bug_row["baseline_checked"]
  triggered = bug_row["baseline_triggered"]
  if not checked or triggered is None:
    return "not_checked"
  if bug_row["non_patch_specific"]:
    return "non_patch_specific"
  return "patch_specific"


def _bug_full_dict(bug_row) -> Dict[str, Any]:
  return {
    "id": int(bug_row["id"]),
    "repro_kind": bug_row["repro_kind"],
    "original_ir": bug_row["original_ir"] or "",
    "transformed_ir": bug_row["transformed_ir"] or "",
    "args": bug_row["args"],
    "call_instr": bug_row["call_instr"],
    "log": bug_row["log"] or "",
    "thoughts": bug_row["thoughts"] or "",
    "patch_specificity": patch_specificity(bug_row),
    "status": bug_row["status"],
    "fixed_in_version_id": bug_row["fixed_in_version_id"],
  }


def _bug_compact_dict(bug_row) -> Dict[str, Any]:
  return {
    "id": int(bug_row["id"]),
    "repro_kind": bug_row["repro_kind"],
    "patch_specificity": patch_specificity(bug_row),
    "status": bug_row["status"],
  }


def _review_stats_data(store, review_row) -> Dict[str, Any]:
  """Full per-review payload for inline rendering on the PR page.

  Mirrors the shape consumed by ``renderers._render_review_body`` (strategies,
  full bug records, analysis report, and run metrics) so the PR page can show
  the whole review report without a separate ``/review/<id>`` hop.
  """
  bug_rows = store.list_bugs_for_review(int(review_row["id"]))
  return {
    "strategies": _loads(review_row["strategies"], []),
    "bugs": [_bug_full_dict(b) for b in bug_rows],
    "report": review_row["report"],
    "chat_rounds": review_row["chat_rounds"],
    "chat_cost": review_row["chat_cost"],
    "total_time_sec": review_row["total_time_sec"],
    "total_tokens": review_row["total_tokens"],
  }


def _review_outcome(status: str, bug_count: int) -> str:
  """Collapse a review's raw status + bug count into a single UI outcome."""
  if status in ("running", "queued"):
    return status
  if status == "skipped":
    return "skipped"
  if status in ("succeeded", "tokenlimit"):
    return "bug" if bug_count > 0 else "clean"
  return "failed"


def _review_summary(store, review_row) -> Dict[str, Any]:
  bugs = store.list_bugs_for_review(int(review_row["id"]))
  bug_count = len(bugs)
  patch_specific = sum(1 for b in bugs if patch_specificity(b) == "patch_specific")
  status = review_row["status"]
  return {
    "review_id": int(review_row["id"]),
    "version_id": int(review_row["version_id"]),
    "status": status,
    "outcome": _review_outcome(status, bug_count),
    "skipped_reason": review_row["skipped_reason"],
    "error": review_row["error"],
    "errmsg": review_row["errmsg"],
    "created_at": review_row["created_at"],
    "finished_at": review_row["finished_at"],
    "total_time_sec": review_row["total_time_sec"],
    "total_tokens": review_row["total_tokens"],
    "chat_cost": review_row["chat_cost"],
    "chat_rounds": review_row["chat_rounds"],
    "phase1_round": review_row["phase1_round"],
    "phase2_round": review_row["phase2_round"],
    "bug_count": bug_count,
    "patch_specific_count": patch_specific,
    "bugs": [_bug_compact_dict(b) for b in bugs],
  }


# ------------------------------------------------------------------------------
# Live job overlay
# ------------------------------------------------------------------------------
def _latest_jobs_by_pr(jobs: Optional[List[Any]]) -> Dict[int, Any]:
  latest: Dict[int, Any] = {}
  for job in jobs or []:
    pr_id = int(getattr(job, "pr_id", 0) or 0)
    if pr_id <= 0:
      continue
    current = latest.get(pr_id)
    if current is None or str(getattr(job, "created_at", "")) > str(
      getattr(current, "created_at", "")
    ):
      latest[pr_id] = job
  return latest


def _job_live_phase(job) -> Optional[str]:
  """Return an in-flight phase label for a job, or None if it is not live."""
  if job is None:
    return None
  status = str(getattr(job, "status", "") or "")
  if getattr(job, "finished_at", None):
    return None
  if status in ("queued", "running"):
    return str(getattr(job, "phase", "") or status)
  return None


# ------------------------------------------------------------------------------
# Public view builders
# ------------------------------------------------------------------------------
def pr_summaries(jobs: Optional[List[Any]] = None) -> List[Dict[str, Any]]:
  """One summary row per PR, ordered by most-recent activity.

  A PR is included if it has at least one review in the DB or a live job.
  """
  store = _get_store()
  job_by_pr = _latest_jobs_by_pr(jobs)

  summaries: List[Dict[str, Any]] = []
  seen_pr_ids = set()

  for pr in store.list_prs():
    pr_id = int(pr["pr_id"])
    reviews = store.list_reviews_for_pr(pr_id)
    live_job = job_by_pr.get(pr_id)
    live_phase = _job_live_phase(live_job)

    if not reviews and live_phase is None:
      # Extracted metadata only, never reviewed and not currently running.
      continue

    seen_pr_ids.add(pr_id)
    versions = store.list_versions(pr_id)
    latest_version = versions[-1] if versions else None

    latest_review = reviews[0] if reviews else None
    latest_summary = (
      _review_summary(store, latest_review) if latest_review is not None else None
    )

    bug_count = latest_summary["bug_count"] if latest_summary else 0
    patch_specific = latest_summary["patch_specific_count"] if latest_summary else 0

    # Bugs of earlier versions that a later version has fixed (regression gate).
    # Counted across the whole PR so the board can surface fix progress.
    fixed_bug_count = sum(
      1 for b in store.list_bugs_for_pr(pr_id) if b["status"] == "fixed"
    )

    if live_phase == "queued" or (
      live_job is not None and str(getattr(live_job, "status", "")) == "queued"
    ):
      outcome = "queued"
    elif live_phase is not None:
      outcome = "running"
    elif latest_summary is not None:
      outcome = latest_summary["outcome"]
    else:
      outcome = "queued"

    updated_at = (
      (latest_review["finished_at"] or latest_review["created_at"])
      if latest_review is not None
      else None
    )
    if live_job is not None:
      job_updated = str(getattr(live_job, "updated_at", "") or "")
      if job_updated and (updated_at is None or job_updated > updated_at):
        updated_at = job_updated
    if updated_at is None:
      updated_at = pr["updated_at"]

    summaries.append(
      {
        "pr_id": pr_id,
        "title": pr["title"],
        "author": pr["author"],
        "url": pr["pr_url"],
        "state": pr["state"],
        "components": _loads(pr["components"], []),
        "version_count": len(versions),
        "review_count": len(reviews),
        "latest_commit": latest_version["fix_commit"] if latest_version else "",
        "latest_seq": int(latest_version["seq"]) if latest_version else None,
        "latest_review_id": latest_summary["review_id"] if latest_summary else None,
        "latest_status": latest_summary["status"] if latest_summary else None,
        "bug_count": bug_count,
        "patch_specific_count": patch_specific,
        "fixed_bug_count": fixed_bug_count,
        "outcome": outcome,
        "live": live_phase,
        "updated_at": updated_at,
      }
    )

  summaries.sort(key=lambda s: str(s.get("updated_at") or ""), reverse=True)
  return summaries


def pr_detail(pr_id: int) -> Optional[Dict[str, Any]]:
  """Full PR tree: versions (commits) -> reviews -> bugs."""
  store = _get_store()
  pr = store.get_pr(pr_id)
  if pr is None:
    return None

  versions_out: List[Dict[str, Any]] = []
  # Newest commit version first.
  for ver in reversed(store.list_versions(pr_id)):
    version_id = int(ver["id"])
    reviews = []
    for r in store.list_reviews_for_version(version_id):
      summary = _review_summary(store, r)
      # Attach the full report payload so the PR page can inline it (two-level
      # navigation: board -> PR page, no separate per-review page hop).
      summary["detail"] = _review_stats_data(store, r)
      reviews.append(summary)
    versions_out.append(
      {
        "version_id": version_id,
        "seq": int(ver["seq"]),
        "fix_commit": ver["fix_commit"],
        "base_commit": ver["base_commit"],
        "created_at": ver["created_at"],
        "review_count": len(reviews),
        "reviews": reviews,
      }
    )

  return {
    "pr": {
      "pr_id": int(pr["pr_id"]),
      "title": pr["title"],
      "author": pr["author"],
      "url": pr["pr_url"],
      "state": pr["state"],
      "components": _loads(pr["components"], []),
      "description": pr["description"],
    },
    "versions": versions_out,
  }


def review_view(review_id: int) -> Optional[Dict[str, Any]]:
  """Assemble a ``(stats_data, meta)`` pair for rendering one review.

  ``stats_data`` matches the shape consumed by
  ``renderers.build_review_html_from_stats``; ``meta`` carries version/PR
  identity so the page header can show which commit/version this review is for.
  """
  store = _get_store()
  review = store.get_review(review_id)
  if review is None:
    return None

  version = store.get_version(int(review["version_id"]))
  pr = store.get_pr(int(review["pr_id"]))
  prev_version = store.get_previous_version(int(review["version_id"]))
  bug_rows = store.list_bugs_for_review(review_id)

  stats_data = {
    "strategies": _loads(review["strategies"], []),
    "bugs": [_bug_full_dict(b) for b in bug_rows],
    "report": review["report"],
    "chat_rounds": review["chat_rounds"],
    "chat_cost": review["chat_cost"],
    "total_time_sec": review["total_time_sec"],
    "total_tokens": review["total_tokens"],
  }

  meta = {
    "review_id": int(review["id"]),
    "pr_id": int(review["pr_id"]),
    "title": pr["title"] if pr is not None else "",
    "url": pr["pr_url"] if pr is not None else "",
    "components": _loads(pr["components"], []) if pr is not None else [],
    "version_id": int(review["version_id"]),
    "seq": int(version["seq"]) if version is not None else None,
    "fix_commit": version["fix_commit"] if version is not None else "",
    "base_commit": version["base_commit"] if version is not None else "",
    "prev_commit": prev_version["fix_commit"] if prev_version is not None else None,
    "status": review["status"],
    "skipped_reason": review["skipped_reason"],
    "error": review["error"],
    "errmsg": review["errmsg"],
    "created_at": review["created_at"],
    "finished_at": review["finished_at"],
  }
  return {"stats_data": stats_data, "meta": meta}


def review_history(review_id: int) -> Optional[Dict[str, Any]]:
  """Return the stored chat history + sidecar stats for the trace viewer."""
  store = _get_store()
  review = store.get_review(review_id)
  if review is None:
    return None
  history = _loads(review["history"], None)
  sidecar = {
    "total_tokens": review["total_tokens"],
    "chat_rounds": review["chat_rounds"],
    "phase1_round": review["phase1_round"],
    "phase2_round": review["phase2_round"],
  }
  return {"history": history, "sidecar_stats": sidecar}
