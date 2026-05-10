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


def build_review_html_from_stats(stats_data: dict) -> str:
  strategies = stats_data.get("strategies", [])
  bugs = stats_data.get("bugs", [])
  report_raw = stats_data.get("report", {})

  report = report_raw
  if isinstance(report_raw, str):
    try:
      report = json.loads(report_raw)
    except Exception:
      report = {}

  strategies_html = ""
  for i, strat in enumerate(strategies, 1):
    name = strat.get("name", "")
    target = strat.get("target", "")
    rationale = strat.get("rationale", "")
    expected = strat.get("expected_issue", "")
    strategy_id = f"strategy_{i}"

    strategies_html += f"""
    <div class="strategy-card">
      <div class="strategy-fold" id="{strategy_id}">
        <div class="strategy-head">
          <h4 class="strategy-title"><span style="font-weight: 700;">{i}.</span> {esc(name)}</h4>
          <button type="button" class="fold-toggle" data-target="{strategy_id}" title="展开/收起">
            <span class="fold-icon" aria-hidden="true"></span>
          </button>
        </div>
        <div class="strategy-body">
          <div style="margin: 8px 0; font-size: 13px; line-height: 1.5;">
            <strong style="color: #424a53;">Target:</strong><br>{esc(target)}
          </div>
          <div style="margin: 8px 0; font-size: 13px; line-height: 1.5;">
            <strong style="color: #424a53;">Rationale:</strong><br>{esc(rationale)}
          </div>
          <div style="margin: 8px 0; font-size: 13px; line-height: 1.5;">
            <strong style="color: #424a53;">Expected Issue:</strong><br>{esc(expected)}
          </div>
        </div>
      </div>
    </div>"""

  bugs_html = ""
  for i, bug in enumerate(bugs, 1):
    orig_ir = bug.get("original_ir", "")
    trans_ir = bug.get("transformed_ir", "")
    log = bug.get("log", "")

    unique_id = f"bug_{i}_log"
    orig_ir_html = f'<div class="bug-ir-body">{esc(orig_ir)}</div>'
    trans_ir_html = f'<div class="bug-ir-body">{esc(trans_ir)}</div>'
    log_html = (
      (
        f'<div class="bug-log-fold" id="{unique_id}">'
        f'<div class="bug-log-body">{esc(log)}</div>'
        f'<button type="button" class="fold-toggle" data-target="{unique_id}" title="展开/收起">'
        f'<span class="fold-icon" aria-hidden="true"></span>'
        "</button>"
        "</div>"
      )
      if len(log) > 320
      else (f'<div class="bug-log-body bug-log-body-static">{esc(log)}</div>')
    )

    bugs_html += f"""
    <div style="margin-bottom: 24px; padding: 14px 16px; background: #fef3c7; border-left: 3px solid #d97706; border-radius: 4px;">
      <h4 style="margin: 0 0 12px 0; color: #92400e; font-size: 15px;">Bug #{i}</h4>
      <div style="margin: 12px 0; font-size: 12px;">
        <strong style="color: #92400e; display: block; margin-bottom: 6px;">Original IR:</strong>
        {orig_ir_html}
      </div>
      <div style="margin: 12px 0; font-size: 12px;">
        <strong style="color: #92400e; display: block; margin-bottom: 6px;">Transformed IR:</strong>
        {trans_ir_html}
      </div>
      <div style="margin: 12px 0; font-size: 12px;">
        <strong style="color: #92400e; display: block; margin-bottom: 6px;">Error/Output Log:</strong>
        {log_html}
      </div>
    </div>"""

  if not bugs_html:
    bugs_html = '<p style="color: #999; font-size: 13px;"><em>No bugs found</em></p>'

  report_text = ""
  if isinstance(report, dict) and "thoughts" in report:
    report_text = report["thoughts"]
  else:
    report_text = "No analysis available"

  analysis_html = (
    '<div class="analysis-card">'
    f'<div class="analysis-body">{markdown_to_html(report_text)}</div>'
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
      --ink: #1f2d3d;
      --sub: #60758d;
      --line: #eaf0f7;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: var(--ink); background: #ffffff; }}
    .review-container {{ max-width: 1000px; margin: 0 auto; padding: 24px 32px; }}
    .head {{ margin-bottom: 20px; padding-bottom: 0; }}
    .title {{ margin: 0; font-size: 28px; font-weight: 700; }}
    .subtitle {{ margin-top: 8px; color: var(--sub); font-size: 13px; }}
    .section {{ margin: 28px 0; }}
    .section-title {{ font-size: 16px; font-weight: 700; margin-bottom: 16px; color: var(--ink); }}
    code {{ background: #f5f5f5; padding: 2px 6px; border-radius: 3px; font-family: 'Monaco', 'Menlo', monospace; font-size: 12px; }}
    pre {{ background: #f5f5f5; padding: 12px; border-radius: 4px; overflow-x: auto; line-height: 1.4; font-size: 12px; }}
    strong {{ font-weight: 600; }}
    a {{ color: #2f6fad; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .analysis-card {{ padding: 14px 16px; background: #eef5fc; border-left: 3px solid #2f6fad; border-radius: 4px; }}
    .strategy-card {{ margin-bottom: 20px; padding: 14px 16px; background: #fafbfc; border-left: 3px solid #6e7681; border-radius: 4px; }}
    .strategy-fold {{ position: relative; }}
    .strategy-head {{ position: relative; padding-right: 34px; }}
    .strategy-title {{ margin: 0; color: #1f2d3d; font-size: 15px; }}
    .strategy-body {{ display: none; margin-top: 10px; }}
    .strategy-fold.expanded .strategy-body {{ display: block; }}
    .strategy-card .fold-icon {{ border-color: #cdd9e6; }}
    .strategy-card .fold-icon::before, .strategy-card .fold-icon::after {{
      border-right-color: #546b83;
      border-bottom-color: #546b83;
    }}
    .strategy-card .fold-toggle:hover .fold-icon {{ background: #eef5fc; }}
    .analysis-body {{ line-height: 1.6; font-size: 13px; color: #333; }}
    .analysis-body h1, .analysis-body h2, .analysis-body h3 {{
      margin: 0 0 12px 0;
      color: #1f2d3d;
      line-height: 1.35;
    }}
    .analysis-body h1 {{ font-size: 22px; }}
    .analysis-body h2 {{ font-size: 16px; margin-top: 22px; }}
    .analysis-body h3 {{ font-size: 14px; margin-top: 18px; }}
    .analysis-body p {{ margin: 0 0 14px 0; }}
    .analysis-body ul {{ margin: 0 0 14px 18px; padding: 0; }}
    .analysis-body li {{ margin: 0 0 6px 0; }}
    .analysis-body .md-code-block {{ margin: 0 0 14px 0; background: #f5f5f5; border-radius: 4px; overflow: hidden; }}
    .analysis-body .md-code-lang {{ padding: 8px 12px 0 12px; font-size: 12px; color: #60758d; text-transform: lowercase; }}
    .analysis-body .md-code-block pre {{ margin: 0; border-radius: 0; }}
    .bug-ir-body {{
      background: #fff7e6;
      padding: 10px;
      border-radius: 3px;
      font-family: monospace;
      overflow-x: auto;
      overflow-y: auto;
      max-height: 400px;
      line-height: 1.4;
      color: #333;
      white-space: pre-wrap;
      word-break: normal;
      overflow-wrap: anywhere;
    }}
    .bug-log-fold {{ margin-top: 6px; position: relative; }}
    .bug-log-body {{
      background: #fff7e6;
      padding: 10px;
      border-radius: 3px;
      font-family: monospace;
      overflow-x: auto;
      line-height: 1.4;
      color: #555;
      white-space: pre-wrap;
      word-break: break-all;
    }}
    .bug-log-fold .bug-log-body {{
      margin-top: 0;
      max-height: 9.5em;
      overflow: hidden;
      position: relative;
      transition: max-height 0.18s ease;
      padding-right: 34px;
    }}
    .bug-log-fold .bug-log-body::after {{
      content: "";
      position: absolute;
      left: 0;
      right: 0;
      bottom: 0;
      height: 2.6em;
      background: linear-gradient(to bottom, rgba(255, 247, 230, 0), #fff7e6 75%);
      pointer-events: none;
    }}
    .bug-log-fold.expanded .bug-log-body {{
      max-height: none;
      overflow: visible;
    }}
    .bug-log-fold.expanded .bug-log-body::after {{
      display: none;
    }}
    .bug-log-body-static {{ max-height: 400px; overflow-y: auto; }}
    .fold-toggle {{
      position: absolute;
      right: 2px;
      bottom: 2px;
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
    }}
    .fold-icon {{
      position: relative;
      width: 22px;
      height: 22px;
      border: 1px solid #e3c8a8;
      border-radius: 11px;
      background: #ffffff;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }}
    .fold-icon::before, .fold-icon::after {{
      content: "";
      position: absolute;
      left: 50%;
      width: 6px;
      height: 6px;
      border-right: 2px solid #8a5a21;
      border-bottom: 2px solid #8a5a21;
      transform: translateX(-50%) rotate(45deg);
    }}
    .fold-icon::before {{ top: 4px; }}
    .fold-icon::after {{ top: 9px; }}
    .bug-log-fold.expanded .fold-icon::before, .bug-log-fold.expanded .fold-icon::after {{
      transform: translateX(-50%) rotate(225deg);
    }}
    .fold-toggle:hover .fold-icon {{ background: #fff7e6; }}
    .back-btn {{
      position: fixed;
      top: 24px;
      left: 32px;
      width: 32px;
      height: 32px;
      border: 1px solid #e6eef7;
      background: #f7fbff;
      color: #4f667d;
      border-radius: 4px;
      padding: 0;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 18px;
      z-index: 100;
      font-weight: 600;
    }}
    .back-btn:hover {{
      background: #eef6ff;
      border-color: #d6e3f0;
    }}
  </style>
</head>
<body>
  <button class="back-btn" type="button" title="Back to Review Board" onclick="window.location.href='/'">←</button>
  <div class="review-container">
    <div class="head">
      <h1 class="title">Review Report</h1>
      <div class="subtitle">Agent analysis and findings from PR review</div>
    </div>

    <div class="section">
      <h2 class="section-title">Test Strategies (Phase 1)</h2>
      {strategies_html}
    </div>

    <div class="section">
      <h2 class="section-title">Bugs Found (Phase 2)</h2>
      {bugs_html}
    </div>

    <div class="section">
      <h2 class="section-title">Analysis & Findings</h2>
      {analysis_html}
    </div>
  </div>
  <script>
    document.querySelectorAll('.bug-log-fold, .strategy-fold').forEach(function (box) {{
      box.classList.remove('expanded');
    }});

    document.addEventListener('click', function (ev) {{
      const btn = ev.target.closest('.fold-toggle');
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


def render_artifact_viewer(target: Path) -> str:
  content = target.read_text()

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

  try:
    data = json.loads(content)
    is_json = True
  except Exception:
    is_json = False
    data = content

  html = """<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Agent Trajectory</title>
  <style>
    :root {
      --ink: #1f2d3d;
      --sub: #60758d;
      --line: #eaf0f7;
      --blue-soft: #f4f9ff;
    }
    body { margin: 0; padding: 16px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: var(--ink); background: #ffffff; }
    .viewer { max-width: 1100px; margin: 0 auto; padding: 8px 10px 24px; }
    .head { margin-bottom: 12px; }
    .title { margin: 0; font-size: 26px; line-height: 1.2; font-weight: 700; }
    .sub { margin-top: 6px; color: var(--sub); font-size: 13px; word-break: break-all; }
    .summary-grid { display: grid; grid-template-columns: repeat(4, minmax(120px, 1fr)); gap: 8px; margin: 12px 0; }
    .stat { border: 1px solid var(--line); background: #f9fcff; padding: 8px 10px; }
    .stat-label { font-size: 11px; color: var(--sub); text-transform: uppercase; letter-spacing: 0.04em; }
    .stat-value { margin-top: 4px; font-size: 18px; font-weight: 700; color: var(--ink); }
    .tools { border: 1px solid var(--line); background: #f9fcff; padding: 10px; margin-bottom: 12px; }
    .tools-title { font-size: 12px; color: var(--sub); margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.04em; }
    .tool-badges { display: flex; flex-wrap: wrap; gap: 6px; }
    .tool-badge { border: 1px solid #d5e4f2; background: #ffffff; color: #35516c; padding: 3px 8px; font-size: 12px; }
    pre { background: #f7fbff; padding: 12px; overflow-x: auto; border: 1px solid #eaf0f7; }
    .msg { position: relative; margin: 10px 0; padding: 10px; border-left: 3px solid #2f6fad; background: var(--blue-soft); }
    .msg.user { border-left-color: #c7821f; background: #fff9e6; }
    .msg.assistant { border-left-color: #1f9956; background: #f0f9f0; }
    .msg.system { border-left-color: #2f6fad; background: #eef5fc; }
    .msg.tool { border-left-color: #7a8694; background: #f2f5f8; }
    .msg-body { margin-top: 10px; white-space: pre-wrap; word-break: break-word; }
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
      background: linear-gradient(to bottom, rgba(247, 251, 255, 0), #f7fbff 75%);
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
      right: 2px;
      bottom: 2px;
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
      width: 22px;
      height: 22px;
      border: 1px solid #cdd9e6;
      border-radius: 11px;
      background: #ffffff;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }
    .fold-icon::before, .fold-icon::after {
      content: "";
      position: absolute;
      left: 50%;
      width: 6px;
      height: 6px;
      border-right: 2px solid #546b83;
      border-bottom: 2px solid #546b83;
      transform: translateX(-50%) rotate(45deg);
    }
    .fold-icon::before { top: 4px; }
    .fold-icon::after { top: 9px; }
    .msg-fold.expanded .fold-icon::before, .msg-fold.expanded .fold-icon::after {
      transform: translateX(-50%) rotate(225deg);
    }
    .fold-toggle:hover .fold-icon { background: #eef5fc; }
    h3 { margin: 0; font-size: 12px; color: #60758d; }
    .back-btn {
      position: fixed;
      top: 24px;
      left: 32px;
      width: 32px;
      height: 32px;
      border: 1px solid #e6eef7;
      background: #f7fbff;
      color: #4f667d;
      border-radius: 4px;
      padding: 0;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 18px;
      z-index: 100;
      font-weight: 600;
    }
    .back-btn:hover {
      background: #eef6ff;
      border-color: #d6e3f0;
    }
  </style>
</head>
<body>
  <button class="back-btn" type="button" title="Back to Review Board" onclick="window.location.href='/'">←</button>
  <div class="viewer">
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
        return "tool", f"TOOL CALL: {name}", args_text
      if msg_type == "function_call_output":
        output_text = content_to_text(msg.get("output", ""))
        return "tool", "TOOL OUTPUT", output_text
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

    token_text = f"{token_total:,}" if has_tokens else "-"
    total_rounds_text = str(tool_calls_total)
    phase1_rounds_text = str(phase_rounds.get(1, 0))
    phase2_rounds_text = str(phase_rounds.get(2, 0))
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
