import json
import re
from pathlib import Path


def esc(v):
  return (v or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def markdown_to_html(md_text: str) -> str:
  if not md_text:
    return "<p><em>(no content)</em></p>"

  def format_inline(text: str) -> str:
    placeholders = []

    def stash_code(match: re.Match[str]) -> str:
      placeholders.append(f"<code>{esc(match.group(1))}</code>")
      return f"@@CODE{len(placeholders) - 1}@@"

    escaped = re.sub(r"`([^`]+)`", stash_code, text)
    escaped = esc(escaped)
    escaped = re.sub(
      r"\[([^\]]+)\]\(([^)]+)\)",
      lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>',
      escaped,
    )
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"__(.+?)__", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", escaped)
    escaped = re.sub(r"_([^_]+)_", r"<em>\1</em>", escaped)
    for idx, value in enumerate(placeholders):
      escaped = escaped.replace(f"@@CODE{idx}@@", value)
    return escaped

  lines = md_text.splitlines()
  blocks = []
  paragraph_lines = []
  list_items = []
  code_lines = []
  code_lang = ""
  in_code_block = False

  def flush_paragraph() -> None:
    nonlocal paragraph_lines
    if not paragraph_lines:
      return
    text = "<br>".join(format_inline(line) for line in paragraph_lines)
    blocks.append(f"<p>{text}</p>")
    paragraph_lines = []

  def flush_list() -> None:
    nonlocal list_items
    if not list_items:
      return
    items = "".join(f"<li>{format_inline(item)}</li>" for item in list_items)
    blocks.append(f"<ul>{items}</ul>")
    list_items = []

  def flush_code() -> None:
    nonlocal code_lines, code_lang
    if not code_lines and not code_lang:
      return
    label = f'<div class="md-code-lang">{esc(code_lang)}</div>' if code_lang else ""
    code_html = esc("\n".join(code_lines))
    blocks.append(
      f'<div class="md-code-block">{label}<pre><code>{code_html}</code></pre></div>'
    )
    code_lines = []
    code_lang = ""

  for raw_line in lines:
    line = raw_line.rstrip()

    if line.startswith("```"):
      flush_paragraph()
      flush_list()
      if in_code_block:
        flush_code()
        in_code_block = False
      else:
        in_code_block = True
        code_lang = line[3:].strip()
        code_lines = []
      continue

    if in_code_block:
      code_lines.append(raw_line)
      continue

    stripped = line.strip()
    if not stripped:
      flush_paragraph()
      flush_list()
      continue

    heading = re.match(r"^(#{1,3})\s+(.+)$", stripped)
    if heading:
      flush_paragraph()
      flush_list()
      level = len(heading.group(1))
      blocks.append(f"<h{level}>{format_inline(heading.group(2))}</h{level}>")
      continue

    list_match = re.match(r"^-\s+(.+)$", stripped)
    if list_match:
      flush_paragraph()
      list_items.append(list_match.group(1))
      continue

    paragraph_lines.append(stripped)

  if in_code_block:
    flush_code()
  flush_paragraph()
  flush_list()
  return "".join(blocks) if blocks else "<p><em>(no content)</em></p>"


def _is_placeholder_text(value: object) -> bool:
  return not isinstance(value, str) or value.strip() in ("", "<not-provided>")


_PATCH_SPEC_META = {
  "patch_specific": ("Patch-specific", "ps-patch"),
  "non_patch_specific": ("Non-patch-specific", "ps-nonpatch"),
  "not_checked": ("Baseline not checked", "ps-none"),
}


def build_review_html_from_stats(stats_data: dict, meta: dict | None = None) -> str:
  meta = meta or {}
  raw_strategies = stats_data.get("strategies", []) or []
  bugs = stats_data.get("bugs", []) or []

  # Drop the "<not-provided>" placeholder strategy that RunStats seeds by default
  # so that runs without real strategies do not render a fake card.
  strategies = [
    s
    for s in raw_strategies
    if isinstance(s, dict) and not _is_placeholder_text(s.get("name"))
  ]

  strategies_html = ""
  for i, strat in enumerate(strategies, 1):
    name = strat.get("name", "")
    target = strat.get("target", "")
    rationale = strat.get("rationale", "")
    expected = strat.get("expected_issue", "")
    strategy_id = f"strategy_{i}"

    strategies_html += f"""
    <div class="strat" id="{strategy_id}">
      <div class="strat-head" data-target="{strategy_id}">
        <span class="strat-idx">{i}</span>
        <span class="strat-name">{esc(name)}</span>
        <span class="caret" aria-hidden="true"></span>
      </div>
      <div class="strat-body">
        <div class="field">
          <div class="field-label">Target</div>
          <div class="field-val">{esc(target)}</div>
        </div>
        <div class="field">
          <div class="field-label">Rationale</div>
          <div class="field-val">{esc(rationale)}</div>
        </div>
        <div class="field">
          <div class="field-label">Expected Issue</div>
          <div class="field-val">{esc(expected)}</div>
        </div>
      </div>
    </div>"""

  if not strategies_html:
    strategies_html = '<p class="empty">No test strategies recorded</p>'

  bugs_html = ""
  for i, bug in enumerate(bugs, 1):
    orig_ir = bug.get("original_ir", "")
    trans_ir = bug.get("transformed_ir", "")
    log = bug.get("log", "")
    thoughts = bug.get("thoughts") or ""

    unique_id = f"bug_{i}_log"
    ps_key = bug.get("patch_specificity")
    ps_label, ps_cls = _PATCH_SPEC_META.get(ps_key, ("", ""))
    ps_html = (
      f'<span class="ps-chip {ps_cls}">{esc(ps_label)}</span>' if ps_label else ""
    )
    fixed_html = (
      '<span class="ps-chip ps-fixed">Fixed in later version</span>'
      if bug.get("status") == "fixed"
      else ""
    )
    thoughts_html = (
      (
        '<div class="field">'
        '<div class="field-label">Analysis</div>'
        f'<div class="field-val md-body">{markdown_to_html(thoughts)}</div>'
        "</div>"
      )
      if thoughts.strip()
      else ""
    )
    if len(log) > 320:
      log_html = (
        f'<div class="log-fold" id="{unique_id}">'
        f'<pre class="code log-body">{esc(log)}</pre>'
        f'<button type="button" class="more-btn" data-target="{unique_id}">'
        '<span class="more-label"></span>'
        '<span class="caret" aria-hidden="true"></span>'
        "</button>"
        "</div>"
      )
    else:
      log_html = f'<pre class="code">{esc(log)}</pre>'

    bugs_html += f"""
    <div class="bug">
      <div class="bug-head"><span class="bug-tag">BUG #{i}</span>{ps_html}{fixed_html}</div>
      {thoughts_html}
      <div class="field">
        <div class="field-label">Original IR</div>
        <pre class="code">{esc(orig_ir)}</pre>
      </div>
      <div class="field">
        <div class="field-label">Transformed IR</div>
        <pre class="code">{esc(trans_ir)}</pre>
      </div>
      <div class="field">
        <div class="field-label">Output Log</div>
        {log_html}
      </div>
    </div>"""

  if not bugs_html:
    bugs_html = '<p class="empty">No bugs found</p>'

  # stats.report is the agent's "thoughts" string (see main.py). Older/other runs
  # may store the whole report tool JSON, so accept both shapes.
  report_raw = stats_data.get("report")
  report_text = ""
  if isinstance(report_raw, dict):
    report_text = report_raw.get("thoughts") or ""
  elif isinstance(report_raw, str) and report_raw.strip():
    stripped = report_raw.strip()
    parsed = None
    if stripped.startswith("{"):
      try:
        parsed = json.loads(stripped)
      except Exception:
        parsed = None
    if isinstance(parsed, dict) and isinstance(parsed.get("thoughts"), str):
      report_text = parsed["thoughts"]
    else:
      report_text = report_raw

  if not report_text.strip():
    report_text = "No analysis available"

  analysis_html = (
    '<div class="analysis-card">'
    f'<div class="analysis-body">{markdown_to_html(report_text)}</div>'
    "</div>"
  )

  def _fmt_int(value: object) -> str:
    return f"{value:,}" if isinstance(value, int) else "-"

  def _fmt_duration(seconds: object) -> str:
    try:
      secs = float(seconds)  # type: ignore[arg-type]
    except (TypeError, ValueError):
      return "-"
    if secs <= 0:
      return "-"
    if secs < 60:
      return f"{secs:.1f}s"
    minutes, rem = divmod(int(secs), 60)
    if minutes < 60:
      return f"{minutes}m {rem}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"

  chat_rounds = stats_data.get("chat_rounds")
  chat_cost = stats_data.get("chat_cost")

  rounds_text = _fmt_int(chat_rounds)

  cost_text = (
    f"${chat_cost:.4f}" if isinstance(chat_cost, (int, float)) and chat_cost else "-"
  )

  summary_html = (
    '<div class="summary-grid">'
    f'<div class="stat"><div class="stat-label">Bugs Found</div>'
    f'<div class="stat-value">{len(bugs)}</div></div>'
    f'<div class="stat"><div class="stat-label">Total Time</div>'
    f'<div class="stat-value">{_fmt_duration(stats_data.get("total_time_sec"))}</div></div>'
    f'<div class="stat"><div class="stat-label">Chat Rounds</div>'
    f'<div class="stat-value">{rounds_text}</div></div>'
    f'<div class="stat"><div class="stat-label">Total Tokens</div>'
    f'<div class="stat-value">{_fmt_int(stats_data.get("total_tokens"))}</div></div>'
    f'<div class="stat"><div class="stat-label">Est. Cost</div>'
    f'<div class="stat-value">{cost_text}</div></div>'
    "</div>"
  )

  # Header: identify which PR / commit version / review this page is for.
  _STATUS_CLS = {
    "succeeded": "st-ok",
    "clean": "st-ok",
    "failed": "st-err",
    "tokenlimit": "st-warn",
    "skipped": "st-muted",
    "running": "st-warn",
    "queued": "st-muted",
  }
  if meta:
    pr_id = meta.get("pr_id")
    title_bits = []
    if pr_id:
      title_bits.append(f"PR #{pr_id} Review")
    else:
      title_bits.append("Review Report")
    title_text = " ".join(title_bits)

    status = str(meta.get("status") or "")
    status_html = (
      f'<span class="st-pill {_STATUS_CLS.get(status, "st-muted")}">{esc(status)}</span>'
      if status
      else ""
    )

    meta_rows = []
    pr_title = meta.get("title")
    if pr_title:
      url = meta.get("url")
      if url:
        meta_rows.append(
          f'<a class="hdr-title-link" href="{esc(url)}" target="_blank" '
          f'rel="noreferrer">{esc(pr_title)}</a>'
        )
      else:
        meta_rows.append(f'<span class="hdr-title-link">{esc(pr_title)}</span>')

    chips = []
    seq = meta.get("seq")
    if seq is not None:
      chips.append(f"Version seq #{seq}")
    fix_commit = meta.get("fix_commit")
    if fix_commit:
      chips.append(f"fix {esc(str(fix_commit)[:10])}")
    base_commit = meta.get("base_commit")
    if base_commit:
      chips.append(f"base {esc(str(base_commit)[:10])}")
    prev_commit = meta.get("prev_commit")
    if prev_commit:
      chips.append(f"prev {esc(str(prev_commit)[:10])}")
    chips_html = "".join(f'<span class="hdr-chip">{c}</span>' for c in chips)

    skipped_reason = meta.get("skipped_reason")
    note_html = (
      f'<div class="hdr-note">{esc(str(skipped_reason))}</div>'
      if skipped_reason
      else ""
    )
    errmsg = meta.get("errmsg")
    if errmsg and status == "failed":
      note_html += f'<div class="hdr-note hdr-err">{esc(str(errmsg))}</div>'

    head_html = (
      '<div class="head">'
      f'<div class="hdr-top"><h1 class="title">{esc(title_text)}</h1>{status_html}</div>'
      + ("".join(meta_rows))
      + (f'<div class="hdr-chips">{chips_html}</div>' if chips_html else "")
      + note_html
      + "</div>"
    )
  else:
    head_html = (
      '<div class="head">'
      '<h1 class="title">Review Report</h1>'
      '<div class="subtitle">Agent analysis and findings from PR review</div>'
      "</div>"
    )

  html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Review</title>
  <style>
    :root {{
      --ink: #16181d;
      --sub: #6b7280;
      --faint: #9aa1ac;
      --line: #e7e9ee;
      --line-strong: #d3d7de;
      --accent: #4f46e5;
      --err: #dc2626;
      --mono: ui-monospace, "SF Mono", "JetBrains Mono", "Fira Code", Menlo, Consolas, monospace;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; padding: 0; font-family: var(--mono); font-size: 13px; color: var(--ink); background: #ffffff; -webkit-font-smoothing: antialiased; }}
    .review-container {{ max-width: 1040px; margin: 0 auto; padding: 42px 28px 80px; }}
    .head {{ margin-bottom: 20px; padding-bottom: 16px; border-bottom: 2px solid var(--ink); }}
    .title {{ margin: 0; font-size: 22px; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; }}
    .subtitle {{ margin-top: 9px; color: var(--sub); font-size: 11.5px; letter-spacing: 0.03em; }}
    .hdr-top {{ display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }}
    .hdr-title-link {{ display: inline-block; margin-top: 9px; color: var(--ink); font-size: 13px; font-weight: 500; }}
    .hdr-chips {{ margin-top: 11px; display: flex; gap: 7px; flex-wrap: wrap; }}
    .hdr-chip {{ border: 1px solid var(--line-strong); color: var(--sub); padding: 2px 8px; font-size: 11px; font-weight: 600; letter-spacing: 0.02em; }}
    .hdr-note {{ margin-top: 10px; font-size: 12px; color: var(--sub); line-height: 1.5; }}
    .hdr-note.hdr-err {{ color: var(--err); }}
    .st-pill {{ display: inline-flex; align-items: center; font-size: 11px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; padding: 3px 9px; }}
    .st-pill.st-ok {{ color: #0f9d63; background: #eef6f1; }}
    .st-pill.st-err {{ color: var(--err); background: #fbebeb; }}
    .st-pill.st-warn {{ color: #d97706; background: #fbf2e3; }}
    .st-pill.st-muted {{ color: var(--sub); background: #eef0f3; }}
    .ps-chip {{ display: inline-block; margin-left: 10px; font-size: 10px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; padding: 2px 8px; }}
    .ps-chip.ps-patch {{ color: var(--err); background: #fbebeb; }}
    .ps-chip.ps-nonpatch {{ color: #d97706; background: #fbf2e3; }}
    .ps-chip.ps-none {{ color: var(--sub); background: #eef0f3; }}
    .ps-chip.ps-fixed {{ color: #0f9d63; background: #eef6f1; }}
    .section {{ margin: 14px 0 0; padding-top: 12px; border-top: 1px solid var(--line); }}
    .section-title {{ font-size: 11px; font-weight: 700; margin-bottom: 10px; color: var(--sub); text-transform: uppercase; letter-spacing: 0.12em; }}

    /* summary — linear hairline row, no cards */
    .summary-grid {{ display: flex; flex-wrap: wrap; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); margin: 0; }}
    .stat {{ flex: 1 1 120px; padding: 11px 18px; border-left: 1px solid var(--line); }}
    .stat:first-child {{ border-left: none; padding-left: 0; }}
    .stat-label {{ font-size: 10px; color: var(--sub); text-transform: uppercase; letter-spacing: 0.1em; font-weight: 600; }}
    .stat-value {{ margin-top: 6px; font-size: 22px; font-weight: 700; color: var(--ink); font-family: var(--mono); }}
    code {{ background: #f3f4f6; padding: 1px 5px; font-family: var(--mono); font-size: 12px; }}
    pre {{ background: #f7f8fa; padding: 12px; overflow-x: auto; line-height: 1.5; font-size: 12px; border: 1px solid var(--line); }}
    strong {{ font-weight: 700; }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .rounds-split {{ font-size: 11px; color: var(--sub); font-weight: 600; margin-left: 6px; font-family: var(--mono); }}
    .empty {{ color: var(--sub); font-size: 12.5px; font-style: italic; margin: 0; }}

    /* analysis — flat, left rule instead of card */
    .analysis-card {{ padding: 2px 0 2px 16px; border-left: 2px solid var(--ink); }}
    .analysis-body {{ line-height: 1.65; font-size: 13px; color: var(--ink); }}
    .analysis-body h1, .analysis-body h2, .analysis-body h3 {{ margin: 0 0 10px 0; color: var(--ink); line-height: 1.35; font-weight: 700; }}
    .analysis-body h1 {{ font-size: 16px; }}
    .analysis-body h2 {{ font-size: 14px; margin-top: 18px; }}
    .analysis-body h3 {{ font-size: 13px; margin-top: 14px; }}
    .analysis-body p {{ margin: 0 0 10px 0; }}
    .analysis-body ul {{ margin: 0 0 10px 18px; padding: 0; }}
    .analysis-body li {{ margin: 0 0 5px 0; }}
    .analysis-body .md-code-block {{ margin: 0 0 10px 0; background: #f7f8fa; border: 1px solid var(--line); overflow: hidden; }}
    .analysis-body .md-code-lang {{ padding: 8px 12px 0 12px; font-size: 12px; color: var(--sub); font-family: var(--mono); }}
    .analysis-body .md-code-block pre {{ margin: 0; border: none; }}

    /* unified field layout */
    .field {{ margin: 10px 0; }}
    .field:first-child {{ margin-top: 0; }}
    .field-label {{ font-size: 10px; font-weight: 700; color: var(--sub); text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 7px; }}
    .field-val {{ font-size: 13px; line-height: 1.6; color: var(--ink); }}

    /* unified code / IR / log block */
    .code {{ background: #f7f8fa; border: 1px solid var(--line); padding: 12px; margin: 0; font-family: var(--mono); font-size: 12px; line-height: 1.5; color: var(--ink); white-space: pre-wrap; word-break: break-word; overflow-wrap: anywhere; overflow-x: auto; max-height: 400px; overflow-y: auto; }}

    /* strategy — hairline rows, no card */
    .strat {{ border-bottom: 1px solid var(--line); }}
    .strat:first-of-type {{ border-top: 1px solid var(--line); }}
    .strat-head {{ display: flex; align-items: center; gap: 12px; padding: 10px 0; cursor: pointer; user-select: none; }}
    .strat-head:hover .strat-name {{ color: var(--accent); }}
    .strat-idx {{ flex: none; width: 22px; height: 22px; background: var(--ink); color: #fff; font-size: 11px; font-weight: 700; font-family: var(--mono); display: inline-flex; align-items: center; justify-content: center; }}
    .strat-name {{ flex: 1; font-size: 13px; font-weight: 600; color: var(--ink); }}
    .strat-body {{ display: none; padding: 2px 0 10px 34px; }}
    .strat.expanded .strat-body {{ display: block; }}

    /* bug — sharp left rule, no card */
    .bug {{ border-left: 2px solid var(--err); padding: 2px 0 2px 16px; margin-bottom: 24px; }}
    .bug-head {{ margin-bottom: 12px; }}
    .bug-tag {{ display: inline-block; font-family: var(--mono); font-size: 11px; font-weight: 700; letter-spacing: 0.1em; color: var(--err); text-transform: uppercase; }}

    /* log fold */
    .log-fold {{ position: relative; }}
    .log-fold .log-body {{ position: relative; max-height: 9.5em; overflow: hidden; transition: max-height .18s ease; }}
    .log-fold .log-body::after {{ content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 2.8em; background: linear-gradient(to bottom, rgba(247,248,250,0), #f7f8fa 80%); pointer-events: none; }}
    .log-fold.expanded .log-body {{ max-height: 600px; overflow: auto; }}
    .log-fold.expanded .log-body::after {{ display: none; }}
    .more-btn {{ margin-top: 8px; display: inline-flex; align-items: center; gap: 7px; background: #ffffff; border: 1px solid var(--line-strong); padding: 6px 12px; font-size: 11px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: var(--sub); cursor: pointer; font-family: var(--mono); transition: all .15s; }}
    .more-btn:hover {{ color: #fff; background: var(--ink); border-color: var(--ink); }}
    .more-btn:hover .caret {{ border-color: #fff; }}
    .more-btn .more-label::before {{ content: "Show full log"; }}
    .log-fold.expanded .more-btn .more-label::before {{ content: "Collapse"; }}

    /* clean caret shared by strategy heads and log toggle */
    .caret {{ flex: none; width: 7px; height: 7px; border-right: 1.5px solid var(--sub); border-bottom: 1.5px solid var(--sub); transform: rotate(45deg); transition: transform .18s ease; }}
    .strat.expanded .strat-head .caret {{ transform: rotate(225deg); }}
    .log-fold.expanded .caret {{ transform: rotate(225deg); }}
  </style>
</head>
<body>
  <div class="review-container">
    {head_html}

    {summary_html}

    <div class="section">
      <h2 class="section-title">Test Strategies (Phase 1)</h2>
      {strategies_html}
    </div>

    <div class="section">
      <h2 class="section-title">Bugs Found (Phase 2)</h2>
      {bugs_html}
    </div>

    <div class="section">
      <h2 class="section-title">Analysis &amp; Findings</h2>
      {analysis_html}
    </div>
  </div>
  <script>
    document.addEventListener('click', function (ev) {{
      const btn = ev.target.closest('[data-target]');
      if (!btn) return;
      const id = btn.getAttribute('data-target');
      if (!id) return;
      const box = document.getElementById(id);
      if (!box) return;
      box.classList.toggle('expanded');
    }});
  </script>
</body>
</html>"""

  return html


_OUTCOME_META = {
  "queued": ("Queued", "st-muted"),
  "running": ("Running", "st-warn"),
  "bug": ("Buggy", "st-err"),
  "clean": ("Clean", "st-ok"),
  "failed": ("Failed", "st-muted"),
  "skipped": ("Skipped", "st-muted"),
  "succeeded": ("Succeeded", "st-ok"),
  "tokenlimit": ("Token limit", "st-warn"),
}

_PS_UI = {
  "patch_specific": ("Patch-specific", "ps-patch"),
  "non_patch_specific": ("Non-patch-specific", "ps-nonpatch"),
  "not_checked": ("Not checked", "ps-none"),
}


def _short_sha(sha) -> str:
  return str(sha)[:10] if sha else ""


def _extract_report_text(report_raw) -> str:
  """Normalise the stored report field into displayable markdown text."""
  if isinstance(report_raw, dict):
    return report_raw.get("thoughts") or ""
  if isinstance(report_raw, str) and report_raw.strip():
    stripped = report_raw.strip()
    parsed = None
    if stripped.startswith("{"):
      try:
        parsed = json.loads(stripped)
      except Exception:
        parsed = None
    if isinstance(parsed, dict) and isinstance(parsed.get("thoughts"), str):
      return parsed["thoughts"]
    return report_raw
  return ""


def _render_review_body(detail: dict, id_prefix: str = "") -> str:
  """Inline a single review's full report (analysis + bugs + strategies).

  ``detail`` matches ``db_view._review_stats_data``. ``id_prefix`` keeps the
  collapsible strategy/log element ids unique when several reviews are rendered
  on the same PR page.
  """
  detail = detail or {}
  raw_strategies = detail.get("strategies", []) or []
  bugs = detail.get("bugs", []) or []
  strategies = [
    s
    for s in raw_strategies
    if isinstance(s, dict) and not _is_placeholder_text(s.get("name"))
  ]

  # --- Analysis & findings (agent report) ---
  report_text = _extract_report_text(detail.get("report"))
  analysis_html = ""
  if report_text.strip():
    analysis_html = (
      '<div class="rev-section"><h4 class="rev-sec-title">Analysis &amp; Findings</h4>'
      '<div class="analysis-card"><div class="analysis-body">'
      f"{markdown_to_html(report_text)}</div></div></div>"
    )

  # --- Bugs (full detail) ---
  bugs_html = ""
  for i, bug in enumerate(bugs, 1):
    orig_ir = bug.get("original_ir", "")
    trans_ir = bug.get("transformed_ir", "")
    log = bug.get("log", "")
    thoughts = bug.get("thoughts") or ""
    unique_id = f"{id_prefix}bug_{i}_log"

    ps_key = bug.get("patch_specificity")
    ps_label, ps_cls = _PATCH_SPEC_META.get(ps_key, ("", ""))
    ps_html = (
      f'<span class="ps-chip {ps_cls}">{esc(ps_label)}</span>' if ps_label else ""
    )
    fixed_html = (
      '<span class="ps-chip ps-fixed">Fixed in later version</span>'
      if bug.get("status") == "fixed"
      else ""
    )
    thoughts_html = (
      (
        '<div class="field"><div class="field-label">Analysis</div>'
        f'<div class="field-val md-body">{markdown_to_html(thoughts)}</div></div>'
      )
      if thoughts.strip()
      else ""
    )
    if len(log) > 320:
      log_html = (
        f'<div class="log-fold" id="{unique_id}">'
        f'<pre class="code log-body">{esc(log)}</pre>'
        f'<button type="button" class="more-btn" data-target="{unique_id}">'
        '<span class="more-label"></span>'
        '<span class="caret" aria-hidden="true"></span>'
        "</button></div>"
      )
    else:
      log_html = f'<pre class="code">{esc(log)}</pre>'

    fields = ""
    if orig_ir:
      fields += (
        '<div class="field"><div class="field-label">Original IR</div>'
        f'<pre class="code">{esc(orig_ir)}</pre></div>'
      )
    if trans_ir:
      fields += (
        '<div class="field"><div class="field-label">Transformed IR</div>'
        f'<pre class="code">{esc(trans_ir)}</pre></div>'
      )
    if log:
      fields += (
        f'<div class="field"><div class="field-label">Output Log</div>{log_html}</div>'
      )

    bugs_html += (
      '<div class="bug">'
      f'<div class="bug-head"><span class="bug-tag">BUG #{i}</span>{ps_html}{fixed_html}</div>'
      f"{thoughts_html}{fields}</div>"
    )
  bugs_section = ""
  if bugs_html:
    bugs_section = (
      f'<div class="rev-section"><h4 class="rev-sec-title">Bugs ({len(bugs)})</h4>'
      f"{bugs_html}</div>"
    )

  # --- Test strategies (collapsible) ---
  strategies_html = ""
  for i, strat in enumerate(strategies, 1):
    name = strat.get("name", "")
    target = strat.get("target", "")
    rationale = strat.get("rationale", "")
    expected = strat.get("expected_issue", "")
    sid = f"{id_prefix}strategy_{i}"
    strategies_html += (
      f'<div class="strat" id="{sid}"><div class="strat-head" data-target="{sid}">'
      f'<span class="strat-idx">{i}</span><span class="strat-name">{esc(name)}</span>'
      '<span class="caret" aria-hidden="true"></span></div>'
      '<div class="strat-body">'
      f'<div class="field"><div class="field-label">Target</div><div class="field-val">{esc(target)}</div></div>'
      f'<div class="field"><div class="field-label">Rationale</div><div class="field-val">{esc(rationale)}</div></div>'
      f'<div class="field"><div class="field-label">Expected Issue</div><div class="field-val">{esc(expected)}</div></div>'
      "</div></div>"
    )
  strat_section = ""
  if strategies_html:
    strat_section = (
      '<div class="rev-section"><h4 class="rev-sec-title">Test Strategies</h4>'
      f"{strategies_html}</div>"
    )

  body = analysis_html + bugs_section + strat_section
  if not body:
    body = '<p class="empty">No report content recorded for this review.</p>'
  return body


def build_pr_detail_html(detail: dict) -> str:
  """Render a PR's full tree (version -> review -> bugs) as a standalone page.

  ``detail`` matches ``db_view.pr_detail`` output. Each review links out to the
  existing per-review report (``/review/<id>``) and trace (``/trace/<id>``).
  """
  pr = detail.get("pr") or {}
  versions = detail.get("versions") or []

  pr_id = pr.get("pr_id")
  pr_url = pr.get("url") or f"https://github.com/llvm/llvm-project/pull/{pr_id}"
  title = pr.get("title") or "(no title)"
  components = pr.get("components") or []
  description = pr.get("description") or ""

  comp_html = ""
  if components:
    comp_html = (
      '<div class="hdr-chips">'
      + "".join(f'<span class="hdr-chip">{esc(str(c))}</span>' for c in components)
      + "</div>"
    )

  desc_html = ""
  if description and description.strip():
    desc_html = (
      '<div class="section"><h2 class="section-title">Description</h2>'
      f'<div class="analysis-card"><div class="analysis-body">{markdown_to_html(description)}</div></div>'
      "</div>"
    )

  # Only the newest review on the page starts expanded; the rest render as a
  # collapsed overview row the user can click open (two-level: board -> PR page,
  # with each review as an expandable summary rather than everything inlined).
  expand_state = {"used": False}

  def _render_review(rev: dict) -> str:
    outcome = rev.get("outcome") or "queued"
    label, cls = _OUTCOME_META.get(outcome, ("Pending", "st-muted"))
    review_id = rev.get("review_id")
    status = str(rev.get("status") or "")

    metrics = []
    if rev.get("total_time_sec"):
      metrics.append(f"{round(rev['total_time_sec'])}s")
    if rev.get("total_tokens"):
      metrics.append(f"{rev['total_tokens']:,} tok")
    if rev.get("chat_rounds"):
      metrics.append(f"{rev['chat_rounds']} rounds")
    metrics_html = (
      f'<span class="rev-metrics">{esc(" · ".join(metrics))}</span>' if metrics else ""
    )

    bug_count = rev.get("bug_count") or 0
    ps_count = rev.get("patch_specific_count") or 0
    bug_summary = ""
    if bug_count > 0:
      bug_summary = (
        f'<span class="bug-count">{bug_count} bug{"s" if bug_count > 1 else ""}</span>'
      )
      if ps_count > 0:
        bug_summary += f' <span class="bug-sub">({ps_count} patch-specific)</span>'

    # Skipped reviews carry no report; render just the reason, no toggle.
    if status == "skipped":
      reason = rev.get("skipped_reason")
      reason_html = (
        f'<div class="rev-reason">{esc(str(reason))}</div>' if reason else ""
      )
      return (
        f'<div class="rev {cls}">'
        '<div class="rev-top rev-top-static">'
        + f'<span class="st-pill {cls}">{esc(label)}</span>'
        + (f"<span>{bug_summary}</span>" if bug_summary else "")
        + metrics_html
        + "</div>"
        + reason_html
        + "</div>"
      )

    if status == "failed":
      return (
        f'<div class="rev {cls}">'
        '<div class="rev-top rev-top-static">'
        + f'<span class="st-pill {cls}">{esc(label)}</span>'
        + metrics_html
        + "</div>"
        '<div class="rev-reason">Review failed before a report was produced.</div>'
        + "</div>"
      )

    # Everything else inlines the full report inside a collapsible block
    # (expanded by default), so the whole review lives on this one page.
    trace_html = ""
    if status in ("succeeded", "tokenlimit"):
      trace_html = (
        '<div class="rev-links">'
        f'<a href="/trace/{review_id}" onclick="event.stopPropagation()">'
        "View agent trace &rarr;</a></div>"
      )
    err_html = ""
    if status == "failed" and rev.get("errmsg"):
      err_html = f'<div class="rev-reason">{esc(str(rev["errmsg"]))}</div>'

    body_inner = _render_review_body(
      rev.get("detail") or {}, id_prefix=f"r{review_id}_"
    )
    rev_dom = f"rev_{review_id}"
    # Newest review (first one rendered) opens by default; others stay collapsed.
    expanded_cls = "" if expand_state["used"] else " expanded"
    expand_state["used"] = True
    return (
      f'<div class="rev {cls}{expanded_cls}" id="{rev_dom}">'
      f'<div class="rev-top" data-target="{rev_dom}">'
      + f'<span class="st-pill {cls}">{esc(label)}</span>'
      + (f"<span>{bug_summary}</span>" if bug_summary else "")
      + metrics_html
      + '<span class="caret rev-caret" aria-hidden="true"></span>'
      + "</div>"
      '<div class="rev-body">'
      + err_html
      + trace_html
      + body_inner
      + "</div>"
      + "</div>"
    )

  def _render_version(v: dict) -> str:
    seq = v.get("seq")
    fix_commit = v.get("fix_commit") or ""
    base_commit = v.get("base_commit") or ""
    base_html = ""
    if base_commit:
      base_html = (
        '<span class="ver-meta">on base</span>'
        f'<span class="commit" title="{esc(str(base_commit))}">{esc(_short_sha(base_commit))}</span>'
      )
    head = (
      '<div class="ver-head">'
      f'<span class="ver-seq" title="Commit #{seq} of this PR that Archer reviewed">Commit #{seq}</span>'
      '<span class="ver-meta">reviewing</span>'
      f'<span class="commit" title="{esc(str(fix_commit))}">{esc(_short_sha(fix_commit))}</span>'
      + base_html
      + "</div>"
    )
    reviews = v.get("reviews") or []
    if reviews:
      revs_html = "".join(_render_review(r) for r in reviews)
    else:
      revs_html = '<div class="rev-reason">No review for this commit yet.</div>'
    return f'<div class="ver">{head}{revs_html}</div>'

  if versions:
    versions_html = "".join(_render_version(v) for v in versions)
  else:
    versions_html = '<p class="empty">No commit versions recorded for this PR.</p>'

  return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>PR #{esc(str(pr_id))} Detail</title>
  <style>
    :root {{
      --ink: #16181d; --sub: #6b7280; --faint: #9aa1ac;
      --line: #e7e9ee; --line-strong: #d3d7de; --accent: #4f46e5; --err: #dc2626;
      --mono: ui-monospace, "SF Mono", "JetBrains Mono", "Fira Code", Menlo, Consolas, monospace;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; padding: 0; font-family: var(--mono); font-size: 13px; color: var(--ink); background: #ffffff; -webkit-font-smoothing: antialiased; }}
    .review-container {{ max-width: 1040px; margin: 0 auto; padding: 42px 28px 80px; }}
    .back-link {{ display: inline-block; margin-bottom: 16px; color: var(--sub); font-size: 11.5px; letter-spacing: 0.04em; text-decoration: none; }}
    .back-link:hover {{ color: var(--accent); }}
    .head {{ margin-bottom: 20px; padding-bottom: 16px; border-bottom: 2px solid var(--ink); }}
    .hdr-top {{ display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }}
    .title {{ margin: 0; font-size: 22px; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; }}
    .pr-num-link {{ color: var(--accent); font-size: 14px; font-weight: 700; text-decoration: none; }}
    .pr-num-link:hover {{ text-decoration: underline; }}
    .hdr-title-link {{ display: block; margin-top: 9px; color: var(--ink); font-size: 13px; font-weight: 500; }}
    .hdr-chips {{ margin-top: 11px; display: flex; gap: 7px; flex-wrap: wrap; }}
    .hdr-chip {{ border: 1px solid var(--line-strong); color: var(--sub); padding: 2px 8px; font-size: 11px; font-weight: 600; }}
    .section {{ margin: 20px 0 0; padding-top: 14px; border-top: 1px solid var(--line); }}
    .section-title {{ font-size: 11px; font-weight: 700; margin-bottom: 10px; color: var(--sub); text-transform: uppercase; letter-spacing: 0.12em; }}
    .empty {{ color: var(--sub); font-size: 12.5px; font-style: italic; margin: 0; }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}

    .ver {{ border-top: 1px solid var(--line); padding: 16px 0 6px; }}
    .ver:first-child {{ border-top: none; }}
    .ver-head {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: var(--sub); }}
    .ver-seq {{ background: var(--ink); color: #fff; padding: 2px 8px; font-size: 10px; }}
    .commit {{ font-family: var(--mono); color: var(--ink); background: #eef0f3; padding: 2px 7px; font-size: 11px; letter-spacing: 0; text-transform: none; }}
    .ver-meta {{ color: var(--faint); font-weight: 600; }}

    .rev {{ border-left: 2px solid var(--line-strong); margin: 12px 0 0; padding: 10px 0 10px 14px; }}
    .rev.st-err {{ border-left-color: var(--err); }}
    .rev.st-ok {{ border-left-color: #0f9d63; }}
    .rev.st-warn {{ border-left-color: #d97706; }}
    .rev-top {{ display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }}
    .rev-metrics {{ color: var(--faint); font-size: 11px; font-weight: 600; }}
    .rev-links {{ display: inline-flex; gap: 14px; }}
    .rev-links a {{ font-size: 12px; font-weight: 600; }}
    .rev-reason {{ margin-top: 7px; font-size: 11.5px; color: var(--sub); line-height: 1.5; }}
    .rev-bugs {{ margin-top: 8px; display: flex; flex-direction: column; gap: 5px; }}
    .bug-line {{ display: flex; align-items: center; gap: 8px; font-size: 11.5px; color: var(--ink); }}
    .bug-line .kind {{ color: var(--sub); font-weight: 600; }}
    .bug-count {{ font-weight: 700; color: var(--err); }}
    .bug-sub {{ color: var(--sub); font-weight: 600; font-size: 11px; }}

    .st-pill {{ display: inline-flex; align-items: center; font-size: 11px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; padding: 3px 9px; }}
    .st-pill.st-ok {{ color: #0f9d63; background: #eef6f1; }}
    .st-pill.st-err {{ color: var(--err); background: #fbebeb; }}
    .st-pill.st-warn {{ color: #d97706; background: #fbf2e3; }}
    .st-pill.st-muted {{ color: var(--sub); background: #eef0f3; }}
    .ps-chip {{ display: inline-block; margin-left: 10px; font-size: 10px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; padding: 2px 8px; }}
    .ps-chip.ps-patch {{ color: var(--err); background: #fbebeb; }}
    .ps-chip.ps-nonpatch {{ color: #d97706; background: #fbf2e3; }}
    .ps-chip.ps-none {{ color: var(--sub); background: #eef0f3; }}
    .ps-chip.ps-fixed {{ color: #0f9d63; background: #eef6f1; }}

    .analysis-card {{ padding: 2px 0 2px 16px; border-left: 2px solid var(--ink); }}
    .analysis-body {{ line-height: 1.65; font-size: 13px; color: var(--ink); }}
    .analysis-body p {{ margin: 0 0 10px 0; }}
    .analysis-body p:last-child {{ margin-bottom: 0; }}
    .analysis-body ul {{ margin: 0 0 10px 18px; padding: 0; }}
    .analysis-body li {{ margin: 0 0 5px 0; }}
    .analysis-body pre {{ background: #f7f8fa; padding: 12px; border: 1px solid var(--line); overflow-x: auto; font-size: 12px; }}
    .analysis-body h1, .analysis-body h2, .analysis-body h3 {{ margin: 0 0 10px 0; color: var(--ink); line-height: 1.35; font-weight: 700; }}
    .analysis-body h1 {{ font-size: 16px; }}
    .analysis-body h2 {{ font-size: 14px; margin-top: 16px; }}
    .analysis-body h3 {{ font-size: 13px; margin-top: 12px; }}
    .analysis-body .md-code-block {{ margin: 0 0 10px 0; background: #f7f8fa; border: 1px solid var(--line); overflow: hidden; }}
    .analysis-body .md-code-lang {{ padding: 8px 12px 0 12px; font-size: 12px; color: var(--sub); }}
    .analysis-body .md-code-block pre {{ margin: 0; border: none; }}
    code {{ background: #f3f4f6; padding: 1px 5px; font-family: var(--mono); font-size: 12px; }}

    /* Collapsible review + inlined full report */
    .rev-top {{ cursor: pointer; }}
    .rev-top-static {{ cursor: default; }}
    .rev-caret {{ margin-left: auto; }}
    .rev-body {{ display: none; margin-top: 12px; }}
    .rev.expanded > .rev-body {{ display: block; }}
    .rev.expanded .rev-caret {{ transform: rotate(225deg); }}
    .rev-links {{ margin: 2px 0 14px; }}
    .rev-links a {{ font-size: 12px; font-weight: 600; }}
    .rev-section {{ margin-top: 16px; }}
    .rev-sec-title {{ font-size: 10.5px; font-weight: 700; color: var(--sub); text-transform: uppercase; letter-spacing: 0.1em; margin: 0 0 10px; }}

    .field {{ margin: 10px 0; }}
    .field-label {{ font-size: 10px; font-weight: 700; color: var(--sub); text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 7px; }}
    .field-val {{ font-size: 13px; line-height: 1.6; color: var(--ink); }}
    .code {{ background: #f7f8fa; border: 1px solid var(--line); padding: 12px; margin: 0; font-family: var(--mono); font-size: 12px; line-height: 1.5; color: var(--ink); white-space: pre-wrap; word-break: break-word; overflow-wrap: anywhere; overflow-x: auto; max-height: 400px; overflow-y: auto; }}

    .strat {{ border-bottom: 1px solid var(--line); }}
    .strat:first-of-type {{ border-top: 1px solid var(--line); }}
    .strat-head {{ display: flex; align-items: center; gap: 12px; padding: 10px 0; cursor: pointer; user-select: none; }}
    .strat-head:hover .strat-name {{ color: var(--accent); }}
    .strat-idx {{ flex: none; width: 22px; height: 22px; background: var(--ink); color: #fff; font-size: 11px; font-weight: 700; display: inline-flex; align-items: center; justify-content: center; }}
    .strat-name {{ flex: 1; font-size: 13px; font-weight: 600; color: var(--ink); }}
    .strat-body {{ display: none; padding: 2px 0 10px 34px; }}
    .strat.expanded .strat-body {{ display: block; }}

    .bug {{ border-left: 2px solid var(--err); padding: 2px 0 2px 16px; margin-bottom: 20px; }}
    .bug-head {{ margin-bottom: 12px; }}
    .bug-tag {{ display: inline-block; font-size: 11px; font-weight: 700; letter-spacing: 0.1em; color: var(--err); text-transform: uppercase; }}

    .log-fold {{ position: relative; }}
    .log-fold .log-body {{ position: relative; max-height: 9.5em; overflow: hidden; transition: max-height .18s ease; }}
    .log-fold .log-body::after {{ content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 2.8em; background: linear-gradient(to bottom, rgba(247,248,250,0), #f7f8fa 80%); pointer-events: none; }}
    .log-fold.expanded .log-body {{ max-height: 600px; overflow: auto; }}
    .log-fold.expanded .log-body::after {{ display: none; }}
    .more-btn {{ margin-top: 8px; display: inline-flex; align-items: center; gap: 7px; background: #fff; border: 1px solid var(--line-strong); padding: 6px 12px; font-size: 11px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: var(--sub); cursor: pointer; font-family: var(--mono); transition: all .15s; }}
    .more-btn:hover {{ color: #fff; background: var(--ink); border-color: var(--ink); }}
    .more-btn:hover .caret {{ border-color: #fff; }}
    .more-btn .more-label::before {{ content: "Show full log"; }}
    .log-fold.expanded .more-btn .more-label::before {{ content: "Collapse"; }}

    .caret {{ flex: none; width: 7px; height: 7px; border-right: 1.5px solid var(--sub); border-bottom: 1.5px solid var(--sub); transform: rotate(45deg); transition: transform .18s ease; }}
    .strat.expanded .strat-head .caret {{ transform: rotate(225deg); }}
    .log-fold.expanded .caret {{ transform: rotate(225deg); }}
  </style>
</head>
<body>
  <div class="review-container">
    <a class="back-link" href="/">&larr; Back to board</a>
    <div class="head">
      <div class="hdr-top">
        <h1 class="title">PR Detail</h1>
        <a class="pr-num-link" href="{esc(str(pr_url))}" target="_blank" rel="noreferrer">#{esc(str(pr_id))}</a>
      </div>
      <span class="hdr-title-link">{esc(str(title))}</span>
      {comp_html}
    </div>
    {desc_html}
    <div class="section">
      <h2 class="section-title">Commit Versions &amp; Reviews</h2>
      {versions_html}
    </div>
  </div>
  <script>
    document.addEventListener('click', function (ev) {{
      const btn = ev.target.closest('[data-target]');
      if (!btn) return;
      const id = btn.getAttribute('data-target');
      if (!id) return;
      const box = document.getElementById(id);
      if (!box) return;
      box.classList.toggle('expanded');
    }});
  </script>
</body>
</html>"""


def render_markdown_page(md_text: str, title: str = "Review") -> str:
  body = markdown_to_html(md_text)
  return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{esc(title)}</title>
  <style>
    :root {{ --accent: #4f46e5; --line: #e7e9ee; --line-strong: #d3d7de; --sub: #6b7280; --ink: #16181d; --mono: ui-monospace, "SF Mono", "JetBrains Mono", "Fira Code", Menlo, Consolas, monospace; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; padding: 0; font-family: var(--mono); color: var(--ink); background: #ffffff; -webkit-font-smoothing: antialiased; }}
    .review-container {{ max-width: 1040px; margin: 0 auto; padding: 42px 28px 80px; line-height: 1.65; font-size: 13px; }}
    .review-container h1 {{ font-size: 20px; margin: 0 0 18px 0; padding-bottom: 14px; border-bottom: 2px solid var(--ink); font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; }}
    .review-container h2 {{ font-size: 15px; margin: 26px 0 10px 0; font-weight: 700; }}
    .review-container h3 {{ font-size: 13px; margin: 18px 0 8px 0; font-weight: 700; }}
    .review-container p {{ margin: 0 0 12px 0; }}
    .review-container ul {{ margin: 0 0 12px 18px; padding: 0; }}
    .review-container li {{ margin: 0 0 5px 0; }}
    code {{ background: #f3f4f6; padding: 1px 5px; font-family: var(--mono); font-size: 12px; }}
    pre {{ background: #f7f8fa; padding: 12px; overflow-x: auto; line-height: 1.5; font-size: 12px; border: 1px solid var(--line); }}
    .md-code-block {{ margin: 0 0 12px 0; background: #f7f8fa; border: 1px solid var(--line); overflow: hidden; }}
    .md-code-lang {{ padding: 8px 12px 0 12px; font-size: 12px; color: var(--sub); text-transform: lowercase; font-family: var(--mono); }}
    .md-code-block pre {{ margin: 0; border: none; }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <div class="review-container">{body}</div>
</body>
</html>"""


def render_artifact_viewer(target: Path) -> str:
  content = target.read_text()

  # For the agent trajectory (history.json) the authoritative run metrics
  # (tokens, chat rounds, phase split) live in the sibling stats.json, not in
  # the per-message history (individual messages carry no usage data). Load it
  # so the summary shows real numbers instead of "-"/0.
  sidecar_stats: dict = {}
  if str(target).endswith(".history.json"):
    sibling_stats = Path(str(target).rsplit(".", 2)[0] + ".stats.json")
    if sibling_stats.exists():
      try:
        loaded = json.loads(sibling_stats.read_text())
        if isinstance(loaded, dict):
          sidecar_stats = loaded
      except Exception:
        sidecar_stats = {}

  if str(target).endswith(".stats.json"):
    try:
      stats_data = json.loads(content)
      return build_review_html_from_stats(stats_data)
    except Exception as e:
      return f"<pre>Error parsing stats.json: {str(e)}</pre>"

  if str(target).endswith(".review.md"):
    base_path = str(target).rsplit(".", 2)[0]
    stats_path = Path(base_path + ".stats.json")

    if stats_path.exists():
      try:
        stats_data = json.loads(stats_path.read_text())
        return build_review_html_from_stats(stats_data)
      except Exception:
        pass

    # No sibling stats.json: render the markdown itself instead of dumping raw text.
    return render_markdown_page(content, title="Review")

  if str(target).endswith(".md"):
    return render_markdown_page(content, title=target.name)

  try:
    data = json.loads(content)
  except Exception:
    return f"<pre>{esc(str(content))}</pre>"
  if not isinstance(data, list):
    return f"<pre>{esc(json.dumps(data, ensure_ascii=False, indent=2))}</pre>"
  return render_trajectory_page(data, sidecar_stats)


def render_trajectory_page(data, sidecar_stats=None) -> str:
  """Render an agent chat-history list into the trajectory HTML page.

  Reused both by the file-based artifact viewer and by the DB-backed trace
  endpoint (``reviews.history``). ``sidecar_stats`` supplies authoritative
  token/round counters when the per-message history lacks them.
  """
  sidecar_stats = sidecar_stats or {}
  is_json = True
  html = """<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Agent Trajectory</title>
  <style>
    :root {
      --ink: #16181d;
      --sub: #6b7280;
      --faint: #9aa1ac;
      --line: #e7e9ee;
      --line-strong: #d3d7de;
      --accent: #4f46e5;
      --mono: ui-monospace, "SF Mono", "JetBrains Mono", "Fira Code", Menlo, Consolas, monospace;
    }
    * { box-sizing: border-box; }
    body { margin: 0; padding: 0; font-family: var(--mono); font-size: 13px; color: var(--ink); background: #ffffff; -webkit-font-smoothing: antialiased; }
    .viewer { max-width: 1040px; margin: 0 auto; padding: 42px 28px 80px; }
    .back-link { display: inline-block; margin-bottom: 16px; color: var(--sub); font-size: 11.5px; letter-spacing: 0.04em; text-decoration: none; cursor: pointer; }
    .back-link:hover { color: var(--accent); }
    .head { margin-bottom: 22px; padding-bottom: 16px; border-bottom: 2px solid var(--ink); }
    .title { margin: 0; font-size: 22px; line-height: 1.2; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; }
    .sub { margin-top: 9px; color: var(--sub); font-size: 11.5px; word-break: break-all; letter-spacing: 0.03em; }
    .summary-grid { display: flex; flex-wrap: wrap; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); margin: 0 0 18px; }
    .stat { flex: 1 1 120px; padding: 11px 18px; border-left: 1px solid var(--line); }
    .stat:first-child { border-left: none; padding-left: 0; }
    .stat-label { font-size: 10px; color: var(--sub); text-transform: uppercase; letter-spacing: 0.1em; font-weight: 600; }
    .stat-value { margin-top: 6px; font-size: 22px; font-weight: 700; color: var(--ink); font-family: var(--mono); }
    .tools { border-bottom: 1px solid var(--line); padding: 4px 0 18px; margin-bottom: 20px; }
    .tools-title { font-size: 10px; color: var(--sub); margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.1em; font-weight: 700; }
    .tool-badges { display: flex; flex-wrap: wrap; gap: 6px; }
    .tool-badge { border: 1px solid var(--line-strong); background: transparent; color: var(--ink); padding: 3px 9px; font-size: 11px; font-family: var(--mono); font-weight: 600; }
    pre { background: #f7f8fa; padding: 12px; overflow-x: auto; border: 1px solid var(--line); font-family: var(--mono); font-size: 12px; }
    .msg { position: relative; margin: 0; padding: 12px 0 12px 16px; border-left: 2px solid var(--line-strong); border-bottom: 1px solid var(--line); }
    .msg.user { border-left-color: #d97706; }
    .msg.assistant { border-left-color: #0f9d63; }
    .msg.system { border-left-color: var(--accent); }
    .msg.tool { border-left-color: #9aa1ac; }
    .msg.tool-call { border-left-color: var(--accent); background: #fafaff; }
    .msg.tool-call h3 { color: var(--accent); }
    .msg.tool-output { border-left-color: #cbd0d8; }
    .msg.tool-output h3 { color: var(--faint); }
    .msg-body { margin-top: 9px; white-space: pre-wrap; word-break: break-word; }
    pre.msg-body { background: #f7f8fa; border: none; padding: 11px 12px; font-size: 12px; line-height: 1.55; }
    .msg-fold { margin-top: 8px; position: relative; }
    .msg-fold .msg-body {
      margin-top: 0;
      max-height: 9.5em;
      overflow: hidden;
      position: relative;
      transition: max-height 0.18s ease;
    }
    .msg-fold .msg-body::after {
      content: "";
      position: absolute;
      left: 0;
      right: 0;
      bottom: 0;
      height: 2.6em;
      background: linear-gradient(to bottom, rgba(247, 248, 250, 0), #f7f8fa 75%);
      pointer-events: none;
    }
    .msg-fold.expanded .msg-body {
      max-height: none;
      overflow: visible;
    }
    .msg-fold.expanded .msg-body::after {
      display: none;
    }
    .fold-toggle {
      position: absolute;
      right: 6px;
      bottom: 6px;
      width: 24px;
      height: 24px;
      border: none;
      background: transparent;
      padding: 0;
      cursor: pointer;
      z-index: 2;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }
    .fold-icon {
      position: relative;
      width: 24px;
      height: 24px;
      border: 1px solid var(--line-strong);
      background: #ffffff;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      transition: all .15s;
    }
    .fold-icon::before {
      content: "";
      width: 7px;
      height: 7px;
      border-right: 1.5px solid var(--sub);
      border-bottom: 1.5px solid var(--sub);
      transform: translateY(-2px) rotate(45deg);
      transition: transform .18s ease;
    }
    .msg-fold.expanded .fold-icon::before {
      transform: translateY(1px) rotate(225deg);
    }
    .fold-toggle:hover .fold-icon { border-color: var(--ink); background: var(--ink); }
    .fold-toggle:hover .fold-icon::before { border-color: #fff; }
    h3 { margin: 0; font-size: 10px; color: var(--sub); text-transform: uppercase; letter-spacing: 0.1em; font-family: var(--mono); font-weight: 700; }
  </style>
</head>
<body>
  <div class="viewer">
    <a class="back-link" href="/" onclick="if(history.length>1){history.back();return false;}">&larr; Back</a>
    <div class="head">
      <h1 class="title">Agent Trajectory</h1>
      <div class="sub">Conversation timeline with tool traces and model turns</div>
    </div>
"""

  if is_json and isinstance(data, list):
    allowed_roles = {"user", "assistant", "system", "tool"}

    def content_to_text(value):
      if isinstance(value, str):
        return value
      if isinstance(value, list):
        parts = []
        for item in value:
          if isinstance(item, str):
            parts.append(item)
          elif isinstance(item, dict):
            if isinstance(item.get("text"), str):
              parts.append(item["text"])
            elif isinstance(item.get("content"), str):
              parts.append(item["content"])
            else:
              parts.append(json.dumps(item, ensure_ascii=False))
          else:
            parts.append(str(item))
        return "\n".join(p for p in parts if p)
      if isinstance(value, dict):
        if isinstance(value.get("text"), str):
          return value["text"]
        return json.dumps(value, ensure_ascii=False, indent=2)
      return str(value)

    def entry_to_view(msg):
      role = str(msg.get("role", "")).strip().lower()
      if role in allowed_roles:
        return role, role.upper(), content_to_text(msg.get("content", ""))

      msg_type = str(msg.get("type", "")).strip().lower()
      if msg_type == "function_call":
        name = str(msg.get("name", "tool"))
        args_text = content_to_text(msg.get("arguments", ""))
        return "tool tool-call", f"TOOL CALL: {name}", args_text
      if msg_type == "function_call_output":
        output_text = content_to_text(msg.get("output", ""))
        return "tool tool-output", "TOOL OUTPUT", output_text
      if msg_type:
        content_text = content_to_text(msg.get("content", msg))
        return "tool", f"EVENT: {msg_type}", content_text

      return None

    shown = 0
    trajectory_html = []
    fold_id = 0
    preview_limit = 320
    tool_calls_total = 0
    tool_name_counts = {}
    phase_rounds = {}
    current_phase = None
    token_input = 0
    token_output = 0
    token_total = 0
    has_tokens = False

    def read_int(dct, key):
      val = dct.get(key)
      return val if isinstance(val, int) else None

    def ingest_tokens(msg):
      nonlocal token_input, token_output, token_total, has_tokens
      in_tok = None
      out_tok = None
      total_tok = None

      if isinstance(msg.get("usage"), dict):
        u = msg["usage"]
        in_tok = read_int(u, "input_tokens")
        if in_tok is None:
          in_tok = read_int(u, "prompt_tokens")
        out_tok = read_int(u, "output_tokens")
        if out_tok is None:
          out_tok = read_int(u, "completion_tokens")
        total_tok = read_int(u, "total_tokens")

      if in_tok is None:
        in_tok = read_int(msg, "input_tokens")
      if in_tok is None:
        in_tok = read_int(msg, "prompt_tokens")
      if out_tok is None:
        out_tok = read_int(msg, "output_tokens")
      if out_tok is None:
        out_tok = read_int(msg, "completion_tokens")
      if total_tok is None:
        total_tok = read_int(msg, "total_tokens")

      if in_tok is None and out_tok is None and total_tok is None:
        return

      has_tokens = True
      if in_tok is not None:
        token_input += in_tok
      if out_tok is not None:
        token_output += out_tok
      if total_tok is not None:
        token_total += total_tok
      else:
        token_total += (in_tok or 0) + (out_tok or 0)

    def detect_phase_number(msg):
      if str(msg.get("role", "")).strip().lower() != "user":
        return None
      txt = content_to_text(msg.get("content", ""))
      m = re.search(r"#\s*phase\s*(\d+)", txt, re.I)
      if not m:
        return None
      try:
        return int(m.group(1))
      except Exception:
        return None

    for msg in data:
      if not isinstance(msg, dict):
        continue

      phase_no = detect_phase_number(msg)
      if phase_no is not None:
        current_phase = phase_no

      view = entry_to_view(msg)
      if view is None:
        continue

      msg_type = str(msg.get("type", "")).strip().lower()
      if msg_type == "function_call":
        tool_calls_total += 1
        if current_phase is not None:
          phase_rounds[current_phase] = phase_rounds.get(current_phase, 0) + 1
        tname = str(msg.get("name", "tool"))
        tool_name_counts[tname] = tool_name_counts.get(tname, 0) + 1

      ingest_tokens(msg)

      css_role, label, txt = view
      display_txt = txt.strip()
      if not display_txt:
        display_txt = "(empty output)" if label == "TOOL OUTPUT" else "(empty content)"

      if len(display_txt) > preview_limit:
        fold_id += 1
        fold_dom_id = f"fold-{fold_id}"
        trajectory_html.append(
          f'<div class="msg {css_role}">'
          f"<h3>{esc(label)}</h3>"
          f'<div class="msg-fold" id="{fold_dom_id}">'
          f'<pre class="msg-body">{esc(display_txt)}</pre>'
          f'<button type="button" class="fold-toggle" data-target="{fold_dom_id}" title="展开/收起">'
          f'<span class="fold-icon" aria-hidden="true"></span>'
          f"</button>"
          f"</div>"
          f"</div>"
        )
      else:
        trajectory_html.append(
          f'<div class="msg {css_role}"><h3>{esc(label)}</h3><pre class="msg-body">{esc(display_txt)}</pre></div>'
        )
      shown += 1

    def sidecar_int(key):
      val = sidecar_stats.get(key)
      return val if isinstance(val, int) else None

    stats_tokens = sidecar_int("total_tokens")
    stats_rounds = sidecar_int("chat_rounds")
    stats_phase1 = sidecar_int("phase1_round")
    stats_phase2 = sidecar_int("phase2_round")

    # Prefer authoritative stats.json values; fall back to history-derived ones.
    if stats_tokens is not None and stats_tokens > 0:
      token_total = stats_tokens
      has_tokens = True
    total_rounds = stats_rounds if stats_rounds is not None else tool_calls_total
    phase1_rounds = stats_phase1 if stats_phase1 is not None else phase_rounds.get(1, 0)
    phase2_rounds = stats_phase2 if stats_phase2 is not None else phase_rounds.get(2, 0)

    token_text = f"{token_total:,}" if has_tokens else "-"
    total_rounds_text = str(total_rounds)
    phase1_rounds_text = str(phase1_rounds)
    phase2_rounds_text = str(phase2_rounds)
    if tool_name_counts:
      sorted_tools = sorted(tool_name_counts.items(), key=lambda kv: (-kv[1], kv[0]))
      badges = "".join(
        f'<span class="tool-badge">{esc(name)} x {count}</span>'
        for name, count in sorted_tools[:24]
      )
    else:
      badges = '<span class="tool-badge">(no tool calls)</span>'

    summary_html = (
      '<div class="summary-grid">'
      f'<div class="stat"><div class="stat-label">Total Rounds</div><div class="stat-value">{total_rounds_text}</div></div>'
      f'<div class="stat"><div class="stat-label">Phase 1 Analyze</div><div class="stat-value">{phase1_rounds_text}</div></div>'
      f'<div class="stat"><div class="stat-label">Phase 2 Validate</div><div class="stat-value">{phase2_rounds_text}</div></div>'
      f'<div class="stat"><div class="stat-label">Total Tokens</div><div class="stat-value">{token_text}</div></div>'
      "</div>"
      '<div class="tools">'
      '<div class="tools-title">Tool Call Distribution</div>'
      f'<div class="tool-badges">{badges}</div>'
      "</div>"
    )
    html += summary_html
    html += "".join(trajectory_html)

    if shown == 0:
      html += "<p>No visible history entries found.</p>"
  else:
    html += f"<pre>{esc(str(data))}</pre>"

  html += """
  <script>
    document.addEventListener('click', function (ev) {
      const btn = ev.target.closest('.fold-toggle');
      if (!btn) return;
      const id = btn.getAttribute('data-target');
      if (!id) return;
      const box = document.getElementById(id);
      if (!box) return;
      box.classList.toggle('expanded');
    });
  </script>
"""

  html += "</div></body></html>"
  return html
