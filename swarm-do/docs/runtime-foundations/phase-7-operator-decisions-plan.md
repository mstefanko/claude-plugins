# Phase 7 - Operator Decisions

Date: 2026-05-02
Status: active implementation plan after Phases 1 and 2
Source section: `docs/swarmdaddy-runtime-foundations-adoption-plan-2026-05-02.md` Phase 7

## Objective

Represent mutating human recovery choices as auditable operator decision
artifacts. Normal happy-path pumping should not depend on these records.

## Senior Implementation Decision

Scope this to recovery commands only. The useful pattern from LangGraph is the
contract shape: pause with a value, resume with an explicit command. SwarmDaddy
does not need `interrupt()` inside its runner.

Also keep the name explicit. `phase_decisions.py` already means shared
controller-promoted decisions between phases. This phase is about human
operator recovery choices.

> CONCERN: The naming collision is sharper than the source plan acknowledged.
> `swarm phases decisions add ...` is **already a shipped subcommand** that
> writes shared (controller-promoted) decisions to `shared_decisions.v1.json`
> via `add_shared_decision()` in `phase_decisions.py:21` (verified
> `cli.py:3099-3110`). A top-level `swarm decisions ...` verb sits next to
> `swarm phases decisions ...` and **invites operator confusion**. See
> Resolved Open Questions §CLI verb for the resolution adopted by this plan.

## Evidence and Source Anchors

### LangGraph upstream — verified at pinned commit

**Pin:** `langchain-ai/langgraph@a48a045596d0dc90adfd04ec87c85d32382852d3`
(authored 2026-04-29 by William FH; last commit touching `types.py` as of
2026-05-02 fetch. Verified via GitHub API
`/repos/langchain-ai/langgraph/commits?path=libs/langgraph/langgraph/types.py`.)

**File:** `libs/langgraph/langgraph/types.py`

#### `Command` (lines 748-770)

```python
@dataclass(**_DC_KWARGS)
class Command(Generic[N], ToolOutputMixin):
    """One or more commands to update the graph's state and send messages to nodes.

    Args:
        graph: Graph to send the command to. Supported values are:

            - `None`: the current graph
            - `Command.PARENT`: closest parent graph
        update: Update to apply to the graph's state.
        resume: Value to resume execution with. To be used together with
            [`interrupt()`][langgraph.types.interrupt].
            Can be one of the following:

            - Mapping of interrupt ids to resume values
            - A single value with which to resume the next interrupt
        goto: ...
    """
```

Field declarations (further down the class body, same commit):

```python
graph: str | None = None
update: Any | None = None
resume: dict[str, Any] | Any | None = None
goto: Send | Sequence[Send | N] | N = ()
```

#### `interrupt()` (line 801)

```python
def interrupt(value: Any) -> Any:
    """Interrupt the graph with a resumable exception from within a node.

    The `interrupt` function enables human-in-the-loop workflows by pausing
    graph execution and surfacing a value to the client. This value can
    communicate context or request input required to resume execution.

    In a given node, the first invocation of this function raises a
    `GraphInterrupt` exception, halting execution. The provided `value` is
    included with the exception and sent to the client executing the graph.

    A client resuming the graph must use the [`Command`][langgraph.types.Command]
    primitive to specify a value for the interrupt and continue execution.
    The graph resumes from the start of the node, **re-executing** all logic.
    """
```

#### `Interrupt` carrier (line 525)

```python
@dataclass(init=False, slots=True)
class Interrupt:
    """Information about an interrupt that occurred in a node."""
    value: Any
    """The value associated with the interrupt."""
```

**SwarmDaddy adaptation:** borrow the contract shape only — pause-with-value,
resume-with-typed-command — as the schema of `OperatorDecision`. **Do NOT**
adopt `interrupt()` inside `phase_pump.py`. SwarmDaddy already pauses by
writing terminal statuses (`STATUS_BLOCKED`, `STATUS_NEEDS_INPUT`,
`STATUS_RETRY_EXHAUSTED`); the operator decision is the resume command.

### Internal anchors — verified 2026-05-02

| Claim                          | File:line                                     | Verified text                                                              |
|---|---|---|
| Shared decisions filename      | `phase_decisions.py:14`                       | `SHARED_DECISIONS_FILENAME = "shared_decisions.v1.json"`                   |
| Shared decisions schema        | `phase_decisions.py:13`                       | `SCHEMA_VERSION = 1`                                                       |
| Shared decisions path helper   | `phase_decisions.py:17-18`                    | `(data_dir or resolve_data_dir()) / "runs" / run_id / SHARED_DECISIONS_FILENAME` |
| Phase-session state filename   | `phase_sessions.py:36`                        | `STATE_FILENAME = "phase_sessions.v1.json"`                                |
| Phase-session state path       | `phase_sessions.py:117-118`                   | `runs/<run_id>/phase_sessions.v1.json`                                     |
| Existing `phases decisions add`| `cli.py:3099-3110`                            | already a SHIPPED subcommand for shared decisions, NOT operator decisions  |
| `phases status --events` flag  | `cli.py:3001`                                 | `p.add_argument("--events", action="store_true")` on `phases status`       |
| `phases doctor` subcommand     | `cli.py:2993`                                 | exists; called from `commands/redo.md`                                     |
| `phases redo` subcommand       | `cli.py:3030-3037`                            | accepts `--phase --hard --rebuild-worktree --archive-branch --force`       |
| Phase recovery primitives      | `phase_recovery.py:39-58` (imports)           | `abandon_attempt_and_retry, adopt_phase_result, mark_phase_blocked, mark_retry_exhausted, release_retry_waiting, repair_active_phase_lease` |
| Recovery event emit            | `phase_recovery.py` `_append_recovery_event`  | already writes `run_events.jsonl` rows; piggyback for decision audit       |
| `redo` slash command body      | `commands/redo.md`                            | currently calls `swarm phases doctor` then `swarm phases redo`             |
| `repump` slash command body    | `commands/repump.md`                          | calls `swarm phases pump --max-phases=1` and `swarm phases status --events`|

