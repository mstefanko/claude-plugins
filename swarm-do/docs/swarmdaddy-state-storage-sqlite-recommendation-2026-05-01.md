# SwarmDaddy State Storage Architecture: SQLite Research And Recommendation

**Date:** 2026-05-01
**Status:** Recommendation for Section 12 follow-up
**Scope:** `swarm-do/docs/swarmdaddy-recovery-ux-and-drift-hardening-plan.md` Section 12, plus current run-orchestration storage under `py/swarm_do/pipeline/`.

## Executive Recommendation

Adopt SQLite as the canonical store for SwarmDaddy's run control-plane state, incrementally, after the Recovery UX work has its writer seam. Do not do a big-bang rewrite, and do not put every artifact byte into SQLite just because SQLite exists. The right shape is:

- Canonical state: per-run SQLite DB under `${CLAUDE_PLUGIN_DATA}/runs/<run-id>/state.sqlite`.
- Compatibility/debug/export boundary: keep `prepared.md`, `prepared_plan.v1.json`, `inspect.v1.json`, work-unit JSON sidecars, phase results, and handoffs as generated files where workers and tests already expect them.
- Audit: write state changes and audit events in the same SQLite transaction, then continue mirroring to `telemetry/run_events.jsonl` for existing telemetry consumers.
- Worktree reality: continue reconciling against `git`; SQLite can store intended/observed worktree state, but it cannot make git branch creation/removal transactional.

This is a "go, but narrow" recommendation. The code-walk memo is right that `PreparedArtifactWriter` fixes the immediate bug. The research memo is right that the current multi-file model is fighting a class of problems SQLite was built to solve. Since this is still local-only and there is no large installed migration burden, moving the source of truth now is cheaper than waiting until there are more state files, more recovery verbs, and real historical compatibility constraints.

Do not block the Section 1-11 recovery plan on this migration. Instead, make `PreparedArtifactWriter` the short-term JSON owner and the future migration seam.

## Current Storage Shape

Facts from the current code:

- `prepare_plan_run()` builds a run as multiple files: `prepared.md`, `inspect.v1.json`, work-unit sidecars, and the XDG `prepared_plan.v1.json` artifact (`py/swarm_do/pipeline/prepare.py:619-913`).
- `prepared_plan_sha` hashes the markdown `prepared.md`, not `prepared_plan.v1.json` (`prepare.py:674-676`, checked again by `check_stale()` at `prepare.py:2041-2047`).
- Work-unit artifacts are denormalized three ways: embedded descriptor `artifact`, sidecar JSON bytes, and descriptor `sha` (`prepare.py:750-767`, verified at `prepare.py:1273-1286`).
- Prepared run paths can cross two roots. If `${CLAUDE_PLUGIN_DATA}/runs/<id>` is outside the repo, `_repo_visible_run_dir()` places worker-visible exports under `<repo>/data/runs/<id>` (`prepare.py:1416-1423`), while the canonical prepared artifact lives under XDG data (`prepare.py:1773-1774`, `prepare.py:1798-1816`).
- Phase-session queue state is a single JSON file with an explicit POSIX lock (`phase_sessions.py:35-37`, `phase_sessions.py:117-122`) and many mutable per-phase fields (`phase_sessions.py:180-219`). It writes atomically per file (`phase_sessions.py:1558-1562`).
- Worktree state is another JSON manifest under `${CLAUDE_PLUGIN_DATA}/worktrees/<run-id>/manifest.json`; it currently hard-aborts on any mismatch including base drift (`execution_worktree.py:169-194`, `execution_worktree.py:859-874`).
- The event log is append-only JSONL (`run_state.py:57-69`), separate from the JSON state writes it describes.
- The repo already uses SQLite, but not as the run-orchestration source of truth: telemetry `query` loads JSONL into `sqlite3 :memory:` (`py/swarm_do/telemetry/subcommands/query.py:111-137`), `mem_prime.LocalSqliteAdapter` is a fixture adapter (`py/swarm_do/pipeline/mem_prime.py:57-78`), and sibling/local tools such as `tech-radar` and `beads` use SQLite.

