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

P0 decision types (each maps to an existing recovery primitive in
`phase_recovery.py` / `phase_sessions.py`):

| `kind`                    | Backing primitive                                         | Mutates state? | Idempotent rule (see §Guardrails) |
|---|---|---|---|
| `resume_with_input`       | `release_retry_waiting` + handoff merge                   | yes            | no-op if already applied         |
| `retry_phase`             | `abandon_attempt_and_retry`                               | yes            | controlled error if already applied |
| `reset_phase`             | `phases reset --phase` (`cli.py:3024`)                    | yes            | controlled error if already applied |
| `rebuild_worktree`        | `phases redo --rebuild-worktree` (`cli.py:3034`)          | yes (destructive) | controlled error if already applied |
| `archive_attempt`         | `phases redo --archive-branch` (`cli.py:3035`)            | yes (destructive) | controlled error if already applied |
| `cancel_run`              | `phases cancel` (`cli.py:3061`)                           | yes (destructive) | no-op if already applied         |
| `abort_phase`             | `mark_phase_blocked` with operator reason                 | yes            | no-op if already applied         |
| `accept_provider_partial` | provider-review acceptance (Phase 6 territory)            | yes            | no-op if already applied         |

> CONCERN: `accept_provider_partial` is the weakest P0 candidate — Phase 6
> (provider review) does not yet have a partial-accept gap that demonstrably
> needs it. See "Reflect / Cuts" — proposed for deferral.

Defer `skip_best_effort_stage` unless the live stage marker work has a concrete
recovery command that needs it.

## Schema

### `OperatorDecision` (envelope, all kinds share these fields)

```json
{
  "schema_version": 1,
  "decision_id": "od-<run_id_short>-<sequence_3digit>-<sha1_8>",
  "run_id": "run-2026-05-02-abc123",
  "kind": "retry_phase",
  "created_at": "2026-05-02T17:30:00Z",
  "operator": "local:mstefanko@local",
  "payload": { /* per-kind, see below */ },
  "status": "recorded",
  "applied_at": null,
  "applied_event_path": null,
  "supersedes": null
}
```

**`status`** is a closed enum: `recorded | applied | superseded | revoked | error`.

**`operator`** format: `<scope>:<identity>`. P0 scopes are `local` (local
user) and `ci` (automation). Identity comes from `os.environ.get('USER')`
falling back to `socket.gethostname()`. Email is **never** captured — see
Guardrails §PII.

**`decision_id`** is content-addressed for safe replay: deterministic
sequence prefix + SHA-1 of `(run_id, kind, canonical_json(payload),
created_at_truncated_to_minute)`. Same operator recording the same
intent within the same minute produces the same id (idempotent record);
a different minute produces a new id (intentional re-record).

### Per-kind `payload` shapes

```json
// resume_with_input
{ "phase_id": "1", "input": { /* free-form, redaction applied — see Guardrails */ } }

// retry_phase | reset_phase | abort_phase
{ "phase_id": "1", "reason": "operator-supplied free text" }

// rebuild_worktree
{ "phase_id": "1", "reason": "...", "archive_branch": false }

// archive_attempt
{ "phase_id": "1", "attempt": 3, "reason": "..." }

// cancel_run
{ "reason": "...", "confirm_token": "<echoed dry-run token>" }

// accept_provider_partial
{ "phase_id": "1", "manifest_path": "<path>", "accepted_findings": ["..."] }
```

> NOTE: every payload validator lives in `operator_decisions.py`. Unknown
> top-level keys for a given `kind` are rejected (matches the strictness
> rule in `phase-4-5-readonly-sqlite-projector-plan.md` §Acceptance).

## Resolved Open Questions

1. **`payload` schema per kind.** Defined in §Schema above. Validators live
   in `operator_decisions.py` and are exercised by
   `test_operator_decisions.py`.
2. **`operator` field contents.** `<scope>:<identity>` — P0 scopes are
   `local` and `ci`. Identity = `$USER` or `socket.gethostname()`. **No
   email, no display name.** Phase 7 does NOT introduce auth; "anyone who
   can run `swarm` can record" is the explicit P0 trust model. See
   Guardrails §Auth.
3. **`decision_id` generation.** Deterministic content-address, see §Schema.
   Re-recording the SAME `(run_id, kind, payload, created_at_minute)`
   produces the same id (idempotent record). The OPERATION of `apply` is
   what's idempotent — the id itself is just a stable handle.
4. **Idempotent re-application semantics.** Re-running `apply` on a decision
   with `status == "applied"` follows the per-kind table in §Decision Types:
   non-destructive kinds = no-op (return the existing `applied_at`);
   destructive kinds (`retry_phase`, `reset_phase`, `rebuild_worktree`,
   `archive_attempt`) = exit code 2, JSON error
   `{"error": "decision-already-applied", "decision_id": "..."}`.
   `applied_at` is **never** rewritten. The artifact is **append-only for
   records**, with status updates written as a paired event row, never by
   in-place mutation of the original record. (See Guardrails §Append-only.)
