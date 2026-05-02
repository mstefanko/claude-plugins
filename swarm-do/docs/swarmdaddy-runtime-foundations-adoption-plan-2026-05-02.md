# SwarmDaddy Runtime Foundations Adoption Plan

Date: 2026-05-02
Status: implementation-ready proposal
Owner: swarm-do runtime, storage, recovery, telemetry, and TUI surfaces
Source comparison: ADK Python, smolagents, LangGraph, and current SwarmDaddy code

Related research:

- `docs/research-similar-systems-2026-05-01.md`
- `docs/swarmdaddy-state-storage-sqlite-recommendation-2026-05-01.md`
- `docs/architecture-assessment-2026-05-01.md`
- `docs/swarmdaddy-durable-run-capabilities-research-plan.md`
- `docs/ecc-pattern-adoption-plan.md`

## Goal

Adopt the small set of proven agent-runtime patterns that make SwarmDaddy more
reliable as a local development orchestrator, without turning it into a
production app-agent framework.

SwarmDaddy's durable product boundary is:

```text
local repo + Beads + prepared plan + phase/session state + worktrees
  + provider evidence + recovery + telemetry + operator control
```

ADK and LangGraph are production-capable agent application runtimes. smolagents
is a compact agent loop and tool/runtime framework. SwarmDaddy should borrow
their state, contract, policy, replay, and lifecycle ideas only where those
ideas strengthen local development orchestration.

## Executive Recommendation

Do not replace SwarmDaddy with LangGraph, ADK, or smolagents. Build a thinner
runtime foundation underneath the existing CLI/plugin harness:

1. Add a state ownership boundary before changing storage.
2. Move orchestration dicts into typed domain contracts.
3. Centralize retry, timeout, cache, and budget policy objects.
4. Build a run trace plus replay/eval harness.
5. Normalize internal run events behind a typed envelope.
6. Add an internal hook lifecycle after contracts exist.
7. Represent operator decisions as auditable command artifacts.
8. Add reducer-style merges only for fan-out artifacts that need them.
9. Consider SQLite only after the state seam exists.

This sequence gives most of the operational benefit while preserving the
single-machine, inspectable development-harness model.

## Purpose And Overlap Comparison

| System | Primary purpose | Overlap with SwarmDaddy | What it does differently | Should SwarmDaddy copy it? |
| --- | --- | --- | --- | --- |
| SwarmDaddy | Local development harness for orchestrating repo work across agents, Beads, worktrees, phase sessions, provider evidence, recovery, and operator-facing CLI/TUI flows. | Durable runs, staged orchestration, multi-agent fan-out/review, local artifacts, recovery, telemetry. | Treats the repository and git worktrees as the operating environment. Optimizes for developer trust, auditability, and recovery rather than serving app users. | Keep this mission. Borrow foundations that make local runs easier to inspect, resume, and test. |
| Google ADK Python | Production-capable agent application framework with typed agents, runners, services, sessions, artifacts, memory, credentials, plugins, tools, and eval. | Agents, callbacks/hooks, sessions, artifacts, plugin lifecycle, evaluation. | Assumes an app runtime around users, sessions, credentials, and services. Has more infrastructure surface than SwarmDaddy needs for repo-local orchestration. | Copy service boundaries, typed models, lifecycle hooks, and eval concepts. Do not copy user/session/credential app runtime scope into core. |
| Hugging Face smolagents | Compact agent loop framework focused on tool/code agents, managed agents, step memory, monitoring, and local/remote code execution. | Step traces, run result shape, managed agents, final checks, monitoring, executor boundaries. | Centers the agent reasoning loop and tool/code execution. SwarmDaddy usually delegates agent reasoning to Claude/Codex lanes and owns the control plane around them. | Copy compact step/run trace and monitoring ideas. Avoid embedding a second general-purpose agent loop unless a concrete lane needs it. |
| LangGraph | Graph runtime for stateful, durable, resumable agent workflows with typed state, reducers, checkpoints, streaming, interrupts, commands, retry, timeout, and cache policy. | DAG execution, state updates, checkpoint/recovery, fan-out/merge, interrupts, policies, streaming. | Provides a reusable graph runtime for app workflows. SwarmDaddy already has a pipeline engine tied to Beads, worktrees, provider review, and local artifacts. | Copy typed state, checkpointer, policy, event stream, interrupt, and reducer patterns selectively. Do not rewrite SwarmDaddy as a LangGraph graph. |

