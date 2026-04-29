# Phase Session Foundation Plan

Date: 2026-04-29
Status: Proposed, revised after code validation
Owner: swarm-do runtime, dispatcher, and TUI surfaces

## Goal

Let SwarmDaddy run a large accepted prepared plan one phase at a time in fresh
execution contexts without requiring the operator to manually restart every
phase, while reducing token and tool-call waste inside workers.

This is not only an auto-advance feature. If we launch fresh phase sessions but
keep handing every worker broad plan/session context, the system will still burn
context and tools. The foundation therefore combines two changes:

1. durable phase-session scheduling and resume state;
2. lazy, scoped context bundles rendered for each requested phase, work unit,
   and role.

The long-term north star is a reliable control plane that can survive context
compaction, process failure, operator interruption, and eventual daemonization
without changing the execution contract again.

## Validation Summary

The review verdict was correct: the prior plan was directionally sound but not
execution-ready. These claims were validated against the repo:

- Data paths must be derived through `py/swarm_do/pipeline/paths.py`
  `resolve_data_dir()`. It reads `CLAUDE_PLUGIN_DATA` when set and falls back to
  repo-local `data/`. New code should not hard-code `${CLAUDE_PLUGIN_DATA}` as
  the contract.
- Atomic JSON writes exist in `run_state.py`, `prepare.py`, `actions.py`, and
  `rollout.py`, but there is no `fcntl`, `flock`, or shared advisory lock helper
  in `py/swarm_do/pipeline/`. Phase sessions must add their own lock contract
  instead of claiming reuse.
- Schema files live under repo-root `schemas/`; telemetry schemas live under
  `schemas/telemetry/`. New schema paths in this plan are repo-relative paths
  such as `schemas/phase_sessions.schema.json`, not data-dir paths.
- `py/swarm_do/pipeline/context.py` already owns preset/pipeline telemetry
  context. The new module must be `py/swarm_do/pipeline/context_bundle.py`.
- `schemas/telemetry/run_events.schema.json` has a closed `event_type` enum.
  Every new run event must be listed in that enum and covered by tests.
- Existing run `data/runs/01KQAC90FK5FNF4JWXMXHHR2AQ/prepared_plan.v1.json` is
  accepted, has phase ids `1` through `7`, and has no phase-session state. The
  rollout must include an init/backfill story for existing prepared runs.

## Recommendation

Build deterministic CLI primitives and TUI controls first. Do not build a daemon
as the first implementation.

Robustness should come from durable on-disk state, idempotent commands, leases,
atomic writes, checkpoints, explicit resume manifests, and a small advisory lock
around state transitions. A daemon can be added later as a thin runner over the
same commands if unattended background execution becomes important enough.

The first production shape should be:

```text
accepted prepared artifact
  -> phase-session state file
  -> lazy phase/context bundle renderer
  -> foreground phase pump CLI
  -> TUI action that invokes/monitors the same pump
  -> optional daemon wrapper later
```

The crucial constraint: phase sessions are bounded workers. They may claim one
phase, render the context for that phase, launch a fresh execution context, and
record a structured result. They do not recursively decide the global plan,
rewrite the phase queue, or spawn another open-ended orchestrator.

## Current SwarmDaddy Foundation

SwarmDaddy already has the right source-of-truth pieces:

- Prepared artifacts are the execution contract:
  `schemas/prepared_plan.schema.json` requires `phase_map`,
  `work_unit_artifacts`, source/prepared hashes, git base, review findings, and
  acceptance state.
- Prepared dispatch is pure consumption:
  `py/swarm_do/pipeline/prepare.py::verify_prepared_for_dispatch` loads an
  accepted artifact, checks schema/trust boundaries/staleness/sidecars, appends
  `prepare_dispatch_started`, and returns a dispatch result.
- Resume is manifest-based:
  `py/swarm_do/pipeline/resume.py::build_resume_report` returns `prepared`,
  `ready`, `complete`, `drift`, or `not-found`, plus `resume_from` and
  `completed_units`.
- Active state and checkpoints already include prepared metadata:
  `py/swarm_do/pipeline/run_state.py::write_checkpoint_from_active` persists
  `phase_map`, `review_findings`, and `work_unit_artifacts`.
- Work-unit scheduling is deterministic inside one phase:
  `py/swarm_do/pipeline/executor.py` computes ready units, batches, and resume
  points from a work-unit artifact plus state.
- The dispatcher skill has a hard invariant:
  do not duplicate the resume orchestration protocol; resume injects a manifest
  into the existing dispatcher.

This means the right change is additive: a phase-session state layer and a
context renderer over the existing prepared artifact. It should not be a second
planner.