> NOTE: `tests/test_run_eval.py` is **not yet present** on disk (Phase 4
> deliverable). See Dependencies — this is a hard prereq for the eval-fixture
> acceptance criterion below.

## Scope

Owned files:

```text
py/swarm_do/pipeline/operator_decisions.py
py/swarm_do/pipeline/tests/test_operator_decisions.py
```

Artifact:

```text
runs/<run-id>/operator_decisions.v1.json   # one file per run, beside phase_sessions.v1.json
```

(Verified parallel structure: `phase_sessions.py:117-118` resolves
`runs/<run_id>/phase_sessions.v1.json`. The new file lives in the SAME
per-run directory.)

CLI surfaces — **finalized verb to avoid collision** (see Resolved Open
Questions §CLI verb):

```text
swarm operator-decision record <run-id> --kind <kind> --payload <json> [--operator <id>] [--json]
swarm operator-decision apply  <run-id> <decision-id> [--json]
swarm operator-decision list   <run-id> [--status <s>] [--kind <k>] [--json]
swarm operator-decision show   <run-id> <decision-id> [--json]
```

> CONCERN: do NOT register a top-level `swarm decisions` verb. `swarm phases
> decisions add` already exists at `cli.py:3099-3110` and writes
> **shared decisions** (controller-promoted, not operator-recorded). A
> top-level `swarm decisions` would be one tab-completion away from the
> existing shared-decision verb.

## Dependencies

- **Phase 1** state store wrappers — decision writes route through the same
  owner boundary. **HARD prereq** for atomic write fences.
- **Phase 2** domain records — status/recovery summaries reused for the
  decision payload validators.
- **Phase 4** eval fixtures — at least one recovery flow fixture must exist
  before this plan's "fixture-backed apply" acceptance criterion can be met.
  Specific fixture pinned: `clean single phase` from
  `phase-4-run-trace-eval-plan.md` step 5 (the smallest deterministic flow).
  > NOTE: `tests/fixtures/run-traces/` and `test_run_eval.py` do not yet
  > exist on disk (verified 2026-05-02). If Phase 4 is not landed when
  > Phase 7 starts, ship steps 1-7 of the Implementation Steps below and
  > gate the eval-fixture acceptance behind a `# TODO(phase-4)` marker.

Does not depend on the deferred event envelope.

## Non-Goals

- No generic workflow interrupt system.
- No public plugin API.
- No happy-path requirement that every normal phase transition has an operator
  decision.
- No rename or merger of `phase_decisions.py`.

## Decision Types

P0 decision types:

```text
resume_with_input
retry_phase
reset_phase
rebuild_worktree
archive_attempt
cancel_run
abort_phase
accept_provider_partial
```

Defer `skip_best_effort_stage` unless the live stage marker work has a concrete
recovery command that needs it.

## Implementation Steps

1. Add `OperatorDecision` and `OperatorDecisionStore` in
   `operator_decisions.py`.
2. Store records in `operator_decisions.v1.json` beside phase-session state.
3. Include stable `decision_id`, `run_id`, `kind`, `created_at`, `operator`,
   `payload`, `status`, and `applied_at`.
4. Make `decision_id` idempotent. Re-recording or reapplying the same decision
   is either a no-op or a controlled error with JSON output.
5. Add record/apply CLI commands.
6. Integrate mutating recovery commands one at a time. Start with the command
   that has the clearest existing test coverage.
7. Add a docstring sentence to `phase_decisions.py` that distinguishes shared
   phase decisions from operator decisions.
8. Let `phases status --events` or equivalent status output show recent
   operator decisions after the artifact exists.

## Acceptance Criteria

- Every integrated recovery mutation can point to the operator decision that
  caused it.
- Reapplying a decision is deterministic.
- Existing recovery commands remain usable.
- Help text and errors say "operator decision" to avoid confusion with shared
  phase decisions.
- No happy-path pump flow requires an operator decision record.

## Tests

Required targeted tests:

```text
py/swarm_do/pipeline/tests/test_operator_decisions.py
py/swarm_do/pipeline/tests/test_phase_recovery.py
py/swarm_do/pipeline/tests/test_phase_cli.py
py/swarm_do/pipeline/tests/test_run_eval.py
```

## Handoff Notes

List which recovery commands are decision-backed and which are not yet
integrated. Do not imply full recovery coverage until each mutating command is
actually wired.
