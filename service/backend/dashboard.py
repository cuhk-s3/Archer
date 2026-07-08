import json
from pathlib import Path
from typing import Optional

# Shared dashboard styling + client logic. Injected into both the backend-served
# page (build_dashboard_html, same-origin) and, in spirit, the static frontend.
_DASHBOARD_STYLE = """
    :root {
      --bg: #ffffff;
      --ink: #16181d;
      --muted: #6b7280;
      --faint: #9aa1ac;
      --line: #e7e9ee;
      --line-strong: #d3d7de;
      --accent: #4f46e5;
      --ok: #0f9d63;
      --ok-bg: #eef6f1;
      --err: #dc2626;
      --err-bg: #fbebeb;
      --run: #d97706;
      --run-bg: #fbf2e3;
      --queue: #6b7280;
      --queue-bg: #eef0f3;
      --mono: ui-monospace, "SF Mono", "JetBrains Mono", "Fira Code", Menlo, Consolas, monospace;
    }
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; color: var(--ink); background: var(--bg); font-family: var(--mono); font-size: 13px; -webkit-font-smoothing: antialiased; }
    .shell { max-width: 1040px; margin: 0 auto; padding: 0 24px 64px; }

    .topbar { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; padding: 22px 0 14px; border-bottom: 2px solid var(--ink); }
    .brand { display: flex; align-items: center; gap: 14px; min-width: 0; }
    .logo { width: 34px; height: 34px; flex: 0 0 auto; object-fit: contain; display: block; }
    .brand-text { display: flex; flex-direction: column; line-height: 1.05; min-width: 0; }
    .brand-name { font-size: 21px; font-weight: 700; letter-spacing: 0.16em; text-transform: uppercase; }
    .brand-tag { font-size: 10.5px; color: var(--muted); letter-spacing: 0.16em; text-transform: uppercase; margin-top: 5px; }
    .topbar-right { display: flex; align-items: center; gap: 18px; flex-wrap: wrap; justify-content: flex-end; }
    .live { display: inline-flex; align-items: center; gap: 7px; font-size: 11px; color: var(--ok); letter-spacing: 0.12em; text-transform: uppercase; font-weight: 600; }
    .live-dot { width: 6px; height: 6px; background: var(--ok); animation: pulse 1.8s infinite; }
    @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.2; } 100% { opacity: 1; } }
    .nav-link { color: var(--muted); font-size: 11.5px; text-decoration: none; display: inline-flex; gap: 6px; letter-spacing: 0.03em; }
    .nav-link strong { color: var(--ink); font-weight: 700; }
    .nav-link:hover { color: var(--accent); }

    .stats { display: grid; grid-template-columns: repeat(4, 1fr); border-bottom: 1px solid var(--line); }
    .stat-card { padding: 11px 18px 10px; border-left: 1px solid var(--line); }
    .stat-card:first-child { border-left: none; padding-left: 0; }
    .stat-num { font-size: 24px; font-weight: 700; line-height: 1; letter-spacing: -0.02em; }
    .stat-card.run .stat-num { color: var(--run); }
    .stat-card.bug .stat-num { color: var(--err); }
    .stat-card.done .stat-num { color: var(--ok); }
    .stat-label { display: block; margin-top: 8px; font-size: 10.5px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.12em; font-weight: 600; }

    .toolbar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin: 16px 0 0; }
    .search-box { display: flex; align-items: center; flex: 1 1 260px; min-width: 220px; height: 38px; background: var(--bg); border: 1px solid var(--line-strong); padding: 0 6px 0 12px; transition: border-color .15s; }
    .search-box:focus-within { border-color: var(--ink); }
    .search-ico { color: var(--faint); flex: 0 0 auto; display: flex; }
    .search-input { flex: 1; min-width: 0; border: none; background: transparent; height: 100%; padding: 0 8px; font-size: 13px; color: var(--ink); font-family: var(--mono); }
    .search-input:focus { outline: none; }
    .search-input::placeholder { color: var(--faint); }
    .input-clear { border: none; background: transparent; width: 28px; height: 28px; color: var(--faint); font-size: 17px; line-height: 1; cursor: pointer; }
    .input-clear:hover { color: var(--ink); }
    .seg { display: inline-flex; border: 1px solid var(--line-strong); flex-wrap: wrap; }
    .seg-btn { border: none; border-left: 1px solid var(--line-strong); background: transparent; color: var(--muted); padding: 0 14px; height: 38px; font-size: 11.5px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; cursor: pointer; font-family: var(--mono); transition: background .12s, color .12s; }
    .seg-btn:first-child { border-left: none; }
    .seg-btn:hover { color: var(--ink); }
    .seg-btn.active { background: var(--ink); color: #fff; }

    .card { border-top: 1px solid var(--line); margin-top: 14px; }
    .table-wrap { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; min-width: 640px; table-layout: fixed; }
    thead th { color: var(--muted); font-weight: 700; font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.12em; text-align: left; padding: 13px 14px; border-bottom: 1px solid var(--line-strong); }
    thead th:first-child { padding-left: 8px; }
    tbody td { border-bottom: 1px solid var(--line); padding: 13px 14px; vertical-align: top; font-size: 13px; }
    tbody td:first-child { padding-left: 8px; }
    tbody tr.pr-row { transition: background .12s; cursor: pointer; }
    tbody tr.pr-row:hover { background: #fafbfc; }
    th:nth-child(1), td:nth-child(1) { width: 57%; }
    th:nth-child(2), td:nth-child(2) { width: 16%; }
    th:nth-child(3), td:nth-child(3) { width: 9%; }
    th:nth-child(4), td:nth-child(4) { width: 18%; padding-right: 24px; }

    .pr-header { line-height: 1.55; }
    .pr-link { color: var(--accent); font-size: 12.5px; font-weight: 700; text-decoration: none; margin-right: 8px; }
    .pr-link:hover { text-decoration: underline; }
    .pr-title-text { color: var(--ink); font-size: 12.5px; font-weight: 500; }
    .subline { margin-top: 6px; font-size: 11px; color: var(--faint); letter-spacing: 0.02em; }
    .subline .commit { color: var(--muted); }
    .tags { margin-top: 8px; display: flex; gap: 6px; flex-wrap: wrap; }
    .tag { background: transparent; color: var(--muted); border: 1px solid var(--line-strong); padding: 1px 7px; font-size: 10.5px; font-weight: 600; }

    .pill { display: inline-flex; align-items: center; gap: 7px; font-weight: 600; font-size: 11px; letter-spacing: 0.06em; padding: 4px 9px; white-space: nowrap; text-transform: uppercase; }
    .pill::before { content: ""; width: 7px; height: 7px; background: currentColor; }
    .pill.queued { color: var(--queue); background: var(--queue-bg); }
    .pill.running { color: var(--run); background: var(--run-bg); }
    .pill.running::before { animation: pulse 1.6s infinite; }
    .pill.bug { color: var(--err); background: var(--err-bg); }
    .pill.clean { color: var(--ok); background: var(--ok-bg); }
    .pill.failed { color: var(--faint); background: var(--queue-bg); }
    .pill.skipped { color: var(--muted); background: var(--queue-bg); }

    .bug-count { font-weight: 700; color: var(--err); }
    .bug-sub { color: var(--muted); font-weight: 600; font-size: 11px; }
    .dash { color: var(--faint); }
    .date-chip { display: inline-block; font-size: 12px; color: var(--muted); white-space: nowrap; }
    .live-note { display: block; margin-top: 6px; font-size: 10.5px; color: var(--run); text-transform: uppercase; letter-spacing: 0.06em; }
    .commit { font-family: var(--mono); color: var(--ink); background: #eef0f3; padding: 2px 7px; font-size: 11px; letter-spacing: 0; }

    .empty { padding: 64px 20px; text-align: center; color: var(--muted); }
    .empty-ico { font-family: var(--mono); font-size: 26px; color: var(--faint); margin-bottom: 10px; }
    .empty-title { font-size: 14px; font-weight: 700; color: var(--ink); }
    .empty-sub { font-size: 12.5px; margin-top: 6px; }
    .skeleton td { padding: 16px 14px; }
    .sk-bar { height: 11px; background: linear-gradient(90deg, #eef1f6 25%, #f6f8fb 37%, #eef1f6 63%); background-size: 400% 100%; animation: shimmer 1.3s infinite; }
    @keyframes shimmer { 0% { background-position: 100% 0; } 100% { background-position: -100% 0; } }

    .pagination-wrap { display: flex; justify-content: center; align-items: center; gap: 8px; padding: 24px 0 0; }
    .pagination-btn { border: 1px solid var(--line-strong); background: var(--bg); color: var(--muted); padding: 8px 14px; font-size: 11.5px; font-weight: 600; letter-spacing: 0.03em; cursor: pointer; font-family: var(--mono); transition: all .12s; }
    .pagination-btn:hover:not(:disabled) { background: var(--ink); color: #fff; border-color: var(--ink); }
    .pagination-btn:disabled { opacity: 0.35; cursor: not-allowed; }
    .page-info { font-size: 11.5px; color: var(--muted); font-weight: 600; min-width: 100px; text-align: center; }

    @media (max-width: 720px) {
      .stats { grid-template-columns: repeat(2, 1fr); }
      .stat-card:nth-child(2) { border-left: 1px solid var(--line); }
      .stat-card:nth-child(3) { border-left: none; padding-left: 0; border-top: 1px solid var(--line); }
      .stat-card:nth-child(4) { border-top: 1px solid var(--line); }
      .topbar { flex-direction: column; align-items: flex-start; }
      .topbar-right { justify-content: flex-start; }
    }
"""

