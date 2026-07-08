"""SQLite schema for the Archer review store.

Design goals:
  - PR-centric: one row per PR in ``prs``.
  - Multi-commit-version: one row per commit version in ``pr_versions``,
    uniquely keyed by ``(pr_id, fix_commit)``. The commit SHA (not open/closed
    state) is what identifies a version. ``state`` is kept only as metadata.
  - Bug-linked: ``bugs`` reference both the ``review`` run that found them and
    the ``pr_version`` they belong to, and carry enough info (repro_kind / args /
    call_instr / original_ir) to be re-run on any build (baseline or a newer
    version) for regression / patch-specificity checks.
"""

SCHEMA_VERSION = 1

DDL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT
);

CREATE TABLE IF NOT EXISTS prs (
  pr_id             INTEGER PRIMARY KEY,
  pr_url            TEXT    NOT NULL DEFAULT '',
  title             TEXT    NOT NULL DEFAULT '',
  author            TEXT    NOT NULL DEFAULT '',
  components        TEXT    NOT NULL DEFAULT '[]',   -- json array
  labels            TEXT    NOT NULL DEFAULT '[]',   -- json array
  description       TEXT    NOT NULL DEFAULT '',
  knowledge_cutoff  TEXT    NOT NULL DEFAULT '',
  state             TEXT    NOT NULL DEFAULT '',     -- open/closed, metadata only
  latest_version_id INTEGER,
  created_at        TEXT    NOT NULL,
  updated_at        TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS pr_versions (
  id                      INTEGER PRIMARY KEY AUTOINCREMENT,
  pr_id                   INTEGER NOT NULL REFERENCES prs(pr_id) ON DELETE CASCADE,
  fix_commit              TEXT    NOT NULL,          -- head sha: identifies the version
  base_commit             TEXT    NOT NULL DEFAULT '',
  patch                   TEXT    NOT NULL DEFAULT '',
  tests                   TEXT    NOT NULL DEFAULT '[]',   -- json
  patch_location_lineno   TEXT    NOT NULL DEFAULT '{}',   -- json
  patch_location_funcname TEXT    NOT NULL DEFAULT '{}',   -- json
  comments                TEXT    NOT NULL DEFAULT '[]',   -- json
  state                   TEXT    NOT NULL DEFAULT '',     -- state at extraction time
  seq                     INTEGER NOT NULL DEFAULT 1,      -- 1-based ordering per PR
  created_at              TEXT    NOT NULL,
  UNIQUE(pr_id, fix_commit)
);

CREATE TABLE IF NOT EXISTS reviews (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  pr_id          INTEGER NOT NULL,
  version_id     INTEGER NOT NULL REFERENCES pr_versions(id) ON DELETE CASCADE,
  fix_commit     TEXT    NOT NULL DEFAULT '',
  status         TEXT    NOT NULL DEFAULT 'queued',  -- queued/running/succeeded/failed/tokenlimit/skipped
  skipped_reason TEXT,
  strategies     TEXT    NOT NULL DEFAULT '[]',      -- json
  reason_thou    TEXT,
  report         TEXT,
  chat_rounds    INTEGER NOT NULL DEFAULT 0,
  phase1_round   INTEGER NOT NULL DEFAULT 0,
  phase2_round   INTEGER NOT NULL DEFAULT 0,
  input_tokens   INTEGER NOT NULL DEFAULT 0,
  output_tokens  INTEGER NOT NULL DEFAULT 0,
  cached_tokens  INTEGER NOT NULL DEFAULT 0,
  total_tokens   INTEGER NOT NULL DEFAULT 0,
  chat_cost      REAL    NOT NULL DEFAULT 0.0,
  total_time_sec REAL    NOT NULL DEFAULT 0.0,
  error          TEXT,
  errmsg         TEXT,
  traceback      TEXT,
  history        TEXT,                                -- json chat history (nullable)
  created_at     TEXT    NOT NULL,
  finished_at    TEXT
);

CREATE TABLE IF NOT EXISTS bugs (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  pr_id               INTEGER NOT NULL,
  version_id          INTEGER NOT NULL REFERENCES pr_versions(id) ON DELETE CASCADE,
  review_id           INTEGER REFERENCES reviews(id) ON DELETE SET NULL,
  repro_kind          TEXT    NOT NULL DEFAULT 'verify',  -- verify/trans/difftest
  original_ir         TEXT,
  transformed_ir      TEXT,
  args                TEXT,                                -- opt args (reproducer)
  call_instr          TEXT,                                -- difftest call instr (nullable)
  log                 TEXT,
  thoughts            TEXT,
  baseline_checked    INTEGER NOT NULL DEFAULT 0,
  baseline_triggered  INTEGER,                             -- nullable until checked
  non_patch_specific  INTEGER NOT NULL DEFAULT 0,          -- baseline also triggered
  status              TEXT    NOT NULL DEFAULT 'active',   -- active/fixed
  fixed_in_version_id INTEGER,
  created_at          TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_versions_pr   ON pr_versions(pr_id);
CREATE INDEX IF NOT EXISTS idx_reviews_pr    ON reviews(pr_id);
CREATE INDEX IF NOT EXISTS idx_reviews_ver   ON reviews(version_id);
CREATE INDEX IF NOT EXISTS idx_bugs_pr       ON bugs(pr_id);
CREATE INDEX IF NOT EXISTS idx_bugs_ver      ON bugs(version_id);
CREATE INDEX IF NOT EXISTS idx_bugs_review   ON bugs(review_id);

-- At most one review per (pr, commit version): a commit is reviewed exactly
-- once. Any repeated attempt (scanner re-enqueue, remote runner ingest replay,
-- CLI re-run of the same PR) must resolve to the same review row rather than
-- inserting a new one. Enforced at the DB layer so no code path can bypass it.
CREATE UNIQUE INDEX IF NOT EXISTS ux_reviews_pr_ver ON reviews(pr_id, version_id);
"""