5. **Run-id no longer exists.** `record` requires `runs/<run-id>/` to exist
   and validates against `phase_sessions.v1.json`. If the directory is gone
   (worktree deleted, run archived), `record` fails fast with
   `{"error": "run-not-found"}`. `apply` adds the same check plus a
   `phase_sessions.v1.json` schema-version check.
6. **Artifact location.** Per-run, single file:
   `runs/<run-id>/operator_decisions.v1.json`. Verified parallel to
   `phase_sessions.py:117-118`.
7. **Concurrency.** Wrap every write in the same `locked_phase_sessions(run_id)`
   advisory file lock that `phase_sessions.py` already uses (verified
   `phase_sessions.py:172` → `locked_phase_sessions`). Two operators
   recording at the same instant serialize on the lock.
8. **Append-only vs rewrite.** Records are append-only. Status transitions
   (`recorded → applied`) are stored as a NEW JSON record in a sibling
   `events` array within the same artifact, plus a `run_events.jsonl` row
   via the existing `_append_recovery_event()` helper
   (`phase_recovery.py`). The original record is never mutated; readers
   compute current status by folding the events array.
9. **Validation.** `record` validates payload shape per `kind` and rejects
   unknown keys. Schema mismatches return exit code 2 with JSON error.
10. **CLI completeness.** `record`, `apply`, `list`, `show` for P0. `revoke`
    is OUT OF SCOPE for P0 — see §Out of scope deferred.
11. **Auth.** No allow-list in P0. The `operator` field is informational.
    Loud guardrail in CLI help: "operator decisions are not authenticated;
    do not use this artifact as a security boundary."
12. **Phase 4 fixture pinned.** `clean single phase` fixture from
    `phase-4-run-trace-eval-plan.md` step 5. If absent at start, gate the
    eval-fixture acceptance criterion behind `# TODO(phase-4)`.
13. **CLI verb.** `swarm operator-decision <verb>` (singular noun chosen
    deliberately to mirror "operator decision" disambiguation in error
    messages, and to be unambiguously distinct from the existing
    `swarm phases decisions add`). The original "swarm decisions" verb is
    rejected in this plan.
14. **First integrated recovery command.** `retry_phase` — backed by
    `abandon_attempt_and_retry` (`phase_sessions.py`), already covered by
    multiple tests in `test_phase_recovery.py` (e.g.,
    `test_expired_lease_without_artifacts_becomes_retryable_with_history`,
    `test_same_failure_kind_twice_blocks_instead_of_retry_exhausting`,
    `test_retry_after_is_clamped_and_sets_retry_waiting`). Lowest blast
    radius and densest coverage of any P0 kind.

## Guardrails (CRITICAL)

> ⚠️ **G1 — Happy-path independence.** Normal pump flow MUST NOT require
> an operator decision to make progress. Enforce with a test that runs the
> entire `do → prepare → pump → complete` happy path in a temp dir,
> asserts `operator_decisions.v1.json` is **absent**, and fails the
> integration if it appears. Test name pin:
> `test_happy_path_does_not_create_operator_decisions` in
> `test_phase_cli.py`.

> ⚠️ **G2 — Append-only artifact.** The `decisions[]` array is write-once
> per id. The `events[]` array carries status transitions. Add a unit test
> that asserts every `apply` invocation grows `events[]` by exactly one
> row and never mutates `decisions[]`. Test name pin:
> `test_apply_is_append_only` in `test_operator_decisions.py`.

> ⚠️ **G3 — Destructive-kind dry-run.** `cancel_run`, `archive_attempt`,
> `rebuild_worktree`, `reset_phase` (with `--hard`) require a confirm
> token. The `record` step prints a dry-run summary and a token; the
> `apply` step refuses without `--confirm <token>`. Token = first 8 chars
> of `decision_id`. Surface this in CLI help text verbatim and in the
> JSON output.

> ⚠️ **G4 — PII redaction.** `payload.input` for `resume_with_input` may
> contain operator-pasted content. Apply redaction parity with
> `phase-4-run-trace-eval-plan.md` §PII (paths and digests only — never
> inline content into trace dumps). For Phase 7 specifically: `payload`
> is stored verbatim on disk (operator's data, on the operator's machine)
> but is **stripped from `run_events.jsonl` rows** to a digest +
> truncated preview (≤ 256 chars) before `_append_recovery_event()`.

