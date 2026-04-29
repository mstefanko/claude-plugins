# Phase Session Autopilot And Scoped Handoffs Plan

Date: 2026-04-29
Owner: swarm-do runtime and prepare-gate execution
Audit incorporated: `docs/phase-session-autopilot-sequential-plan.audit.md`

## Goal

Make accepted prepared plans run without operator babysitting while keeping phase
execution sequential for now.

The near-term target is:

1. the prepare gate verifies that the plan is in a sane build order;
2. each phase runs in a fresh Claude session through a proven launcher adapter;
3. each phase receives only the context it needs;
4. each phase emits validated result and handoff artifacts;
5. the phase pump advances to the next phase automatically after successful
   completion.

The non-goal is parallel phase execution. Parallel phases are a later feature
after explicit phase dependency metadata, dependency-scoped handoffs, worktree
isolation, and merge queue semantics exist.

V1 autopilot is foreground-only. "No babysitting" means no per-phase manual
restart or prompt handoff. It does not mean the process survives terminal or
host death. Daemonization remains a later phase.

## Audit Resolution

The audit was accepted as directionally correct. The plan now makes the required
choices:

- Keep phase execution sequential and preserve the one-active-phase invariant.
- Keep `decisions.md` for dependency-local decisions to avoid path churn.
- Add `shared-decisions.md` from an explicit run-scoped shared-decisions
  sidecar; do not auto-promote every prior handoff decision.
- Keep plan-review finding shape unchanged. Deterministic lint findings may use
  `code`; LLM plan-review findings stay `{severity, phase_id, location, reason,
  citation}`.
- Use existing run-event enum values. Do not add new `event_type` values for
  autopilot unless a later implementation proves the existing `details` fields
  are insufficient.
- Treat `--init` and `--live` as existing CLI features, not new work.
- Use an argv-based `subprocess` launch for Claude. Do not use shell command
  substitution for prompt text.
- Add phase dependency metadata as optional v1 schema fields, not a schema
  version bump.

## Prior-Art Direction

This plan keeps the architecture close to the lessons already adopted from
Superpowers, metaswarm, and ECC:

- From Superpowers: use detailed plans, fresh bounded workers, exact file and
  validation scopes, and review after each task. Do not hand workers a giant
  inherited session.
- From metaswarm: use hard gates, persisted state, blocking semantics, and
  recovery from disk. Do not copy recursive orchestration into phase workers.
- From ECC: treat sessions, summaries, worktrees, start/stop/resume, and future
  daemonization as a boring control plane. The launcher is an adapter, not the
  source of truth.

The boundary to protect: phase sessions may claim and execute one phase, but
they do not decide the global plan, mutate the phase queue arbitrarily, or spawn
their own child orchestrators.

## Current Behavior

The current v1 queue is intentionally sequential:

- `phase_sessions.init_phase_sessions()` copies `phase_id` values from
  `prepared_plan.v1.json.phase_map`.
- It creates `depends_on_phase_ids` as a simple previous-phase chain:
  phase 1 has no dependency, phase 2 depends on phase 1, phase 3 depends on
  phase 2, and so on.
- `claim_next_phase()` refuses to claim anything if another phase is already
  `leased` or `running`.
- `_dependencies_complete()` requires every listed dependency to be `complete`.
- `phase_pump.pump_phases()` claims one phase, starts it, renders the dispatcher
  context, invokes the launcher, records the result, then loops.
- `--init` already exists on `bin/swarm phases pump` and maps to
  `pump_phases(init_if_missing=True)`.

This is good enough for unattended sequential runs once a real launcher is
enabled. It is not a phase-DAG scheduler.

## Handoff Problem

Today the context bundle renderer includes completed handoffs for every earlier
phase by index:

```text
phase_ids = all prepared.phase_map ids where idx < current_phase_index
```

That means phase 5 can receive phase 1, 2, 3, and 4 handoff summaries even when
only phase 4 is the actual dependency. `decisions.md` also flattens decisions
from every earlier handoff into one unattributed bullet list.

