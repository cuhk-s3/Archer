import json
from pathlib import Path
from typing import Optional


def build_dashboard_html() -> str:
  return """<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Archer Live Review Board</title>
  <style>
    :root {
      --ink: #1f2d3d;
      --sub: #60758d;
      --line: #eaf0f7;
      --brand-1: #2f6fad;
      --brand-2: #6aa6d6;
      --ok: #1f9956;
      --err: #d64545;
      --run: #c7821f;
      --queue: #6e7d8c;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      background: #ffffff;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif;
      padding: 12px 14px;
    }
    .shell { max-width: 900px; margin: 0 auto; }
    .brand-strip { height: 4px; background: linear-gradient(90deg, var(--brand-1), var(--brand-2)); border-radius: 0; margin-bottom: 8px; }
    .head { padding: 10px 12px; display: flex; justify-content: space-between; align-items: flex-end; gap: 10px; }
    .head-main { min-width: 0; }
    .head-badge { font-size: 11px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: #35516c; background: #eef5fc; padding: 4px 8px; border-radius: 0; }
    .title { margin: 0; font-size: clamp(24px, 3vw, 36px); font-weight: 700; line-height: 1; }
    .sub { margin-top: 8px; color: var(--sub); font-size: 13px; }
    .toolbar { padding: 8px 12px; }
    .query-wrap { width: 100%; overflow-x: auto; }
    .query-row { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 8px; align-items: center; min-width: 980px; }
    .filter-stack { display: flex; align-items: center; gap: 8px; flex-wrap: nowrap; white-space: nowrap; }
    .search-box { display: flex; align-items: center; border: 1px solid #e6eef7; border-radius: 0; background: #f7fbff; height: 34px; overflow: hidden; min-width: 240px; }
    .search-input { min-width: 0; width: 100%; border: none; height: 32px; padding: 0 10px; background: transparent; font-size: 14px; color: var(--ink); }
    .search-input:focus { outline: none; }
    .input-clear { border: none; border-left: 1px solid #e6eef7; background: #f7fbff; width: 34px; height: 100%; padding: 0; color: #5e7388; font-size: 16px; line-height: 1; cursor: pointer; }
    .input-clear:hover { background: #eef6ff; }
    .status-tabs { display: inline-flex; border: 1px solid #e6eef7; border-radius: 0; overflow: hidden; background: #f7fbff; height: 34px; flex: 0 0 auto; }
    .status-tab { border: none; border-right: 1px solid #e6eef7; background: transparent; color: #4f667d; padding: 0 12px; font-size: 12px; font-weight: 600; height: 100%; cursor: pointer; }
    .status-tab:last-child { border-right: none; }
    .status-tab.active { background: #eaf3fd; color: #2c5071; }
    #bugTabs .status-tab.active { background: #eaf3fd; color: #2c5071; }
    .status { color: var(--sub); min-height: 20px; font-size: 12px; padding: 4px 12px; }
    .table-wrap { overflow: auto; }
    table { width: 100%; border-collapse: collapse; min-width: 750px; table-layout: fixed; }
    th, td { border-bottom: 1px solid var(--line); padding: 6px 10px; text-align: left; vertical-align: top; font-size: 13px; }
    th { color: #2a435a; font-weight: 700; font-size: 13px; position: sticky; top: 0; background: #f7fbff; letter-spacing: 0.02em; }
    th:nth-child(1), td:nth-child(1) { width: 40%; }
    th:nth-child(2), td:nth-child(2) { width: 10%; }
    th.state-col, td.state-col { text-align: left; }
    td.state-col .pill { justify-content: flex-start; padding-left: 0; }
    th:nth-child(3), td:nth-child(3) { width: 8%; }
    th:nth-child(4), td:nth-child(4) { width: 8%; }
    th:nth-child(5), td:nth-child(5) { width: 8%; }
    th:nth-child(6), td:nth-child(6) { width: 16%; }
    tbody tr:hover { background: #fbfdff; }
    .pagination-wrap { display: flex; justify-content: center; align-items: center; gap: 12px; padding: 12px 12px; min-height: 40px; }
    .pagination-btn { border: 1px solid #e6eef7; background: #f7fbff; color: #4f667d; padding: 6px 12px; font-size: 12px; font-weight: 600; border-radius: 0; cursor: pointer; }
    .pagination-btn:hover:not(:disabled) { background: #eef6ff; }
    .pagination-btn:disabled { opacity: 0.4; cursor: not-allowed; }
    .page-info { font-size: 12px; color: #60758d; font-weight: 600; min-width: 60px; text-align: center; }
    .pill { border-radius: 0; padding: 3px 8px; display: inline-flex; font-weight: 700; font-size: 13px; gap: 4px; align-items: center; text-transform: lowercase; }
    .pill::before { content: '#'; width: auto; height: auto; border-radius: 0; font-weight: 800; }
    .queued { color: #6e7d8c; }
    .running { color: #c7821f; }
    .tokenlimit { color: #8a5a21; }
    .done { color: #1f9956; }
    .failed { color: #d64545; }
    .bug-pill { border-radius: 0; padding: 2px 6px; font-size: 13px; font-weight: 700; display: inline-block; }
    .bug-yes { background: #fdeaea; color: #bb2f2f; }
    .bug-no { background: #e9f7ef; color: #1f9956; }
    .bug-unknown { background: #f2f5f8; color: #6e7d8c; }
    .tags { margin-top: 2px; display: flex; gap: 4px; flex-wrap: wrap; }
    .tag { background: #eef5fc; color: #2f6fad; padding: 2px 6px; font-size: 12px; border-radius: 0; }
    .date-chip { display: inline-block; padding: 2px 8px; background: #f2f6fb; color: #4e657b; border-radius: 0; font-size: 12px; white-space: nowrap; }
    .pr-header { line-height: 1.4; }
    .pr-title-text { color: #1f2d3d; font-size: 13px; font-weight: 600; }
    .pr-link { color: #1750a6; font-size: 13px; font-weight: 700; display: inline; margin-right: 8px; }
    a { color: #1750a6; text-decoration: none; font-weight: 700; }
    a:hover { text-decoration: underline; }
    @media (max-width: 750px) { .query-row { min-width: 750px; } }
  </style>
</head>
<body>
  <div class="shell">
    <div class="brand-strip"></div>
    <div class="head">
      <div class="head-main">
        <h1 class="title">Archer Review Board</h1>
        <div class="sub">Live tracking for PR review progress.</div>
      </div>
      <div class="head-badge">Archer</div>
    </div>

    <div class="toolbar">
      <div class="query-wrap">
        <div class="query-row">
          <div class="filter-stack">
            <div id="statusTabs" class="status-tabs">
              <button class="status-tab" data-status="running">Running</button>
              <button class="status-tab" data-status="queued">Queued</button>
              <button class="status-tab" data-status="succeeded">Done</button>
              <button class="status-tab" data-status="failed">Failed</button>
            </div>
            <div id="bugTabs" class="status-tabs">
              <button class="status-tab" data-bug="found">Found</button>
              <button class="status-tab" data-bug="none">None</button>
              <button class="status-tab" data-bug="unknown">Unknown</button>
            </div>
          </div>
          <div class="search-box">
            <input id="searchInput" class="search-input" type="text" placeholder="Search PR, title, components..." />
            <button id="clearBtn" class="input-clear" type="button">×</button>
          </div>
        </div>
      </div>
    </div>

    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>PR</th>
            <th class="state-col">State</th>
            <th>Bug</th>
            <th>Review</th>
            <th>History</th>
            <th>Date</th>
          </tr>
        </thead>
        <tbody id="tbody"></tbody>
      </table>
    </div>

    <div class="pagination-wrap">
      <button id="firstBtn" class="pagination-btn" type="button">« First</button>
      <button id="prevBtn" class="pagination-btn" type="button">← Previous</button>
      <span id="pageInfo" class="page-info"></span>
      <button id="nextBtn" class="pagination-btn" type="button">Next →</button>
      <button id="lastBtn" class="pagination-btn" type="button">Last »</button>
    </div>
  </div>

  <script>
    let allJobs = [];
    let currentStatus = '';
    let currentBug = '';
    let currentPage = 1;
    const ITEMS_PER_PAGE = 15;
    let currentFiltered = [];

    function esc(v) {
      return (v || '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
    }

    function formatDate(isoStr) {
      if (!isoStr) return '';
      const d = new Date(isoStr);
      const y = d.getFullYear();
      const m = String(d.getMonth() + 1).padStart(2, '0');
      const day = String(d.getDate()).padStart(2, '0');
      const h = String(d.getHours()).padStart(2, '0');
      const min = String(d.getMinutes()).padStart(2, '0');
      return y + '-' + m + '-' + day + ' ' + h + ':' + min;
    }

    function stateMeta(status) {
      if (status === 'succeeded') return { label: 'done', cls: 'done' };
      if (status === 'running') return { label: 'running', cls: 'running' };
      if (status === 'tokenlimit') return { label: 'tokenlimit', cls: 'tokenlimit' };
      if (status === 'failed') return { label: 'failed', cls: 'failed' };
      if (status === 'queued') return { label: 'queued', cls: 'queued' };
      return { label: 'unknown', cls: 'queued' };
    }

    function matchesBugFilter(job) {
      if (!currentBug) return true;
      if (currentBug === 'found') return job.bug_found === true;
      if (currentBug === 'none') return job.bug_found === false;
      if (currentBug === 'unknown') return job.bug_found == null;
      return true;
    }

    function applyFilters(options = {}) {
      const resetPage = options.resetPage !== false;
      const query = (document.getElementById('searchInput').value || '').trim().toLowerCase();
      currentFiltered = allJobs.filter(j => {
        if (currentStatus && (j.status || '') !== currentStatus) return false;
        if (!matchesBugFilter(j)) return false;
        if (!query) return true;
        const bugText = j.bug_found === true ? 'bug yes found' : (j.bug_found === false ? 'bug no not found' : 'bug unknown');
        const hay = [String(j.pr_id || ''), j.title || '', (j.components || []).join(' '), bugText].join(' ').toLowerCase();
        return hay.includes(query);
      });
      const totalPages = Math.ceil(currentFiltered.length / ITEMS_PER_PAGE) || 1;
      if (resetPage) {
        currentPage = 1;
      } else if (currentPage > totalPages) {
        currentPage = totalPages;
      }
      renderRows();
      updatePaginationControls();
    }

    function setStatusFilter(status) {
      currentStatus = currentStatus === status ? '' : status;
      document.querySelectorAll('#statusTabs .status-tab').forEach(el => el.classList.toggle('active', el.dataset.status === currentStatus));
      applyFilters({ resetPage: true });
    }

    function setBugFilter(bug) {
      currentBug = currentBug === bug ? '' : bug;
      document.querySelectorAll('#bugTabs .status-tab').forEach(el => el.classList.toggle('active', el.dataset.bug === currentBug));
      applyFilters({ resetPage: true });
    }

    function renderRows() {
      const tbody = document.getElementById('tbody');
      const start = (currentPage - 1) * ITEMS_PER_PAGE;
      const end = start + ITEMS_PER_PAGE;
      const pageJobs = currentFiltered.slice(start, end);

      tbody.innerHTML = pageJobs.map(j => {
        const state = stateMeta(j.status);
        const prCell = '<div class="pr-header"><a class="pr-link" href="https://github.com/llvm/llvm-project/pull/' + j.pr_id + '" target="_blank">#' + j.pr_id + '</a><span class="pr-title-text">' + esc(j.title || '(no title)') + '</span></div>'
          + (j.components && j.components.length ? '<div class="tags">' + j.components.map(c => '<span class="tag">' + esc(c) + '</span>').join('') + '</div>' : '');
        const stateCell = '<span class="pill ' + esc(state.cls) + '">' + esc(state.label) + '</span>';
        const bugCell = j.bug_found === true
          ? '<span class="bug-pill bug-yes">found</span>'
          : (j.bug_found === false
            ? '<span class="bug-pill bug-no">none</span>'
            : '<span class="bug-pill bug-unknown">unknown</span>');
        const reviewLink = j.review_path ? '<a href="/artifact?path=' + encodeURIComponent(j.review_path) + '" target="_blank">view</a>' : '—';
        const historyLink = j.history_path ? '<a href="/artifact?path=' + encodeURIComponent(j.history_path) + '" target="_blank">view</a>' : '—';
        const dateStr = formatDate(j.updated_at);
        return '<tr><td>' + prCell + '</td><td class="state-col">' + stateCell + '</td><td>' + bugCell + '</td><td>' + reviewLink + '</td><td>' + historyLink + '</td><td><span class="date-chip">' + dateStr + '</span></td></tr>';
      }).join('');
    }

    function updatePaginationControls() {
      const totalPages = Math.ceil(currentFiltered.length / ITEMS_PER_PAGE) || 1;
      const firstBtn = document.getElementById('firstBtn');
      const prevBtn = document.getElementById('prevBtn');
      const nextBtn = document.getElementById('nextBtn');
      const lastBtn = document.getElementById('lastBtn');
      const pageInfo = document.getElementById('pageInfo');

      pageInfo.textContent = 'Page ' + currentPage + ' / ' + totalPages;
      firstBtn.disabled = currentPage <= 1;
      prevBtn.disabled = currentPage <= 1;
      nextBtn.disabled = currentPage >= totalPages;
      lastBtn.disabled = currentPage >= totalPages;
    }

    async function refreshJobs() {
      try {
        const resp = await fetch('/api/jobs');
        if (!resp.ok) throw new Error('Failed');
        allJobs = (await resp.json()).jobs || [];
        applyFilters({ resetPage: false });
      } catch (err) {
        document.getElementById('pageInfo').textContent = 'Error: ' + err;
      }
    }

    document.getElementById('searchInput').addEventListener('input', () => applyFilters({ resetPage: true }));
    document.getElementById('statusTabs').addEventListener('click', ev => {
      if (ev.target.classList.contains('status-tab')) setStatusFilter(ev.target.dataset.status || '');
    });
    document.getElementById('bugTabs').addEventListener('click', ev => {
      if (ev.target.classList.contains('status-tab')) setBugFilter(ev.target.dataset.bug || '');
    });
    document.getElementById('clearBtn').addEventListener('click', () => {
      document.getElementById('searchInput').value = '';
      currentStatus = '';
      currentBug = '';
      document.querySelectorAll('#statusTabs .status-tab').forEach(el => el.classList.remove('active'));
      document.querySelectorAll('#bugTabs .status-tab').forEach(el => el.classList.remove('active'));
      applyFilters({ resetPage: true });
      document.getElementById('searchInput').focus();
    });
    document.getElementById('firstBtn').addEventListener('click', () => {
      if (currentPage > 1) {
        currentPage = 1;
        renderRows();
        updatePaginationControls();
      }
    });
    document.getElementById('prevBtn').addEventListener('click', () => {
      if (currentPage > 1) {
        currentPage--;
        renderRows();
        updatePaginationControls();
      }
    });
    document.getElementById('nextBtn').addEventListener('click', () => {
      const totalPages = Math.ceil(currentFiltered.length / ITEMS_PER_PAGE) || 1;
      if (currentPage < totalPages) {
        currentPage++;
        renderRows();
        updatePaginationControls();
      }
    });
    document.getElementById('lastBtn').addEventListener('click', () => {
      const totalPages = Math.ceil(currentFiltered.length / ITEMS_PER_PAGE) || 1;
      if (currentPage < totalPages) {
        currentPage = totalPages;
        renderRows();
        updatePaginationControls();
      }
    });

    setInterval(() => refreshJobs(), 5000);
    refreshJobs();
  </script>
</body>
</html>"""


def detect_bug_found(stats_path: Optional[str]) -> Optional[bool]:
  if not stats_path:
    return None
  try:
    data = json.loads(Path(stats_path).read_text())
  except Exception:
    return None

  bugs = data.get("bugs") if isinstance(data, dict) else None
  if isinstance(bugs, list):
    return len(bugs) > 0
  return None