## Ranking

| Rank | Pattern / Gap | Value | Effort | Risk | Decision |
| ---: | --- | --- | --- | --- | --- |
| 1 | State ownership boundary before full SQLite | Very high | Medium | Low-medium | Do first |
| 2 | Typed run/phase/stage contracts | Very high | Medium | Low | Do next |
| 3 | Retry/timeout/cache/budget policy objects | High | Low-medium | Low | Do with contracts |
| 4 | Run trace, replay, and eval harness | High | Medium | Low | Do after state seam |
| 5 | Unified typed event envelope | High | Medium-high | Medium | Stage in behind existing JSONL |
| 6 | Internal hook/plugin lifecycle | Medium-high | Medium | Medium | Do after contracts/events |
| 7 | Operator interrupt/resume decision model | Medium-high | Medium | Medium | Do as a scoped recovery feature |
| 8 | Reducer-style fan-out/merge state | Medium | Medium-high | Medium | Use selectively |
| 9 | SQLite canonical control-plane store | High | High | Medium-high | Defer until seams make it cheap |
| 10 | Production app-agent runtime features | Low | Very high | High | Reject for core SwarmDaddy |

## Non-Goals

- No production app-agent server in this plan.
- No replacement of Claude/Codex launcher workflows with ADK or LangGraph.
- No generic user-session, auth, or memory service for end-user applications.
- No wholesale rewrite of pipeline execution into LangGraph.
- No pure event sourcing as the source of truth.
- No SQLite big-bang migration.
- No public third-party plugin API until internal hook points prove stable.
- No hidden daemon requirement; foreground CLI/TUI flows remain valid.

## Current SwarmDaddy Anchors

The plan assumes the current architecture remains the execution substrate:

- Pipeline graphs are YAML stage DAGs resolved through existing pipeline helpers.
- Implementation runs create Beads-backed work, phase-scoped context, worktrees,
  provider-review evidence, and final review/docs lanes.
- Phase sessions are durable local state files with lease, retry, and recovery
  semantics.
- Provider review is fail-closed until doctor/read-only/schema/auth gates prove
  eligibility.
- Telemetry exists as JSONL ledgers, with run events separate from observations.
- The TUI and slash commands are operator surfaces over the same CLI helpers.

New work should strengthen these surfaces rather than bypass them.

## Evidence Used

The comparison was based on local SwarmDaddy code and fresh upstream clones of
the three referenced repositories. The most relevant source areas were:

- SwarmDaddy:
  - `README.md`
  - `pipelines/default.yaml`
  - `py/swarm_do/pipeline/engine.py`
  - `py/swarm_do/pipeline/phase_sessions.py`
  - `py/swarm_do/pipeline/phase_pump.py`
  - `py/swarm_do/pipeline/provider_review.py`
  - `py/swarm_do/pipeline/executor.py`
  - `py/swarm_do/pipeline/validation.py`
- ADK Python:
  - `src/google/adk/agents/base_agent.py`
  - `src/google/adk/agents/sequential_agent.py`
  - `src/google/adk/agents/parallel_agent.py`
  - `src/google/adk/agents/loop_agent.py`
  - `src/google/adk/runners.py`
  - `src/google/adk/sessions/base_session_service.py`
  - `src/google/adk/sessions/database_session_service.py`
  - `src/google/adk/plugins/base_plugin.py`
  - `src/google/adk/evaluation/agent_evaluator.py`
- smolagents:
  - `src/smolagents/agents.py`
  - `src/smolagents/tools.py`
  - `src/smolagents/memory.py`
  - `src/smolagents/local_python_executor.py`
  - `src/smolagents/remote_executors.py`
  - `src/smolagents/monitoring.py`
- LangGraph:
  - `libs/langgraph/langgraph/graph/state.py`
  - `libs/langgraph/langgraph/types.py`
  - `libs/checkpoint/langgraph/checkpoint/base/__init__.py`
  - `libs/cli/README.md`

## Source Pattern Summary

### LangGraph Patterns To Borrow

- Typed state graph where nodes return partial state updates.
- Explicit checkpointer concept with versioned snapshots and resume keys.
- Retry, timeout, cache, and durability policy objects.
- Stream event modes separating values, updates, checkpoints, tasks, debug, and
  messages.
