# Phase 4 - Run Trace, Replay, And Eval

Date: 2026-05-02
Status: active implementation plan
Source section: `docs/swarmdaddy-runtime-foundations-adoption-plan-2026-05-02.md` Phase 4
Audit: 2026-05-02 senior-engineer review folded in (see §Concerns And Guardrails,
§Open Questions Resolved, and verified field-source citations throughout).

## Objective

Create a read-only trace and fixture-backed eval harness over durable run
artifacts. The harness should verify control-plane behavior without live
Claude/Codex calls.

## Why This Is The Behavioral Test Net

SwarmDaddy is a local development harness. Its highest leverage reliability
move is not a richer graph runtime; it is being able to replay and assert what
the control plane did from the artifacts it already wrote. This phase should
make later refactors safer, especially the read-only projector and any future
state backend change.

## Dependencies

Can start while Phase 1 is in progress:

- P0 reads existing JSON artifacts directly through current helper functions.
- Once Phase 1 lands, move reads behind `state_store.py` or owner readers where
  that reduces duplication.
- Do not wait for Phase 4.5. The projector should consume this harness, not
  block it.

Coordinate with the live stage marker streaming plan. `AttemptTrace` must carry
`command.json.stage_controller` counters as opaque optional metadata when they
exist. The streaming plan locks the canonical counter field names (see
`phase-session-live-stage-marker-streaming-plan.md` §Phase 4 — Capability And
Metadata): `pending_marker_count`, `duplicate_marker_count`, `amended_count`,
`rejected_marker_count`, `rejected_unknown_stage`, `rejected_invalid_path`,
`rejected_invalid_result`, `parse_error`, `legacy_json_retry`,
`ignored_frame_types`. **Renaming any of these requires a coordinated update
between Phase 4 and the streaming plan.**

⚠️ GUARDRAIL: order-of-merge with streaming plan. Streaming plan is intended
to ship first and locks the contract. If streaming lands after Phase 4, ship
Phase 4 with the `stage_controller` reader present but the streaming-fixture
family (see §Implementation Steps step 5, last bullet) gated behind a TODO.
Everything else in Phase 4 is independent.

⚠️ GUARDRAIL: rebase against Phase 1. Phase 1's acceptance criteria pin
"existing persisted file paths and JSON shapes are unchanged" — Phase 4
readers go through public load functions only and are unaffected by Phase 1
internal moves.

⚠️ GUARDRAIL: Phase 4.5 contract direction. Trace JSON contract is owned
here, file-based forever. Phase 4.5 (read-only SQLite projector) is a
*consumer* of the same on-disk artifacts (or of `RunTrace` directly), not a
producer. If 4.5 needs a change, it lives in 4.5.

## Scope

Owned files:

```text
py/swarm_do/pipeline/run_trace.py
py/swarm_do/pipeline/run_eval.py
py/swarm_do/pipeline/tests/test_run_trace.py
py/swarm_do/pipeline/tests/test_run_eval.py
py/swarm_do/pipeline/tests/test_run_trace_is_read_only.py
py/swarm_do/pipeline/tests/test_run_trace_determinism.py
tests/fixtures/run-traces/
docs/eval-recipes.md
```

CLI surfaces:

```text
swarm trace build <run-id> [--json] [--out <path>] [--data-dir <dir>]
swarm eval run <fixture-dir> [--json]
swarm eval record <run-dir> --to <fixture-dir>
```

Run-id resolution: `swarm trace build <run-id>` resolves to
`resolve_data_dir() / "runs" / <run-id>` (matches the pattern at
`py/swarm_do/pipeline/resume.py:188`). The `--data-dir` flag overrides for
tests.

## Non-Goals

- No deterministic replay of model reasoning.
- No live Claude/Codex calls in unit tests.
- No new source of truth for state.
- No SQLite dependency in P0.
- No event envelope or hook lifecycle.
- No content-redaction logic; trace stores paths and digests only (see
  Concerns §PII).
