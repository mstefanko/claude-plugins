PRAGMA foreign_keys = ON;
PRAGMA journal_mode = DELETE;
PRAGMA busy_timeout = 5000;

CREATE TABLE projector_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
) STRICT;

CREATE TABLE runs (
  run_id                  TEXT PRIMARY KEY
    CHECK (length(run_id) = 26),
  schema_version          INTEGER NOT NULL,
  bd_epic_id              TEXT,
  status                  TEXT NOT NULL,
  prepared_artifact_path  TEXT,
  prepared_plan_path      TEXT,
  prepared_plan_sha       TEXT
    CHECK (prepared_plan_sha IS NULL OR length(prepared_plan_sha) = 64),
  prepared_inspect_path   TEXT,
  integration_branch_head TEXT
    CHECK (integration_branch_head IS NULL OR length(integration_branch_head) = 40),
  active_phase_id         TEXT,
  active_phase_index      INTEGER,
  active_attempt          INTEGER,
  updated_at              TEXT NOT NULL
) STRICT;

CREATE TABLE phases (
  run_id                  TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  phase_id                TEXT NOT NULL
    CHECK (phase_id GLOB '[A-Za-z0-9_.-]*'),
  phase_index             INTEGER NOT NULL CHECK (phase_index >= 0),
  title                   TEXT NOT NULL,
  status                  TEXT NOT NULL,
  depends_on_phase_ids    TEXT NOT NULL,
  attempt                 INTEGER NOT NULL DEFAULT 0,
  session_name            TEXT,
  lease_owner             TEXT,
  lease_host              TEXT,
  lease_pid               INTEGER,
  lease_command           TEXT,
  lease_expires_at        TEXT,
  started_at              TEXT,
  completed_at            TEXT,
  result_path             TEXT,
  handoff_path            TEXT,
  last_error              TEXT,
  last_failure_kind       TEXT,
  PRIMARY KEY (run_id, phase_id)
) STRICT;

CREATE TABLE phase_attempts (
  run_id                  TEXT NOT NULL,
  phase_id                TEXT NOT NULL,
  attempt                 INTEGER NOT NULL CHECK (attempt >= 1),
  generated_at            TEXT NOT NULL,
  session_name            TEXT,
  launcher                TEXT,
  status                  TEXT NOT NULL,
  launch_dir              TEXT NOT NULL,
  evidence_path           TEXT NOT NULL,
  command_path            TEXT,
  prompt_path             TEXT,
  source_prompt_path      TEXT,
  stdout_path             TEXT,
  stderr_path             TEXT,
  result_path             TEXT,
  handoff_path            TEXT,
  prompt_sha              TEXT
    CHECK (prompt_sha IS NULL OR length(prompt_sha) = 64),
  source_prompt_sha       TEXT
    CHECK (source_prompt_sha IS NULL OR length(source_prompt_sha) = 64),
  settings_sha            TEXT
    CHECK (settings_sha IS NULL OR length(settings_sha) = 64),
  parent_pid              INTEGER,
  child_pid               INTEGER,
  process_group_id        INTEGER,
  returncode              INTEGER,
  started_at              TEXT,
  completed_at            TEXT,
  elapsed_seconds         REAL,
  failure_kind            TEXT,
  failure_details_json    TEXT,
  recovery_json           TEXT,
  metrics_json            TEXT,
  partial_artifacts       INTEGER NOT NULL DEFAULT 0 CHECK (partial_artifacts IN (0,1)),
  PRIMARY KEY (run_id, phase_id, attempt),
  FOREIGN KEY (run_id, phase_id) REFERENCES phases(run_id, phase_id) ON DELETE CASCADE
) STRICT;

CREATE TABLE events (
  run_id                  TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  event_seq               INTEGER NOT NULL,
  timestamp               TEXT NOT NULL,
  event_type              TEXT NOT NULL,
  bd_epic_id              TEXT,
  phase_id                TEXT,
  work_unit_id            TEXT,
  child_bead_ids_json     TEXT,
  reason                  TEXT,
  retry_count             INTEGER CHECK (retry_count IS NULL OR retry_count >= 0),
  handoff_count           INTEGER CHECK (handoff_count IS NULL OR handoff_count >= 0),
  integration_branch_head TEXT
    CHECK (integration_branch_head IS NULL OR length(integration_branch_head) = 40),
  details_json            TEXT,
  schema_ok               INTEGER NOT NULL CHECK (schema_ok IN (0,1)),
  payload_json            TEXT NOT NULL,
  PRIMARY KEY (run_id, event_seq)
) STRICT;
CREATE INDEX events_by_type ON events(run_id, event_type);
CREATE INDEX events_by_phase ON events(run_id, phase_id);

CREATE TABLE artifact_sources (
  run_id        TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  kind          TEXT NOT NULL,
  path          TEXT NOT NULL,
  sha256        TEXT NOT NULL CHECK (length(sha256) = 64),
  size_bytes    INTEGER NOT NULL CHECK (size_bytes >= 0),
  mtime_ns      INTEGER NOT NULL CHECK (mtime_ns >= 0),
  read_at       TEXT NOT NULL,
  PRIMARY KEY (run_id, kind, path)
) STRICT;

CREATE TABLE projection_warnings (
  run_id       TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  warn_seq     INTEGER NOT NULL,
  kind         TEXT NOT NULL,
  source       TEXT,
  message      TEXT NOT NULL,
  details_json TEXT,
  PRIMARY KEY (run_id, warn_seq)
) STRICT;