- `interrupt` and `Command(resume=...)` as a clean human-gate contract.
- `Send` and reducer-style aggregation for map-reduce fan-out.

### ADK Patterns To Borrow

- Typed agent/runtime models with strict extra-field handling.
- Service interfaces around sessions, artifacts, memory, credentials, and
  plugins.
- Lifecycle plugins that intercept run, event, agent, model, and tool phases.
- Database-backed session service with schema-managed persistence.
- Evaluation harnesses that replay cases and assert metric thresholds.

### smolagents Patterns To Borrow

- Minimal step memory with action, planning, final-answer, timing, token usage,
  error, and observation fields.
- Compact run result containing output, state, steps, token usage, and timing.
- Step callbacks for monitoring without overbuilding a plugin platform.
- Explicit local/remote executor boundary and final-answer checks.

## Implementation Principles

- Prefer local, explicit, inspectable artifacts.
- Preserve existing JSON exports until a separate storage migration replaces
  them.
- Introduce seams first, then move storage behind them.
- Keep validators and recovery verbs deterministic.
- Make every implicit state change produce an auditable event.
- Treat git reality as authoritative for worktrees; store observed state, but
  always reconcile against git.
- Keep public CLI contracts versioned when JSON output is consumed by tests,
  TUI, or slash commands.
- Let TUI consume the same JSON contracts as CLI and tests.
- Avoid abstraction until at least two call sites need it, except for state
  ownership seams where the missing abstraction is already causing defects.

## Execution Rules For Agents

Agents implementing this plan must follow these rules:

- Do not add an app-user production runtime, hosted graph server, user memory
  service, or credential service as part of this plan.
- Do not start a SQLite canonical-store migration before the state ownership
  seam, typed contracts, event envelope, and trace/eval checks exist.
- Preserve existing JSON artifacts and CLI JSON contracts unless the task
  explicitly includes a schema version bump and compatibility tests.
- Route new state mutations through owner modules. Do not add fresh direct
  writes to prepared artifacts, phase-session state, worktree manifests, or run
  event ledgers outside the store/event layer.
- Keep hook support internal-only until built-in hook behavior is stable and
  tested. Do not add user-discoverable plugins.
- Keep reducers narrow. Use them only for artifact families with real fan-out
  merge pressure.
- Add failure-mode tests for each behavioral change. Do not use live
  Claude/Codex calls in unit tests.
- Each agent must list changed files, tests run, and compatibility risks in
  its handoff.

## Dependency Graph

```text
Phase 1 state ownership boundary
  -> Phase 2 typed domain contracts
  -> Phase 3 policy objects
  -> Phase 4 run trace / replay / eval
  -> Phase 5 event envelope
  -> Phase 6 internal hooks
  -> Phase 7 operator decisions
  -> Phase 8 selective reducers
  -> Phase 9 SQLite decision / migration
```

Phase 3 can begin while Phase 2 is in progress if it only wraps existing
policy dictionaries. Phase 4 should wait until Phase 1 makes state reads
consistent. Phase 9 should not start until Phases 1, 2, and 5 have stabilized.

## Phase 1 - State Ownership Boundary

### Objective

Create narrow owner modules for run, prepared artifact, phase-session, worktree,
and event writes before changing the underlying storage format.

### Why

The current risk is not JSON itself. The risk is coupled state spread across
several files and modules. A storage seam gets the largest reliability gain
with the lowest migration risk.

### Proposed Modules

```text
py/swarm_do/pipeline/state_store.py
py/swarm_do/pipeline/prepared_artifact_writer.py
py/swarm_do/pipeline/phase_session_store.py
py/swarm_do/pipeline/worktree_state_store.py
```

Use existing modules as much as possible. Do not duplicate validation logic.
This phase is an ownership refactor, not a behavior rewrite.

### Implementation

1. Add `state_store.py` with small interfaces and current JSON-backed
   implementations:
   - `RunStateStore`
   - `PreparedArtifactStore`
   - `PhaseSessionStore`
   - `WorktreeStateStore`
   - `RunEventSink`
2. Add `prepared_artifact_writer.py` if not already present:
   - load accepted prepared artifact
   - update git base and sidecar artifacts atomically
   - recompute descriptor hashes
   - write sidecars before final artifact
   - preserve backup on failure
