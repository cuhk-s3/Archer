import json
from pathlib import Path
from typing import Optional


def build_dashboard_html() -> str:
  return """<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Archer Review Board</title>
  <style>
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
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      background: var(--bg);
      font-family: var(--mono);
      font-size: 13px;
      -webkit-font-smoothing: antialiased;
    }
    .shell { max-width: 1080px; margin: 0 auto; padding: 0 24px 64px; }

    /* Masthead */
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

    /* Stats — linear, hairline separated, no cards */
    .stats { display: grid; grid-template-columns: repeat(4, 1fr); border-bottom: 1px solid var(--line); }
    .stat-card { padding: 15px 18px 14px; border-left: 1px solid var(--line); }
    .stat-card:first-child { border-left: none; padding-left: 8px; }
    .stat-num { font-size: 24px; font-weight: 700; line-height: 1; letter-spacing: -0.02em; }
    .stat-card.run .stat-num { color: var(--run); }
    .stat-card.bug .stat-num { color: var(--err); }
    .stat-card.done .stat-num { color: var(--ok); }
    .stat-label { display: block; margin-top: 8px; font-size: 10.5px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.12em; font-weight: 600; }

    /* Toolbar */
    .toolbar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin: 24px 0 0; }
    .search-box { display: flex; align-items: center; flex: 1 1 260px; min-width: 220px; height: 38px; background: var(--bg); border: 1px solid var(--line-strong); padding: 0 6px 0 12px; transition: border-color .15s; }
    .search-box:focus-within { border-color: var(--ink); }
    .search-ico { color: var(--faint); flex: 0 0 auto; display: flex; }
    .search-input { flex: 1; min-width: 0; border: none; background: transparent; height: 100%; padding: 0 8px; font-size: 13px; color: var(--ink); font-family: var(--mono); }
    .search-input:focus { outline: none; }
    .search-input::placeholder { color: var(--faint); }
    .input-clear { border: none; background: transparent; width: 28px; height: 28px; color: var(--faint); font-size: 17px; line-height: 1; cursor: pointer; }
    .input-clear:hover { color: var(--ink); }
    .seg { display: inline-flex; border: 1px solid var(--line-strong); }
    .seg-btn { border: none; border-left: 1px solid var(--line-strong); background: transparent; color: var(--muted); padding: 0 14px; height: 38px; font-size: 11.5px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; cursor: pointer; font-family: var(--mono); transition: background .12s, color .12s; }
    .seg-btn:first-child { border-left: none; }
    .seg-btn:hover { color: var(--ink); }
    .seg-btn.active { background: var(--ink); color: #fff; }

    /* Table — no card, hairline rows */
    .card { border-top: 1px solid var(--line); margin-top: 20px; }
    .table-wrap { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; min-width: 620px; table-layout: fixed; }
    thead th { color: var(--muted); font-weight: 700; font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.12em; text-align: left; padding: 13px 14px; border-bottom: 1px solid var(--line-strong); }
    thead th:first-child { padding-left: 8px; }
    tbody td { border-bottom: 1px solid var(--line); padding: 15px 14px; vertical-align: top; font-size: 13px; }
    tbody td:first-child { padding-left: 8px; }
    tbody tr { transition: background .12s; }
    tbody tr:hover { background: #fafbfc; }
    th:nth-child(1), td:nth-child(1) { width: 50%; }
    th:nth-child(2), td:nth-child(2) { width: 17%; }
    th:nth-child(3), td:nth-child(3) { width: 17%; }
    th:nth-child(4), td:nth-child(4) { width: 16%; }

    .pr-header { line-height: 1.5; display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px; }
    .pr-link { color: var(--accent); font-size: 12.5px; font-weight: 700; text-decoration: none; }
    .pr-link:hover { text-decoration: underline; }
    .pr-title-text { color: var(--ink); font-size: 12.5px; font-weight: 500; }
    .tags { margin-top: 8px; display: flex; gap: 6px; flex-wrap: wrap; }
    .tag { background: transparent; color: var(--muted); border: 1px solid var(--line-strong); padding: 1px 7px; font-size: 10.5px; font-weight: 600; }

    /* Square status marker */
    .pill { display: inline-flex; align-items: center; gap: 7px; font-weight: 600; font-size: 11px; letter-spacing: 0.06em; padding: 4px 9px; white-space: nowrap; text-transform: uppercase; }
    .pill::before { content: ""; width: 7px; height: 7px; background: currentColor; }
    .pill.queued { color: var(--queue); background: var(--queue-bg); }
    .pill.running { color: var(--run); background: var(--run-bg); }
    .pill.running::before { animation: pulse 1.6s infinite; }
    .pill.bug { color: var(--err); background: var(--err-bg); }
    .pill.clean { color: var(--ok); background: var(--ok-bg); }
    .pill.failed { color: var(--faint); background: var(--queue-bg); }

    .art-links { display: flex; gap: 14px; flex-wrap: wrap; }
    .art-link { color: var(--accent); font-size: 12px; font-weight: 600; text-decoration: none; letter-spacing: 0.03em; }
    .art-link:hover { text-decoration: underline; }
    .dash { color: var(--faint); }
    .date-chip { display: inline-block; font-size: 12px; color: var(--muted); white-space: nowrap; }

    /* Empty / loading */
    .empty { padding: 64px 20px; text-align: center; color: var(--muted); }
    .empty-ico { font-family: var(--mono); font-size: 26px; color: var(--faint); margin-bottom: 10px; }
    .empty-title { font-size: 14px; font-weight: 700; color: var(--ink); }
    .empty-sub { font-size: 12.5px; margin-top: 6px; }
    .skeleton td { padding: 16px 14px; }
    .sk-bar { height: 11px; background: linear-gradient(90deg, #eef1f6 25%, #f6f8fb 37%, #eef1f6 63%); background-size: 400% 100%; animation: shimmer 1.3s infinite; }
    @keyframes shimmer { 0% { background-position: 100% 0; } 100% { background-position: -100% 0; } }

    /* Pagination */
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
  </style>
</head>
<body>
  <div class="shell">
    <header class="topbar">
      <div class="brand">
        <img class="logo" src="/logo.png" alt="Archer" />
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
      <div class="stat-card bug"><span class="stat-num" id="statBugs">0</span><span class="stat-label">Bugs Found</span></div>
      <div class="stat-card done"><span class="stat-num" id="statDone">0</span><span class="stat-label">Completed</span></div>
    </section>

    <div class="toolbar">
      <div class="search-box">
        <span class="search-ico" aria-hidden="true">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"></circle><path d="m21 21-4.3-4.3"></path></svg>
        </span>
        <input id="searchInput" class="search-input" type="text" placeholder="Search PR number, title, components..." />
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
              <th>Details</th>
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

  <script>
    let allJobs = [];
    let currentOutcome = '';
    let currentPage = 1;
    const ITEMS_PER_PAGE = 15;
    let currentFiltered = [];
    let hasLoaded = false;

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

    // Collapse the two-axis (state + bug) model into a single clear outcome.
    function outcomeMeta(job) {
      const s = job.status || '';
      if (s === 'queued') return { key: 'queued', label: 'Queued', cls: 'queued' };
      if (s === 'running') return { key: 'running', label: 'Running', cls: 'running' };
      if (s === 'succeeded') {
        if (job.bug_found === true) return { key: 'bug', label: 'Buggy', cls: 'bug' };
        return { key: 'clean', label: 'Clean', cls: 'clean' };
      }
      return { key: 'failed', label: 'Failed', cls: 'failed' };
    }

    function jobSortTimestamp(job) {
      const ts = Date.parse(job.created_at || job.updated_at || '');
      return Number.isNaN(ts) ? 0 : ts;
    }

    function collapseJobsByPr(jobs) {
      const latestByPr = new Map();
      for (const job of jobs) {
        const prId = String(job.pr_id || '');
        if (!prId) continue;

        const normalizedJob = {
          ...job,
          components: Array.isArray(job.components) ? [...job.components] : [],
        };

        const existing = latestByPr.get(prId);
        if (!existing) {
          latestByPr.set(prId, normalizedJob);
          continue;
        }

        const normalizedExisting = {
          ...existing,
          components: Array.isArray(existing.components)
            ? [...existing.components]
            : [],
        };
        const useNewJob = jobSortTimestamp(normalizedJob) > jobSortTimestamp(normalizedExisting);
        const latest = useNewJob ? normalizedJob : normalizedExisting;
        const older = useNewJob ? normalizedExisting : normalizedJob;

        if (!latest.title && older.title) latest.title = older.title;
        if (!latest.author && older.author) latest.author = older.author;
        if ((!latest.components || !latest.components.length) && older.components && older.components.length) {
          latest.components = [...older.components];
        }

        latestByPr.set(prId, latest);
      }
      return Array.from(latestByPr.values());
    }

    function updateStats() {
      const total = allJobs.length;
      const running = allJobs.filter(j => (j.status || '') === 'running').length;
      const bugs = allJobs.filter(j => j.bug_found === true).length;
      const done = allJobs.filter(j => (j.status || '') === 'succeeded').length;
      document.getElementById('statTotal').textContent = total;
      document.getElementById('statRunning').textContent = running;
      document.getElementById('statBugs').textContent = bugs;
      document.getElementById('statDone').textContent = done;
    }

    function applyFilters(options = {}) {
      const resetPage = options.resetPage !== false;
      const query = (document.getElementById('searchInput').value || '').trim().toLowerCase();
      currentFiltered = allJobs.filter(j => {
        if (currentOutcome && outcomeMeta(j).key !== currentOutcome) return false;
        if (!query) return true;
        const hay = [String(j.pr_id || ''), j.title || '', (j.components || []).join(' '), outcomeMeta(j).label].join(' ').toLowerCase();
        return hay.includes(query);
      });
      const totalPages = Math.ceil(currentFiltered.length / ITEMS_PER_PAGE) || 1;
      if (resetPage) {
        currentPage = 1;
      } else if (currentPage > totalPages) {
        currentPage = totalPages;
      }
      updateStats();
      renderRows();
      updatePaginationControls();
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
        return;
      }

      if (currentFiltered.length === 0) {
        const msg = allJobs.length === 0
          ? { t: 'No runs yet', s: 'The dispatcher has not queued any PR reviews.' }
          : { t: 'No matching results', s: 'Try adjusting your search or filters.' };
        tbody.innerHTML = '<tr><td colspan="4"><div class="empty"><div class="empty-ico">{ }</div><div class="empty-title">' + msg.t + '</div><div class="empty-sub">' + msg.s + '</div></div></td></tr>';
        return;
      }

      const start = (currentPage - 1) * ITEMS_PER_PAGE;
      const end = start + ITEMS_PER_PAGE;
      const pageJobs = currentFiltered.slice(start, end);

      tbody.innerHTML = pageJobs.map(j => {
        const outcome = outcomeMeta(j);
        const prCell = '<div class="pr-header"><a class="pr-link" href="https://github.com/llvm/llvm-project/pull/' + j.pr_id + '" target="_blank">#' + j.pr_id + '</a><span class="pr-title-text">' + esc(j.title || '(no title)') + '</span></div>'
          + (j.components && j.components.length ? '<div class="tags">' + j.components.map(c => '<span class="tag">' + esc(c) + '</span>').join('') + '</div>' : '');
        const statusCell = '<span class="pill ' + outcome.cls + '">' + outcome.label + '</span>';
        // Only completed runs (buggy/clean) have a meaningful review + trace.
        const links = [];
        if (outcome.key === 'bug' || outcome.key === 'clean') {
          if (j.review_path) links.push('<a class="art-link" href="/artifact?path=' + encodeURIComponent(j.review_path) + '" target="_blank">Review</a>');
          if (j.history_path) links.push('<a class="art-link" href="/artifact?path=' + encodeURIComponent(j.history_path) + '" target="_blank">Trace</a>');
        }
        const detailsCell = links.length ? '<div class="art-links">' + links.join('') + '</div>' : '<span class="dash">—</span>';
        const dateStr = formatDate(j.updated_at);
        return '<tr><td>' + prCell + '</td><td>' + statusCell + '</td><td>' + detailsCell + '</td><td><span class="date-chip">' + dateStr + '</span></td></tr>';
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
        const jobs = (await resp.json()).jobs || [];
        allJobs = collapseJobsByPr(jobs);
        hasLoaded = true;
        applyFilters({ resetPage: false });
      } catch (err) {
        document.getElementById('pageInfo').textContent = 'Error: ' + err;
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

    renderRows();
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

  # A failed/errored run has no meaningful bug verdict: an empty "bugs" list here
  # would otherwise be shown as "none" (no bug), which is misleading.
  if isinstance(data, dict) and data.get("error") and not bugs:
    return None

  if isinstance(bugs, list):
    return len(bugs) > 0
  return None