## Path And Schema Rules

Use these path rules everywhere in the implementation:

```text
data_dir = py.swarm_do.pipeline.paths.resolve_data_dir()
repo_root = py.swarm_do.pipeline.paths.REPO_ROOT

data_dir/runs/<run_id>/phase_sessions.v1.json
data_dir/runs/<run_id>/context/<phase_id>/...
data_dir/runs/<run_id>/phase_results/<phase_id>/attempt-<n>.result.json
data_dir/runs/<run_id>/phase_handoffs/<phase_id>/attempt-<n>.handoff.json
```

Schema files are repo-root files:

```text
schemas/phase_context.schema.json
schemas/phase_sessions.schema.json
schemas/phase_result.schema.json
schemas/phase_handoff.schema.json
schemas/telemetry/run_events.schema.json
```

Human-readable Markdown mirrors may be written next to JSON artifacts, but JSON
is authoritative for CLI/TUI/resume.

## Phase Identity And Dependency Model

Phase ids are not derived from titles, indexes, work-unit ids, or filenames.
They are copied exactly from the accepted prepared artifact:

```python
for phase_index, phase in enumerate(prepared_plan["phase_map"]):
    phase_id = phase["phase_id"]
```

For v1, phase dependencies are sequential by `phase_map` array order:

- phase `phase_map[0]` has no phase dependency;
- phase `phase_map[i]` depends on `phase_map[i - 1]` being `complete`;
- work-unit DAG dependencies remain inside each phase's
  `work_unit_artifacts[phase_id]` sidecar;
- no parallel phase execution is allowed in v1;
- future parallel execution must add explicit phase dependency metadata to the
  prepared artifact or a new schema version.

The phase-session state should persist `phase_index` and
`depends_on_phase_ids` so the CLI can explain why a phase is not claimable.

## Context Bundle Contract

Context bundles are rendered lazily. The renderer writes only the requested
`run_id` + `phase_id` + optional `unit_id` + `role` bundle, not the full
`phases x roles x units` cartesian product.

Example data-dir layout:

```text
data_dir/runs/<run_id>/context/<phase_id>/
  dispatcher.context.json
  dispatcher.prompt.md
  phase-summary.md
  decisions.md
  previous-handoff.md
  units/<unit_id>/agent-writer.context.json
  units/<unit_id>/agent-writer.prompt.md
  units/<unit_id>/agent-spec-review.context.json
  units/<unit_id>/agent-spec-review.prompt.md
```

Suggested `*.context.json` fields:

```json
{
  "schema_version": 1,
  "run_id": "01...",
  "phase_id": "2",
  "phase_index": 1,
  "role": "agent-writer",
  "work_unit_id": "unit-2-1",
  "source_artifact_path": "data/runs/01.../prepared_plan.v1.json",
  "prepared_plan_sha": "sha256...",
  "phase_content_sha": "sha256...",
  "work_unit_artifact_path": "data/runs/01.../work_units/2.<hash>.work_units.v2.json",
  "work_unit_artifact_sha": "sha256...",
  "allowed_files": ["py/swarm_do/pipeline/..."],
  "blocked_files": [],
  "context_files": ["py/swarm_do/pipeline/..."],
  "acceptance_criteria": [],
  "validation_commands": [],
  "prior_decisions_path": "data/runs/01.../context/2/decisions.md",
  "previous_handoff_path": "data/runs/01.../context/2/previous-handoff.md",
  "source_list": [],
  "warnings": [],
  "max_prompt_bytes": 24000,
  "prompt_bytes": 0,
  "estimated_tokens": 0,
  "rendered_prompt_path": "data/runs/01.../context/2/units/unit-2-1/agent-writer.prompt.md"
}
```

Rules:

- The controller renders context. Workers receive rendered prompts plus artifact
  pointers. They should not be told to read the whole prepared plan.
- Include exact phase text only when it fits under budget. Otherwise include a
  phase summary plus artifact path and sha.
- Include completed prior-phase handoff summaries, not full prior transcripts.
- Include exact allowed/blocked files, validation commands, acceptance
  criteria, retry count, handoff count, and budget ceilings.
- Include `mem_prime` output when available, but only as a bounded artifact.
- Record prompt byte count, estimated token count, and context source list.
- Re-rendering the same inputs is idempotent and produces stable JSON/Markdown
  except for an optional `rendered_at` field.
- The module name is `py/swarm_do/pipeline/context_bundle.py`; do not reuse
  `pipeline/context.py`.

### Role Persona Boundary

This renderer augments the role-spec layer; it does not replace it.

- `role-specs/` remains the source for generated `agents/`, `roles/`, and
  `permissions/` artifacts.