The current approach is acceptable for small sequential dogfood runs, but it is
the wrong habit:

- it grows prompt context with stale or irrelevant history;
- it can bias the next worker toward unrelated previous decisions;
- it makes later parallelization harder because "all earlier phases" is not the
  same as "dependencies of this phase";
- it violates the Superpowers-style narrow-context principle.

## Desired Handoff Contract

Even while execution remains sequential, the next phase should receive:

1. **Current phase contract**
   - phase id, phase index, title, kind, and complexity
   - exact current phase text when within budget
   - allowed files, blocked files, context files
   - acceptance criteria
   - validation commands
   - prepared artifact, prepared plan, and work-unit sidecar paths plus shas

2. **Direct dependency handoffs**
   - only handoff summaries for `depends_on_phase_ids`
   - each dependency handoff summary
   - each dependency's `next_phase_context`
   - dependency handoff artifact path and sha

3. **Dependency-local decisions**
   - `decisions.md` remains the dependency-local decisions file
   - it contains decisions from direct dependency handoffs only
   - it should keep source attribution by dependency phase where possible

4. **Explicit shared decisions**
   - `shared-decisions.md` is rendered separately
   - it is sourced from a run-scoped `shared_decisions.v1.json` sidecar
   - it contains only controller/operator-promoted decisions
   - when no shared sidecar exists, it says `No shared decisions.`

5. **Queue status**
   - current phase attempt
   - direct dependency statuses
   - any blocked/stale/needs-input state relevant to this phase

The next phase should not receive:

- all earlier phase handoffs by default;
- full prior transcripts;
- unrelated phase text;
- unrelated worker notes;
- queue mutation instructions;
- instructions to spawn a second orchestrator.

## Recommendation

Keep implementation phases sequential for now.

This buys us the important user value, no manual "run phase 2, run phase 3"
babysitting, without taking on the risk of concurrent worktrees, merge races,
partial-order scheduling, and richer conflict recovery.

The build order should be:

1. prepare-gate build-order checks;
2. dependency-scoped handoff rendering while preserving sequential execution;
3. `claude-print` fixtures, parser, and launcher adapter;
4. unattended sequential pump UX;
5. optional explicit phase dependency metadata used for validation and handoff
   scoping;
6. future parallel execution only after the above has proven stable.

## Phase 1 - Prepare-Gate Build-Order Review

### Objective

Ensure the plan order is safe before any fresh phase sessions are launched.

### Ownership Split

Do not encode every build-order heuristic deterministically. Split ownership:

- Deterministic lint lives in `py/swarm_do/pipeline/plan.py` and emits the
  existing lint-finding shape: `{code, severity, phase_id, location, message}`.
- Judgment-call review lives in the canonical role spec
  `role-specs/agent-plan-review.md`; regenerated mirrors may update
  `agents/agent-plan-review.md` and `roles/agent-plan-review/shared.md`.
- `validate_plan_review_finding()` in `prepare.py` keeps its current strict
  plan-review shape: `{severity, phase_id, location, reason, citation}`. Do not
  add `code` to LLM plan-review findings in this phase.

### Deterministic Checks

Add only checks that can be reliably derived from parsed phase text, file
targets, and validation commands:

- `validation_uses_later_phase_file`:
  a phase's validation command references a repo path that is only introduced
  as a file target in a later phase. Severity: `blocking`.
- `overlapping_file_scope_without_order_note`:
  adjacent phases touch overlapping file targets and the later phase does not
  mention sequencing, follow-up, handoff, or dependency language. Severity:
  `advisory`.
- `phase_order_ambiguous_validation`:
  validation is plan-level or fallback-only while a later phase introduces
  validation infrastructure. Severity: `advisory`.

Store these in `review_findings` alongside existing deterministic lint findings,
using the existing deterministic lint shape.

### Plan-Review Checks

Update `role-specs/agent-plan-review.md` to ask the reviewer to inspect build
order for:

- a phase consuming a schema, API, config, CLI command, migration, fixture, or
  helper before any prior phase creates or modifies it;
- docs, cleanup, review, telemetry, or migration-follow-up phases appearing
  before the implementation they describe or validate;
- callers being updated before the callee contract exists;
- migrations being introduced after code that expects the migrated shape;
- broad "wire up everything" language that hides dependency order.

These are LLM-judged findings. They use the existing plan-review shape and
`severity` values.

### Auto-Continue Semantics

`auto_continue_decision()` already blocks on advisory findings. Keep that
behavior and add regression coverage proving build-order advisories block
`--prepare --continue` but do not block manual acceptance.

### Fixtures And Acceptance

Add fixtures under:

```text
py/swarm_do/pipeline/tests/fixtures/build_order/
  reversed_dependency_plan.md
  valid_sequential_plan.md
```

Acceptance:

- `reversed_dependency_plan.md` produces a blocking deterministic or
  plan-review finding.
- `valid_sequential_plan.md` prepares cleanly.
- Advisory build-order findings appear in the acceptance summary and block
  `--prepare --continue`, but not manual acceptance.
- `role-specs/agent-plan-review.md` explicitly includes build-order review.

## Phase 2 - Dependency-Scoped Handoffs

### Objective

Stop using "all earlier phases" as the handoff set.

### Naming Choice

Keep `decisions.md` as the dependency-local decisions file. Add
`shared-decisions.md` as the explicit shared-decision file. Do not rename
`decisions.md` in this phase.

### Shared Decisions Source

Introduce a run-scoped sidecar:

```text
data/runs/<run-id>/shared_decisions.v1.json
```

Shape:

```json
{
  "schema_version": 1,
  "run_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
  "decisions": [
    {
      "id": "decision-001",
      "source_phase_id": "2",
      "created_at": "2026-04-29T00:00:00Z",
      "text": "The prepared artifact remains schema_version 1.",
      "applies_to_phase_ids": ["*"],
      "reason": "Needed by later context rendering and schema validation."
    }
  ]
}
```

Add a small controller-owned helper and CLI surface:

```bash
bin/swarm phases decisions add <run-id> \
  --source-phase <phase-id> \
  --text <decision> \
  [--applies-to <phase-id>|--global] \
  [--reason <reason>]
```

This command is the only writer for shared decisions in v1. The context renderer
only reads the sidecar. It does not auto-promote handoff decisions.

Do not emit a run event for shared-decision additions in v1; the sidecar carries
`created_at`, `source_phase_id`, and `reason`. If later observability requires a
ledger event, add a dedicated enum value and schema test in that later change.

### Implementation

Add a dependency resolver before `_prior_handoffs()`:

```python
dependency_phase_ids = _dependency_phase_ids(
    prepared=prepared,
    phase_id=phase_id,
    phase_index=phase_index,
    data_dir=base,
    run_id=run_id,
)
prior = _prior_handoffs(base, run_id, dependency_phase_ids)
```

Rules:

- If `phase_sessions.v1.json` exists, use the current phase's
  `depends_on_phase_ids`.
- If phase-session state does not exist and prepared metadata has
  `depends_on_phase_ids`, use those ids.
- If neither source exists, use the v1 fallback: `phase_map[index - 1]` only.
- Phase 1 gets no dependency handoffs.
- Do not include nondependency prior phase handoffs.
- Render `shared-decisions.md` from `shared_decisions.v1.json` when present;
  otherwise render `No shared decisions.`

### Current vs Next

Today, phase 4 gets:

```text
previous-handoff.md:
  Phase 1 summary
  Phase 2 summary
  Phase 3 summary

decisions.md:
  all decisions from Phase 1, Phase 2, and Phase 3 handoffs
```

After this change, with v1 sequential fallback, phase 4 gets:

```text
previous-handoff.md:
  Phase 3 summary
  Phase 3 next_phase_context

decisions.md:
  decisions from Phase 3 handoff only

shared-decisions.md:
  run-scoped shared decisions, or "No shared decisions."
```

