# SwarmDaddy Runtime Foundations Adoption Plan

Date: 2026-05-02
Status: decomposed roadmap/reference; active implementation plans live under `docs/runtime-foundations/`
Owner: swarm-do runtime, storage, recovery, telemetry, and TUI surfaces
Source comparison: ADK Python, smolagents, LangGraph, and current SwarmDaddy code

Related research:

- `docs/research-similar-systems-2026-05-01.md`
- `docs/swarmdaddy-state-storage-sqlite-recommendation-2026-05-01.md`
- `docs/architecture-assessment-2026-05-01.md`
- `docs/swarmdaddy-durable-run-capabilities-research-plan.md`
- `docs/ecc-pattern-adoption-plan.md`

Implementation split:

- `docs/runtime-foundations/README.md` is the active build-order roadmap.
- `docs/runtime-foundations/phase-1-state-ownership-boundary-plan.md`
- `docs/runtime-foundations/phase-4-run-trace-eval-plan.md`
- `docs/runtime-foundations/phase-3-policy-consolidation-plan.md`
- `docs/runtime-foundations/phase-4-5-readonly-sqlite-projector-plan.md`
- `docs/runtime-foundations/phase-2-domain-contracts-plan.md`
- `docs/runtime-foundations/phase-7-operator-decisions-plan.md`

Treat this file as the long-form strategy/evidence reference. Implement from
the smaller child plans above.

In-flight plan with overlapping surface (must coordinate before either lands):

- `docs/phase-session-live-stage-marker-streaming-plan.md` — adds
  `stage_controller.py` and `claude_stream.py` (consumers, not writers),
  emits early `stage_adopted` events, and writes `command.json.stage_controller`
  counters that Phase 4 trace must surface. See § Phase 1 fence whitelist,
  § Phase 4 streaming coordination, § Phase 9 migration order rank 2.5,
  and § Concerns And Regression Boundary for the full coordination contract.

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

1. Finish the state ownership boundary already prototyped in
   `prepared_artifact_writer.py` (`RunStateStore`/`RunStateTxn` Protocols).
2. Build a run trace plus replay/eval harness so behavior can be verified
   without live model calls. This is the highest leverage move for a local
   development harness and gates everything downstream.
3. Centralize retry/timeout/budget policy objects, consolidating the existing
   `phase_autopilot_policy.py` instead of building a parallel system.
4. Move orchestration dicts into typed domain contracts incrementally —
   without creating a second schema system parallel to existing JSON schemas.
5. Stand up a read-only SQLite projector as a derived view (Phase 4.5) before
   any canonical-store migration, so trace/eval, status, doctor, and TUI all
   read from one place without committing to a write-side migration.
6. Represent operator decisions as auditable command artifacts, scoped to
   recovery commands only.
7. Defer the typed event envelope, internal hook lifecycle, and broad
   reducer system until ≥2 concrete call sites need them.
8. Re-evaluate the SQLite canonical move only after Phases 1, 3, 4, and 4.5
   prove the read-side seam works.

This sequence gives most of the operational benefit while preserving the
single-machine, inspectable development-harness model.

### Ranking Revision Note (2026-05-02)

This plan was reviewed against actual repo state. Findings driving the revised
ranking and Concerns sections below:

- `prepared_artifact_writer.py` already exists (517 lines) and ships
  `RunStateStore`/`RunStateTxn` Protocol stubs — Phase 1 is partially landed.
- `phase_autopilot_policy.py` already provides `AutopilotPolicyConfig`,
  `AutopilotPolicyInput`, `AutopilotPolicyDecision`, `ResolvedPolicyUpdate` —
  Phase 3 must consolidate, not duplicate.
- `phase_decisions.py` already exists for "shared decisions" — Phase 7's
  `operator_decisions.py` must disambiguate naming.
- `phase_evidence.py` already enforces SCHEMA_VERSION manifests — Phase 2 must
  not become a parallel schema system.
- Provider review (`provider_review.py`) already has `_consensus_groups`,
  `consensus_policy()`, calibration logic — Phase 8 has only one mature call
  site, violating this plan's own "≥2 call sites" rule.
- Control-plane state is JSON; SQLite is used only for `:memory:` telemetry
  query (`telemetry/subcommands/query.py`) and the `mem_prime` fixture
  adapter. No canonical SQLite store exists yet.

## Purpose And Overlap Comparison

| System | Primary purpose | Overlap with SwarmDaddy | What it does differently | Should SwarmDaddy copy it? |
| --- | --- | --- | --- | --- |
| SwarmDaddy | Local development harness for orchestrating repo work across agents, Beads, worktrees, phase sessions, provider evidence, recovery, and operator-facing CLI/TUI flows. | Durable runs, staged orchestration, multi-agent fan-out/review, local artifacts, recovery, telemetry. | Treats the repository and git worktrees as the operating environment. Optimizes for developer trust, auditability, and recovery rather than serving app users. | Keep this mission. Borrow foundations that make local runs easier to inspect, resume, and test. |
| Google ADK Python | Production-capable agent application framework with typed agents, runners, services, sessions, artifacts, memory, credentials, plugins, tools, and eval. | Agents, callbacks/hooks, sessions, artifacts, plugin lifecycle, evaluation. | Assumes an app runtime around users, sessions, credentials, and services. Has more infrastructure surface than SwarmDaddy needs for repo-local orchestration. | Copy service boundaries, typed models, lifecycle hooks, and eval concepts. Do not copy user/session/credential app runtime scope into core. |
| Hugging Face smolagents | Compact agent loop framework focused on tool/code agents, managed agents, step memory, monitoring, and local/remote code execution. | Step traces, run result shape, managed agents, final checks, monitoring, executor boundaries. | Centers the agent reasoning loop and tool/code execution. SwarmDaddy usually delegates agent reasoning to Claude/Codex lanes and owns the control plane around them. | Copy compact step/run trace and monitoring ideas. Avoid embedding a second general-purpose agent loop unless a concrete lane needs it. |
| LangGraph | Graph runtime for stateful, durable, resumable agent workflows with typed state, reducers, checkpoints, streaming, interrupts, commands, retry, timeout, and cache policy. | DAG execution, state updates, checkpoint/recovery, fan-out/merge, interrupts, policies, streaming. | Provides a reusable graph runtime for app workflows. SwarmDaddy already has a pipeline engine tied to Beads, worktrees, provider review, and local artifacts. | Copy typed state, checkpointer, policy, event stream, interrupt, and reducer patterns selectively. Do not rewrite SwarmDaddy as a LangGraph graph. |