The recurring bug class is not "JSON is bad." It is "the source of truth is spread across several JSON files and git state, and recovery verbs need to mutate several of them consistently." Per-file atomic replace is good engineering, but it is not a transaction across XDG state, repo-visible sidecars, and JSONL audit rows.

## 2026 Pattern Check

SQLite remains the mainstream answer for local, embedded, durable application state:

- SQLite's own application-file-format guidance explicitly frames it as a replacement for a pile of files, with schema, constraints, indexes, and atomic transactions in one file.
- SQLite's atomic commit contract is exactly the invariant Section 3.4.0 hand-rolls today: all changes in one transaction happen, or none do.
- Prefect 3 uses a database to persist flow/task run state, logs, artifacts, work pools, events, and automations; its docs recommend SQLite by default for lightweight single-server deployments and PostgreSQL for production HA/multi-server use.
- Dagster's default local storage uses SQLite for run storage and event log storage; its event log storage shards SQLite databases per run for concurrent performance.

Important 2026 caveat: do not blindly enable WAL mode for SwarmDaddy's canonical state on the currently available Python runtime. This machine's `python3` reports SQLite `3.49.1`. SQLite's WAL documentation notes a rare WAL-reset bug affecting WAL databases with multiple connections, fixed in `3.51.3` and certain backports. Because SwarmDaddy is a local CLI with short-lived processes and tiny writes, rollback-journal mode plus `BEGIN IMMEDIATE` is acceptable at first. WAL can be version-gated later when the runtime SQLite is known-good.

Modern SQLite features that matter here:

- `STRICT` tables are available since SQLite `3.37.0`; use them for new tables.
- JSON functions are built in by default since SQLite `3.38.0`; use `json_valid()` checks for JSON payload columns where useful.
- JSONB exists since `3.45.0`, but should not be the first storage format for operator-visible artifacts. Store canonical JSON payloads as `TEXT` initially; JSONB is a later performance choice.
- Foreign keys must be enabled on every connection with `PRAGMA foreign_keys = ON`.
- Python's `sqlite3` connection context manager commits or rolls back but does not close the connection, so wrap connections explicitly and close them. This also matches existing test noise about SQLite `ResourceWarning`.

## What SQLite Would Solve

SQLite would materially improve the parts of SwarmDaddy that have transactional state:

1. Cross-file atomicity.
   `prepare refresh-base` should update prepared metadata, work-unit artifacts, descriptor SHAs/export records, phase-session references, and an audit event as one unit. In SQLite this is one transaction. In JSON it is snapshot/stage/replace/rollback code.

2. Referential invariants.
   A `phase` row can own `work_unit_artifact` rows with foreign keys and uniqueness constraints. The database can prevent "descriptor exists for missing phase" and "phase exists without artifact" classes before the code has to rediscover them.

3. Idempotent recovery.
   Recovery commands can be expressed as transactionally inserting an event with a unique idempotency key, then updating projected state. Re-running the same command becomes a no-op or a controlled retry.

4. Better doctor/status queries.
   `phases doctor`, TUI state, and future dashboards can query one state view instead of loading N JSON files, sidecars, and JSONL rows. Existing telemetry proves this repo already benefits from SQL for joins.

5. Durable audit coupling.
   Today `append_run_event()` is separate from the state mutation. A crash after state write but before JSONL append loses audit, and a crash after append but before state write creates a misleading audit row. SQLite can make state change and audit event one commit.

6. Less attractive `/tmp` surgery.
   Operators can still inspect and repair with stable commands, but the sanctioned repair surface becomes `swarm state dump`, `swarm state doctor`, and SQL-backed recovery verbs rather than ad-hoc JSON mutation across several paths.

## What SQLite Would Not Solve

SQLite is not magic glue around everything:

- It cannot make `git worktree add`, branch deletion, checkout dirtiness, or copyback transactional. Worktree commands still need reconciliation against real git state.
- It cannot make repo-visible exported JSON and XDG DB bytes atomic if both are source of truth. The design must demote exported JSON to derived snapshots, not add SQLite as another peer store.
- It does not remove the need for validators. It moves structural invariants into schema constraints, but artifact payloads still need application/schema validation.
- It does not give multi-writer freedom. SQLite has one writer at a time. SwarmDaddy should keep the existing "single operator, local process" assumption and use a short busy timeout plus `BEGIN IMMEDIATE`.
- It can reduce human-readable `cat` debugging. Mitigate that with `swarm state dump <run-id> --json`, `swarm state export-artifacts`, and keeping generated JSON snapshots in the run dir.