- `bin/load-role.sh` remains the shell helper used by the dispatcher skill to
  inject existing role personas.
- The context bundle renderer supplies task context and artifact pointers. If it
  needs persona byte telemetry, use the existing generated role artifacts or
  `bin/load-role.sh --manifest`; do not fork a second role-spec renderer in this
  phase.

## Phase-Session State Model

Add one phase-session state file under the run directory:

```text
data_dir/runs/<run_id>/phase_sessions.v1.json
```

Shape:

```json
{
  "schema_version": 1,
  "run_id": "01...",
  "prepared_artifact_path": "data/runs/01.../prepared_plan.v1.json",
  "prepared_plan_sha": "sha256...",
  "created_at": "2026-04-29T00:00:00Z",
  "updated_at": "2026-04-29T00:00:00Z",
  "mode": "cli-pump",
  "lease_policy": {
    "claim_ttl_seconds": 900,
    "running_ttl_seconds": 14400,
    "refresh_interval_seconds": 300
  },
  "phases": [
    {
      "phase_id": "1",
      "phase_index": 0,
      "title": "Bootstrap",
      "depends_on_phase_ids": [],
      "status": "pending",
      "lease_owner": null,
      "lease_host": null,
      "lease_pid": null,
      "lease_command": null,
      "lease_expires_at": null,
      "attempt": 0,
      "session_name": null,
      "started_at": null,
      "completed_at": null,
      "result_path": null,
      "handoff_path": null,
      "last_error": null
    }
  ]
}
```

State transitions:

```text
pending -> leased -> running -> complete
                       |        -> failed
                       |        -> blocked
                       |        -> needs_input
leased/running -> stale -> pending
```

Rules:

- `init` derives phases only from an accepted prepared artifact.
- `phase_id` equals `prepared_plan.phase_map[i].phase_id` exactly.
- `claim` verifies the prepared artifact before leasing.
- `claim` returns the first pending phase whose prior phase dependency is
  complete.
- `claim`, `start`, `refresh`, `complete`, `fail`, and `reap` hold a new
  advisory state lock while reading, validating, mutating, and atomically
  writing `phase_sessions.v1.json`.
- The lock is new implementation work. It should live in `phase_sessions.py`,
  use a sibling `phase_sessions.v1.lock` file, and be held only around state
  mutation, never while a launcher is running.
- The v1 lock backend is stdlib `fcntl.flock(..., LOCK_EX)` on POSIX. If a
  non-POSIX fallback is added later, it must live behind the same helper and
  pass the same tests.
- Lock acquisition waits up to 10 seconds by default, then fails with a clear
  message that includes the run id and lock path.
- Atomic writes should reuse or mirror the existing
  `run_state._atomic_json_write` pattern: same-directory temp file, fsync,
  `os.replace`.
- One phase can be running at a time by default. Parallel phase sessions are a
  future schema version.
- Expired leases are not silently overwritten by workers. A coordinator command
  marks them `stale` and records why.
- Completion requires a structured result file and a structured handoff
  artifact.
- JSON state is authoritative; Markdown status/handoff files are mirrors.

### Lease Policy

Persisted lease times use timezone-aware UTC timestamps from
`run_state.utc_now()`. Expiry checks compare persisted UTC wall-clock timestamps
to the current UTC wall clock. A monotonic clock cannot be persisted safely
across processes, so clock skew is treated as an operator/environment issue and
reported in `details` when detected.

Default policy:

- `claim_ttl_seconds`: 900. A claim reserves the phase long enough to render
  context and start a launcher.
- `running_ttl_seconds`: 14400. Starting a phase extends the lease to four
  hours by default.
- `refresh_interval_seconds`: 300. The foreground pump refreshes the running
  lease every five minutes while a child launcher is active.

Commands:

- `phases claim` sets `lease_expires_at = now + claim_ttl_seconds`.
- `lease_owner` is generated by the CLI/helper as
  `<hostname>:<pid>:<uuid4-hex>` unless explicitly supplied by tests.
- `phases start` increments `attempt`, records session/launcher metadata, and
  sets `lease_expires_at = now + running_ttl_seconds`.
- `phases refresh` extends only a currently `running` phase owned by the same
  `lease_owner`.
- `phases reap` marks expired `leased` or `running` phases as `stale` and
  emits `phase_session_lease_expired`.
- `phases claim --reclaim-stale` may move a stale phase back to `pending` and
  then claim it; default `claim` only reports the stale lease.

## Result And Handoff Contracts

### Worker-To-Controller Result

The controller consumes a structured result file:

```text
data_dir/runs/<run_id>/phase_results/<phase_id>/attempt-<n>.result.json
```

Schema path: `schemas/phase_result.schema.json`.