## Ranking

Re-ranked 2026-05-02 after repo audit. Driver: highest leverage for a *local
development harness* is reproducible behavior verification (trace/eval), not
abstraction layers.

| Rank | Pattern / Gap | Value | Effort | Risk | Decision |
| ---: | --- | --- | --- | --- | --- |
| 1 | Run trace, replay, and eval harness (Phase 4) | Very high | Medium | Low | Promote to first — proves behavior without live model calls |
| 2 | State ownership boundary (Phase 1) | High | Low-medium | Low | Partially landed; finish + add fence test |
| 3 | Read-only SQLite projector (Phase 4.5) | High | Medium | Low | New phase — derived view powering trace/status/doctor; no write migration |
| 4 | Retry/timeout/budget policy objects (Phase 3) | High | Low-medium | Low | Must consolidate `phase_autopilot_policy.py`, not duplicate |
| 5 | Typed run/phase/stage contracts (Phase 2) | Medium-high | Medium | Medium | Incremental only; risk of double schema system |
| 6 | Operator interrupt/resume decision model (Phase 7) | Medium-high | Medium | Medium | Scope to recovery commands; disambiguate from `phase_decisions.py` |
| 7 | Unified typed event envelope (Phase 5) | Medium | Medium-high | Medium | Defer — adapter-only benefit until SQLite arrives |
| 8 | Reducer-style fan-out/merge state (Phase 8) | Low-medium | Medium-high | Medium | Defer — only one mature call site (provider review) |
| 9 | Internal hook/plugin lifecycle (Phase 6) | Low | Medium | High | Cut for now — plan itself admits "invisible control flow" risk; revisit only if a concrete decoupling need appears |
| 10 | SQLite canonical control-plane store (Phase 9) | High | High | Medium-high | Defer; gated on Phase 4.5 dogfood + Phase 1 fence + behavioral test net |
| 11 | Production app-agent runtime features | Low | Very high | High | Reject for core SwarmDaddy |

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
the three referenced repositories.

**Required before agent execution:** every upstream file referenced in this
plan MUST be re-pinned to a specific commit hash and verified against
the API snippets below. Upstream churn between research and adoption can
silently invalidate "pattern names" used here. The implementing agent for
each phase must record the commit SHA they read against in their handoff.

Suggested pin format in handoff:

```text
adk-python@<sha>  src/google/adk/plugins/base_plugin.py:<lines>
langgraph@<sha>   libs/langgraph/langgraph/types.py:<lines>
smolagents@<sha>  src/smolagents/memory.py:<lines>
```

Source areas referenced:

- SwarmDaddy (this repo, 2026-05-02 main):
  - `README.md`
  - `pipelines/default.yaml`
  - `py/swarm_do/pipeline/engine.py`
  - `py/swarm_do/pipeline/phase_sessions.py`
  - `py/swarm_do/pipeline/phase_pump.py`
  - `py/swarm_do/pipeline/provider_review.py`
  - `py/swarm_do/pipeline/executor.py`
  - `py/swarm_do/pipeline/validation.py`
  - `py/swarm_do/pipeline/prepared_artifact_writer.py` (already declares
    `RunStateStore`/`RunStateTxn` Protocol stubs — Phase 1 anchor)
  - `py/swarm_do/pipeline/phase_autopilot_policy.py` (already typed; Phase 3
    must subsume)
  - `py/swarm_do/pipeline/phase_decisions.py` (existing "shared decisions" —
    Phase 7 must disambiguate)
  - `py/swarm_do/pipeline/phase_evidence.py` (existing SCHEMA_VERSION pattern)
  - `py/swarm_do/pipeline/run_state.py` (`append_run_event`, atomic JSON write)
  - `py/swarm_do/telemetry/subcommands/query.py` (existing `:memory:` SQLite
    surface — regression boundary for Phase 4.5/Phase 9)
- ADK Python (`google/adk-python`, pin TBD):
  - `src/google/adk/agents/base_agent.py`
  - `src/google/adk/agents/sequential_agent.py`
  - `src/google/adk/agents/parallel_agent.py`
  - `src/google/adk/agents/loop_agent.py`
  - `src/google/adk/runners.py`
  - `src/google/adk/sessions/base_session_service.py`
  - `src/google/adk/sessions/database_session_service.py`
  - `src/google/adk/plugins/base_plugin.py`
  - `src/google/adk/evaluation/agent_evaluator.py`
- smolagents (`huggingface/smolagents`, pin TBD):
  - `src/smolagents/agents.py`
  - `src/smolagents/tools.py`
  - `src/smolagents/memory.py`
  - `src/smolagents/local_python_executor.py`
  - `src/smolagents/remote_executors.py`
  - `src/smolagents/monitoring.py`
- LangGraph (`langchain-ai/langgraph`, pin TBD):
  - `libs/langgraph/langgraph/graph/state.py`
  - `libs/langgraph/langgraph/types.py`
  - `libs/checkpoint/langgraph/checkpoint/base/__init__.py`
  - `libs/cli/README.md`

## Borrowed API Surfaces (Reference Snippets)

These snippets capture the *shape* of each borrowed pattern as known at plan
authorship. They are not authoritative — implementing agents must re-read
upstream at their pinned commit and update the snippets here if they drift.

### LangGraph — `interrupt` and `Command` (Phase 7)

Pin: `langgraph@<TBD>` `libs/langgraph/langgraph/types.py`

```python
# Approximate API surface — verify at pinned commit before adoption.
def interrupt(value: Any) -> Any:
    """Pause the graph. Operator resumes with Command(resume=...).
    The same call returns the resumed value when re-entered."""

@dataclass
class Command(Generic[N]):
    graph: str | None = None
    update: dict[str, Any] | Sequence[tuple[str, Any]] | None = None
    resume: dict[str, Any] | Any | None = None
    goto: str | Send | Sequence[str | Send] | None = None
```

SwarmDaddy adaptation: do NOT embed `interrupt()` in the pipeline runner.
Use the *contract* — pause-with-value, resume-with-typed-command — as the
shape of `OperatorDecision` in Phase 7.

### LangGraph — Policy objects (Phase 3)

Pin: `langgraph@<TBD>` `libs/langgraph/langgraph/types.py`

