# Phase 4.5 - Read-Only SQLite Projector

Date: 2026-05-02
Status: active implementation plan after Phases 1, 4, and 3
Source section: `docs/swarmdaddy-runtime-foundations-adoption-plan-2026-05-02.md` Phase 4.5

## Objective

Build a per-run SQLite mirror derived from JSON state. JSON remains canonical.
The mirror exists to make trace, eval, status, doctor, and TUI queries simpler
while proving the schema before any canonical migration is considered.

Owner JSON modules whose state is mirrored:

- `swarm-do/py/swarm_do/pipeline/run_state.py:20` — active-run + checkpoint
- `swarm-do/py/swarm_do/pipeline/phase_sessions.py:35,117` — phase sessions
- `swarm-do/py/swarm_do/pipeline/stage_sessions.py:21,43` — per-phase stage sessions
- `swarm-do/py/swarm_do/pipeline/phase_evidence.py:15-26` — attempt evidence manifests
- `swarm-do/py/swarm_do/pipeline/execution_worktree.py:206,358,442,453,614,630,814` — worktree manifests
- `swarm-do/py/swarm_do/pipeline/prepared_artifact_writer.py:5` — prepared plan
- `swarm-do/py/swarm_do/pipeline/run_state.py:62-63` — `<data>/telemetry/run_events.jsonl`

## Senior Implementation Decision

Land this in two increments:

1. Project and diff only. Build the mirror from scratch, add CLI commands, and
   let Phase 4 eval read it in tests.
2. Prefer mirror reads for status/doctor/TUI only after projection and
   diff-mirror are stable. Every operator command must fall back to JSON if the
   mirror is missing or corrupt.

This keeps SQLite as a read model, not a quiet write-side migration.

## Dependencies

Required before starting:

- **Phase 1 state-ownership boundary plan** — `phase-1-state-ownership-boundary-plan.md` (write fence test landed; owner modules listed in `runtime-foundations/README.md` cross-plan rules).
- **Phase 4 trace/eval suite** — `phase-4-run-trace-eval-plan.md`. At minimum the `clean single phase` and `retryable failure then success` fixture families must exist before step 11 (eval `--use-mirror` parity). **Phase 4 fixtures do not yet exist on disk** — `find ... -name 'test_run_trace*' -o -name 'test_run_eval*'` returns nothing. This plan's step 11 is a hard prereq on Phase 4.
- **Phase 3 policy consolidation** — `phase-3-policy-consolidation-plan.md`. Only required if step 12 (status/doctor/TUI mirror reads) lands in the same PR.

## Scope

Owned files:

```text
py/swarm_do/pipeline/state_projector.py
py/swarm_do/pipeline/state_projector_schema.sql
py/swarm_do/pipeline/tests/test_state_projector.py
py/swarm_do/pipeline/tests/test_state_projector_diff.py
py/swarm_do/pipeline/tests/test_state_projector_strict_compat.py
```

CLI surfaces (registered in `swarm-do/py/swarm_do/pipeline/cli.py` sibling to `cmd_run_state` at line 1464; the `swarm` shim at `swarm-do/bin/swarm:5` already execs `python3 -m swarm_do.pipeline.cli`):

```text
swarm state project <run-id>
swarm state mirror <run-id> --query "<sql>"
swarm state diff-mirror <run-id>
```

Mirror path:

```text
resolve_data_dir() / "runs" / <run-id> / "state.mirror.sqlite"
```

> ⚠️ **`${CLAUDE_PLUGIN_DATA}` is NOT a reliable shorthand.** `resolve_data_dir()` (`paths.py:13-25`) returns `$CLAUDE_PLUGIN_DATA` only if set; otherwise it falls back to `$XDG_DATA_HOME/swarmdaddy` or `~/.local/share/swarmdaddy`. Always go through `resolve_data_dir()`; never hardcode `${CLAUDE_PLUGIN_DATA}` in code or paths.

## Sources Projected

For run `<run_id>` rooted at `<data> = resolve_data_dir()` (`paths.py:13`):