- No property-based testing for trace readers in P0; golden fixtures are the
  primitive.
- No JSON Schema files on disk for fixture validation; embed schema in
  `run_eval.py`.

## Verified Artifact Families And Source Map

Trace readers consume the following on-disk artifact families. File:line
citations verify presence in the codebase as of 2026-05-02. Trace stores
PATHS and DIGESTS only — content is never inlined (see Concerns §PII).

| Family | Path under `data/runs/<run-id>/` | Owner module (writer) | Verification |
|---|---|---|---|
| Prepared plan | `prepared_plan.v1.json` | `prepared_artifact_writer.py`, `prepare.py` | `prepare.py:43` `SCHEMA_VERSION = 1` |
| Phase sessions | `phase_sessions.v1.json` | `phase_sessions.py` | `phase_sessions.py:35` `SCHEMA_VERSION = 1` |
| Stage sessions | `stage_sessions.v1.json` | `stage_sessions.py` | Phase 1 fence whitelist |
| Shared decisions | `shared_decisions.v1.json` | `phase_decisions.py` | `phase_decisions.py:13` `SCHEMA_VERSION = 1` |
| Active run pointer | `active_run.json` | `run_state.py` | Phase 1 fence whitelist |
| Per-attempt evidence | `phases/<phase>/attempts/<n>/evidence.json` | `phase_evidence.py` | `phase_evidence.py:16-17` `MANIFEST_SCHEMA_VERSION = 1`, `MANIFEST_FILENAME = "evidence.json"` |
| Per-attempt command metadata | `phases/<phase>/attempts/<n>/command.json` | launcher-visible workspace metadata (not state) | streaming plan §Phase 4 — Capability And Metadata locks `stage_controller.*` field names |
| Per-attempt prompt/stdout/stderr/result/handoff | same dir: `prompt.txt`, `stdout.txt`/`stdout.stream.jsonl`, `stderr.txt`/`stderr.stream.txt`, `result.json`, `handoff.json` | various | `phase-artifact-contract.md §Required Identity` |
| Provider review | `<artifact>.provider-review.manifest.json` | `provider_evidence.py` | `provider_evidence.py:139` |
| Worktree manifest | `worktrees/<run-id>/manifest.json` | `execution_worktree.py` | `tests/test_execution_worktree.py:150` |
| Run events | `telemetry/run_events.jsonl` (data-dir scoped, not run-dir scoped) | `run_state.py` | `run_state.py:63`, `resume.py:188` |
| Post-writer report | per-attempt `post_writer_report.v1` | `post_writer.py` | `post_writer.py:16` (`SCHEMA_VERSION = "post_writer_report.v1"`, string-versioned) |
| Provider findings (mco) | per-stage `provider-findings.v1-draft` | `mco_stage.py` | `mco_stage.py:27` (`SCHEMA_VERSION = "provider-findings.v1-draft"`, string-versioned — see Concerns §heterogeneous schemas) |

🚨 CONCERN: `mco_stage.py:27` and `post_writer.py:16` use string-style
schema versions while every other family uses integer `SCHEMA_VERSION = 1`.
The trace reader normalizes to a `{family, version_str}` shape so callers
do not need to branch on encoding. This inconsistency is flagged for Phase 2
to clean up; Phase 4 does not fix it.

## Trace Shape

`RunTrace` is a derived view assembled by reading the artifacts in §Verified
Artifact Families And Source Map. Trace records paths and digests; it never
inlines `prompt.txt`, `stdout.txt`, `stderr.txt`, `result.json`,
`handoff.json`, or `evidence.json` content (see Concerns §PII).