## Recommended Architecture

Use a per-run SQLite DB as canonical control-plane state.

Path:

```text
${CLAUDE_PLUGIN_DATA}/runs/<run-id>/state.sqlite
```

Keep these as generated/exported files, not independent source-of-truth records:

```text
<repo>/data/runs/<run-id>/prepared.md
<repo>/data/runs/<run-id>/inspect.v1.json
<repo>/data/runs/<run-id>/work_units/*.json
${CLAUDE_PLUGIN_DATA}/runs/<run-id>/prepared_plan.v1.json
${CLAUDE_PLUGIN_DATA}/runs/<run-id>/phase_sessions.v1.json
${CLAUDE_PLUGIN_DATA}/worktrees/<run-id>/manifest.json
```

The compatibility files can remain for launchers, existing tests, safe worktree copies, and operator inspection. The key change is that recovery commands update the DB first, then export deterministic snapshots. Snapshot exports should be tracked by an `artifact_exports` table containing path, kind, sha256, and event sequence.

Minimal schema sketch:

```sql
PRAGMA foreign_keys = ON;

CREATE TABLE runs (
  run_id TEXT PRIMARY KEY,
  bd_epic_id TEXT,
  repo_root TEXT NOT NULL,
  git_base_ref TEXT NOT NULL,
  git_base_sha TEXT NOT NULL CHECK(length(git_base_sha) = 40),
  source_plan_path TEXT NOT NULL,
  source_plan_sha TEXT NOT NULL CHECK(length(source_plan_sha) = 64),
  prepared_plan_path TEXT NOT NULL,
  prepared_plan_sha TEXT NOT NULL CHECK(length(prepared_plan_sha) = 64),
  status TEXT NOT NULL CHECK(status IN (
    'draft', 'ready_for_acceptance', 'needs_input', 'accepted', 'stale', 'rejected'
  )),
  created_at TEXT NOT NULL,
  ready_at TEXT,
  accepted_at TEXT
) STRICT;

CREATE TABLE phases (
  run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  phase_id TEXT NOT NULL,
  phase_index INTEGER NOT NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN (
    'pending', 'leased', 'running', 'complete', 'failed', 'blocked',
    'needs_input', 'stale', 'retry_waiting', 'retry_exhausted'
  )),
  cache_key TEXT NOT NULL CHECK(length(cache_key) = 64),
  content_sha TEXT NOT NULL CHECK(length(content_sha) = 64),
  plan_context_sha TEXT NOT NULL CHECK(length(plan_context_sha) = 64),
  phase_json TEXT NOT NULL CHECK(json_valid(phase_json)),
  PRIMARY KEY (run_id, phase_id)
) STRICT;

CREATE TABLE work_unit_artifacts (
  run_id TEXT NOT NULL,
  phase_id TEXT NOT NULL,
  artifact_json TEXT NOT NULL CHECK(json_valid(artifact_json)),
  artifact_sha TEXT NOT NULL CHECK(length(artifact_sha) = 64),
  export_path TEXT NOT NULL,
  PRIMARY KEY (run_id, phase_id),
  FOREIGN KEY (run_id, phase_id) REFERENCES phases(run_id, phase_id) ON DELETE CASCADE
) STRICT;

CREATE TABLE phase_attempts (
  run_id TEXT NOT NULL,
  phase_id TEXT NOT NULL,
  attempt INTEGER NOT NULL,
  status TEXT NOT NULL,
  result_path TEXT,
  handoff_path TEXT,
  launcher_json TEXT CHECK(launcher_json IS NULL OR json_valid(launcher_json)),
  evidence_json TEXT CHECK(evidence_json IS NULL OR json_valid(evidence_json)),
  PRIMARY KEY (run_id, phase_id, attempt),
  FOREIGN KEY (run_id, phase_id) REFERENCES phases(run_id, phase_id) ON DELETE CASCADE
) STRICT;

CREATE TABLE worktrees (
  run_id TEXT PRIMARY KEY REFERENCES runs(run_id) ON DELETE CASCADE,
  branch TEXT NOT NULL,
  base_sha TEXT NOT NULL CHECK(length(base_sha) = 40),
  base_ref TEXT NOT NULL,
  safe_git_worktree_root TEXT NOT NULL,
  safe_project_root TEXT NOT NULL,
  adoption_state TEXT NOT NULL,
  observed_head_sha TEXT,
  observed_dirty INTEGER NOT NULL DEFAULT 0
) STRICT;

CREATE TABLE events (
  run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  seq INTEGER NOT NULL,
  event_type TEXT NOT NULL,
  phase_id TEXT,
  idempotency_key TEXT,
  payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
  created_at TEXT NOT NULL,
  PRIMARY KEY (run_id, seq),
  UNIQUE (run_id, idempotency_key)
) STRICT;

CREATE TABLE artifact_exports (
  run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  path TEXT NOT NULL,
  sha256 TEXT NOT NULL CHECK(length(sha256) = 64),
  event_seq INTEGER NOT NULL,
  PRIMARY KEY (run_id, kind, path),
  FOREIGN KEY (run_id, event_seq) REFERENCES events(run_id, seq)
) STRICT;
```