| Source kind | Path | Owner module:line |
|---|---|---|
| active-run | `<data>/active-run.json` (only if `run_id` matches) | `run_state.py:20` |
| checkpoint | `<data>/runs/<run_id>/checkpoint.v1.json` | `run_state.py:23` |
| prepared-plan | `<data>/runs/<run_id>/prepared_plan.v1.json` | `prepared_artifact_writer.py:5` |
| phase-sessions | `<data>/runs/<run_id>/phase-sessions.json` | `phase_sessions.py:117` |
| stage-sessions | `<data>/runs/<run_id>/stage-sessions/<phase_id>.json` (per phase) | `stage_sessions.py:43` |
| evidence | `<data>/runs/<run_id>/phase_launches/<phase_id>/attempt-<n>/evidence.json` | `phase_evidence.py:23` |
| worktree-manifest | `<data>/worktrees/<run_id>/manifest.json` and `…/integration/manifest.json` | `execution_worktree.py:206,453` |
| run-events | `<data>/telemetry/run_events.jsonl` (filtered by `run_id`) | `run_state.py:62` |

> ⚠️ **`run_events.jsonl` is GLOBAL, not per-run.** A single shared JSONL contains rows for every run on this machine and grows unboundedly. The projector must stream-parse it line by line and filter by `run_id` — never load the whole file into memory. Document the scan cost.

## Non-Goals

- No canonical SQLite store.
- No `SWARM_STATE_BACKEND` flag.
- No write path that mutates SQLite without first mutating JSON.
- No global database.
- No WAL requirement. Use rollback-journal mode initially.
- No projector-side mutations of `state.mirror.sqlite` outside `state_projector.py`. Verified by AST fence test (see Acceptance Criteria).

## Initial Schema

Concrete `state_projector_schema.sql` derived from on-disk JSON shapes. The
`STRICT` keyword present on every table; the runtime gate strips `STRICT` on
SQLite < 3.37.

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = DELETE;
PRAGMA busy_timeout = 5000;

-- Schema version of the projector itself, NOT the JSON sources.
CREATE TABLE projector_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
) STRICT;
-- rows: ('schema_version','1'), ('sqlite_version', …), ('projected_at', …),
--       ('json_source_sha_combined', …)

-- One row per run.
CREATE TABLE runs (
  run_id                  TEXT PRIMARY KEY
    CHECK (length(run_id) = 26),                         -- ULID; matches run_events.schema.json:17
  schema_version          INTEGER NOT NULL,              -- from active-run / checkpoint
  bd_epic_id              TEXT,
  status                  TEXT NOT NULL,                 -- 'incomplete'|'completed'|...
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
  updated_at              TEXT NOT NULL                  -- ISO-8601 Z
) STRICT;

-- One row per phase, sourced from phase-sessions.json[phases].
CREATE TABLE phases (
  run_id                  TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  phase_id                TEXT NOT NULL
    CHECK (phase_id GLOB '[A-Za-z0-9_.-]*'),             -- matches phase_sessions.schema.json
  phase_index             INTEGER NOT NULL CHECK (phase_index >= 0),
  title                   TEXT NOT NULL,
  status                  TEXT NOT NULL,                 -- pending|leased|running|completed|failed|blocked|...
  depends_on_phase_ids    TEXT NOT NULL,                 -- JSON array text
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

-- One row per attempt (from phase_launches/<phase_id>/attempt-<n>/evidence.json).
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
  failure_details_json    TEXT,                          -- raw JSON text of evidence.failure
  recovery_json           TEXT,                          -- raw JSON of evidence.recovery
  metrics_json            TEXT,                          -- raw JSON of evidence.metrics
  partial_artifacts       INTEGER NOT NULL DEFAULT 0 CHECK (partial_artifacts IN (0,1)),
  PRIMARY KEY (run_id, phase_id, attempt),
  FOREIGN KEY (run_id, phase_id) REFERENCES phases(run_id, phase_id) ON DELETE CASCADE
) STRICT;