If a future prepared artifact says phase 4 depends on phases 1 and 3, phase 4
gets:

```text
previous-handoff.md:
  Phase 1 summary
  Phase 1 next_phase_context
  Phase 3 summary
  Phase 3 next_phase_context

decisions.md:
  decisions from Phase 1 and Phase 3 handoffs only

shared-decisions.md:
  controller-promoted global decisions
```

### Acceptance

- A three-phase fixture renders phase 3 context with only phase 2 handoff under
  v1 sequential fallback.
- Given hand-edited phase-session state where phase 3 depends only on phase 1,
  rendered phase 3 context includes phase 1 handoff and excludes phase 2
  handoff.
- `decisions.md` remains present and contains dependency-local decisions only.
- `shared-decisions.md` is present and renders `No shared decisions.` when the
  sidecar is absent.
- Direct dependency handoffs include path and sha in `source_list`.
- Existing accepted prepared artifacts continue to render context without
  migration.

## Phase 3 - No-Babysitting Launcher Enablement

### Objective

Enable `claude-print` so the foreground pump can run accepted prepared phases
without manual per-phase restarts.

Current status:

- Claude CLI is present when probed locally.
- `claude -p --help` confirms `--name`, `--output-format json`,
  `--max-budget-usd`, `--permission-mode`, and `--json-schema` exist.
- Current local help does not advertise `--max-turns`, so the v1 adapter must
  not pass `--max-turns`.
- `claude-print` remains ineligible because there are no committed real
  fixtures under `py/swarm_do/pipeline/tests/fixtures/claude_print/`.
- `phase_pump` currently enables only `manual` and `fake-test`.
- `sessions doctor --live` already exists.

### Step 1 - Define The Launcher Contract

The adapter must launch Claude without a shell:

```python
argv = [
    claude_path,
    "-p",
    "--name",
    f"swarmdaddy-{run_id}-{phase_id}",
    "--output-format",
    "json",
    "--permission-mode",
    "dontAsk",
    "--allowedTools",
    allowed_tools_arg,
    prompt_text,
]
```

Do not use `shell=True`. Do not use `"$(cat <dispatcher.prompt.md>)"`. Load the
prompt with `Path(prompt_path).read_text()` and pass it as the final argv
element.

V1 permission mode is `dontAsk` with explicit `--allowedTools` derived from the
dispatcher/writer permission contract. Missing permissions should fail closed
instead of prompting. Do not use `bypassPermissions` or
`--dangerously-skip-permissions`.

The dispatcher prompt must include the exact artifact paths:

- result path: `phase_result_path(run_id, phase_id, attempt)`
- handoff path: `phase_handoff_path(run_id, phase_id, attempt)`

The child Claude session must write those files and return an outer
`--output-format json` payload that lets the adapter identify status and paths.

The adapter records a phase only after `record_phase_result()` validates the
result and handoff files. Model prose is never completion authority.

### Step 2 - Bootstrap Fixture Capture

The pump cannot capture the first fixtures because `claude-print` is ineligible
until fixtures exist. Add a one-off capture script that bypasses the phase pump
but uses the same prompt contract:

```text
bin/capture-claude-print-fixture
```

Responsibilities:

- create or accept a tiny prepared fixture run;
- render dispatcher context;
- compute the expected result and handoff paths;
- call `claude -p --output-format json` directly with argv, not shell;
- write the raw outer Claude JSON to the fixture directory;
- write any result/handoff artifacts under a temporary run directory;
- redact machine-specific absolute prefixes, account identifiers, and prompt
  text that is not structurally needed by the parser tests;
- document every redaction in
  `py/swarm_do/pipeline/tests/fixtures/claude_print/README.md`.

Do not temporarily weaken `_claude_print_capability()` to capture fixtures.

### Step 3 - Capture Real Fixtures

Capture these raw outputs from real `claude -p --output-format json` runs:

1. `success.json`
   - phase writes valid result and handoff files
   - status is `complete`
   - validation summary is present

2. `failed.json`
   - phase writes valid result and handoff files
   - status is `failed`
   - error message is present

3. `blocked.json`
   - phase writes valid result and handoff files
   - status is `blocked`
   - blocked reason is present

4. `needs_input.json`
   - phase writes valid result and handoff files
   - status is `needs_input`
   - requested input list is present

Store them under:

```text
py/swarm_do/pipeline/tests/fixtures/claude_print/
```

Keep fixtures as raw outer Claude JSON shape after documented redaction. Parser
tests should replay these fixtures without contacting Claude.

### Step 4 - Implement Parser Tests

Keep `parse_claude_print_json(text)` as the thin outer JSON-object validator.
Add a new parser in `session_capabilities.py`:

```python
extract_claude_print_artifacts(payload, *, run_dir) -> dict[str, Any]
```

It returns:

```json
{
  "status": "complete",
  "result_path": ".../attempt-1.result.json",
  "handoff_path": ".../attempt-1.handoff.json",
  "session_name": "swarmdaddy-<run-id>-<phase-id>",
  "raw": {}
}
```

Parser tests must cover:

- each committed fixture;
- invalid JSON;
- JSON array instead of object;
- missing result path;
- missing status;
- unsupported status;
- result path outside the run directory;
- output where Claude exits nonzero but still writes a valid result;
- output where Claude exits zero but result validation fails.

### Step 5 - Strengthen Capability Probe

Update `_claude_print_capability()` so eligibility requires:

- Claude CLI path exists;
- required fixture files are present;
- every fixture parses successfully through `parse_claude_print_json()`;
- every fixture normalizes through `extract_claude_print_artifacts()`;
- optional `--live` probe can run `claude --version`.

The probe should return hard blockers such as:

```text
claude_print_fixtures_missing
claude_print_fixture_parse_failed
claude_cli_missing
claude_version_probe_failed
```

Do not add a spendful live `claude -p` round trip to `sessions doctor` by
default. Fixture parsing is the eligibility proof; `--live` remains a version
probe unless a later plan explicitly adds spendful smoke testing.

### Step 6 - Implement The Adapter

Add `claude-print` to `ENABLED_LAUNCHERS` only after the fixture-backed parser
is in place.

The adapter loop should:

1. claim the next phase;
2. start the phase with session name `swarmdaddy-<run-id>-<phase-id>`;
3. render dispatcher context;
4. compute the exact result and handoff paths for the current attempt;
5. append launcher instructions to the rendered prompt that require Claude to
   write those exact paths;
6. run `claude -p --output-format json` using argv;
7. refresh the lease by calling `refresh_phase()` every
   `refresh_interval_seconds` while the process is running;
8. parse the outer Claude JSON;
9. normalize status and artifact paths with `extract_claude_print_artifacts()`;
10. call `record_phase_result()` with expected status from the parsed output;
11. write checkpoint state;
12. continue to the next phase only when status is `complete`;
13. stop on `failed`, `blocked`, `needs_input`, stale lease, parse failure,
    process failure, or result validation failure.

Failure reporting uses existing events:

- `phase_pump_started`
- `phase_pump_stopped` with `details.status` and `details.reason`
- `phase_session_failed` when a running phase records a failed result
- `phase_pump_launcher_ineligible`

Do not add new run-event enum values in this phase.

### Step 7 - Add Process And Timeout Controls

The adapter needs explicit controls:

- optional max budget via `--max-budget-usd`;
- running TTL refresh interval from `lease_policy.refresh_interval_seconds`;
- subprocess timeout derived as
  `running_ttl_seconds - (2 * refresh_interval_seconds)`, which is 13800
  seconds with today's defaults;
- environment redaction in logs;
- no shell interpolation of prompt text;
- captured stdout/stderr and command metadata under:
  `data/runs/<run-id>/phase_launches/<phase-id>/attempt-<n>/`;
- command metadata records argv without embedding full prompt text; store
  prompt path and sha instead.