> ⚠️ **G5 — Re-entrancy / pump locking.** `apply` MUST acquire the same
> `locked_phase_sessions(run_id)` lock the pump uses before mutating
> recovery state. If `apply` cannot acquire the lock within 5 seconds it
> returns `{"error": "run-locked"}` exit code 75 (`EX_TEMPFAIL`).
> Verified lock primitive exists at `phase_sessions.py:172`.

> ⚠️ **G6 — Naming-collision lint.** Add an import-time assertion in
> `operator_decisions.py`:
> ```python
> assert "shared_decisions" not in __doc__.lower(), (
>     "operator_decisions module must not be confused with shared_decisions"
> )
> ```
> AND a Phase-1-style fence test: `test_operator_decisions_imports_only_owned_state.py`
> that fails if `operator_decisions.py` directly writes
> `shared_decisions.v1.json` or imports `add_shared_decision`.

> ⚠️ **G7 — Retention.** P0 ships with no rotation. Document in CLI help
> that `operator_decisions.v1.json` grows monotonically; cleanup happens
> when the entire `runs/<run-id>/` directory is archived (existing
> `phases archive` flow at `cli.py:3074`). If a run accumulates >1000
> decision records, emit a warning row to `run_events.jsonl` with type
> `operator_decisions_retention_warning`.

> ⚠️ **G8 — Disk-full / write failures.** Wrap every write in the same
> `_atomic_json_write` helper used by `phase_decisions.py` (`run_state.py`
> `_atomic_json_write`). On `OSError` from atomic write, return
> `{"error": "write-failed", "path": "..."}` exit code 74 (`EX_IOERR`)
> WITHOUT side-effects on the rest of the run.

## Implementation Steps

1. Add `OperatorDecision` dataclass and `OperatorDecisionStore` class in
   `py/swarm_do/pipeline/operator_decisions.py`. Use the §Schema envelope.
   Implement `_atomic_json_write` (reuse `run_state._atomic_json_write`).
2. Implement per-kind payload validators. One function per `kind`, returning
   a dataclass; reject unknown keys.
3. Add `record(run_id, kind, payload, *, operator, data_dir)` that:
   - acquires `locked_phase_sessions(run_id)`,
   - validates `runs/<run-id>/phase_sessions.v1.json` exists and schema_version=1,
   - computes content-addressed `decision_id`,
   - returns `{"path", "decision"}`.
4. Add `apply(run_id, decision_id, *, data_dir, confirm_token=None)` that:
   - acquires the same lock,
   - looks up the decision and its current status,
   - dispatches to the backing primitive per §Decision Types table,
   - emits an `events[]` row plus a `run_events.jsonl` row via
     `_append_recovery_event` (with G4 redaction applied),
   - sets `applied_at` (in events row, not decisions row).
5. Add `list` and `show` read-only commands.
6. Wire CLI under top-level verb `operator-decision` (NOT `decisions`):
   `cli.py` `sub.add_parser("operator-decision")` with subparsers
   `record | apply | list | show`. Help text MUST contain the literal
   string "operator decision" — never "decision" alone.
7. Add a docstring sentence to `phase_decisions.py` that distinguishes
   shared phase decisions from operator decisions, with a literal pointer:
   `See py/swarm_do/pipeline/operator_decisions.py for human-recorded
   recovery decisions.`
8. **Integrate first kind: `retry_phase`.** Call `record` from inside the
   existing `phases redo` (or a new `--via-operator-decision` flag, see
   step 9) when `--phase` is supplied without `--rebuild-worktree`. Verify
   under `test_phase_recovery.py` that the existing test bodies still pass
   (zero-regression bar) and add one new test that asserts the decision
   row is written.
9. **Integration order for remaining kinds** (one PR each; do not batch):
   `abort_phase` → `reset_phase` → `archive_attempt` → `rebuild_worktree`
   → `cancel_run` → `resume_with_input` → `accept_provider_partial`.
   This order is by ascending blast radius and ascending novelty —
   `abort_phase`/`reset_phase` are pure state transitions;
   `rebuild_worktree`/`archive_attempt` mutate filesystem; `cancel_run`
   ends a run; `resume_with_input` introduces operator-typed payload (G4
   tightens here); `accept_provider_partial` requires Phase 6.
10. Extend `phases status --events` (existing flag at `cli.py:3001`) to
    interleave operator-decision rows when the artifact exists. Read-only,
    additive — no schema change to existing event rows.
11. Add the §Tests fence tests (G1, G2, G6) to the targeted test list.
12. Update `commands/redo.md` and `commands/repump.md` to mention that
    mutating choices now create an audit row. Do NOT change the slash
    command verbs.

## Acceptance Criteria

- Every integrated recovery mutation can point to the operator decision that
  caused it (verified by audit cross-reference test).
- Reapplying a decision follows the per-kind table in §Decision Types and
  the rule in Resolved Open Questions §4.