```python
@dataclass
class RetryPolicy:
    initial_interval: float = 0.5
    backoff_factor: float = 2.0
    max_interval: float = 128.0
    max_attempts: int = 3
    jitter: bool = True
    retry_on: type[Exception] | Sequence[type[Exception]] | Callable[[Exception], bool] = ...

@dataclass
class CachePolicy(Generic[ValueT]):
    key_func: Callable[..., str] | None = None
    ttl: float | None = None
```

SwarmDaddy adaptation: `policies.RetryPolicy` consolidates the
`AutopilotPolicyConfig` retry fields. Do NOT add `CachePolicy` until a
concrete cacheable operation exists (this plan's Implementation Principles
explicitly forbid it).

### smolagents — `RunResult` and step memory (Phase 4)

Pin: `smolagents@<TBD>` `src/smolagents/memory.py`

```python
@dataclass
class RunResult:
    output: Any | None
    state: Literal["success", "max_steps_error"]
    messages: list[dict]
    token_usage: TokenUsage | None
    timing: Timing

@dataclass
class ActionStep:
    step_number: int
    timing: Timing
    model_input_messages: list[ChatMessage] | None = None
    tool_calls: list[ToolCall] | None = None
    error: AgentError | None = None
    model_output_message: ChatMessage | None = None
    observations: str | None = None
    action_output: Any = None
```

SwarmDaddy adaptation: `RunTrace`/`AttemptTrace` mirror this shape but
project from durable artifacts on disk — they are NOT a live execution
memory. SwarmDaddy's "step" is a phase attempt, not a model turn.

### ADK Python — `BasePlugin` lifecycle (Phase 6, deferred)

Pin: `adk-python@<TBD>` `src/google/adk/plugins/base_plugin.py`

```python
class BasePlugin:
    name: str

    async def on_user_message_callback(self, *, invocation_context, user_message): ...
    async def before_run_callback(self, *, invocation_context): ...
    async def on_event_callback(self, *, invocation_context, event): ...
    async def after_run_callback(self, *, invocation_context): ...
    async def before_agent_callback(self, *, agent, callback_context): ...
    async def after_agent_callback(self, *, agent, callback_context): ...
    async def before_model_callback(self, *, callback_context, llm_request): ...
    async def after_model_callback(self, *, callback_context, llm_response): ...
    async def before_tool_callback(self, *, tool, tool_args, tool_context): ...
    async def after_tool_callback(self, *, tool, tool_args, tool_context, result): ...
```

SwarmDaddy adaptation: deferred (Phase 6 is cut). Reference kept so any
future revival starts from the right surface, but we will not add async
plugin callbacks to a synchronous CLI harness without a concrete need.

### ADK Python — `BaseSessionService` interface (Phase 9 reference)

Pin: `adk-python@<TBD>` `src/google/adk/sessions/base_session_service.py`

```python
class BaseSessionService(ABC):
    @abstractmethod
    async def create_session(self, *, app_name, user_id, state=None, session_id=None) -> Session: ...
    @abstractmethod
    async def get_session(self, *, app_name, user_id, session_id, config=None) -> Session | None: ...
    @abstractmethod
    async def list_sessions(self, *, app_name, user_id) -> ListSessionsResponse: ...
    @abstractmethod
    async def delete_session(self, *, app_name, user_id, session_id) -> None: ...
    @abstractmethod
    async def append_event(self, session, event) -> Event: ...
```

SwarmDaddy adaptation: SwarmDaddy has no end-user concept. The borrowed
shape is "a service interface with a JSON backend and a SQLite backend
behind the same Protocol", not the user-session semantics. See Phase 9.

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

Revised 2026-05-02 to reflect promotion of trace/eval and addition of
read-only projector.

```text
Phase 0 live stage marker streaming coordination
  -> Phase 1 state ownership boundary (finish prototype)
       -> Phase 4 run trace / replay / eval   [can begin read-only in parallel]
       -> Phase 3 policy consolidation
Phase 1 + Phase 3 + Phase 4
  -> Phase 4.5 read-only SQLite projector
       -> Phase 2 typed domain contracts (selective)
            -> Phase 7 operator decisions (recovery scope)
                 -> Phase 9 SQLite canonical (gated)
DEFERRED: Phase 5 event envelope
DEFERRED: Phase 8 reducers (until ≥2 call sites)
CUT:      Phase 6 internal hooks
```

Phase 1 is partially landed — `prepared_artifact_writer.py` already
declares the Protocols. Phase 4 trace/eval is the highest-leverage move and
should run in parallel with finishing Phase 1 (their seams touch, but Phase
4 is read-only). Phase 3 lands before Phase 4.5 in implementation order
because resolved policy output should not be split across old and new
status/query surfaces. Phase 9 must not start until Phases 1, 4, and 4.5 have
been dogfooded for ≥10 runs without divergence between JSON and the
SQLite mirror.

## Phase 1 - State Ownership Boundary

### Status: Partially Landed

`py/swarm_do/pipeline/prepared_artifact_writer.py` already exists (517 lines)
and already declares `RunStateStore` and `RunStateTxn` Protocols
(`prepared_artifact_writer.py:35-49`). This phase is consolidation +
fence-test work, NOT greenfield.

### Objective

Promote the Protocols already in `prepared_artifact_writer.py` to a shared
`state_store.py` module, route remaining direct writers through the seam,
and add a fence test before Phase 4/4.5 begin reading state through it.

### Why

The current risk is not JSON itself. The risk is coupled state spread across
several files and modules. The seam already exists for prepared artifacts;
finishing it before Phase 4.5 means trace/eval and the read-only projector
read state through one place.

### Proposed Modules

```text
py/swarm_do/pipeline/state_store.py            (new — promotes existing Protocols)
py/swarm_do/pipeline/prepared_artifact_writer.py  (existing — consolidate)
py/swarm_do/pipeline/phase_session_store.py    (new — wraps phase_sessions.py writes)
py/swarm_do/pipeline/worktree_state_store.py   (new — wraps execution_worktree.py writes)
```

Existing writers that the fence must whitelist (anything else writing to
core state is a defect):