This is not meant as final DDL. It shows the ownership boundary: the DB owns the relationships and current state; JSON exports are deterministic materializations.

## Storage Rules

1. Use stdlib `sqlite3` first.
   No SQLAlchemy/Alembic dependency is needed unless SwarmDaddy starts supporting multiple database backends. Use `PRAGMA user_version` and explicit migration functions.

2. Use rollback journal initially, not WAL.
   Version-gate WAL until SQLite is at least `3.51.3` or a documented fixed backport. The current local runtime is SQLite `3.49.1`.

3. Use one short-lived connection per command.
   Configure:
   - `PRAGMA foreign_keys = ON`
   - `PRAGMA busy_timeout = 5000`
   - `BEGIN IMMEDIATE`
   - explicit commit/rollback
   - explicit close

4. Keep external artifacts textual.
   Store canonical payloads as JSON `TEXT` in DB columns and export pretty, sorted JSON exactly as current code does. Avoid JSONB until there is measured parse/update pressure.

5. Keep generated snapshots deterministic.
   A snapshot exporter should compute bytes in memory, write with the existing atomic replace helper, recompute sha256, and record the export in `artifact_exports`.

6. Keep `git` as observed reality.
   The `worktrees` table records desired and observed state. Every command still snapshots `git rev-parse`, branch existence, status, and ahead/behind before deciding whether DB state is current.

## Effort Estimate

The earlier "2 weeks" estimate for full SQLite migration is too optimistic for this codebase. No large user-data migration helps, but code and tests still depend on JSON paths and exact artifact bytes.

Reasonable effort:

- 1 week: DB helper, migrations via `user_version`, per-run DB path, transaction helper, state dump command, tests for rollback/busy/foreign-key behavior.
- 1 to 1.5 weeks: move prepared artifact + work-unit artifact ownership behind a DB-backed `PreparedArtifactWriter`, while continuing to export identical JSON snapshots.
- 1.5 to 2 weeks: move phase-session queue state and attempt history into DB-backed operations; preserve JSON export for current launch/copy paths.
- 1 week: worktree manifest table/cache, event table + JSONL mirror, doctor/status integration, compatibility fixtures.

Total: about 4 to 5.5 focused engineering weeks for a durable migration. A one-week spike can prove or kill the direction by implementing only the DB helper plus prepared/work-unit artifact vertical slice for new runs.

## Rollout Plan

1. Finish the immediate Recovery UX changes with `PreparedArtifactWriter`.
   This is needed either way. Keep the JSON rollback recipe for the current PR, but design the writer API so the storage backend can change.

2. Add a storage facade.
   Introduce `RunStateStore` with two implementations:
   - `JsonRunStateStore` wrapping current files.
   - `SqliteRunStateStore` for new experimental runs.