Required fields:

```json
{
  "schema_version": 1,
  "run_id": "01...",
  "phase_id": "1",
  "phase_attempt": 1,
  "status": "complete",
  "launcher": "manual",
  "session_name": "swarmdaddy-01...-1",
  "prepared_plan_sha": "sha256...",
  "phase_content_sha": "sha256...",
  "started_at": "2026-04-29T00:00:00Z",
  "completed_at": "2026-04-29T00:00:00Z",
  "handoff_path": "data/runs/01.../phase_handoffs/1/attempt-1.handoff.json",
  "summary": "Short factual summary.",
  "completed_work_units": [],
  "failed_work_units": [],
  "blocked_reason": null,
  "needs_input": [],
  "validation": [],
  "artifacts": [],
  "error": null
}
```

`status` enum:

```text
complete
failed
blocked
needs_input
```

Launcher adapters may receive this JSON directly from a child process, or they
may parse the child output and write the result file themselves. Either way,
`phases complete/fail/block/needs-input` validates this schema before mutating
phase-session state.

### Phase Handoff Artifact

The durable handoff is also structured:

```text
data_dir/runs/<run_id>/phase_handoffs/<phase_id>/attempt-<n>.handoff.json
```

Schema path: `schemas/phase_handoff.schema.json`.

Required fields:

```json
{
  "schema_version": 1,
  "run_id": "01...",
  "phase_id": "1",
  "phase_attempt": 1,
  "status": "complete",
  "written_at": "2026-04-29T00:00:00Z",
  "summary": "What changed and why.",
  "decisions": [],
  "changed_files": [],
  "completed_work_units": [],
  "open_items": [],
  "blockers": [],
  "do_not_retry": [],
  "validation_summary": [],
  "artifacts": [],
  "next_phase_context": []
}
```

The context renderer reads only prior completed handoff summaries and explicitly
listed `next_phase_context` entries. It does not ingest full prior transcripts.

## Run Events

Update `schemas/telemetry/run_events.schema.json` in the same implementation
phase that first writes these events. The exact enum additions are:

```text
phase_session_initialized
phase_session_claimed
phase_session_started
phase_session_refreshed
phase_session_completed
phase_session_failed
phase_session_blocked
phase_session_needs_input
phase_session_lease_expired
phase_result_recorded
phase_handoff_recorded
phase_context_rendered
phase_pump_started
phase_pump_stopped
phase_pump_launcher_ineligible
```

Event details should include enough state to debug without reading child
transcripts: `phase_index`, `phase_id`, `attempt`, `lease_owner`,
`lease_expires_at`, `launcher`, `session_name`, result/handoff paths, and
schema validation status where relevant.

## Resume Ownership

Avoid a `phase_sessions.py` <-> `resume.py` cycle.

- `phase_sessions.py` owns load/validate/write/state-transition helpers.
- `phase_sessions.py` must not import `resume.py`.
- `resume.py` may read phase-session summaries through a read-only helper from
  `phase_sessions.py`.
- `resume.py` must never mutate `phase_sessions.v1.json`.
- CLI commands are responsible for mutation. Resume only reports status and the
  next recommended command.

Resume output must distinguish:

- accepted prepared artifact waiting for phase-session init;
- phase queue initialized, next phase pending;
- phase currently leased/running;
- stale lease requiring `phases reap` or explicit reclaim;
- phase blocked/needs input;
- all phases complete;
- drift between checkpoint/run events/prepared artifact.

## Launcher Adapters

The launcher is an adapter, not the control plane.

### Adapter 1: manual

MVP and always available. It renders the next phase dispatcher prompt and prints
the exact command/instructions for an operator to run. This is the fallback and
debugging path.

Manual mode may claim/start a phase only when the operator asks the pump to
reserve it. It must print the follow-up command that records completion from a
validated result file:

```bash
bin/swarm phases complete <run-id> --phase <phase-id> --json-file <result.json>
```

### Adapter 2: fake-test

Test-only adapter used by `test_phase_pump.py`. It returns deterministic
`phase_result` and `phase_handoff` fixtures without invoking real agents.

### Adapter 3: claude-print

Later adapter, not part of the MVP pump. It may be enabled only after a local
capability probe and a committed parser fixture prove the output contract:

```bash
claude -p \
  --name "swarmdaddy-<run-id>-<phase-id>" \
  --output-format json \
  --max-turns <n> \
  --max-budget-usd <budget> \
  --permission-mode <mode> \
  "$(cat <dispatcher.prompt.md>)"
```

Before writing a parser, commit a fixture under
`py/swarm_do/pipeline/tests/fixtures/claude_print/` that shows the actual JSON
shape produced by a successful phase run and a failed/blocked run. Until those
fixtures exist, `claude-print` is reported as ineligible.