```text
py/swarm_do/pipeline/phase_sessions.py        (phase_sessions.v1.json)
py/swarm_do/pipeline/stage_sessions.py        (stage_sessions.v1.json)
py/swarm_do/pipeline/phase_decisions.py       (shared_decisions.v1.json)
py/swarm_do/pipeline/phase_evidence.py        (evidence.json per attempt)
py/swarm_do/pipeline/phase_beads.py           (per-stage bead transitions)
py/swarm_do/pipeline/prepared_artifact_writer.py  (prepared_plan.v1.json)
py/swarm_do/pipeline/run_state.py             (active_run, run_events.jsonl)
py/swarm_do/pipeline/execution_worktree.py    (worktree manifest.json)
```

Modules that are CONSUMERS of the writer set above (they orchestrate calls
into writers but do not own state files of their own) — do NOT whitelist
them, and reject any PR that adds direct writes from them:

```text
py/swarm_do/pipeline/phase_pump.py
py/swarm_do/pipeline/stage_controller.py      (per streaming plan; NEW — consumer)
py/swarm_do/pipeline/claude_stream.py         (per streaming plan; NEW — pure parser)
```

Coordination note: the
`docs/phase-session-live-stage-marker-streaming-plan.md` adds
`stage_controller.py` and `claude_stream.py`. Both must remain on the
consumer side of this seam. `StageMarkerProcessor` calls into
`stage_sessions.record_stage_*`, `phase_beads`, `commit_stage_artifacts`,
and `run_state.append_run_event` — never writes JSON directly.

This phase is an ownership refactor, not a behavior rewrite. Do not
duplicate validation logic from `phase_evidence.MANIFEST_SCHEMA_VERSION`,
`phase_sessions.SCHEMA_VERSION`, or `phase_decisions.SCHEMA_VERSION`.

### Implementation

1. Promote existing Protocols from `prepared_artifact_writer.py` to a new
   `state_store.py`:
   - `RunStateStore` (already prototyped at
     `prepared_artifact_writer.py:46-49`)
   - `RunStateTxn` (already prototyped at
     `prepared_artifact_writer.py:35-44`)
   - Add `PreparedArtifactStore`, `PhaseSessionStore`, `WorktreeStateStore`,
     `RunEventSink` Protocols around them.
2. Add `phase_session_store.py` and `worktree_state_store.py` thin wrappers
   that delegate to existing module functions; do not change persisted shape.
3. Move remaining direct phase-session writes behind `PhaseSessionStore`.
4. Move worktree manifest writes behind `WorktreeStateStore`.
5. Keep JSON file paths unchanged for compatibility.
6. Add a lightweight fence test that fails if new direct writes to core
   state files appear outside store modules listed above.
7. **Regression boundary:** the following tests must remain green without
   modification — `test_phase_sessions.py`, `test_phase_pump.py`,
   `test_phase_recovery.py`, `test_prepared_verification.py`,
   `test_phase_crash_resume.py`, `test_provider_review.py`,
   `test_post_writer_report.py`, `test_execution_worktree.py`.

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

### Concern: Risk Of Double Schema System

Existing typed surfaces already exist and MUST be reused, not paralleled:

- `phase_autopilot_policy.AutopilotPolicyConfig` /
  `AutopilotPolicyInput` / `AutopilotPolicyDecision` /
  `ResolvedPolicyUpdate`
- `phase_evidence` SCHEMA_VERSION-versioned manifests
- `prepared_artifact_writer.RefreshBaseResult` (frozen dataclass)
- JSON Schema validators for prepared artifacts, phase results, work units

The `domain.py` boundary is: **runtime control-plane shape inside the
process**. It is NOT for artifact payloads validated by JSON schemas, and
NOT a replacement for SCHEMA_VERSION on persisted manifests.

### Objective

Replace unstructured orchestration dicts in core code paths with typed domain
objects, reusing existing dataclasses where they already cover a record type.

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

Initial dataclasses (Phase 2 first increment):

```text
PhaseRecord
PhaseAttemptRecord
DoctorFinding
PhaseStatusReport
```

Deferred until a real cross-module caller needs them or the phase-record
increment has survived a dogfood run:

```text
ProviderRunRecord
ProviderFindingRecord
RunRef
RunRecord
StageRecord
WorkUnitRecord
ArtifactExport
```

`PolicyDecision` is intentionally not duplicated in `domain.py`; reuse or
extend `phase_autopilot_policy.AutopilotPolicyDecision` during Phase 3 policy
consolidation.

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

### Concern: Must Consolidate, Not Duplicate

`phase_autopilot_policy.py` already exists and provides a typed retry-policy
surface (`AutopilotPolicyConfig`, `evaluate_autopilot_policy`,
`fallback_retry_after_seconds`, `validate_policy_overrides`). Phase 3 must
either:

- (a) move `phase_autopilot_policy` into `policies.py` and re-export from the
  old module to preserve callers, or
- (b) leave `phase_autopilot_policy` in place and have `policies.py` import
  and re-expose its dataclasses.

A NEW parallel `RetryPolicy` class that does not subsume
`AutopilotPolicyConfig` is forbidden — it would silently fork retry behavior
between phase-session pumping and other call sites.

### Objective

Centralize retry and provider-selection policy display first, without
forking existing runtime policy behavior. Timeout, writer-budget,
failure-tolerance, and worktree-recovery policy objects are follow-up
surfaces that should only be introduced when there is a concrete caller to
consolidate.

### Why

LangGraph's `RetryPolicy` and `TimeoutPolicy` are strong because they are
explicit, inspectable, and reusable. SwarmDaddy already has these concepts —
some in `phase_autopilot_policy`, some in dicts, some in helper arguments —
and the consolidation is overdue. (See "Borrowed API Surfaces" above for
the LangGraph reference shape.)