```jsonc
{
  "schema_version": 1,                       // integer; matches existing project convention
  "run_id": "<str>",
  "data_dir": "<abs path>",                  // absolute path the trace was built against
  "run_dir": "<abs path>",                   // data_dir/runs/<run_id>
  "source_paths": { "<family>": "<rel path>" },          // every path the trace read from
  "source_digests": { "<rel path>": "<sha256>" },
  "phases": [PhaseTrace, ...],               // ordered by phase_id then start time
  "attempts": [AttemptTrace, ...],           // ordered by (phase_id, attempt_number)
  "provider_reviews": [ProviderReviewTrace, ...],        // projects provider-review.manifest.json
  "worktree_observations": [WorktreeObservation, ...],   // worktrees/<run-id>/manifest.json over time
  "run_event_summary": { "count": N, "kinds": {kind: count}, "last_seq": N, "path": "<rel>" },
  "run_event_recent": [RunEventRow, ...],    // capped at 200; full read via fixture flag (GUARDRAIL: trace size)
  "artifacts": [ArtifactRef, ...],           // every file under run_dir, classified or unclassified
  "warnings": [TraceWarning, ...],           // missing optional artifacts, parse warnings
  "unrecognized_artifacts": ["<rel path>", ...],         // forces Phase 4 update when a new family lands
  "summary": { "phases": N, "attempts": N, "warnings": N, "unrecognized": N }
}
```

`AttemptTrace`:

```jsonc
{
  "phase_id": "<str>",
  "attempt_number": <int>,
  "launcher": "<claude|codex|...>",
  "command_json_path": "<rel>",
  "prompt_path": "<rel>",
  "stdout_path": "<rel>", "stdout_stream_path": "<rel|null>",
  "stderr_path": "<rel>", "stderr_stream_path": "<rel|null>",
  "result_path": "<rel|null>", "handoff_path": "<rel|null>",
  "evidence_path": "<rel|null>",
  "failure_kind": "<str|null>",              // values from failure-taxonomy.md
  "retry_decision": "<retryable|do_not_retry|...|null>",
  "tokens": {"input": N, "output": N} | null,
  "cost_usd": <float|null>,
  "changed_files": ["<path>", ...] | null,
  "stage_controller": null | {               // copied verbatim from command.json.stage_controller
    "live": <bool>, "completed": <bool>,
    "pending_marker_count": N, "duplicate_marker_count": N,
    "amended_count": N, "rejected_marker_count": N,
    "rejected_unknown_stage": N, "rejected_invalid_path": N,
    "rejected_invalid_result": N, "parse_error": N,
    "legacy_json_retry": N, "ignored_frame_types": {<frame>: N}
    // ⚠️ Field names locked by streaming plan §Phase 4 — Capability And Metadata.
  },
  "stream_metadata": null | { ... }          // command.json.stream_metadata, opaque pass-through
}
```

`TraceWarning = {kind: str, path: str, detail: str}`.

Schema versioning policy (locked):

- `schema_version` is integer (matches `phase_evidence.py:16`,
  `phase_decisions.py:13`, `phase_sessions.py:35`, `prepare.py:43`).
- v1 = the field set listed above. Any **rename** or **removal** is a bump.
  Additions of optional fields do **not** bump.
- Bump policy is documented in `run_trace.py`'s module docstring and
  cross-referenced from `eval-recipes.md`.

## Fixture Format

One fixture = one directory under `tests/fixtures/run-traces/<family>/`:

```text
<family>/
  expectation.yaml          # assertions (human-edited; comments allowed)
  run/                      # synthetic run dir mirroring data/runs/<run-id>/
    prepared_plan.v1.json
    phase_sessions.v1.json
    ...
  events.jsonl              # synthetic telemetry/run_events.jsonl slice
```

Worked example (`clean-single-phase/expectation.yaml`):

```yaml
schema_version: 1
required_artifacts:
  - prepared_plan.v1.json
  - phase_sessions.v1.json
  - phases/p1/attempts/0/evidence.json
expected_phase_transitions:
  - phase_id: p1
    statuses: [pending, running, complete]
expected_attempts:
  - phase_id: p1
    attempt_number: 0
    failure_kind: null
    retry_decision: null
expected_warnings: []
forbidden_warnings: [malformed_result]
unrecognized_artifacts_allowed: false
```