### Step 8 - Add Integration Tests

Extend existing tests rather than inventing a new module:

- `test_session_capabilities.py`
  - fixture parser success and failure paths
  - capability eligibility with fixtures present
  - fixture parse blocker when one fixture is malformed

- `test_phase_pump.py`
  - pump using a fake injected `claude-print` runner
  - successful two-phase unattended sequential run
  - failed phase stops and leaves downstream pending
  - blocked phase stops and surfaces blocker
  - stale lease is reaped and not silently retried
  - nonzero process exit with no valid result does not claim completion
  - replayed fixture via injected runner produces result/handoff artifacts that
    pass schema validation

### Step 9 - Document Operator Flow

Update README and command docs:

```bash
bin/swarm sessions doctor --live
bin/swarm phases pump <run-id> --launcher claude-print --max-phases all --init
bin/swarm phases status <run-id>
```

Document that `claude-print` is the no-babysitting sequential foreground
launcher. It is not a daemon, a parallel scheduler, or a recursive orchestrator.

### Acceptance

- `bin/swarm sessions doctor --json` reports `claude-print` eligible when
  fixtures, parser, and Claude CLI are available.
- `bin/swarm phases pump <run-id> --launcher claude-print --max-phases all
  --init` can complete a multi-phase fixture using an injected runner.
- Real launcher failures do not mark phases complete.
- Phase result and handoff schemas remain the only completion authority.

## Phase 4 - Sequential Autopilot UX

### Objective

Make unattended sequential foreground execution the obvious happy path.

### Implementation

`--init` already exists. This phase documents it and makes status output more
actionable.

Current `phase_status()` behavior:

- `not_found`
- `drift`
- `not_initialized`
- `complete`
- active phase statuses: `leased` or `running`
- `stale`
- `blocked` or `needs_input`
- `ready`
- `waiting` when no phase is claimable and no special state matched; this can
  hide `failed`

Target `phase_status()` behavior:

- `not_found`: no prepared artifact
- `drift`: invalid or stale state
- `not_initialized`: accepted prepared artifact exists, no phase state yet
- `complete`: all phases complete
- `leased` or `running`: active phase exists
- `stale`: a lease expired
- `failed`: at least one phase failed
- `blocked`: at least one phase blocked
- `needs_input`: at least one phase needs input
- `ready`: next claimable phase exists
- `waiting`: no claimable phase because dependencies are incomplete, with
  dependency status included in the response

Generalize `recommended_command` inside `phase_sessions.phase_status()`, not
CLI-only formatting, so TUI/resume callers see the same next action.

Use existing `phase_pump_stopped` for every pump stop reason. Add tests that
every return path from `pump_phases()` has already emitted `phase_pump_stopped`.
Do not add new run-event enum values.

Keep `manual` as the debugging fallback.

### Acceptance

- Given a three-phase fixture with `--launcher fake-test --max-phases all
  --init`, `pump_phases()` returns `status="complete"` with three completed
  phases and emits three `phase_session_completed` events.
- A failed phase produces `phase_status()["status"] == "failed"` and downstream
  phases remain pending.
- Every state listed above has a stable `recommended_command` or an explicit
  `None` when complete.
- No operator action is needed between successful phases.

## Phase 5 - Explicit Phase Dependency Metadata

### Objective

Add dependency metadata for correctness and context scoping, not for parallel
execution yet.

### Schema Strategy

Use a backward-compatible optional field on prepared artifact schema version 1.
Do not bump `schema_version`.

Add optional properties to `phase_map.items.properties`:

```json
{
  "depends_on_phase_ids": {
    "type": "array",
    "items": { "type": "string", "minLength": 1 },
    "uniqueItems": true
  },
  "dependency_reason": { "type": ["string", "null"] }
}
```

Do not add either field to `required`. Existing accepted prepared artifacts keep
working without migration.

### Execution Semantics

V1 preserves array-order execution and the one-active-phase invariant.