`CachePolicy` is explicitly out of scope per Implementation Principles
("Do not add caching behavior until a concrete cacheable operation is
chosen.").

### Proposed Module

```text
py/swarm_do/pipeline/policies.py
```

Initial surface:

```text
AutopilotPolicyConfig / retry helpers re-exported from phase_autopilot_policy.py
ResolvedPolicySummary for display/reporting
ReviewProviderPolicy re-exported from provider_review.py
```

### Implementation

1. Add `policies.py` as the canonical import/display facade.
2. Re-export existing phase-session retry policy symbols directly; do not
   introduce a parallel `RetryPolicy`.
3. Collapse duplicated phase-session retry defaults into one source of truth.
4. Re-export provider-review `ReviewProviderPolicy`.
5. Expose cost-USD retry gates through `ResolvedPolicySummary.budget`.
6. Defer generic `TimeoutPolicy`, `BudgetPolicy`,
   `FailureTolerancePolicy`, and `WorktreeRecoveryPolicy` until a follow-up
   phase has real consolidation call sites. In particular, do not merge
   writer-tool budgets with cost-USD retry gates.
7. Update TUI/config/status rendering to display policies through one helper.
8. Do not add caching behavior until a concrete cacheable operation is chosen.

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
- stage controller summary (when present): `stages_completed`,
  `duplicate_marker_count`, `amended_count`, `pending_marker_count`,
  `rejected_marker_count`, `rejected_unknown_stage`,
  `rejected_invalid_path`, `rejected_invalid_result`, `parse_error`,
  `legacy_json_retry`, `ignored_frame_types`. Source is
  `command.json.stage_controller` written by the streaming plan
  (`docs/phase-session-live-stage-marker-streaming-plan.md`). Trace
  treats this block as opaque additive metadata — fields appear when the
  streaming runner is in use, absent otherwise.

### Streaming Plan Coordination

The streaming plan adds a stream-json mode that emits early `stage_adopted`
events (already in `schemas/telemetry/run_events.schema.json`). Phase 4
fixtures must include:

- one streaming run where stage 1 adoption timestamp precedes phase exit
  (proves liveness) — assertion target;
- one malformed-frame run that exceeds the 25%/50-frame raw-only threshold
  (proves graceful degradation, not abort);
- one legacy-fallback run where capability probe selects `--output-format
  json` (proves the fallback path still produces a `RunResult`-equivalent
  trace).

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

## Phase 4.5 - Read-Only SQLite Projector

### Status: New Phase (added 2026-05-02)

This is the SwarmDaddy-fit alternative to "do nothing until Phase 9." It
delivers most of SQLite's read-side benefit with none of the write-side
migration risk.

### Objective

Stand up a per-run SQLite database that is **derived from JSON state**
(JSON remains canonical) and powers `swarm trace build`, `phases doctor`,
`phases status`, the TUI, and Phase 4 eval assertions. Validate the
schema in production conditions before considering canonical migration.

### Why This Fits SwarmDaddy

- **Per-run blast radius.** Mirrors Dagster's per-run SQLite shard pattern.
  One run's mirror corruption never touches another run.
- **Deterministic projection.** JSON files are the source; the mirror is
  rebuilt by replaying state files + `run_events.jsonl`. If projection
  diverges, the mirror is the wrong one — JSON wins.
- **Existing SQLite footprint.** `telemetry/subcommands/query.py` already
  has a `:memory:` sqlite3 surface. The projector is a persistent version
  of that pattern, not new technology.
- **Phase 4 needs it anyway.** Trace/eval must read state from one place;
  doing it as SQL queries is cleaner than walking 6 JSON files per query.
- **Free dogfood for Phase 9.** Every divergence between JSON and the
  projector is a schema bug found before write migration risks a real run.

### Proposed Modules

```text
py/swarm_do/pipeline/state_projector.py
py/swarm_do/pipeline/state_projector_schema.sql
py/swarm_do/pipeline/tests/test_state_projector.py
```

### Path

```text
${CLAUDE_PLUGIN_DATA}/runs/<run-id>/state.mirror.sqlite
```

Note: `state.mirror.sqlite` (not `state.sqlite`) — the filename signals
"derived view" and prevents Phase 9 from accidentally inheriting the
read-only path as a canonical store.

### Schema (initial)

Use `STRICT` tables (SQLite >= 3.37). Use rollback-journal mode initially —
the SQLite recommendation memo notes the WAL-reset bug fix in 3.51.3 and
SwarmDaddy is single-writer per run anyway.

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = DELETE;
PRAGMA busy_timeout = 5000;

CREATE TABLE runs (
  run_id TEXT PRIMARY KEY,
  bd_epic_id TEXT,
  repo_root TEXT NOT NULL,
  git_base_sha TEXT NOT NULL CHECK(length(git_base_sha) = 40),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  json_source_sha TEXT NOT NULL    -- sha of last projected JSON snapshot
) STRICT;

CREATE TABLE phases (
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  phase_id TEXT NOT NULL,
  status TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (run_id, phase_id)
) STRICT;

CREATE TABLE phase_attempts (
  run_id TEXT NOT NULL,
  phase_id TEXT NOT NULL,
  attempt INTEGER NOT NULL,
  status TEXT NOT NULL,
  failure_kind TEXT,
  cost_usd REAL,
  started_at TEXT,
  ended_at TEXT,
  PRIMARY KEY (run_id, phase_id, attempt),
  FOREIGN KEY (run_id, phase_id) REFERENCES phases(run_id, phase_id)
) STRICT;

CREATE TABLE events (
  run_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  ts TEXT NOT NULL,
  kind TEXT NOT NULL,
  phase_id TEXT,
  attempt INTEGER,
  payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
  PRIMARY KEY (run_id, seq),
  FOREIGN KEY (run_id) REFERENCES runs(run_id)
) STRICT;
```

### Implementation

1. Add `state_projector.py` with `project_run(run_id, data_dir)` that:
   - reads `prepared_plan.v1.json`, `phase_sessions.v1.json`,
     `shared_decisions.v1.json`, `evidence.json` per attempt, and tail of
     `run_events.jsonl`;
   - rebuilds the SQLite mirror from scratch in a temp file;
   - `os.replace()`s into final path on success;
   - records the JSON source SHA so divergence is detectable.
2. Add `swarm state project <run-id>` and `swarm state mirror <run-id>
   --query "<sql>"`.
3. Trigger projection from the same writer touchpoints that already exist
   (Phase 1 store modules call `project_run` after each commit).
4. Wire Phase 4 trace/eval to read from the mirror via SQL.
5. Add `swarm state diff-mirror <run-id>` that re-projects to a temp DB
   and diffs against the live mirror — surface any divergence as a
   doctor finding.

### Test Anchors

```text
py/swarm_do/pipeline/tests/test_state_projector.py
py/swarm_do/pipeline/tests/test_state_projector_diff.py
py/swarm_do/pipeline/tests/test_run_eval.py        (Phase 4 consumer)
```

### Acceptance Criteria

- A run can be re-projected from JSON to SQLite deterministically.
- `swarm state diff-mirror` finds zero divergence on a clean dogfood run.
- `phases doctor` and TUI status read SQL queries instead of multiple
  JSON loads.
- Mirror corruption never blocks operator commands — re-project from JSON
  recovers.

### Risk

Low. The mirror is derived; if it breaks, delete and re-project. The only
real failure mode is a schema gap — caught quickly by Phase 4 eval cases
and the diff-mirror command.

### Concern: Do Not Promote To Canonical Without Phase 9 ADR

Phase 4.5 must remain read-only. Any code path that writes to the mirror
without also writing to JSON is a Phase 9 migration in disguise and must
be blocked at review.

## Phase 5 - Unified Typed Event Envelope

### Status: DEFERRED (2026-05-02)

The benefit of an envelope is mostly an *adapter for downstream consumers*
(SQLite, TUI, replay). With Phase 4.5 read-only projector now landing
first, those consumers read SQL — not raw events — so the envelope adds
churn without a clear payoff. Revisit only when:

- ≥2 new event consumers need a typed shape that current `run_events.jsonl`
  rows do not provide; or
- Phase 9 SQLite canonical migration starts (event/state coupling needs the
  envelope as the transactional unit).

Until then: keep `run_state.append_run_event` and `validate_run_event` as-is.

### Concern: Telemetry Regression Boundary

If this phase is later un-deferred, `test_query_parity.py` is the regression
boundary — the existing `:memory:` SQL surface in
`telemetry/subcommands/query.py` MUST keep working without modification, or
all downstream telemetry tooling breaks.

### Objective (when un-deferred)

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

### Status: CUT (2026-05-02)

The plan itself flags hooks as "Medium risk" with the rationale "Hook
systems can become invisible control flow." For a single-operator local
harness with synchronous CLI flows, the cost of invisible control flow
exceeds the decoupling benefit.

Cut signals:

- ADK's `BasePlugin` exists because ADK is an async, multi-tenant app
  runtime with unrelated lifecycle owners. SwarmDaddy is none of those.
- Today's "coupling" between phase pump, provider review, doctor, and
  telemetry is small and direct. There is no concrete pain that hooks
  would relieve that a plain function call would not.
- The reference API surface is preserved in "Borrowed API Surfaces"
  above so any future revival starts from the right shape.

Revival criteria:

- Two distinct teams or modules need to inject behavior at the same
  lifecycle point without seeing each other; OR
- A test framework needs to deterministically intercept lifecycle
  transitions across modules without monkeypatching.

Until either appears, prefer ordinary function composition.

### Objective (only if un-cut)

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

### Concern: Naming Collision

`py/swarm_do/pipeline/phase_decisions.py` already exists for "shared
decisions" — controller-promoted decisions that propagate context between
phases (`shared_decisions.v1.json`). Phase 7's `operator_decisions.py` is
a DIFFERENT concept: human-gate recovery commands.

Mitigation:

- Module name: `operator_decisions.py` (not `decisions.py`).
- Artifact filename: `operator_decisions.v1.json` (not `decisions.json`).
- CLI verb: `swarm operator-decision ...` is used so every help string and
  error message must say "operator decision" to disambiguate from shared
  decisions.
- Add a sentence to `phase_decisions.py` docstring linking to
  `operator_decisions.py` so the two concepts cross-reference.

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

`skip_best_effort_stage` is a schema-slot/deferred kind until stage recovery
has a concrete operator command that needs it.

### Implementation

1. Add `OperatorDecision` typed artifact.
2. Add `swarm operator-decision record <run-id> ... --json`.
3. Add `swarm operator-decision apply <run-id> <decision-id> --json`.
4. Make `/swarmdaddy:redo` and future mutating recovery commands record a
   decision event before mutation. Plain `/swarmdaddy:repump` remains a
   happy-path pump tick and does not create an operator decision record.
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

- Every integrated mutating recovery command can explain which operator
  decision caused it. Plain pump/repump progress is excluded by design.
- Reapplying the same decision is a no-op or a controlled error.
- `phases status --events` can show recent operator decisions.

### Risk

Medium. Do not make normal happy-path phase pumping depend on decision records.
Use this for human gates and recovery mutations.

## Phase 8 - Selective Reducer-Style Fan-Out Merges

### Status: DEFERRED (2026-05-02)

This plan's own Implementation Principles say: "Avoid abstraction until at
least two call sites need it." Provider review is the only mature merge
site today, and it already has `_consensus_groups`, `consensus_policy()`,
and calibration logic in `provider_review.py:369+, 2000+`. Adding a 5-class
`reducers.py` for one consumer creates abstraction without payoff.

Revival criteria — un-defer when ANY of:

- A second concrete merge site needs the same protocol (research-merge,
  analysis-merge, plan-review-merge each move from agent-only to having
  structured deduplication needs).
- Provider review is being refactored anyway and the consensus logic could
  cleanly extract.
- Phase 4 eval reveals the merge logic is the failure source, not the
  upstream agents.

Until then: leave provider review's consensus code in place; do not
extract speculatively.

### Objective (only if un-deferred)

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

## Phase 9 - SQLite Canonical Control-Plane (Conditional, Per-Family)

### Status: DEFERRED with concrete preconditions (revised 2026-05-02)

The SQLite recommendation memo
(`docs/swarmdaddy-state-storage-sqlite-recommendation-2026-05-01.md`) is
correct that the recurring bug class — cross-file atomicity, descriptor
SHA self-references, audit/state coupling — is exactly what SQLite solves.
This plan still defers, but with a concrete path and per-family migration
shape rather than "decide later."

### Decision: Defer, then migrate one family at a time

Reasoning for keeping deferred:

- Phase 4.5 (read-only mirror) delivers ~70% of the practical SQL benefit
  (queryable status, doctor, trace/eval inputs) with zero canonical
  migration risk.
- A canonical move requires the Phase 4 behavioral test net to detect any
  regression.
- Single-operator, short-lived processes mean the "atomic state + audit"
  win, while real, has a low daily incidence — operators can repair JSON
  divergence today.

Reasoning for committing to it eventually:

- `prepare refresh-base` and other recovery verbs DO have the cross-file
  atomicity problem the recommendation memo describes. Phase 4.5's
  diff-mirror tooling will surface the divergences quantitatively.
- When divergence rate exceeds a threshold (see "Migration Trigger" below),
  per-family canonical move is the right answer.

### Migration Trigger (objective)

Begin Phase 9 ONLY when ALL of:

1. Phase 1 fence test has been green for ≥30 days with no whitelist
   exceptions added.
2. Phase 4 eval suite covers ≥6 control-plane scenarios without live
   model calls.
3. Phase 4.5 read-only mirror has been dogfooded for ≥10 real runs.
4. `swarm state diff-mirror` reports zero divergence on those runs OR
   every divergence has a tracked schema fix.
5. At least one cross-file atomicity bug has been logged that the per-run
   mirror could have prevented.

If condition 5 is never met within a quarter of dogfood, Phase 9 is rejected
— the underlying pain wasn't real enough to justify migration cost.

### SwarmDaddy-Fit Design

Per-run SQLite (NOT global), one family at a time, JSON exports remain
worker-visible.

```text
${CLAUDE_PLUGIN_DATA}/runs/<run-id>/state.sqlite          (canonical)
${CLAUDE_PLUGIN_DATA}/runs/<run-id>/state.mirror.sqlite   (deleted at migration time)
```

Migration order — start with the families that have real atomicity pain:

| Order | Family | Current source | Reason |
|---:|---|---|---|
| 1 | `runs`, `events` | `prepared_plan.v1.json` + `run_events.jsonl` | Couples state mutation with audit append in one tx — the recommendation memo's primary motivation. |
| 2 | `phase_sessions` | `phase_sessions.v1.json` | Single-file lock today; clean migration boundary. |
| 2.5 | `stage_sessions` | `stage_sessions.v1.json` | Same fcntl-flock + atomic-replace pattern as `phase_sessions`. Streaming plan's "main-thread-only" concurrency invariant matches SQLite's single-writer-per-process model — net invariant simplification, not addition. Adopt with `phase_sessions` if both writers can be migrated together; otherwise rank 2.5. |
| 3 | `prepared_artifact` (descriptor SHAs, work-unit pointers) | `prepared_plan.v1.json` + work-unit sidecars | Descriptor-SHA self-reference is the original bug class. |
| — never — | `worktree manifest` | `manifest.json` + git | Cannot make `git worktree add/remove` transactional; mirror remains an observation cache. |
| — never — | Worker-visible exports | `prepared.md`, work-unit JSON sidecars, phase results, phase handoffs | These are launcher contract; remain JSON. |

### Per-Migration Recipe

For each family chosen:

1. Add canonical SQLite tables for that family.
2. Convert the corresponding `*Store` (Phase 1) to write SQLite first,
   then export deterministic JSON snapshot after commit.
3. Record the snapshot in `artifact_exports(path, kind, sha256, event_seq)`.
4. Add a feature flag: `SWARM_STATE_BACKEND=json|sqlite`. Default: `json`.
5. Run Phase 4 eval suite under both backends; require parity before
   switching the default.
6. Flip default per family only after a dogfood quarter.
7. JSON file remains, downgraded to "post-commit snapshot" semantics.

### What This Design Is NOT

- Not a global SQLite database — per-run only.
- Not WAL on the current Python's SQLite (3.49.1) — use rollback-journal
  + `BEGIN IMMEDIATE`. Re-evaluate WAL once the runtime SQLite is ≥3.51.3
  (recommendation memo notes the WAL-reset bug fix).
- Not a replacement for `validate_run_event`/JSON Schema — application
  validators stay; constraints add structural invariants in addition.
- Not an event-sourcing system — `events` table is an audit projection
  coupled to state mutation in the same tx, not the source of truth.
- Not a hosted DB. No daemon. No multi-process writers.
- Not a forced migration of telemetry JSONL —
  `telemetry/subcommands/query.py`'s `:memory:` surface stays as-is until
  there is concrete reason to converge.

### Test Anchors

```text
py/swarm_do/pipeline/tests/test_state_sqlite.py
py/swarm_do/pipeline/tests/test_state_store.py
py/swarm_do/pipeline/tests/test_run_eval.py        (parity under both backends)
py/swarm_do/pipeline/tests/test_state_projector.py (becomes parity check)
docs/adr/
```

### Acceptance Criteria (per family)

- State mutation and event append happen in one transaction.
- `SWARM_STATE_BACKEND=json` and `SWARM_STATE_BACKEND=sqlite` produce
  identical Phase 4 eval outcomes.
- Existing CLI and slash commands do not branch on backend.
- Operators can dump DB state as JSON via `swarm state dump <run-id>`.
- JSON exports are deterministic and recorded in `artifact_exports`.
- Rollback to `json` for a family is one config flip + (optional)
  `swarm state import-json <run-id>`.

### Risk

Medium-high. Mitigated by:

- Per-family migration (one bad family does not stall the rest).
- Backend feature flag with parity-tested default flip.
- Phase 4.5 dogfood quarter before any flip.
- Worker-visible exports stay JSON — launchers and tests are insulated.

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

## Concerns And Regression Boundary

This section consolidates risks called out across phases so reviewers can
see the full surface in one place. Implementing agents MUST address each
relevant item in their handoff.

### Drift From Primary Mission

SwarmDaddy is a local development harness. The combined effect of Phases
5 + 6 + 8 (event envelope + hooks + reducers) would quietly converge it
toward a thin LangGraph clone. Mitigation:

- Phases 5, 6, 8 are gated on a documented call-site count ≥2 in their
  un-defer / un-cut criteria.
- "Borrowed API Surfaces" snippets exist so future revivals start from
  upstream, not from another in-house abstraction.
- Final Guidance is unchanged: "When a proposed change mainly helps
  hosted app agents, user memory, remote deployment, or public plugin
  ecosystems, cut it."

### Regressions To Guard

The following existing behaviors MUST NOT regress. Any phase that touches
these surfaces names the relevant test in its acceptance criteria.

| Surface | Owner | Guard tests |
|---|---|---|
| Phase-session queue (lease/retry/recovery) | `phase_sessions.py` | `test_phase_sessions.py`, `test_phase_pump.py`, `test_phase_recovery.py`, `test_phase_crash_resume.py` |
| Stage-session ledger + adoption | `stage_sessions.py`, `phase_beads.py` | `test_stage_sessions.py`, `test_phase_beads.py` |
| Stage marker processing (streaming + post-exit) | `stage_controller.py` (new per streaming plan), `phase_pump._process_stage_markers` | `test_stage_controller.py` (new), `test_phase_pump.py` |
| Claude stream-json parser | `claude_stream.py` (new per streaming plan) | `test_claude_stream.py` (new), fixtures under `tests/fixtures/claude_stream/` |
| Legacy claude-print result parsing | `parse_claude_print_json`, `phase_recovery._failure_kind_for_attempt` | `test_phase_recovery.py`, fixtures under `tests/fixtures/claude_print/` |
| Prepared artifact integrity | `prepared_artifact_writer.py`, `prepare.py` | `test_prepared_verification.py`, `test_prepare_artifact.py` |
| Provider review consensus | `provider_review.py` | `test_provider_review.py` |
| Telemetry `:memory:` SQL surface | `telemetry/subcommands/query.py` | `test_query_parity.py` |
| Telemetry JSONL writer | `telemetry/jsonl.py`, `run_state.append_run_event` | `telemetry/tests/test_jsonl.py`, `telemetry/tests/test_schemas.py` |
| Worktree manifest reconciliation | `execution_worktree.py` | `test_execution_worktree.py` |
| Phase autopilot retry policy | `phase_autopilot_policy.py` | `test_phase_autopilot_policy.py` |
| MCO stage / synthesis | `mco_stage.py` | `test_mco_stage.py` |
| Post-writer report | `post_writer.py` | `test_post_writer_report.py` |
| Resume report | `resume.py` | `test_resume.py` if present, else integration coverage |
| Capability probe | `session_capabilities._claude_print_capability` | `test_session_capabilities.py` |

### Phase-Specific Concerns (cross-reference)

| Concern | Phase | Where stated |
|---|---|---|
| Partial-implementation acknowledgement | 1 | Phase 1 § Status |
| Risk of double schema system | 2 | Phase 2 § Concern |
| Must consolidate `phase_autopilot_policy` | 3 | Phase 3 § Concern |
| Mirror must remain read-only | 4.5 | Phase 4.5 § Concern |
| Telemetry regression boundary if un-deferred | 5 | Phase 5 § Concern |
| Hooks add invisible control flow | 6 | Phase 6 § Status |
| Naming collision with `phase_decisions.py` | 7 | Phase 7 § Concern |
| Single-call-site abstraction risk | 8 | Phase 8 § Status |
| Migration trigger must be objective | 9 | Phase 9 § Migration Trigger |

### State-Path Split Not To Forget

`Phase 1 WorktreeStateStore` must explicitly handle the existing split:

- `${CLAUDE_PLUGIN_DATA}/worktrees/<run-id>/manifest.json` (XDG, observed
  intent)
- Repo-visible exports under `<repo>/data/runs/<run-id>/...` (worker
  contract)

Plus git itself, which remains authoritative for branch existence,
checkout cleanliness, and copyback. The store may record observed state
but MUST reconcile against `git` on every read that affects mutation.

### Upstream Reference Drift

Every cited upstream pattern can change between plan authorship and
adoption. Mitigation:

- "Borrowed API Surfaces" includes shape snippets, not just file paths.
- "Evidence Used" requires implementing agents to record commit SHAs in
  their handoff and update snippets if drifted.
- API drift detected at adoption time is a phase blocker until reconciled.

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

### Agent C - Trace And Eval (PROMOTED — runs in parallel with Agent A)

Owns:

```text
py/swarm_do/pipeline/run_trace.py
py/swarm_do/pipeline/run_eval.py
py/swarm_do/pipeline/tests/test_run_trace.py
py/swarm_do/pipeline/tests/test_run_eval.py
docs/eval-recipes.md
```

Depends on Agent A state-read seam (read-only — can begin against existing
JSON readers and migrate to `state_store.py` reads once they land).

Deliverable: Phase 4 complete. This is the primary deliverable for the
quarter.

### Agent D - Read-Only SQLite Projector (NEW)

Owns:

```text
py/swarm_do/pipeline/state_projector.py
py/swarm_do/pipeline/state_projector_schema.sql
py/swarm_do/pipeline/tests/test_state_projector.py
py/swarm_do/pipeline/tests/test_state_projector_diff.py
```

Depends on: Agents A and C complete (state seam owns writes; trace/eval
consumes mirror).

Deliverable: Phase 4.5 complete. Mirror is read-only; any code path that
writes to the mirror without writing JSON first is rejected at review.

### Agent E - Operator Decisions

Owns:

```text
py/swarm_do/pipeline/operator_decisions.py
py/swarm_do/pipeline/tests/test_operator_decisions.py
```

Depends on Agents A and B. NOT the (deferred) event envelope.

Deliverable: Phase 7 — recovery-scoped operator decisions, naming
disambiguated from existing `phase_decisions.py`.

### Agent F - SQLite Canonical (gated)

Owns:

```text
docs/adr/
docs/swarmdaddy-state-storage-sqlite-recommendation-2026-05-01.md
py/swarm_do/pipeline/tests/test_state_sqlite.py
```

Depends on Phase 9 Migration Trigger conditions ALL met. Until then, this
agent does not run. The Phase 4.5 mirror is the substitute.

Deliverable: Per-family canonical migration with `SWARM_STATE_BACKEND` flag,
parity tests, and rollback. One family at a time, never global. Worker-
visible exports remain JSON.

### Agents D-prev (events/hooks) and E-prev (reducers) — DISBANDED

Phases 5, 6, 8 are deferred or cut per the revised ranking. No agent is
spun up for these until their revival criteria are met.

## Rollout Strategy

Revised 2026-05-02 to reflect promotion of Phase 4 and addition of Phase 4.5.

1. Finish Phase 1 state-ownership seam (Protocols already prototyped) and
   land the fence test. Existing JSON behavior unchanged.
2. Run the regression-boundary tests listed above; require full green.
3. In parallel, land Phase 4 trace/eval against existing JSON readers.
4. Land Phase 3 policy consolidation, subsuming `phase_autopilot_policy`.
5. Land Phase 4.5 read-only SQLite projector; wire trace/eval and TUI to
   read from it. Run `swarm state diff-mirror` continuously during
   dogfood; treat any divergence as a P1 schema bug.
6. Dogfood one prepared run, one phase-session recovery, and one
   `prepare refresh-base` cycle through the full stack.
7. Land Phase 2 typed contracts incrementally (phase records first), only
   for record types not already covered by existing dataclasses.
8. Land Phase 7 operator decisions for recovery commands. Disambiguate
   naming from `phase_decisions.py`.
9. Watch Phase 9 Migration Trigger conditions. Do not start canonical
   migration speculatively.
10. Phases 5, 6, 8 remain dormant. Revive only on documented criteria.

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