Fixtures are **YAML** (human edited; comments matter for golden updates).
The fixture JSON Schema lives embedded in `run_eval.py` and is asserted by
`test_run_eval.py`.

⚠️ GUARDRAIL: warning vs. required. `required_artifacts: [...]` are hard
fails on absence. Any optional artifact missing surfaces as
`RunTrace.warnings[]` and the eval still passes unless explicitly listed in
`forbidden_warnings`. The first-mismatch failure message format is:
`{kind, expected, actual, path}`.

## Read-Only Invariant Enforcement

🚨 CONCERN: read-only must be **enforced**, not asserted.

`run_trace.py` and `run_eval.py` MUST NOT write to disk. Enforced two ways:

1. Phase 1 write-fence test treats both modules as **consumers** — no
   entries in the writer whitelist. Pattern follows
   `py/swarm_do/pipeline/tests/test_prepared_artifact_fence.py`.
2. A dedicated test, `test_run_trace_is_read_only.py`, AST-scans both
   modules for: `Path.write_text`, `Path.write_bytes`, `open(..., "w"|"a"|
   "wb"|"ab")`, `json.dump`, `os.makedirs`, `os.mkdir`, `shutil.copy*`,
   `shutil.move`, and any `subprocess`/`os.system` call. Any match fails the
   test. The test ships in the same PR as `run_trace.py`.

CLI `swarm trace build` may write its JSON to stdout or `--out <path>`; if
`--out` is given, the write happens in `cli.py`, not in `run_trace.py`.

## Concerns And Guardrails

🚨 CONCERN: PII / secrets exposure. Prompts and stdout routinely contain
secrets (API keys, paths with usernames, tokens echoed by tools). **Hard
rule:** trace never inlines content of `prompt.txt`, `stdout.txt`,
`stderr.txt`, `result.json`, `handoff.json`, or `evidence.json`. Trace
stores **paths and digests only**. Eval assertions operate on paths, sizes,
presence, schema validity, and structured fields — never on free-form text
content.

🚨 CONCERN: Fixture brittleness. Every legitimate `command.json` schema
change breaks every fixture. Mitigation: ship `swarm eval record <run-dir>
--to <fixture-dir>` to regenerate `expectation.yaml` from a real run.
Without a regeneration tool, fixture maintenance becomes hand-edit hell
within one quarter.

🚨 CONCERN: `command.json` is **launcher-visible workspace metadata**, not
control-plane state. Eval assertions valid: `stage_controller.*` counter
values; presence of `command.json` itself. Eval assertions invalid:
launcher-specific argv shape. Document in fixture-authoring guide in
`eval-recipes.md`.

🚨 CONCERN: heterogeneous schema-version encoding. `mco_stage.py:27`
(string `"provider-findings.v1-draft"`) and `post_writer.py:16` (string
`"post_writer_report.v1"`) differ from the integer convention used
everywhere else. Reader normalizes to `{family, version_str}`; root cause
fix belongs to Phase 2.

⚠️ GUARDRAIL: Trace size bounds. A long-running run produces thousands of
`run_events.jsonl` rows. `RunTrace.run_event_recent[]` is capped at the
last 200; full event history is read on-demand via the
`load_full_events: true` fixture flag.

⚠️ GUARDRAIL: Determinism. Trace builders MUST be deterministic for the
same input dir:
- All list outputs sorted by stable keys (phase_id, attempt_number,
  event_seq, path).
- Timestamps preserved verbatim from artifacts (no clock reads).
- Paths normalized as relative to `data/runs/<run-id>/`.
- No environment reads.
- `test_run_trace_determinism.py` builds the same fixture twice and
  asserts byte-identical output.

⚠️ GUARDRAIL: New artifact families discovered post-merge. Trace builder
emits an `unrecognized_artifacts: [...]` list when scanning the run dir
finds files no reader classified. CI assertion: list is empty against
current fixtures, so adding a new family forces a Phase 4 update rather
than silent omission.

