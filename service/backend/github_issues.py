"""Publish verified Archer findings as GitHub issues."""

import json
from typing import Any, Optional

import requests

_GITHUB_API = "https://api.github.com"
_MAX_GITHUB_BODY = 65000


def _trim(value: Any, limit: int = _MAX_GITHUB_BODY) -> str:
  text = str(value or "").strip()
  if len(text) <= limit:
    return text
  return text[: limit - 32].rstrip() + "\n\n[truncated by Archer]"


def _marker(pr_id: int) -> str:
  """Stable issue identity: one GitHub issue per LLVM PR."""
  return f"archer-pr-{pr_id}"


def _commit_marker(marker: str, fix_commit: str) -> str:
  return f"{marker}-commit-{fix_commit[:12]}"


def _comment_marker(marker: str) -> str:
  return f"{marker}-analysis"


def _issue_title(bug, pr_id: int) -> str:
  transformed_ir = str(bug["transformed_ir"] or "").strip()
  if transformed_ir == "<crash during transformation>":
    return f"Compiler crash found in LLVM PR #{pr_id}"
  return f"Miscompilation found in LLVM PR #{pr_id}"


def _analysis_text(bug, review) -> str:
  report = review["report"]
  if report:
    report_text = str(report).strip()
    try:
      parsed = json.loads(report_text)
    except (TypeError, ValueError):
      return report_text
    if isinstance(parsed, dict) and parsed.get("thoughts"):
      return str(parsed["thoughts"]).strip()
    return report_text

  thoughts = str(bug["thoughts"] or "").strip()
  return thoughts or "No additional analysis was recorded."


def _evidence_body(bug, pr, version, llvm_repo: str, marker: str) -> str:
  fix_commit = str(version["fix_commit"] or "")
  commit_marker = _commit_marker(marker, fix_commit)
  commit_url = f"https://github.com/{llvm_repo}/commit/{fix_commit}"
  args = str(bug["args"] or "").strip()
  call_instr = str(bug["call_instr"] or "").strip()
  command = f"opt {args}" if args else str(bug["repro_kind"] or "verify")
  if call_instr:
    command += f"\ncall: {call_instr}"

  return f"""<!-- {commit_marker} -->
Current commit: [`{fix_commit[:10]}`]({commit_url})

## Buggy Case

~~~llvm
{str(bug["original_ir"] or "").strip()}
~~~

Command:

~~~text
{command}
~~~

## Verification Result

Transformed LLVM IR:

~~~llvm
{str(bug["transformed_ir"] or "").strip()}
~~~

Output:

~~~text
{str(bug["log"] or "").strip()}
~~~
"""


def _issue_body(
  bug,
  pr,
  version,
  llvm_repo: str,
  marker: str,
  additional_bug_count: int = 0,
  review_url: str = "",
) -> str:
  pr_id = int(pr["pr_id"])
  pr_url = str(pr["pr_url"] or f"https://github.com/{llvm_repo}/pull/{pr_id}")
  additional_note = ""
  if additional_bug_count > 0 and review_url:
    noun = "bug was" if additional_bug_count == 1 else "bugs were"
    additional_note = (
      f"\n\n{additional_bug_count} additional patch-specific {noun} found. "
      f"[View the full review on Archer]({review_url})."
    )
  return _trim(
    f"""<!-- {marker} -->
This issue tracks a verified reproducer found while reviewing {pr_url}.

{_evidence_body(bug, pr, version, llvm_repo, marker).rstrip()}{additional_note}"""
  )


def _append_or_update_evidence(
  existing_body: str, evidence: str, commit_marker: str
) -> str:
  start = existing_body.find(f"<!-- {commit_marker} -->")
  if start < 0:
    return _trim(existing_body.rstrip() + "\n\n" + evidence.strip() + "\n")
  next_marker = existing_body.find("<!-- ", start + len(commit_marker) + 9)
  end = next_marker if next_marker >= 0 else len(existing_body)
  return _trim(existing_body[:start] + evidence.strip() + "\n" + existing_body[end:])


def _comment_body(
  bug, review, public_base_url: str, marker: str, fix_commit: str
) -> str:
  review_id = int(review["id"])
  review_url = f"{public_base_url.rstrip('/')}/review/{review_id}"
  body = f"""<!-- {_comment_marker(marker)} -->
## Latest Analysis (commit `{fix_commit[:10]}`)

{_analysis_text(bug, review)}

[View the full review on Archer]({review_url})
"""
  return _trim(body)


def _find_existing_issue(
  session: requests.Session, issue_repo: str, marker: str
) -> Optional[dict]:
  response = session.get(
    f"{_GITHUB_API}/search/issues",
    params={"q": f'repo:{issue_repo} is:issue "{marker}" in:body', "per_page": 10},
    timeout=30,
  )
  response.raise_for_status()
  payload = response.json()
  items = payload.get("items", []) if isinstance(payload, dict) else []
  for item in items if isinstance(items, list) else []:
    if isinstance(item, dict) and marker in str(item.get("body") or ""):
      return item
  return None