3. Move direct prepared-artifact writes behind `PreparedArtifactStore`.
4. Move direct phase-session writes behind `PhaseSessionStore` where practical.
5. Move worktree manifest writes behind `WorktreeStateStore`.
6. Keep JSON file paths unchanged for compatibility.
7. Add a lightweight fence test that fails if new direct writes to core
   state files appear outside store modules.

### Test Anchors

```text
py/swarm_do/pipeline/tests/test_state_store.py
py/swarm_do/pipeline/tests/test_prepared_artifact_writer.py
py/swarm_do/pipeline/tests/test_state_store_write_fence.py
```

Tests must cover:

- load/write round trip with unchanged JSON bytes where compatibility matters;
- simulated mid-write failure restores or leaves prior state intact;
- sidecar descriptor SHA is recomputed with artifact bytes;
- existing `phases status`, `phases pump`, and prepared dispatch fixtures still
  pass;
- direct write fence allows only documented store modules.

### Acceptance Criteria

- All control-plane state mutations route through owner modules or documented
  exceptions.
- Existing CLI behavior is unchanged.
- Existing JSON artifact locations remain valid.
- New store APIs are small enough that a SQLite backend could be added without
  changing callers.

### Risk

Medium risk of churn because state writes are spread across many helpers.
Mitigate by moving one artifact family at a time and keeping compatibility
tests close to existing fixtures.

## Phase 2 - Typed Domain Contracts

### Objective

Replace unstructured orchestration dicts in core code paths with typed domain
objects and explicit validation/conversion boundaries.

### Why

ADK and LangGraph both use typed contracts to make runtime state predictable.
SwarmDaddy has schemas and lints, but much of the orchestration core still
passes open dicts around. Typed contracts reduce accidental shape drift and
make later storage/hook/event work safer.

### Proposed Contracts

Create a domain module:

```text
py/swarm_do/pipeline/domain.py
```

Initial dataclasses:

```text
RunRef
RunRecord
PhaseRecord
PhaseAttemptRecord
StageRecord
WorkUnitRecord
ProviderRunRecord
ProviderFindingRecord
DoctorFinding
PolicyDecision
ArtifactExport
```

Use stdlib dataclasses first. Include:

- `from_mapping()`
- `to_dict()`
- `validate()`
- stable status enums as string constants or `Enum` values where already
  helpful

Avoid converting every module at once.

### Implementation

1. Start with `PhaseRecord`, `PhaseAttemptRecord`, and `DoctorFinding` because
   they sit in status/recovery/TUI paths.
2. Convert `phase_status`, `phase_doctor`, and phase-attempt summaries to
   create typed objects internally and emit existing JSON externally.
3. Add `ProviderFindingRecord` and `ProviderRunRecord` after phase contracts.
4. Add `WorkUnitRecord` only after confirming it does not duplicate schema
   lint behavior.
5. Keep external JSON contracts stable unless an explicit schema version bump
   is part of the implementation.

### Test Anchors

```text
py/swarm_do/pipeline/tests/test_domain_contracts.py
py/swarm_do/pipeline/tests/test_phase_status.py
py/swarm_do/pipeline/tests/test_phase_doctor.py
py/swarm_do/pipeline/tests/test_provider_review.py
```

Tests must cover:

- unknown keys rejected at domain boundaries where appropriate;
- missing required fields produce useful errors;
- status enums accept all existing persisted statuses;
- JSON output remains backward compatible.

### Acceptance Criteria

- Core status/recovery paths no longer need repeated `Mapping[str, Any]`
  shape checks for the same record type.
- Domain objects do not become a second schema system for artifacts already
  governed by JSON schema; they own runtime control-plane shape.

### Risk

Low if incremental. High if treated as a sweeping conversion. Keep phase and
provider paths first.

## Phase 3 - Policy Objects

### Objective

Centralize retry, timeout, cache, budget, and failure-tolerance settings into
small immutable policy objects.

### Why

LangGraph's `RetryPolicy`, `TimeoutPolicy`, and `CachePolicy` are strong because
they are explicit, inspectable, and reusable. SwarmDaddy already has these
concepts in dictionaries and scattered helper arguments.

### Proposed Module

```text
py/swarm_do/pipeline/policies.py
```

Initial objects:

```text
RetryPolicy
TimeoutPolicy
BudgetPolicy
FailureTolerancePolicy
ProviderSelectionPolicy
WorktreeRecoveryPolicy
```