_DASHBOARD_BODY = """
  <div class="shell">
    <header class="topbar">
      <div class="brand">
        <img class="logo" id="brandLogo" src="/logo.png" alt="Archer" />
        <div class="brand-text">
          <span class="brand-name">Archer</span>
          <span class="brand-tag">LLVM PR Review Board</span>
        </div>
      </div>
      <div class="topbar-right">
        <span class="live"><span class="live-dot"></span>live</span>
        <a class="nav-link" href="https://github.com/cuhk-s3/Archer" target="_blank" rel="noreferrer"><strong>GitHub</strong> cuhk-s3/Archer</a>
        <a class="nav-link" href="https://cardigan1008.github.io" target="_blank" rel="noreferrer"><strong>By</strong> Yunbo Ni</a>
      </div>
    </header>

    <section class="stats">
      <div class="stat-card"><span class="stat-num" id="statTotal">0</span><span class="stat-label">PRs Tracked</span></div>
      <div class="stat-card run"><span class="stat-num" id="statRunning">0</span><span class="stat-label">Running</span></div>
      <div class="stat-card bug"><span class="stat-num" id="statBugs">0</span><span class="stat-label">Buggy PRs</span></div>
      <div class="stat-card done"><span class="stat-num" id="statDone">0</span><span class="stat-label">Total Reviews</span></div>
    </section>

    <div class="toolbar">
      <div class="search-box">
        <span class="search-ico" aria-hidden="true">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"></circle><path d="m21 21-4.3-4.3"></path></svg>
        </span>
        <input id="searchInput" class="search-input" type="text" placeholder="Search PR number, title, components, commit..." />
        <button id="clearBtn" class="input-clear" type="button" title="Clear">&times;</button>
      </div>
      <div id="statusTabs" class="seg">
        <button class="seg-btn" data-outcome="queued">Queued</button>
        <button class="seg-btn" data-outcome="running">Running</button>
        <button class="seg-btn" data-outcome="bug">Buggy</button>
        <button class="seg-btn" data-outcome="clean">Clean</button>
        <button class="seg-btn" data-outcome="failed">Failed</button>
      </div>
    </div>

    <div class="card">
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Pull Request</th>
              <th>Status</th>
              <th>Bugs</th>
              <th>Updated</th>
            </tr>
          </thead>
          <tbody id="tbody"></tbody>
        </table>
      </div>
      <div class="pagination-wrap">
        <button id="firstBtn" class="pagination-btn" type="button">&laquo; First</button>
        <button id="prevBtn" class="pagination-btn" type="button">&larr; Prev</button>
        <span id="pageInfo" class="page-info"></span>
        <button id="nextBtn" class="pagination-btn" type="button">Next &rarr;</button>
        <button id="lastBtn" class="pagination-btn" type="button">Last &raquo;</button>
      </div>
    </div>
  </div>
"""