Dependencies may only point to earlier phases in `phase_map`. Out-of-order
execution and forward dependencies are deferred to the future parallel scheduler
work.

### Validation Location

Add `validate_phase_dependencies(phase_map) -> list[dict[str, Any]]` in
`prepare.py`.

Validation should produce deterministic blocking lint findings, not schema load
errors, for:

- unknown dependency phase ids;
- self-dependencies;
- dependency cycles;
- dependencies on later phases;
- duplicate dependencies.

Schema validation still rejects wrong JSON types. Semantic dependency mistakes
flow through the prepare-gate findings so the operator sees them in the normal
acceptance summary.

### Defaulting And Backfill

When prepare writes a new artifact:

- phase 0 gets `depends_on_phase_ids = []`;
- every later phase defaults to `[previous_phase_id]`;
- `dependency_reason` defaults to `"v1 sequential fallback"`.

When loading an existing accepted artifact with no dependency metadata:

- do not mutate the artifact;
- phase sessions and context rendering use the existing previous-phase fallback;
- no re-prepare is required for
  `data/runs/01KQAC90FK5FNF4JWXMXHHR2AQ/prepared_plan.v1.json` or any other
  v1 accepted run.

### Acceptance

- Re-running prepare emits `depends_on_phase_ids = []` for the first phase and
  `[phase_map[i-1].phase_id]` for every later phase.
- Existing prepared artifacts without the field still load and render context.
- Unknown, self, duplicate, cyclic, and forward dependencies are blocking
  prepare findings.
- Phase sessions initialize from explicit dependencies when present.
- Handoff rendering uses explicit dependencies when present.
- Execution still enforces one active phase.

## Future - Parallel Phase Execution

Parallel execution should wait until the sequential autopilot is boring.

This section is non-binding for the phases above. Do not implement parallel
scaffolding while implementing Phase 5 dependency metadata.

Required prerequisites:

- explicit phase dependency DAG;
- dependency-scoped handoffs already shipped;
- per-phase or per-work-unit worktrees;
- merge queue with conflict reporting;
- max parallel phase cap;
- deterministic scheduler tests;
- status view that explains ready, running, blocked, and waiting phases;
- operator opt-in.

Only then should `claim_next_phase()` grow into `claim_ready_phases(max_n)`.

The future scheduler should start multiple sessions only for phases that:

- have all dependencies complete;
- do not overlap write scopes unless isolated by worktree and merge queue;
- are not blocked by a global gate;
- have scoped context bundles that exclude unrelated handoffs;
- have clear rollback/retry behavior.

## Run-Event Policy

The run-event schema has a closed enum. This plan does not require new enum
values.

Use existing events:

- prepare build-order findings: `prepare_lint_findings`,
  `prepare_review_findings`, and `prepare_blocking_findings`
- launcher ineligible: `phase_pump_launcher_ineligible`
- pump lifecycle and stop reasons: `phase_pump_started` and
  `phase_pump_stopped` with `details.status` / `details.reason`
- phase terminal states: `phase_session_completed`, `phase_session_failed`,
  `phase_session_blocked`, `phase_session_needs_input`
- artifact recording: `phase_result_recorded`, `phase_handoff_recorded`
- context rendering: `phase_context_rendered`

If a later implementation cannot express an important signal through these
events, it must update `schemas/telemetry/run_events.schema.json` and add schema
validation tests in the same change.

## Rollback

- Disable `claude-print` by making the capability probe fail closed.
- Fall back to `manual` phase pump.
- Keep phase-session state readable because result and handoff schemas do not
  change for sequential launcher work.
- If dependency metadata causes issues, preserve the v1 previous-phase fallback.
- Existing accepted prepared runs are not migrated and do not need re-prepare.

## Validation Commands

Run from the `swarm-do/` repo root:

```bash
PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_session_capabilities
PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_context_bundle
PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_phase_sessions
PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_phase_pump
PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_prepare_artifact
PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_plan_lint
PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_plan_prepare_write
PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_resume
```