def _find_existing_comment(
  session: requests.Session, issue_repo: str, issue_number: int, marker: str
) -> Optional[dict]:
  response = session.get(
    f"{_GITHUB_API}/repos/{issue_repo}/issues/{issue_number}/comments",
    params={"per_page": 100},
    timeout=30,
  )
  response.raise_for_status()
  payload = response.json()
  for item in payload if isinstance(payload, list) else []:
    if isinstance(item, dict) and marker in str(item.get("body") or ""):
      return item
  return None


def publish_pending_bug_issues(
  store,
  session: requests.Session,
  issue_repo: str,
  llvm_repo: str,
  public_base_url: str,
) -> int:
  """Publish one issue per PR, using its earliest patch-specific bug."""
  published = 0
  pending_by_pr = {}
  for pending_bug in store.list_bugs_pending_publication():
    pending_by_pr.setdefault(int(pending_bug["pr_id"]), []).append(pending_bug)

  for pr_id, pending_bugs in pending_by_pr.items():
    publishable_bugs = store.list_publishable_bugs_for_pr(pr_id)
    if not publishable_bugs:
      continue
    representative = publishable_bugs[0]
    review = store.get_review(int(representative["review_id"]))
    version = store.get_version(int(representative["version_id"]))
    pr = store.get_pr(pr_id)
    if review is None or version is None or pr is None:
      continue

    fix_commit = str(version["fix_commit"] or "")
    marker = _marker(pr_id)
    latest_title = _issue_title(representative, pr_id)
    issue_number = next(
      (
        bug["github_issue_number"]
        for bug in publishable_bugs
        if bug["github_issue_number"] is not None
      ),
      None,
    )
    issue = None
    if issue_number is None:
      issue = _find_existing_issue(session, issue_repo, marker)
      if issue is None:
        response = session.post(
          f"{_GITHUB_API}/repos/{issue_repo}/issues",
          json={
            "title": latest_title,
            "body": _issue_body(
              representative,
              pr,
              version,
              llvm_repo,
              marker,
              len(publishable_bugs) - 1,
              f"{public_base_url.rstrip('/')}/review/{int(review['id'])}",
            ),
          },
          timeout=30,
        )
        response.raise_for_status()
        issue = response.json()
      issue_number = int(issue["number"])
    else:
      issue = {"body": ""}

    issue_url = str(issue.get("html_url") or "") if issue else ""
    if not issue_url:
      issue_url = next(
        (
          str(bug["github_issue_url"])
          for bug in publishable_bugs
          if bug["github_issue_url"]
        ),
        "",
      )
    for bug in publishable_bugs:
      store.set_bug_github_issue(int(bug["id"]), int(issue_number), issue_url)

    if issue is None or issue.get("body") in (None, ""):
      response = session.get(
        f"{_GITHUB_API}/repos/{issue_repo}/issues/{int(issue_number)}", timeout=30
      )
      response.raise_for_status()
      issue = response.json()
    current_title = str(issue.get("title") or "")
    current_body = str(issue.get("body") or "")
    latest_body = _issue_body(
      representative,
      pr,
      version,
      llvm_repo,
      marker,
      len(publishable_bugs) - 1,
      f"{public_base_url.rstrip('/')}/review/{int(review['id'])}",
    )
    if current_title != latest_title or current_body != latest_body:
      response = session.patch(
        f"{_GITHUB_API}/repos/{issue_repo}/issues/{int(issue_number)}",
        json={"title": latest_title, "body": latest_body},
        timeout=30,
      )
      response.raise_for_status()

    comment_id = next(
      (
        bug["github_comment_id"]
        for bug in publishable_bugs
        if bug["github_comment_id"] is not None
      ),
      None,
    )
    comment = None
    if comment_id is None:
      comment = _find_existing_comment(
        session, issue_repo, int(issue_number), _comment_marker(marker)
      )
    comment_body = _comment_body(
      representative, review, public_base_url, marker, fix_commit
    )
    if comment_id is None and comment is None:
      response = session.post(
        f"{_GITHUB_API}/repos/{issue_repo}/issues/{int(issue_number)}/comments",
        json={"body": comment_body},
        timeout=30,
      )
      response.raise_for_status()
      comment = response.json()
    elif comment_id is None and str(comment.get("body") or "") != comment_body:
      response = session.patch(
        f"{_GITHUB_API}/repos/{issue_repo}/issues/{int(issue_number)}/comments/{int(comment['id'])}",
        json={"body": comment_body},
        timeout=30,
      )
      response.raise_for_status()
      comment = response.json()
    if comment_id is None:
      comment_id = int(comment["id"])
    for bug in publishable_bugs:
      store.set_bug_github_comment(int(bug["id"]), int(comment_id))
    published += 1
  return published