- Existing recovery commands remain usable; zero behavioral regression in
  `test_phase_recovery.py`.
- Help text and errors contain the literal string "operator decision" — never
  "decision" alone — to avoid confusion with shared phase decisions.
- No happy-path pump flow requires an operator decision record (G1 test).
- Artifact is append-only (G2 test).
- Naming-collision fence test passes (G6).
- Lock contention returns `EX_TEMPFAIL` within 5s (G5).
- Destructive kinds refuse `apply` without `--confirm <token>` (G3).

## Tests

Required targeted tests:

```text
py/swarm_do/pipeline/tests/test_operator_decisions.py
py/swarm_do/pipeline/tests/test_phase_recovery.py
py/swarm_do/pipeline/tests/test_phase_cli.py
py/swarm_do/pipeline/tests/test_run_eval.py            # gated on Phase 4
py/swarm_do/pipeline/tests/test_operator_decisions_imports_only_owned_state.py  # G6 fence
```

Pinned test names (the writer agent must use these exact names):

- `test_happy_path_does_not_create_operator_decisions` (G1)
- `test_apply_is_append_only` (G2)
- `test_destructive_kind_requires_confirm_token` (G3)
- `test_resume_with_input_payload_is_redacted_in_run_events` (G4)
- `test_apply_acquires_phase_session_lock` (G5)
- `test_record_is_idempotent_within_minute` (decision_id idempotency)
- `test_apply_on_destructive_kind_already_applied_is_controlled_error` (idempotency, destructive)
- `test_apply_on_nondestructive_kind_already_applied_is_noop` (idempotency, non-destructive)
- `test_record_rejects_unknown_payload_keys`
- `test_record_fails_when_run_directory_missing`

## Out of scope deferred

Explicit deferrals (do NOT implement in this phase; create follow-up issues):

- `revoke` CLI subcommand. Operators can record a superseding decision via
  `record` if needed; full revoke semantics need a richer status model.
- Authentication / operator allow-list. Phase 7 explicitly documents the
  trust model as "anyone who can run `swarm`."
- Retention / rotation policy beyond the >1000-row warning (G7).
- `accept_provider_partial` integration. Strong candidate for full deferral
  until Phase 6 (provider review) demonstrates a partial-accept gap. Plan
  ships the schema slot but leaves step 9's last sub-item gated behind
  `# TODO(phase-6)`.
- `skip_best_effort_stage` (already explicitly deferred in source plan).
- SQLite-backed storage. The Phase 4.5 read-only projector is the canonical
  query surface; Phase 7 stays JSON to keep write fences narrow.
- Migration of any pre-existing artifacts (none exist; verified
  `find ... -name 'operator_decisions*'` returns nothing 2026-05-02).

## Reflect / Senior pushback

**Top 3 cuts proposed:**

1. **Defer `accept_provider_partial`** to Phase 6. No demonstrated need
   today; including it widens the schema surface without a backing primitive.
2. **Defer `cancel_run` past P0.** It is the highest-blast-radius kind and
   the existing `swarm phases cancel` (`cli.py:3061`) is already a
   single-purpose verb. Wrapping it in an audit row is valuable but should
   ride on top of the smaller kinds proving the model first.
3. **Drop `list` from P0** (keep `show`). `phases status --events` already
   surfaces the data; a dedicated `list` is convenience that can wait.

**Top 3 must-haves added by this review:**

1. **G6 naming-collision fence test** — without this, the P+1 eng will
   write to the wrong artifact. The collision is sharp (`swarm phases
   decisions add` ships TODAY).
2. **G3 destructive-kind confirm-token flow** — `cancel_run` and
   `archive_attempt` are unrecoverable; a typed token is the cheapest
   guardrail and matches the `--force` / `--archive-branch` posture
   already taken by `phases redo`.
3. **G5 explicit lock acquisition** — without this, `apply` can race the
   pump and corrupt phase-session state. The lock primitive already
   exists; using it is non-negotiable.

## Handoff Notes

List which recovery commands are decision-backed and which are not yet
integrated. Do not imply full recovery coverage until each mutating command is
actually wired. Status table to maintain in this section as integration
progresses:

| `kind`                    | Integrated? | PR / commit | Test name |
|---|---|---|---|
| `retry_phase`             | ☑           | working tree | `test_apply_is_append_only`, `test_phase_redo_records_operator_decision_row` |
| `abort_phase`             | ☐           |             |           |
| `reset_phase`             | ☐           |             |           |
| `archive_attempt`         | ☐           |             |           |
| `rebuild_worktree`        | ☐           |             |           |
| `cancel_run`              | ☐           |             |           |
| `resume_with_input`       | ☐           |             |           |
| `accept_provider_partial` | ☐ (gated)   |             |           |