Capability probe must verify:

- `claude` exists and version is supported;
- print mode can run in the target repo;
- plugin path and environment are available;
- hooks fire or explicit equivalents are rendered;
- permissions behave predictably;
- subagent dispatch is available, or the phase prompt uses only headless-safe
  execution paths;
- output can be parsed into `schemas/phase_result.schema.json`.

### Adapter 4: interactive

Potential later adapter. Starts a named interactive session with an initial
prompt. It may be useful for users who want a visible separate session per
phase, but it is harder to supervise automatically than print mode.

### Adapter 5: daemon

Future wrapper. It should reuse the same phase-session helpers and launcher
adapters. It must not introduce a second state database or a second resume
protocol.

## Dispatcher Boundary

The pump cannot call "the dispatcher skill" as Python. The dispatcher is a
Claude Code skill/prompt surface, not an importable runtime module.

For MVP, the pump may only:

1. verify the prepared artifact through Python helpers;
2. claim/start a phase through Python helpers;
3. render a phase-scoped dispatcher prompt;
4. hand that prompt to the manual adapter or a proven launcher adapter;
5. validate the structured result/handoff files;
6. record state, checkpoint, and run events.

The phrase "reuse existing dispatcher logic" means reuse the existing prepared
artifact and dispatcher prompt contract from a fresh Claude context. It does not
mean importing or reimplementing the dispatcher skill in Python.

## CLI Surface

Recommended primitives:

```bash
bin/swarm sessions doctor [--json] [--live]

bin/swarm context render \
  --run-id <run-id> \
  --phase <phase-id> \
  --role dispatcher|agent-writer|agent-spec-review|agent-review|agent-docs \
  [--unit <unit-id>] \
  --json

bin/swarm phases init <run-id> [--json]
bin/swarm phases status <run-id> [--json]
bin/swarm phases claim <run-id> [--json] [--reclaim-stale]
bin/swarm phases start <run-id> --phase <phase-id> --launcher <name> [--json]
bin/swarm phases refresh <run-id> --phase <phase-id> --lease-owner <owner> [--json]
bin/swarm phases complete <run-id> --phase <phase-id> --json-file <result.json>
bin/swarm phases fail <run-id> --phase <phase-id> --json-file <result.json>
bin/swarm phases block <run-id> --phase <phase-id> --json-file <result.json>
bin/swarm phases needs-input <run-id> --phase <phase-id> --json-file <result.json>
bin/swarm phases reap <run-id> [--json]

bin/swarm phases pump <run-id> \
  --launcher manual|fake-test|claude-print \
  --max-phases <n|all> \
  [--stop-on-checkpoint]
```

## Testing Bootstrap

All implementation phases should pin the repo-local package path in validation
commands. Do not rely on the shell shim hiding import setup when documenting
Python unit test commands.

Baseline command form:

```bash
PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_phase_sessions
PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_context_bundle
PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_phase_pump
```

Use broader discovery only when the phase touches shared contracts:

```bash
PYTHONPATH=py python3 -m unittest discover -s py -p 'test_*.py'
```

## Rollout And Backfill

Existing prepared runs must remain readable. Do not require a migration before
`resume` or current prepared dispatch keeps working.

Rules:

- `phases status <run-id>` reports `not_initialized` when an accepted prepared
  artifact exists but `phase_sessions.v1.json` does not.
- `phases init <run-id>` creates phase-session state from the accepted prepared
  artifact without changing `prepared_plan.v1.json`.
- Existing phase completion is not inferred from `prepare_dispatch_started`.
  That event only proves dispatch began, not that any phase completed.
- Backfill defaults every phase to `pending` unless a future trusted
  `phase_session_completed` event exists for that exact `phase_id`.
- Add a dry-run backfill/status test using a fixture copied from
  `01KQAC90FK5FNF4JWXMXHHR2AQ` so the accepted-run/no-session-state case is
  locked down without depending on mutable local data.
- If a run has stale or invalid phase-session JSON, `status` reports drift and
  refuses mutation until the operator backs up or repairs the file.

## Implementation Plan

### Phase 0 - Capability And Contract Spike

Objective: prove which launch modes are real on this machine and freeze the
contracts before building automation.

Files:

| File | Change |
| --- | --- |
| `docs/phase-session-foundation-plan.md` | This revised plan. |
| `py/swarm_do/pipeline/session_capabilities.py` | New local probes for `claude`, print mode, plugin env, output parsing, and optional subagent/plugin behavior. |
| `py/swarm_do/pipeline/cli.py` | Add `bin/swarm sessions doctor [--json] [--live]`. |
| `py/swarm_do/pipeline/tests/test_session_capabilities.py` | Fake-runner tests for pass, missing CLI, unsupported feature, malformed JSON. |
| `py/swarm_do/pipeline/tests/fixtures/claude_print/README.md` | Documents that real fixtures are required before enabling `claude-print`. |

Definition of done:

- `bin/swarm sessions doctor --json` reports launcher eligibility for
  `manual`, `fake-test`, `claude-print`, and `interactive`.
- The report distinguishes hard blockers from warnings.
- No real agent spend is required by default. Live probes require `--live`.
- `claude-print` is ineligible until real output fixtures exist.
- Tests pass with:
  `PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_session_capabilities`.

### Phase 1 - Lazy Scoped Context Bundle Renderer

Objective: reduce worker token/tool burn before automatic phase launch hides
the problem.

Files:

| File | Change |
| --- | --- |
| `schemas/phase_context.schema.json` | New schema for context bundle metadata. |
| `py/swarm_do/pipeline/context_bundle.py` | New lazy renderer from prepared artifact, phase map, work-unit sidecar, checkpoints, and handoff summaries. |
| `py/swarm_do/pipeline/cli.py` | Add `bin/swarm context render ...`. |
| `py/swarm_do/pipeline/run_state.py` | Add public context path helpers only if they are shared; otherwise keep path helpers local to `context_bundle.py`. |
| `py/swarm_do/pipeline/tests/test_context_bundle.py` | Fixture tests for bounded prompts, source list, hashes, missing handoff, role prompts, and budget warnings. |
| `skills/swarmdaddy/SKILL.md` | Update dispatch instructions to pass rendered context bundles to roles. |
| `commands/do.md` | Document prepared-mode context bundle behavior. |

Definition of done:

- Rendering requires `run_id`, exact `phase_id`, and `role`; writer/spec-review
  bundles also require `unit_id`.
- The renderer rejects a phase id not present in
  `prepared_plan.phase_map[*].phase_id`.
- Rendering one writer bundle does not create bundles for unrelated phases,
  roles, or units.
- A prepared fixture renders stable context JSON and prompt Markdown for
  dispatcher, writer, spec-review, review, and docs roles.
- Prompt byte budgets are enforced with a `context_truncated` warning.
- Tests assert the rendered writer prompt does not include unrelated phases.
- The renderer records hashes for every source artifact it used.
- Tests pass with:
  `PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_context_bundle`.

### Phase 2 - Phase-Session State, Schemas, And Resume Read Integration

Objective: add durable phase queue state without launching anything yet.

Files:

| File | Change |
| --- | --- |
| `schemas/phase_sessions.schema.json` | New state schema. |
| `schemas/phase_result.schema.json` | New worker-to-controller result schema. |
| `schemas/phase_handoff.schema.json` | New phase handoff schema. |
| `schemas/telemetry/run_events.schema.json` | Add the exact event enum delta listed above. |
| `py/swarm_do/pipeline/phase_sessions.py` | State dataclasses, load/write, advisory lock helper, init, status, claim, start, refresh, complete, fail, block, needs-input, reap. |
| `py/swarm_do/pipeline/resume.py` | Read phase-session status and next phase in resume manifests; never write phase-session state. |
| `py/swarm_do/pipeline/run_state.py` | Include current phase-session fields in checkpoints if active. |
| `py/swarm_do/pipeline/cli.py` | Add `bin/swarm phases init/status/claim/start/refresh/complete/fail/block/needs-input/reap`. |
| `py/swarm_do/pipeline/tests/test_phase_sessions.py` | State machine, exact phase ids, sequential dependencies, locks, stale lease, idempotency, result/handoff validation, backfill fixture tests. |
| `py/swarm_do/pipeline/tests/test_resume.py` | Extend ready/prepared/drift cases for read-only phase-session state. |

Definition of done:

- `phases init` refuses unaccepted or stale prepared artifacts.
- `phases init` copies phase ids exactly from `phase_map`.
- `phases claim` returns the first pending phase whose prior phase is complete.
- `phases claim` is protected by the new state lock and atomic write path.
- Expired leases are visible and recoverable through `reap`; they are not
  silently overwritten.
- Completion requires both a valid `phase_result` and valid `phase_handoff`.
- Resume reports phase-session status but does not mutate phase-session state.
- Existing accepted runs without phase-session state report `not_initialized`.
- Tests pass with:
  `PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_phase_sessions py.swarm_do.pipeline.tests.test_resume`.

### Phase 3 - Foreground Manual Phase Pump

Objective: automatically advance phase state through the durable contract using
manual and fake-test launchers only.

