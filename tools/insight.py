import json
from typing import Callable, Dict, List, Optional

from lms.tool import FuncToolBase, FuncToolCallException, FuncToolSpec


class InsightTool(FuncToolBase):
  """Persist reusable review knowledge, with evidence-gated verification."""

  KINDS = {"hypothesis", "observation", "regression"}
  VERIFICATIONS = {"unverified", "verified"}
  EVIDENCE_TOOLS = {"verify", "difftest", "rwenum"}

  def __init__(
    self,
    store,
    components: List[str],
    pr_id: int,
    version_id: int,
    review_id: int,
    fix_commit: str,
    evidence_provider: Callable[[str], Optional[Dict]],
  ):
    self.store = store
    self.components = components
    self.pr_id = pr_id
    self.version_id = version_id
    self.review_id = review_id
    self.fix_commit = fix_commit
    self.evidence_provider = evidence_provider

  def spec(self):
    return FuncToolSpec("insight", (
      "Record or search durable knowledge shared across VeIR PR reviews. "
      "Verified records must cite a real result from this review."
    ), [
      FuncToolSpec.Param("action", "string", True, "'record' or 'search'."),
      FuncToolSpec.Param("topic", "string", False, "Short subject for a record."),
      FuncToolSpec.Param("content", "string", False, "Reusable semantic knowledge."),
      FuncToolSpec.Param("kind", "string", False,
        "Record kind: hypothesis, observation, or regression."),
      FuncToolSpec.Param("verification", "string", False,
        "unverified or verified; defaults to unverified."),
      FuncToolSpec.Param("source_tool", "string", False,
        "For verified records: verify, difftest, or rwenum."),
      FuncToolSpec.Param("components", "string", False,
        "Optional comma-separated components; defaults to this PR's components."),
      FuncToolSpec.Param("query", "string", False, "Text search for topic/content."),
      FuncToolSpec.Param("verified_only", "boolean", False,
        "Search only evidence-backed knowledge (default false)."),
      FuncToolSpec.Param("limit", "integer", False, "Search result limit, 1..50."),
    ])

  def _call(self, *, action, **kwargs):
    if action == "search":
      limit = max(1, min(int(kwargs.get("limit", 10)), 50))
      rows = self.store.search_insights(
        components=self._components(kwargs.get("components")),
        query=str(kwargs.get("query", "")),
        verified_only=bool(kwargs.get("verified_only", False)),
        limit=limit,
      )
      return json.dumps({"action": "search", "count": len(rows), "insights": rows},
        ensure_ascii=False)
    if action != "record":
      raise FuncToolCallException("action must be 'record' or 'search'")

    topic = str(kwargs.get("topic", "")).strip()
    content = str(kwargs.get("content", "")).strip()
    kind = str(kwargs.get("kind", "observation")).strip()
    verification = str(kwargs.get("verification", "unverified")).strip()
    if not topic or not content:
      raise FuncToolCallException("record requires non-empty topic and content")
    if len(topic) > 160 or len(content) > 4000:
      raise FuncToolCallException("topic/content exceed the 160/4000 character limits")
    if kind not in self.KINDS:
      raise FuncToolCallException(f"kind must be one of {sorted(self.KINDS)}")
    if verification not in self.VERIFICATIONS:
      raise FuncToolCallException(
        f"verification must be one of {sorted(self.VERIFICATIONS)}")

    verified = verification == "verified"
    source_tool = kwargs.get("source_tool")
    evidence = None
    if verified:
      if source_tool not in self.EVIDENCE_TOOLS:
        raise FuncToolCallException(
          "verified records require source_tool=verify, difftest, or rwenum"
        )
      evidence = self.evidence_provider(source_tool)
      if not evidence:
        raise FuncToolCallException(
          f"no {source_tool} result exists in the current review"
        )
      if kind == "regression" and not evidence.get("found", False):
        raise FuncToolCallException(
          "a verified regression requires evidence with found=true"
        )

    insight_id = self.store.upsert_insight(
      components=self._components(kwargs.get("components")), topic=topic,
      kind=kind, content=content, verified=verified,
      evidence_tool=source_tool if verified else None, evidence=evidence,
      pr_id=self.pr_id, version_id=self.version_id, review_id=self.review_id,
      fix_commit=self.fix_commit,
    )
    return json.dumps({"action": "record", "id": insight_id,
      "status": "verified" if verified else "unverified"})

  def _components(self, value) -> List[str]:
    if value is None:
      return list(self.components)
    parsed = [part.strip() for part in str(value).split(",") if part.strip()]
    return parsed or list(self.components)