# The client script is shared verbatim by both entry points. ``API_BASE`` is
# defined by the host page before this script runs ('' for same-origin backend,
# the configured backend URL for the static frontend).
_DASHBOARD_SCRIPT = """
    const REFRESH_MS = 5000;
    const ITEMS_PER_PAGE = 15;
    let allPrs = [];
    let currentOutcome = '';
    let currentPage = 1;
    let currentFiltered = [];
    let hasLoaded = false;
    let lastRenderKey = '';

    const OUTCOME_META = {
      queued: { label: 'Queued', cls: 'queued' },
      running: { label: 'Running', cls: 'running' },
      bug: { label: 'Buggy', cls: 'bug' },
      clean: { label: 'Clean', cls: 'clean' },
      failed: { label: 'Failed', cls: 'failed' },
      none: { label: 'Pending', cls: 'queued' },
    };

    function esc(v) {
      return (v == null ? '' : String(v)).replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
    }
    function shortSha(sha) { return sha ? String(sha).slice(0, 10) : ''; }
    function outcomeMeta(pr) { return OUTCOME_META[pr.outcome] || OUTCOME_META.none; }

    function formatDate(isoStr) {
      if (!isoStr) return '';
      const d = new Date(isoStr);
      if (isNaN(d.getTime())) return '';
      const p = n => String(n).padStart(2, '0');
      return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
    }

    function updateStats() {
      document.getElementById('statTotal').textContent = allPrs.length;
      document.getElementById('statRunning').textContent = allPrs.filter(p => p.outcome === 'running' || p.outcome === 'queued').length;
      document.getElementById('statBugs').textContent = allPrs.filter(p => (p.bug_count || 0) > 0).length;
      document.getElementById('statDone').textContent = allPrs.reduce((sum, p) => sum + (p.review_count || 0), 0);
    }

    function applyFilters(options = {}) {
      const resetPage = options.resetPage !== false;
      const query = (document.getElementById('searchInput').value || '').trim().toLowerCase();
      currentFiltered = allPrs.filter(p => {
        if (currentOutcome && p.outcome !== currentOutcome) return false;
        if (!query) return true;
        const hay = [String(p.pr_id || ''), p.title || '', (p.components || []).join(' '), p.latest_commit || '', outcomeMeta(p).label].join(' ').toLowerCase();
        return hay.includes(query);
      });
      const totalPages = Math.max(1, Math.ceil(currentFiltered.length / ITEMS_PER_PAGE));
      if (resetPage) currentPage = 1;
      else if (currentPage > totalPages) currentPage = totalPages;
      updateStats();
      renderRows();
    }

    function setOutcomeFilter(outcome) {
      currentOutcome = currentOutcome === outcome ? '' : outcome;
      document.querySelectorAll('#statusTabs .seg-btn').forEach(el => el.classList.toggle('active', el.dataset.outcome === currentOutcome));
      applyFilters({ resetPage: true });
    }

    function renderRows() {
      const tbody = document.getElementById('tbody');
      if (!hasLoaded) {
        tbody.innerHTML = Array.from({ length: 6 }).map(() =>
          '<tr class="skeleton"><td><div class="sk-bar" style="width:80%"></div></td><td><div class="sk-bar" style="width:60%"></div></td><td><div class="sk-bar" style="width:50%"></div></td><td><div class="sk-bar" style="width:70%"></div></td></tr>'
        ).join('');
        lastRenderKey = '';
        updatePaginationControls();
        return;
      }
      if (currentFiltered.length === 0) {
        const msg = allPrs.length === 0
          ? { t: 'No reviews yet', s: 'The dispatcher has not reviewed any PR yet.' }
          : { t: 'No matching results', s: 'Try adjusting your search or filters.' };
        tbody.innerHTML = '<tr><td colspan="4"><div class="empty"><div class="empty-ico">{ }</div><div class="empty-title">' + msg.t + '</div><div class="empty-sub">' + msg.s + '</div></div></td></tr>';
        lastRenderKey = '';
        updatePaginationControls();
        return;
      }

      const start = (currentPage - 1) * ITEMS_PER_PAGE;
      const pagePrs = currentFiltered.slice(start, start + ITEMS_PER_PAGE);

      const rowsHtml = pagePrs.map(p => {
        const outcome = outcomeMeta(p);
        const subBits = [];
        subBits.push(p.version_count + ' commit' + (p.version_count === 1 ? '' : 's'));
        subBits.push(p.review_count + ' review' + (p.review_count === 1 ? '' : 's'));
        let subline = subBits.join(' · ');
        if (p.latest_commit) subline += ' · latest <span class="commit">' + esc(shortSha(p.latest_commit)) + '</span>';

        const prCell = '<div class="pr-header">'
          + '<a class="pr-link" href="https://github.com/llvm/llvm-project/pull/' + p.pr_id + '" target="_blank" rel="noreferrer" onclick="event.stopPropagation()">#' + p.pr_id + '</a>'
          + '<span class="pr-title-text">' + esc(p.title || '(no title)') + '</span></div>'
          + '<div class="subline">' + subline + '</div>'
          + (p.components && p.components.length ? '<div class="tags">' + p.components.map(c => '<span class="tag">' + esc(c) + '</span>').join('') + '</div>' : '');

        const liveNote = p.live ? '<span class="live-note">' + esc(p.live) + '</span>' : '';
        const statusCell = '<span class="pill ' + outcome.cls + '">' + outcome.label + '</span>' + liveNote;

        const bugsCell = (p.bug_count || 0) > 0
          ? '<span class="bug-count">' + p.bug_count + '</span>'
          : '<span class="dash">—</span>';

        const dateStr = formatDate(p.updated_at);
        return '<tr class="pr-row" data-pr="' + p.pr_id + '">'
          + '<td>' + prCell + '</td><td>' + statusCell + '</td><td>' + bugsCell + '</td>'
          + '<td><span class="date-chip">' + dateStr + '</span></td></tr>';
      }).join('');

      // Skip the DOM write when the rendered markup is identical to what is
      // already on screen. This removes the flicker/jump the 5s poll caused by
      // blindly rebuilding tbody.innerHTML every refresh.
      const renderKey = String(currentPage) + '|' + rowsHtml;
      if (renderKey !== lastRenderKey) {
        tbody.innerHTML = rowsHtml;
        lastRenderKey = renderKey;
      }

      updatePaginationControls();
    }

    function updatePaginationControls() {
      const totalPages = Math.max(1, Math.ceil(currentFiltered.length / ITEMS_PER_PAGE));
      document.getElementById('pageInfo').textContent = 'Page ' + currentPage + ' / ' + totalPages;
      document.getElementById('firstBtn').disabled = currentPage <= 1;
      document.getElementById('prevBtn').disabled = currentPage <= 1;
      document.getElementById('nextBtn').disabled = currentPage >= totalPages;
      document.getElementById('lastBtn').disabled = currentPage >= totalPages;
    }

    async function refreshPrs() {
      try {
        const resp = await fetch(API_BASE + '/api/prs');
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const data = await resp.json();
        allPrs = (data && data.prs) || [];
        hasLoaded = true;
        applyFilters({ resetPage: false });
      } catch (err) {
        hasLoaded = true;
        renderRows();
      }
    }

    document.getElementById('searchInput').addEventListener('input', () => applyFilters({ resetPage: true }));
    document.getElementById('statusTabs').addEventListener('click', ev => {
      const btn = ev.target.closest('.seg-btn');
      if (btn) setOutcomeFilter(btn.dataset.outcome || '');
    });
    document.getElementById('clearBtn').addEventListener('click', () => {
      document.getElementById('searchInput').value = '';
      currentOutcome = '';
      document.querySelectorAll('#statusTabs .seg-btn').forEach(el => el.classList.remove('active'));
      applyFilters({ resetPage: true });
    });
    document.getElementById('tbody').addEventListener('click', ev => {
      const row = ev.target.closest('tr.pr-row');
      if (!row) return;
      const prId = Number(row.dataset.pr);
      if (prId) window.location.href = API_BASE + '/pr/' + prId;
    });
    document.getElementById('firstBtn').addEventListener('click', () => { if (currentPage > 1) { currentPage = 1; renderRows(); } });
    document.getElementById('prevBtn').addEventListener('click', () => { if (currentPage > 1) { currentPage -= 1; renderRows(); } });
    document.getElementById('nextBtn').addEventListener('click', () => {
      const totalPages = Math.max(1, Math.ceil(currentFiltered.length / ITEMS_PER_PAGE));
      if (currentPage < totalPages) { currentPage += 1; renderRows(); }
    });
    document.getElementById('lastBtn').addEventListener('click', () => {
      const totalPages = Math.max(1, Math.ceil(currentFiltered.length / ITEMS_PER_PAGE));
      if (currentPage < totalPages) { currentPage = totalPages; renderRows(); }
    });

    renderRows();
    setInterval(refreshPrs, REFRESH_MS);
    refreshPrs();
"""


def build_dashboard_html() -> str:
  """Backend-served, same-origin dashboard (relative API base)."""
  return (
    '<!doctype html>\n<html lang="en">\n<head>\n'
    '  <meta charset="UTF-8" />\n'
    '  <meta name="viewport" content="width=device-width, initial-scale=1" />\n'
    "  <title>Archer Review Board</title>\n"
    "  <style>" + _DASHBOARD_STYLE + "</style>\n"
    "</head>\n<body>\n"
    + _DASHBOARD_BODY
    + "  <script>\n    const API_BASE = '';\n"
    + _DASHBOARD_SCRIPT
    + "  </script>\n</body>\n</html>"
  )


def detect_bug_found(stats_path: Optional[str]) -> Optional[bool]:
  if not stats_path:
    return None
  try:
    data = json.loads(Path(stats_path).read_text())
  except Exception:
    return None

  bugs = data.get("bugs") if isinstance(data, dict) else None

  # A failed/errored run has no meaningful bug verdict: an empty "bugs" list here
  # would otherwise be shown as "none" (no bug), which is misleading.
  if isinstance(data, dict) and data.get("error") and not bugs:
    return None

  if isinstance(bugs, list):
    return len(bugs) > 0
  return None