Files:

| File | Change |
| --- | --- |
| `py/swarm_do/pipeline/phase_pump.py` | Pump loop, launcher interface, manual adapter, fake-test adapter. |
| `py/swarm_do/pipeline/cli.py` | Add `bin/swarm phases pump <run-id> --launcher manual|fake-test ...`. |
| `py/swarm_do/pipeline/tests/test_phase_pump.py` | Fake launcher tests for success, failure, blocked phase, stale lease, resume after crash. |
| `skills/swarmdaddy/SKILL.md` | Document that phase sessions render a phase-scoped dispatcher prompt; they do not import dispatcher logic. |
| `README.md` | Add operator workflow. |

Pump behavior:

1. Verify prepared artifact.
2. Initialize phase-session state if missing and explicitly requested.
3. Reap/report stale leases.
4. Claim next phase.
5. Start phase and record launcher/session metadata.
6. Render dispatcher context bundle for that phase.
7. Launch through `manual` or `fake-test`.
8. Validate structured result and handoff artifacts.
9. Mark phase complete/failed/blocked/needs_input.
10. Write checkpoint and run events.
11. Continue unless max phases, checkpoint, failure, blocked state, stale lease,
    or operator stop.

Definition of done:

- `fake-test` can complete a three-phase fixture without manual steps.
- A failed phase stops the pump and leaves a clear resume point.
- Re-running the pump after a completed phase skips it.
- `manual` prints the exact prompt and follow-up result command.
- `manual` mode does not pretend to parse free-form worker output.
- No `claude-print` parser or launcher is enabled in this phase.
- Tests pass with:
  `PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_phase_pump`.

### Phase 3b - Claude Print Adapter

Objective: add a bounded `claude -p` adapter only after the output contract is
proven locally.

Files:

| File | Change |
| --- | --- |
| `py/swarm_do/pipeline/phase_pump.py` | Add `claude-print` adapter and parser. |
| `py/swarm_do/pipeline/session_capabilities.py` | Mark `claude-print` eligible only when fixtures/probes match the parser. |
| `py/swarm_do/pipeline/tests/fixtures/claude_print/*.json` | Real successful, failed, and blocked output samples. |
| `py/swarm_do/pipeline/tests/test_phase_pump_claude_print.py` | Parser and eligibility tests. |

Definition of done:

- Real `claude -p --output-format json` output samples are committed as
  fixtures before parser implementation is accepted.
- The parser produces `schemas/phase_result.schema.json` compliant output.
- Ineligible capability probe results force fallback to manual mode.
- No live `claude` invocation is required by default in unit tests.
- Tests pass with:
  `PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_phase_pump_claude_print`.

### Phase 4 - Slash Command And TUI Integration

Objective: expose the new flow without making the TUI a second orchestrator.

Files:

| File | Change |
| --- | --- |
| `commands/do.md` | Add `--phase-sessions auto|off` or a separate documented resume flow. |
| `commands/resume.md` | Surface phase-session statuses in resume instructions. |
| `py/swarm_do/tui/state.py` | Read phase-session status and context bundle metadata. |
| `py/swarm_do/tui/app.py` | Add action to start foreground pump or copy/manual launch command. |
| `py/swarm_do/tui/tests/test_state.py` | Status rendering tests. |

Definition of done:

- CLI and TUI both use the same Python phase-session helpers.
- The TUI does not compute next phase itself.
- The operator can start phase execution from CLI or TUI.
- The TUI can be closed without losing run state.
- Resume output gives the exact next command after interruption.
- Tests pass with:
  `PYTHONPATH=py python3 -m unittest py.swarm_do.tui.tests.test_state`.

### Phase 5 - Measurement And Promotion

Objective: prove this improves reliability and token/tool efficiency.

Metrics:

- parent dispatcher context growth per phase;
- prompt bytes per rendered context bundle;
- worker tool calls and output bytes by role/unit;
- repeated source file reads per role/unit;
- `NEEDS_CONTEXT`, handoff, retry, and spec-mismatch counts;
- stale lease count;
- phase pump failures by launcher;
- wall clock compared to manual phase handoff.

Files:

| File | Change |
| --- | --- |
| `py/swarm_do/telemetry/subcommands/experiment_report.py` | Add phase-session/context bundle grouping. |
| `py/swarm_do/telemetry/subcommands/dogfood_check.py` | Add promotion/hold checks. |
| `docs/eval-recipes.md` | Add phase-session scorecard. |

Definition of done:

- At least five real multi-phase dogfood runs are measured.
- No unrecoverable phase-session state corruption occurs.
- Median repeated reads and worker output bytes decrease or stay flat.
- `NEEDS_CONTEXT` and handoff counts decrease or stay flat.
- No manual per-phase restart is required in the happy path for eligible
  launchers.