⚠️ GUARDRAIL: streaming plan ordering — see §Dependencies.

⚠️ GUARDRAIL: Phase 1 rebase plan — readers go through public load
functions; Phase 1 internal moves are invisible to Phase 4.

⚠️ GUARDRAIL: Phase 4.5 contract direction — file-based trace JSON is the
contract; 4.5 consumes, never mandates changes here.

## Implementation Steps

1. Add typed records (`@dataclass(frozen=True)`) for `RunTrace`,
   `AttemptTrace`, `PhaseTrace`, `ProviderReviewTrace`,
   `WorktreeObservation`, `RunEventRow`, `ArtifactRef`, `TraceWarning` in
   `run_trace.py`. Field names match §Trace Shape exactly. These are
   internal trace contracts, not persisted source state.
2. Add readers, one per family in §Verified Artifact Families. Each reader
   returns `(record | None, list[TraceWarning])`. Readers go through
   existing public load functions (`phase_evidence`, `phase_decisions`,
   `phase_sessions`, `stage_sessions`, `run_state`, `execution_worktree`,
   `provider_evidence`). Missing optional artifacts produce warnings;
   missing required artifacts (`prepared_plan.v1.json`,
   `phase_sessions.v1.json`, `active_run.json`, `manifest.json`) raise.
3. Add `swarm trace build <run-id> [--json] [--out <path>] [--data-dir
   <dir>]` to `bin/swarm` and `py/swarm_do/pipeline/cli.py`. Resolution:
   `resolve_data_dir() / "runs" / <run-id>` (see resume.py:188 pattern).
4. Add `run_eval.py` with fixture format defined in §Fixture Format.
   Loader validates `expectation.yaml` against the embedded JSON Schema.
   Add `--json` flag for machine-readable output.
5. Add golden fixture families under `tests/fixtures/run-traces/`:
   - `clean-single-phase/` — minimal happy path; ships as the canonical
     example in `eval-recipes.md`
   - `needs-input/`
   - `retryable-failure-then-success/`
   - `provider-review-partial-success/`
   - `worktree-drift/`
   - `malformed-result/`
   - `streaming-stage-adoption/` — gated on streaming plan landing
   Each family's `run/` dir is hand-built and version-controlled.
6. Add `swarm eval run <fixture-dir>`. Output names the FIRST mismatch:
   `{fixture, status: failed, first_mismatch: {kind, expected, actual,
   path}}`. Exit codes: `0`=pass, `1`=assertion fail, `2`=fixture-load
   error, `3`=missing run dir.
7. Add `swarm eval record <run-dir> --to <fixture-dir>` to regenerate
   `expectation.yaml` from a real run (see Concerns §fixture brittleness).
8. Add the read-only AST fence test (`test_run_trace_is_read_only.py`) and
   the determinism test (`test_run_trace_determinism.py`) — see §Read-Only
   Invariant Enforcement and §Concerns / Determinism.
9. Update `docs/eval-recipes.md` with §Adding A Fixture and §Dogfooding
   Against A Real Run.

## Eval Assertions

P0 assertions should cover:

- phase/session status transition order;
- attempt count and retry decisions;
- required evidence files;
- malformed artifact classification;
- provider review quorum/partial-success handling;
- worktree drift detection;
- presence and shape of run events;
- streaming `stage_controller` metadata when present.

CI integration: `swarm eval run tests/fixtures/run-traces/` runs in
unit-test CI alongside `test_run_eval.py`. No separate scheduled job.

## Acceptance Criteria

- Trace generation is read-only — verified by
  `test_run_trace_is_read_only.py` AND by Phase 1's write fence test
  (which lists `run_trace.py`/`run_eval.py` as consumers, not writers).
- Trace builder is deterministic — `test_run_trace_determinism.py` builds
  the same fixture twice and asserts byte-identical output.