### Implementation

1. Add policy objects with `from_mapping()` and `to_dict()`.
2. Wrap existing phase-session retry policy defaults.
3. Wrap provider-review `selection`, `min_success`, `max_parallel`, and
   timeout configuration.
4. Wrap budget preview thresholds.
5. Update TUI/config/status rendering to display policies through one helper.
6. Do not add caching behavior until a concrete cacheable operation is chosen.

### Test Anchors

```text
py/swarm_do/pipeline/tests/test_policies.py
py/swarm_do/pipeline/tests/test_phase_autopilot_policy.py
py/swarm_do/pipeline/tests/test_provider_review.py
py/swarm_do/pipeline/tests/test_budget_estimator.py
```

### Acceptance Criteria

- Policy defaults are defined once.
- CLI/TUI/status output can show resolved policy values.
- Existing policy override behavior remains compatible.
- Invalid policy input errors are deterministic and operator-readable.

### Risk

Low. This is a cleanup with immediate clarity benefits.

## Phase 4 - Run Trace, Replay, And Eval Harness

### Objective

Create a testable replay/eval layer over durable run artifacts so SwarmDaddy can
validate orchestration behavior without live model calls.

### Why

For a development orchestrator, replay and evaluation are more valuable than
production deployment features. smolagents' `RunResult` and step memory are a
good model: compact, serializable, and replayable. ADK's eval harness shows the
value of turning agent behavior into repeatable test cases.

### Proposed Modules

```text
py/swarm_do/pipeline/run_trace.py
py/swarm_do/pipeline/run_eval.py
```

### Trace Shape

`RunTrace` should be a derived view, not a new source of truth:

```text
RunTrace
  run_id
  source_paths
  phases[]
  attempts[]
  provider_runs[]
  worktree_events[]
  run_events[]
  artifacts[]
  summary
```

`AttemptTrace` should include:

- phase id
- attempt number
- launcher
- prompt path
- command metadata path
- stdout/stderr paths
- result/handoff paths
- failure kind
- retry decision
- token/cost metrics when known
- changed files summary when known

### Implementation

1. Add `swarm trace build <run-id> --json`.
2. Add fixture-backed `swarm eval run <fixture-dir>`.
3. Add golden run fixtures for:
   - clean single phase
   - needs-input
   - retryable failure then success
   - provider-review partial success
   - worktree drift
   - malformed result artifact
4. Add assertions over state transitions, emitted events, and recovery
   recommendations.
5. Do not attempt deterministic model-output replay. Replay state, decisions,
   and artifact handling.

### Test Anchors

```text
py/swarm_do/pipeline/tests/test_run_trace.py
py/swarm_do/pipeline/tests/test_run_eval.py
tests/fixtures/run-traces/
docs/eval-recipes.md
```

### Acceptance Criteria

- A fixture can validate orchestration behavior without calling Claude/Codex.
- Failed eval output names the first unexpected transition or missing artifact.
- Trace JSON is versioned.
- Trace generation is read-only.

### Risk

Low-medium. The main risk is trying to replay model reasoning. Keep scope to
control-plane behavior.

## Phase 5 - Unified Typed Event Envelope

### Objective

Define one internal event envelope for orchestration events while continuing to
mirror existing telemetry JSONL outputs.

### Why

LangGraph's stream modes prove the value of typed event categories. SwarmDaddy
currently has run events, stage markers, observations, provider findings, and
TUI state readers. A typed envelope makes status, replay, TUI, and future
SQLite migration easier.

### Proposed Module

```text
py/swarm_do/pipeline/events.py
```

### Envelope

```json
{
  "schema_version": 1,
  "run_id": "...",
  "seq": 1,
  "timestamp": "...",
  "kind": "phase_session_started",
  "actor": "phase_pump",
  "phase_id": "1",
  "stage_id": null,
  "attempt": 1,
  "payload": {}
}
```

Do not collapse telemetry ledgers in this phase. Use the envelope internally,
then adapt to current `telemetry/run_events.jsonl` schema.

### Event Categories

```text
run
phase
stage
attempt
provider
artifact
worktree
operator_decision
doctor
budget
launcher
```

### Implementation

1. Add `RunEventEnvelope` domain type.
2. Add `RunEventSink.append(envelope)`.
3. Adapt existing `append_run_event()` calls gradually.
4. Add deterministic sequence handling where the current sink can support it.
5. Expose `swarm events tail <run-id> --json` as read-only.
6. Keep existing telemetry tests passing.