### Phase 6 - Optional Daemon Wrapper

Objective: add unattended supervision only if foreground mode proves valuable
and insufficient.

Files:

| File | Change |
| --- | --- |
| `py/swarm_do/pipeline/phase_daemon.py` | Thin loop over `phase_sessions` and `phase_pump` helpers. |
| `py/swarm_do/pipeline/cli.py` | Add `bin/swarm phases daemon start/status/stop` only if justified. |
| `py/swarm_do/tui/app.py` | Optional daemon status panel. |

Daemon rules:

- No separate SQLite/database in v1. Use the same JSON state and lock helper.
- No separate scheduler semantics. It claims phases with the same helper.
- No hidden auto-start. Operator must explicitly start it.
- Stop must be graceful and leave active leases inspectable.
- It must be safe to replace daemon execution with the foreground pump.

Definition of done:

- Daemon command uses the same state transition helpers as CLI pump.
- Killing the daemon leaves leases inspectable and reapable.
- Daemon status matches `bin/swarm phases status`.
- No daemon-specific retry policy exists.

## Daemon Promotion Criteria

Do not build the daemon until at least three of these are true:

- the foreground pump is used for real multi-phase runs for two weeks;
- operators leave phase pumps running unattended and want automatic restart;
- phase launches need scheduling while no TUI/terminal is open;
- more than one run must be supervised concurrently;
- cancellation/lease reaping becomes annoying in foreground mode;
- telemetry shows the pump itself, not worker quality, is the bottleneck.

## Risks And Mitigations

| Risk | Mitigation |
| --- | --- |
| `claude -p` lacks parity with interactive plugin sessions | Phase 0 capability probe; manual launcher remains baseline; no print mode without fixtures and eligibility. |
| Phase pump becomes a second dispatcher | Pump only claims/renders/launches/records; existing dispatcher prompt contract owns phase execution. |
| Context bundles omit needed information | Start with warnings and artifact pointers; measure `NEEDS_CONTEXT`; add explicit bundle sources instead of expanding blindly. |
| Workers still reread too much | Record bundle source list, prompt bytes, and repeated file reads; tune role prompts and context files. |
| Lease corruption or stale state | New advisory state lock, atomic writes, stale lease command, schema validation at every read. |
| TUI and CLI drift | TUI consumes CLI/Python helpers only; no duplicate scheduling logic. |
| Resume/state import cycle | `phase_sessions.py` never imports `resume.py`; resume reads summaries only. |
| Existing accepted runs are stranded | `phases status/init` handles accepted runs without phase-session state and starts all phases pending unless trusted phase events exist. |
| Daemon pressure returns too early | Promotion criteria require foreground dogfood evidence. |

## Rejected Alternatives

### Full Recursive Orchestration

Rejected for now. It adds too much surface area around resume, permissions,
state ownership, and failure recovery. A phase-session lease gives a bounded
fresh context per phase without letting sub-orchestrators create another global
plan.

### Daemon First

Rejected for now. The durable state contract is the foundation. A daemon should
be a later wrapper over stable primitives, not the first place those primitives
exist.

### Auto-Run Without Context Bundles

Rejected. It addresses parent context exhaustion but leaves worker token/tool
burn untouched. It may even hide waste by moving it into child sessions.

### Pre-Render Every Context Bundle

Rejected for v1. Pre-rendering `phases x roles x units` creates unnecessary
file churn and makes budget tuning harder. Render lazily and cache only the
bundle that was requested.

### Have Every Worker Read The Prepared Plan

Rejected. It is simple but contrary to the context-discipline goal. The
controller should render exact scoped context and source pointers.

### Store Phase State Only In Beads Notes

Rejected. Beads remains important for task identity and human-readable issue
threads, but SwarmDaddy already has JSON schema, prepared artifacts, run events,
and checkpoints. Phase-session state should be structured, schema-validated,
and easy for CLI/TUI/tests to consume.

### SQLite Immediately

Rejected for v1. SQLite may become attractive after concurrent supervision is a
real requirement. The current state model is JSON plus atomic writes plus JSONL
events, so v1 should extend that model with one explicit lock helper.

## Final Architecture Principle

The control plane should be boring:

```text
Prepared artifact is the contract.
Phase-session state is the queue.
Context bundles are the prompt boundary.
Result and handoff JSON are the worker/controller boundary.
Run events are the audit log.
Resume manifest is the re-entry point.
CLI/TUI/daemon are launch surfaces only.
```

If every future feature preserves that separation, this can grow into a daemon
or a richer TUI without becoming brittle.