-- One row per run_events.jsonl line filtered by run_id.
-- Source: <data>/telemetry/run_events.jsonl (run_state.py:62).
-- event_type enum from swarm-do/schemas/telemetry/run_events.schema.json.
CREATE TABLE events (
  run_id                  TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  event_seq               INTEGER NOT NULL,              -- 0-based line index within run_id filter
  timestamp               TEXT NOT NULL,                 -- ISO-8601 Z
  event_type              TEXT NOT NULL,                 -- enum validated at insert
  bd_epic_id              TEXT,
  phase_id                TEXT,
  work_unit_id            TEXT,
  child_bead_ids_json     TEXT,                          -- JSON array text or NULL
  reason                  TEXT,
  retry_count             INTEGER CHECK (retry_count IS NULL OR retry_count >= 0),
  handoff_count           INTEGER CHECK (handoff_count IS NULL OR handoff_count >= 0),
  integration_branch_head TEXT
    CHECK (integration_branch_head IS NULL OR length(integration_branch_head) = 40),
  details_json            TEXT,                          -- JSON object text or NULL
  schema_ok               INTEGER NOT NULL CHECK (schema_ok IN (0,1)),
  payload_json            TEXT NOT NULL,                 -- full original JSON line
  PRIMARY KEY (run_id, event_seq)
) STRICT;
CREATE INDEX events_by_type ON events(run_id, event_type);
CREATE INDEX events_by_phase ON events(run_id, phase_id);

-- Provenance: every JSON file consulted during projection.
CREATE TABLE artifact_sources (
  run_id        TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  kind          TEXT NOT NULL,                          -- 'active_run'|'checkpoint'|'phase_sessions'|'stage_sessions'|'evidence'|'worktree_manifest'|'prepared_plan'|'run_events'
  path          TEXT NOT NULL,
  sha256        TEXT NOT NULL CHECK (length(sha256) = 64),
  size_bytes    INTEGER NOT NULL CHECK (size_bytes >= 0),
  mtime_ns      INTEGER NOT NULL CHECK (mtime_ns >= 0),
  read_at       TEXT NOT NULL,                          -- ISO-8601 Z, projector clock
  PRIMARY KEY (run_id, kind, path)
) STRICT;