3. Make new runs opt in.
   Add an internal flag or env var, for example `SWARM_STATE_BACKEND=sqlite`, and keep JSON default until the vertical slice passes.

4. Vertical slice: prepared artifacts.
   Store `runs`, `phases`, `work_unit_artifacts`, and `events` in SQLite. Export the exact same `prepared_plan.v1.json` and sidecar JSON. The acceptance test is byte-compatible dispatch plus clean `check_stale()`.

5. Move phase sessions.
   Replace JSON read/modify/write with transactional phase claim/update APIs. The acceptance test is concurrent claim behavior and all existing phase-session tests green.

6. Move worktree manifest cache.
   Store desired and observed worktree state in DB, export `manifest.json` only for compatibility/debug. The acceptance test is the base-drift classifier and rebuild flow.

7. Flip default for new runs.
   Existing JSON runs can remain readable. Add a best-effort import command only if there are real active runs worth preserving.

8. Later cleanup.
   Once no code path reads JSON snapshots as canonical, simplify validators so they validate exports against DB state rather than peer JSON files against each other.

## Decision Criteria

Proceed past the spike if all are true:

- `prepare refresh-base` becomes one DB transaction plus deterministic exports.
- The sidecar embedded/sha/path triple is owned by one backend API, not scattered writer code.
- Existing dispatch and phase-session tests can stay mostly unchanged because exported JSON remains byte-compatible.
- `phases doctor` gets simpler: it queries DB state and then probes filesystem/git reality.
- No new dependency is required for the first version.

Stop or defer if any are true:

- The DB backend becomes "SQLite plus all the same JSON files as equal truth." That is strictly worse.
- Export compatibility requires invasive launcher changes before any durability gain appears.
- Locking complexity rises above the current fcntl lock plus atomic JSON model before phase sessions move.
- The migration requires SQLAlchemy/Alembic/pydantic before the first useful invariant lands.

## Final Verdict

For the most durable foundation, use SQLite for canonical run control-plane state, not as a derived index and not as another cache next to JSON. The timing is favorable because SwarmDaddy is local-only and has little historical migration burden. The migration should be incremental and compatibility-preserving, but the architectural direction should be chosen now:

**DB is truth. JSON files are exports. Git is observed reality. Events are committed with state.**

That model directly addresses the failure that triggered Section 12: multi-file state drift with no transactional recovery boundary.

## Sources

Local code and docs:

- `py/swarm_do/pipeline/prepare.py:619-913` - prepare writes markdown, inspect artifact, work-unit sidecars, and prepared artifact metadata.
- `py/swarm_do/pipeline/prepare.py:1273-1286` - dispatch verifies sidecar hash and embedded artifact equality.
- `py/swarm_do/pipeline/prepare.py:1416-1423` - repo-visible run dir can differ from XDG data dir.
- `py/swarm_do/pipeline/phase_sessions.py:145-257` - phase-session JSON queue initialization.
- `py/swarm_do/pipeline/execution_worktree.py:169-194` and `859-874` - worktree manifest load/validation.
- `py/swarm_do/pipeline/run_state.py:57-69` - JSONL run event append.
- `docs/phase-session-foundation-plan.md` - SQLite rejected for v1 until supervision/concurrency requirements became clearer.
- `docs/plan.md` - telemetry's JSONL truth plus SQLite derived-index pattern.

External primary sources:

- [SQLite as an application file format](https://www.sqlite.org/appfileformat.html)
- [SQLite atomic commit](https://sqlite.org/atomiccommit.html)
- [SQLite write-ahead logging](https://sqlite.org/wal.html)
- [SQLite STRICT tables](https://www.sqlite.org/stricttables.html)
- [SQLite JSON functions and JSONB](https://sqlite.org/json1.html)
- [SQLite foreign key support](https://www.sqlite.org/foreignkeys.html)
- [Python `sqlite3` documentation](https://docs.python.org/3/library/sqlite3.html)
- [Prefect 3 server database documentation](https://docs.prefect.io/v3/concepts/server)
- [Dagster internals docs: SQLite run/event storage](https://legacy-versioned-docs.dagster.dagster-docs.io/_apidocs/internals)
