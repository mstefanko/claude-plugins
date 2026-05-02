# Phase 4.5 - Read-Only SQLite Projector

Date: 2026-05-02
Status: active implementation plan after Phases 1, 4, and 3
Source section: `docs/swarmdaddy-runtime-foundations-adoption-plan-2026-05-02.md` Phase 4.5

## Objective

Build a per-run SQLite mirror derived from JSON state. JSON remains canonical.
The mirror exists to make trace, eval, status, doctor, and TUI queries simpler
while proving the schema before any canonical migration is considered.

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

- Phase 1 write ownership seam and fence test.
- Phase 4 trace/eval suite with at least the initial fixture families.
- Phase 3 policy consolidation if status/doctor/TUI surfaces display resolved
  policies from the projector.

## Scope

Owned files:

```text
py/swarm_do/pipeline/state_projector.py
py/swarm_do/pipeline/state_projector_schema.sql
py/swarm_do/pipeline/tests/test_state_projector.py
py/swarm_do/pipeline/tests/test_state_projector_diff.py
```

CLI surfaces:

```text
swarm state project <run-id>
swarm state mirror <run-id> --query "<sql>"
swarm state diff-mirror <run-id>
```

Mirror path:

```text
${CLAUDE_PLUGIN_DATA}/runs/<run-id>/state.mirror.sqlite
```

## Non-Goals

- No canonical SQLite store.
- No `SWARM_STATE_BACKEND` flag.
- No write path that mutates SQLite without first mutating JSON.
- No global database.
- No WAL requirement. Use rollback-journal mode initially.

## Initial Schema

P0 tables:

```text
runs
phases
phase_attempts
events
artifact_sources
projection_warnings
```

Use `STRICT` tables where supported. Store event payloads as checked JSON text.
Record a `json_source_sha` for the projected source snapshot so divergence is
detectable.

## Implementation Steps

1. Add `state_projector_schema.sql` with `PRAGMA foreign_keys = ON`,
   `PRAGMA journal_mode = DELETE`, and `PRAGMA busy_timeout = 5000`.
2. Add `project_run(run_id, data_dir)` that reads the canonical JSON files and
   rebuilds the mirror in a temp file.
3. Use `os.replace()` to move the temp DB into place only after all inserts and
   integrity checks pass.
4. Record source paths and source hashes in `artifact_sources`.
5. Add projection warnings for missing optional artifacts instead of crashing
   the whole projection.
6. Add `diff_mirror(run_id, data_dir)` that re-projects to a temp DB and
   compares tables against the live mirror.
7. Add CLI commands for project, mirror query, and diff.
8. Wire Phase 4 eval to optionally query the mirror and assert parity with
   JSON-derived trace output.
9. After dogfood, let status/doctor/TUI prefer mirror reads with JSON fallback.

## Failure Handling

- Mirror missing: re-project or read JSON directly.
- Mirror corrupt: delete/re-project; operator commands continue from JSON.
- Projection warning: surface through doctor and eval, but keep commands
  usable.
- Divergence: treat as a schema/projector bug, not a JSON bug.

## Acceptance Criteria

- A run can be projected deterministically from JSON to SQLite.
- `swarm state diff-mirror` reports zero divergence on clean fixtures.
- Trace/eval can compare JSON trace output with mirror-derived output.
- Mirror corruption never blocks recovery/status commands.
- No write path treats the mirror as canonical.

## Tests

Required targeted tests:

```text
py/swarm_do/pipeline/tests/test_state_projector.py
py/swarm_do/pipeline/tests/test_state_projector_diff.py
py/swarm_do/pipeline/tests/test_run_eval.py
```

Regression boundary:

```text
py/swarm_do/telemetry/tests/test_query_parity.py
py/swarm_do/telemetry/tests/test_jsonl.py
py/swarm_do/telemetry/tests/test_schemas.py
```

## Handoff Notes

List every JSON field that was intentionally not projected. Those omissions are
the Phase 9 schema review input, not quiet follow-ups hidden in code comments.