-- Soft failures captured during projection (never raised).
CREATE TABLE projection_warnings (
  run_id     TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  warn_seq   INTEGER NOT NULL,
  kind       TEXT NOT NULL,                              -- 'missing_optional'|'unparseable'|'unknown_schema_version'|'inconsistent_snapshot'|'unsupported_event_type'
  source     TEXT,
  message    TEXT NOT NULL,
  details_json TEXT,
  PRIMARY KEY (run_id, warn_seq)
) STRICT;
```

> **Hashing.** `json_source_sha` uses `hashlib.sha256` on raw bytes — matches existing `prepared_plan_sha`, `prompt_sha` patterns (see `phase_attempt_evidence.schema.json` `^[0-9a-f]{64}$`). One row per source file in `artifact_sources` carrying `(run_id, kind, path, sha256, mtime_ns, size_bytes, read_at)`.

Optional **deferred** P0+1 tables (out of scope for this PR; call out in handoff): `worktree_manifests`, `prepared_plan` (full structured projection), `phase_decisions` (Phase 7 dependency).

## Implementation Steps

1. Add `state_projector_schema.sql` per §"Initial Schema" with `PRAGMA foreign_keys = ON;`, `PRAGMA journal_mode = DELETE;`, `PRAGMA busy_timeout = 5000;`. **Detect `sqlite3.sqlite_version_info < (3, 37, 0)` at runtime and select a non-STRICT variant** (substitute `STRICT` away, drop strict-only check shapes).
2. Add `state_projector.py` exposing `project_run(run_id: str, *, data_dir: Path | None = None) -> ProjectionResult`. Resolve `data_dir = data_dir or resolve_data_dir()`; resolve mirror path as `data_dir / "runs" / run_id / "state.mirror.sqlite"`.
3. **Acquire `fcntl.flock(<run_dir>/.projector.lock)` for the projection duration.** Open the temp DB at `<mirror_path>.<pid>.<ts>.tmp` **in the same directory as the final mirror** (mirror `_atomic_json_write` semantics at `run_state.py:178-202`).
4. Read sources in the order listed in §"Sources Projected". For each source: `sha256` the bytes, capture `mtime_ns` and `size_bytes`, insert one `artifact_sources` row per file. Treat `FileNotFoundError` on optional sources (evidence, worktree integration manifest, stage sessions for not-yet-started phases) as a `projection_warnings` row, not a crash.
5. Validate each loaded JSON against its `schema_version`. If a source declares a `schema_version` the projector does not know, insert a `projection_warnings` row of kind `unknown_schema_version` and skip the dependent table inserts (do not crash).
6. INSERT rows into `runs`, `phases`, `phase_attempts`, `events` inside one transaction. **The `events` source is the GLOBAL `<data>/telemetry/run_events.jsonl`** — stream-parse it line by line, filter by `run_id`, validate each row against `swarm-do/schemas/telemetry/run_events.schema.json` (use existing `validate_value` from `swarm_do.telemetry.schemas`), insert canonical fields plus `payload_json` for the full row.
7. Run `PRAGMA integrity_check;` and `PRAGMA foreign_key_check;`. If either reports issues, **abort: do not replace the live mirror**; surface the failure with `ProjectionError`.
8. Mirror `_atomic_json_write` semantics: `conn.close()`, then open the SQLite file fd, `flush()`, `fsync(fd)`, then `os.replace(tmp_path, mirror_path)`. **The temp file MUST live in `mirror_path.parent`** so `os.replace` is atomic on POSIX.
9. Add `diff_mirror(run_id, *, data_dir=None)` that re-projects to a second temp DB and compares each table's content (ordered SELECT, hashed). Return the first divergent row.
10. Wire CLI under `cmd_state` in `swarm-do/py/swarm_do/pipeline/cli.py`, sibling to `cmd_run_state` (line 1464). Sub-actions: `project`, `mirror`, `diff-mirror`. The `swarm` bin shim already execs `python3 -m swarm_do.pipeline.cli` — no shim work needed.
11. Wire Phase 4 eval to optionally query the mirror. Add a `--use-mirror` flag to `swarm eval run`; when set, eval reads from the mirror and asserts parity against the JSON-derived `RunTrace`. **Gated on Phase 4 plan landing the `RunTrace` serializer** — if Phase 4 has not exposed a stable serialization yet, defer this step.
12. (Increment 2) Convert status/doctor/TUI read sites in `cli.py` (e.g. `cmd_run_state` at 1464, `cmd_doctor`, TUI helpers) to prefer mirror with `try: query mirror; except (sqlite3.DatabaseError, FileNotFoundError): fall back to JSON`. Add an integration test that deletes the mirror mid-test and asserts every command still works.

## Concurrency & Atomicity Guardrails

> ⚠️ **TORN-READ HAZARD across multiple JSON sources.** Atomicity holds per-file via `_atomic_json_write` (`run_state.py:178-202` — rename-atomic), but NOT across the file set. Reading `phase-sessions.json` then `stage-sessions/<phase_id>.json` can straddle a writer's commit, with the two files disagreeing by tens of milliseconds. **Mitigation**: record `json_source_sha` and `read_at` per `artifact_sources` row; emit `projection_warnings.kind = 'inconsistent_snapshot'` when `phase-sessions.updated_at` advances during projection.

> ⚠️ **CROSS-FILESYSTEM `os.replace`.** `os.replace` is atomic only when the temp file and target are on the same filesystem. Putting the temp DB in `/tmp` silently breaks atomicity. **Mitigation**: always create the temp DB in `mirror_path.parent` (mirror the existing pattern at `run_state.py:181`).

> ⚠️ **CONCURRENT PROJECTION RACE.** Two `swarm state project` calls produce two temp DBs; whichever calls `os.replace` last wins, with no error. **Mitigation**: `fcntl.flock` on `<run_dir>/.projector.lock` for the projection duration. The losing call retries (or is rejected with `LockError` — pick rejected for now).

> ⚠️ **WINDOWS `os.replace` reader hazard.** On Windows, `os.replace` raises `PermissionError` if any process has the target open. Status/doctor/TUI on Windows could trip. **Mitigation**: declare POSIX-only for v1; if Windows support becomes a requirement, wrap reads in short-lived connections that close before the swap.

> ⚠️ **STRICT availability.** `STRICT` requires SQLite ≥ 3.37 (Sept 2021). Bootstrap floor is `python3 >= 3.10` (`bin/_lib/python-bootstrap.sh`); macOS 13+, Debian 12+, and Ubuntu 22.04+ all ship sufficient SQLite. **Ubuntu 20.04 ships 3.31 and would break.** **Mitigation**: detect `sqlite3.sqlite_version_info` at projection time and emit a non-STRICT schema variant when below 3.37. Both variants must pass projector tests.

> ⚠️ **GLOBAL `run_events.jsonl` SCAN.** The events table is filtered from a single shared JSONL that grows unboundedly across runs. **Mitigation**: stream-parse line by line with a `run_id` filter; never load the whole file. Document scan cost in the projector's docstring.

> ⚠️ **MIRROR-CORRUPTION-NEVER-BLOCKS claim must be enforced by tests, not assumed.** Every read site must wrap mirror queries in `try/except (sqlite3.DatabaseError, FileNotFoundError) → JSON fallback`. **Mitigation**: integration test that mutates the mirror (`rm`, truncate to zero, random-byte-flip in pages 1-3) and asserts `swarm rollout show`, `swarm doctor`, `swarm status` all succeed.

> ⚠️ **SCHEMA DRIFT.** When JSON owner modules bump their `schema_version`, the projector must bump in lockstep or `diff-mirror` lights up. **Mitigation**: a `projector_compatibility` map in code lists each source schema_version the projector understands; refuse to project if a source declares an unrecognized version (emit `projection_warnings.kind = 'unknown_schema_version'`, leave dependent tables empty).

## Failure Handling

- **Missing optional source** → `projection_warnings(kind='missing_optional', source=…)`; projection succeeds.
- **Malformed required source** (JSON parse error, schema_version unknown) → `projection_warnings(kind='unparseable'|'unknown_schema_version', source=…)`; projection succeeds with that source's downstream tables left empty.
- **`integrity_check` or `foreign_key_check` failure** → raise `ProjectionError`; the live mirror is **not** modified.
- **Concurrent projector race** → second projector waits on the per-run flock; both serialized.
- **Reader sees corrupt mirror** → caller catches `sqlite3.DatabaseError` and falls back to JSON. Status/doctor MUST never error out on mirror corruption.
- **Cross-filesystem `os.replace`** → prevented by always creating the temp DB in the mirror's parent directory.
- **Inconsistent JSON snapshot** mid-projection → captured as `projection_warnings.kind = 'inconsistent_snapshot'`, projection succeeds but operator can re-run.

## Acceptance Criteria

- A run can be projected deterministically: two `project_run` calls against the same JSON snapshot produce **byte-identical** `state.mirror.sqlite` (verify by sha256 after stripping `artifact_sources.read_at` and `projector_meta('projected_at')`).
- `swarm state diff-mirror <run-id>` reports zero divergence on every Phase 4 fixture family that exists at land time (minimum: `clean single phase`, `retryable failure then success`).
- **Mirror is rebuildable.** Deleting `state.mirror.sqlite` and re-running `swarm state project` produces an equivalent file. Test deletes, re-projects, runs `diff-mirror` against a third re-projection.
- **Mirror corruption never blocks recovery/status/doctor.** Integration test mutates the mirror (`rm`, truncate, random byte flip, rename to invalid extension) and asserts every read site succeeds via JSON fallback.
- **No projector-only writes.** AST fence test analogous to `test_prepared_artifact_fence.py` confirms only `state_projector.py` opens `state.mirror.sqlite` for write within `swarm_do/pipeline/`.
- **STRICT compatibility.** Both STRICT (≥ 3.37) and non-STRICT variants pass the projector test suite under the same fixtures.
- **Concurrent projection safety.** Two simultaneous `project_run` calls produce a valid final mirror; neither produces a partial or interleaved file. Test uses `threading.Thread` × 2 with a `multiprocessing.Barrier` to maximize race.
- **Phase 4 parity.** For every Phase 4 fixture family that exists at land time, `swarm eval run --use-mirror` returns the same exit code and same first-divergence message as without `--use-mirror`.
- **Schema-drift detection.** When a source JSON's `schema_version` is bumped without updating the projector, projection emits exactly one `projection_warnings` row of kind `unknown_schema_version` and leaves dependent tables empty (does not crash).
- No write path in `swarm_do/pipeline/` mutates `state.mirror.sqlite` outside `state_projector.py`.

## Tests

`test_state_projector.py` (deterministic projection):

- empty run (only active-run.json + checkpoint) → projects with zero phases, zero attempts, zero events.
- one phase one attempt success → 1 row in `runs`, 1 in `phases`, 1 in `phase_attempts`, evidence rows present, `artifact_sources` lists every file with sha256.
- missing optional evidence file → `projection_warnings` row, projection succeeds.
- malformed JSON in `stage_sessions` → warning row, dependent tables empty, projection succeeds.
- unknown `schema_version` in `phase-sessions.json` → `unknown_schema_version` warning.
- determinism: project twice; sha256 of mirror bytes equal after stripping non-deterministic columns.
- cross-filesystem guard: monkeypatch `tempfile.gettempdir()` to a different filesystem; assert projector still puts temp file in mirror's parent.

`test_state_projector_diff.py` (parity & corruption):

- `diff-mirror` after fresh projection: empty divergence list.
- `diff-mirror` after a `stage_sessions` JSON edit but no re-project: divergence row points at exact `(table, primary_key, column)`.
- mirror corruption (truncate to zero, random-byte-flip in pages 1-3): `swarm rollout show` and `swarm doctor` succeed using JSON fallback.
- concurrent project: two threads call `project_run` simultaneously, both succeed, final mirror is one of the two (not interleaved).

`test_state_projector_strict_compat.py`: monkeypatch `sqlite3.sqlite_version_info` to `(3, 31, 0)`; assert non-STRICT schema variant is selected and projection still succeeds.

Run command (per project memory):

```bash
cd swarm-do && PYTHONPATH=py python3 -m unittest \
  swarm_do.pipeline.tests.test_state_projector \
  swarm_do.pipeline.tests.test_state_projector_diff \
  swarm_do.pipeline.tests.test_state_projector_strict_compat -v
```

Regression boundary (must not break):

```text
py/swarm_do/telemetry/tests/test_query_parity.py
py/swarm_do/telemetry/tests/test_schemas.py
```

> Note: `test_jsonl.py` was previously listed but does not exist on disk. The two telemetry tests above are the actual regression targets and use the same `validate_value` schema machinery the projector reuses for `events`.

## Handoff Notes

- List every JSON field that was intentionally not projected. Those omissions are the input to a future canonical-store ADR, not quiet follow-ups hidden in code comments.
- The mirror schema is the *de facto* candidate for any future canonical-SQLite ADR. **There is currently no Phase 9 plan** (`runtime-foundations/README.md` lists Phase 9 as Dormant Work). When a canonical-store ADR is opened, it should diff its proposed schema against this mirror's tables and explain every additional column or constraint.
- Phase 7 operator-decisions plan (`phase-7-operator-decisions-plan.md`) may want a `decisions` table; **defer until Phase 7 actually lands its JSON shape.**
- Deferred P0+1 tables (`worktree_manifests`, `prepared_plan`, `phase_decisions`) are explicitly out of this PR; document them at handoff so they don't become quiet TODOs.