### Test Anchors

```text
py/swarm_do/pipeline/tests/test_events.py
py/swarm_do/telemetry/tests/test_schemas.py
py/swarm_do/telemetry/tests/test_jsonl.py
```

### Acceptance Criteria

- New orchestration events are created through one envelope type.
- Existing telemetry JSONL consumers are not broken.
- TUI can consume event stream rows without parsing unrelated artifacts.

### Risk

Medium. Event schema churn is easy to spread. Keep the adapter layer explicit
and avoid changing existing ledgers until a separate migration plan.

## Phase 6 - Internal Hook Lifecycle

### Objective

Add internal hook points for policy checks, validators, provider readiness,
telemetry, and artifact export without exposing a public plugin API.

### Why

ADK's plugin lifecycle cleanly separates runtime concerns from core agent
execution. SwarmDaddy can use the same idea internally to reduce coupling
between phase pump, provider review, doctor checks, and telemetry.

### Proposed Module

```text
py/swarm_do/pipeline/hooks.py
```

### Initial Hook Points

```text
before_run_prepare
after_run_prepare
before_phase_claim
after_phase_claim
before_phase_launch
after_phase_result
before_provider_run
after_provider_result
doctor_checks
before_artifact_export
after_artifact_export
```

### Implementation

1. Add an internal hook registry with typed hook inputs/outputs.
2. Register built-in hooks only.
3. Move telemetry append logic behind hooks where this reduces coupling.
4. Move doctor check aggregation to a hook list only after `DoctorFinding`
   exists.
5. Keep hook execution deterministic and ordered.
6. Do not load arbitrary hooks from user config.

### Test Anchors

```text
py/swarm_do/pipeline/tests/test_hooks.py
py/swarm_do/pipeline/tests/test_phase_pump.py
py/swarm_do/pipeline/tests/test_provider_review.py
```

### Acceptance Criteria

- Hook order is stable.
- Hook failures are classified as deterministic contract failures unless the
  hook is explicitly advisory.
- No public extension mechanism is documented.
- Core phase/provider code becomes simpler, not more abstract.

### Risk

Medium. Hook systems can become invisible control flow. Mitigate with a small
registry, typed inputs, and tests that render the active hook list.

## Phase 7 - Operator Decision Model

### Objective

Represent human gates and recovery choices as auditable operator decisions
instead of ad-hoc command flags alone.

### Why

LangGraph's `interrupt` and `Command(resume=...)` provide a clean mental model:
pause with a value, resume with an explicit command. SwarmDaddy should adapt
this for local operator-led recovery.

### Proposed Module

```text
py/swarm_do/pipeline/operator_decisions.py
```

### Decision Types

```text
resume_with_input
retry_phase
skip_best_effort_stage
reset_phase
rebuild_worktree
archive_attempt
cancel_run
abort_phase
accept_provider_partial
```

### Implementation

1. Add `OperatorDecision` typed artifact.
2. Add `swarm decisions record <run-id> ... --json`.
3. Add `swarm decisions apply <run-id> <decision-id> --json`.
4. Make `/swarmdaddy:redo`, `/swarmdaddy:repump`, and future recovery commands
   record a decision event before mutation.
5. Store decisions beside phase-session state initially; route writes through
   the state store.
6. Ensure decisions are idempotent by decision id.

### Test Anchors

```text
py/swarm_do/pipeline/tests/test_operator_decisions.py
py/swarm_do/pipeline/tests/test_phase_recovery.py
py/swarm_do/pipeline/tests/test_phase_cli.py
```

### Acceptance Criteria

- Every mutating recovery command can explain which operator decision caused it.
- Reapplying the same decision is a no-op or a controlled error.
- `phases status --events` can show recent operator decisions.

### Risk

Medium. Do not make normal happy-path phase pumping depend on decision records.
Use this for human gates and recovery mutations.

## Phase 8 - Selective Reducer-Style Fan-Out Merges

### Objective

Improve fan-out merge quality for review, research, analysis, and provider
evidence artifacts without rewriting the pipeline engine.

### Why

LangGraph's reducer model is useful where multiple parallel outputs update the
same state. SwarmDaddy already has fan-out and synthesis concepts. It should
borrow reducers for artifact families that naturally merge.