- A fixture validates orchestration behavior without live model calls —
  every fixture under `tests/fixtures/run-traces/` runs in CI via
  `swarm eval run`.
- Failed eval output names the first mismatch in
  `{kind, expected, actual, path}` form. `test_run_eval.py` asserts the
  format.
- Trace JSON is versioned — `schema_version: 1` integer field present;
  bump policy documented in `run_trace.py` module docstring.
- Harness can run before and after Phase 4.5 — Phase 4.5 derives from the
  same on-disk artifacts; trace JSON shape is the contract; if 4.5 needs
  changes, they happen in 4.5, not in `run_trace.py`. The "compare" is
  fixture pass/fail equivalence, not byte-diff of trace output.
- `swarm trace build <run-id>` resolves via `resolve_data_dir()` and
  accepts `--data-dir` for tests.
- `swarm eval run` and `swarm eval record` ship in the same PR as the
  fixture families.

## Tests

Required targeted tests:

```text
py/swarm_do/pipeline/tests/test_run_trace.py
py/swarm_do/pipeline/tests/test_run_eval.py
py/swarm_do/pipeline/tests/test_run_trace_is_read_only.py
py/swarm_do/pipeline/tests/test_run_trace_determinism.py
```

`test_run_trace.py` covers per-reader unit tests plus one full-build
integration test per fixture family. `test_run_eval.py` covers the
assertion engine (transition order, required artifacts, warnings, exit
codes, `--json` output) and the fixture schema. The read-only and
determinism tests are described in §Read-Only Invariant Enforcement and
§Concerns / Determinism.

Also run the Phase 1 regression tests if trace readers touch state helper
paths.

## Open Questions Resolved

For audit-trail; each item below was an open question discovered during
plan review (2026-05-02) and is now resolved in the body above.

- **Schema version field name and bump policy.** Resolved: integer
  `schema_version`; rename/remove bumps, optional adds do not. See
  §Trace Shape.
- **`provider_runs[]`/`worktree_events[]`/`run_events[]` invented vs.
  defined?** Invented in the original draft. Resolved: renamed to
  `provider_reviews[]`, `worktree_observations[]`, `run_event_summary` +
  `run_event_recent[]` and locked in §Trace Shape.
- **Fixture format (YAML/JSON, schema, example).** Resolved: YAML;
  embedded schema; worked example in §Fixture Format.
- **Streaming plan order-of-merge.** Resolved: streaming first; if not,
  ship `streaming-stage-adoption` fixture gated. See §Dependencies.
- **Trace warnings mechanism.** Resolved: `warnings: TraceWarning[]` field;
  `expected_warnings` / `forbidden_warnings` in fixture. See §Fixture
  Format.
- **Run-id resolution.** Resolved:
  `resolve_data_dir() / "runs" / <run-id>`; `--data-dir` override. See
  §Scope.
- **CI integration.** Resolved: unit-test CI; no separate scheduled job.
  See §Eval Assertions.
- **Exit codes and `--json` for `swarm eval run`.** Resolved: 0/1/2/3 with
  `first_mismatch` shape. See §Implementation Steps step 6.
- **Phase 1 rebase plan.** Resolved: read through public load functions;
  internal moves invisible. See §Dependencies guardrail.
- **Phase 4.5 contract direction.** Resolved: file-based trace JSON is the
  contract; 4.5 consumes. See §Dependencies guardrail.
- **Handoff Notes template.** Resolved: structured table. See §Handoff
  Notes.
- **Heterogeneous schema-version encoding.** Resolved: reader normalizes;
  fix belongs to Phase 2. See Concerns.

## Handoff Notes

Emit a table of artifact families the trace does NOT yet cover. Format:

| Family | Path glob | Reason not covered | Needed for |
|---|---|---|---|

These gaps are inputs for Phase 4.5 schema and Phase 2 contracts, not
silent SQL workarounds.