### Proposed Module

```text
py/swarm_do/pipeline/reducers.py
```

### Initial Reducers

```text
FindingsReducer
ProviderConsensusReducer
ResearchNotesReducer
AnalysisAlternativesReducer
PlanReviewReducer
```

### Implementation

1. Define a reducer protocol:
   - `identity()`
   - `add(left, right)`
   - `finalize(value)`
   - `diagnostics(value)`
2. Start with provider findings because normalization/clustering already
   exists.
3. Add research/analysis reducers only where current pipelines have repeated
   merge pain.
4. Preserve existing merge agents. Reducers prepare structured context; they
   do not replace the synthesizer unless tests prove enough quality.

### Test Anchors

```text
py/swarm_do/pipeline/tests/test_reducers.py
py/swarm_do/pipeline/tests/test_provider_review.py
py/swarm_do/pipeline/tests/test_mco_stage.py
```

### Acceptance Criteria

- Duplicates are collapsed deterministically.
- Severity/confidence/top-N policies are explicit.
- Reducer output is stable across input order where order should not matter.
- Synthesis prompts get cleaner structured input.

### Risk

Medium. Overusing reducers can flatten nuance. Keep human-readable source
notes and provider sidecars available.

## Phase 9 - SQLite Control-Plane Decision

### Objective

After state seams, typed contracts, and event envelopes exist, decide whether
to move canonical run control-plane state into per-run SQLite.

### Why

SQLite is still likely the best eventual answer for atomic multi-file state
updates, status queries, and state/event coupling. It is not the first move
because a storage seam gives immediate benefits and makes migration safer.

### Precondition Checklist

Do not start SQLite migration until:

- Phase 1 state stores own core writes.
- Phase 2 domain contracts cover phase/session/status/provider records.
- Phase 5 event envelope is stable for new orchestration events.
- Run trace can compare pre/post migration behavior.
- A JSON export compatibility story exists.

### Proposed Shape

```text
data_dir/runs/<run-id>/state.sqlite
```

Canonical DB tables:

```text
runs
phases
phase_attempts
stages
work_units
provider_runs
worktrees
events
artifact_exports
operator_decisions
```

Generated/exported files remain:

```text
prepared.md
prepared_plan.v1.json
inspect.v1.json
work_units/*.json
phase_results/*.json
phase_handoffs/*.json
telemetry/*.jsonl
```

The DB owns control-plane state. JSON files are compatibility snapshots and
worker-visible artifacts unless explicitly documented as canonical.

### Implementation Plan

1. Write a research/ADR update confirming SQLite version, WAL/rollback-journal
   choice, migration strategy, and compatibility guarantees.
2. Implement read-only SQLite mirror first.
3. Compare JSON state and SQLite mirror through `swarm trace build`.
4. Switch one state family to DB canonical, likely phase sessions or worktree
   manifest, not everything.
5. Export deterministic JSON snapshots after each DB transaction.
6. Keep rollback path until dogfood runs prove stable.

### Test Anchors

```text
py/swarm_do/pipeline/tests/test_state_sqlite.py
py/swarm_do/pipeline/tests/test_state_store.py
py/swarm_do/pipeline/tests/test_run_trace.py
docs/adr/
```

### Acceptance Criteria

- State mutation and event append can happen in one transaction for migrated
  state families.
- Existing CLI and slash commands do not need to know whether the backend is
  JSON or SQLite.
- Operators can dump DB state as JSON.
- JSON exports are deterministic and recorded in `artifact_exports`.

### Risk

Medium-high. Worth it only after seams lower blast radius. Do not migrate just
because SQLite is cleaner in theory.

## Rejected Track - Production App-Agent Runtime

### Decision

Do not build ADK/LangGraph-style app-agent runtime features into core
SwarmDaddy.

### Examples To Reject

- User session service for app end users.
- Credential management for arbitrary app users.
- Long-term user memory service.
- Hosted graph API server.
- Remote assistant SDK.
- General-purpose tool marketplace.
- Public plugin ecosystem.

### Rationale

These are high-value features for agent applications, but low-value for
SwarmDaddy's local development-orchestration mission. They would add security,
support, deployment, and API-stability burden without improving repo-local
swarm runs enough to justify the cost.

## Cross-Phase Test Strategy

Every phase should include:

- fixture-backed unit tests;
- one CLI JSON-output test when a command surface changes;
- one compatibility test proving existing artifacts still load;
- one failure-mode test, not just happy path;
- no live Claude/Codex calls in unit tests;
- dogfood recipe added or updated in `docs/eval-recipes.md` when behavior is
  visible to operators.

Preferred fixture families:

```text
tests/fixtures/run-traces/
py/swarm_do/pipeline/tests/fixtures/claude_print/
py/swarm_do/pipeline/tests/fixtures/claude_transcripts/
py/swarm_do/pipeline/tests/fixtures/mco_review_*.json
```

## Agent Work Breakdown

### Agent A - State Seam

Owns:

```text
py/swarm_do/pipeline/state_store.py
py/swarm_do/pipeline/prepared_artifact_writer.py
py/swarm_do/pipeline/tests/test_state_store*.py
```

Do not touch:

```text
py/swarm_do/pipeline/reducers.py
py/swarm_do/pipeline/hooks.py
```

Deliverable: Phase 1 complete.

### Agent B - Domain Contracts And Policies

Owns:

```text
py/swarm_do/pipeline/domain.py
py/swarm_do/pipeline/policies.py
py/swarm_do/pipeline/tests/test_domain_contracts.py
py/swarm_do/pipeline/tests/test_policies.py
```

Coordinate with Agent A on store return types.

Deliverable: Phases 2 and 3 minimal contracts complete.

### Agent C - Trace And Eval

Owns:

```text
py/swarm_do/pipeline/run_trace.py
py/swarm_do/pipeline/run_eval.py
py/swarm_do/pipeline/tests/test_run_trace.py
py/swarm_do/pipeline/tests/test_run_eval.py
docs/eval-recipes.md
```

Depends on Agent A state-read seam.

Deliverable: Phase 4 complete.

### Agent D - Events And Hooks

Owns:

```text
py/swarm_do/pipeline/events.py
py/swarm_do/pipeline/hooks.py
py/swarm_do/pipeline/tests/test_events.py
py/swarm_do/pipeline/tests/test_hooks.py
```

Depends on Agent B domain contracts.

Deliverable: Phases 5 and 6 minimal internal-only versions complete.

### Agent E - Operator Decisions And Reducers

Owns:

```text
py/swarm_do/pipeline/operator_decisions.py
py/swarm_do/pipeline/reducers.py
py/swarm_do/pipeline/tests/test_operator_decisions.py
py/swarm_do/pipeline/tests/test_reducers.py
```

Depends on Agent D event envelope.

Deliverable: Phases 7 and 8 minimal versions complete.

### Agent F - SQLite Decision

Owns:

```text
docs/adr/
docs/swarmdaddy-state-storage-sqlite-recommendation-2026-05-01.md
py/swarm_do/pipeline/tests/test_state_sqlite.py
```

Depends on Phases 1, 2, 4, and 5.

Deliverable: Phase 9 ADR and optional read-only mirror prototype. Do not switch
canonical storage without separate approval.

## Rollout Strategy

1. Land Phase 1 behind current JSON behavior.
2. Run full pipeline tests.
3. Dogfood one prepared run and one phase-session recovery.
4. Land Phases 2 and 3 in small PRs.
5. Add trace/eval fixtures before changing event envelope.
6. Add event envelope adapter while preserving telemetry JSONL.
7. Add hooks only after tests can show hook order and failure behavior.
8. Add operator decisions for recovery commands first, not happy-path pump.
9. Revisit SQLite with evidence from trace/eval and state-store ergonomics.

## Success Metrics

- Fewer direct state writes outside owner modules.
- Fewer repeated `Mapping[str, Any]` shape checks in core orchestration code.
- Recovery commands can explain state changes through events or decisions.
- Run traces can reproduce control-plane outcomes without live model calls.
- TUI/status code consumes typed summaries rather than parsing several files.
- SQLite migration, if pursued, becomes a backend swap rather than a system
  rewrite.

## Final Guidance For Implementing Agents

Keep SwarmDaddy weird in the right way. It is not a generic agent app platform.
It is a local, auditable development harness that governs agent engineering
runs. Refactors should make runs easier to trust, inspect, resume, and test.
When a proposed change mainly helps hosted app agents, user memory, remote
deployment, or public plugin ecosystems, cut it unless it directly improves
repo-local orchestration.
