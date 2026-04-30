# SwarmDaddy Durable Run Candidates 1-2 Implementation Plan

Status: implementation-ready after analysis-review clarifications
Date: 2026-04-30
Source research: `docs/swarmdaddy-durable-run-capabilities-research-plan.md`
Related recovery plan: `docs/phase-session-durable-recovery-plan.md`
Related launcher plan: `docs/sensitive-path-launcher-hardening-plan.md`

## Goal

Turn the first two durable-run capability candidates into concrete work for
SwarmDaddy:

1. Failure Taxonomy As A Feature.
2. Forensic Agent Execution.

The implementation should improve the existing phase-session harness. It should
not create a second orchestration protocol, move phase sessions to Agent Teams,
or duplicate raw prompts/transcripts/stdout into new long-lived stores.

## Research Findings

The current tree already contains more of this capability than the initial
research plan assumed:

- `py/swarm_do/pipeline/phase_failure_classifier.py` classifies launcher
  failures and already separates `writer_tool_denied_no_artifacts` and
  `writer_silent_with_turns`.
- `py/swarm_do/pipeline/claude_transcript_diagnostics.py` locates and parses
  Claude JSONL transcripts for suspicious launches.
- `py/swarm_do/pipeline/phase_recovery.py` writes stdout/stderr tails,
  diff summaries, transcript diagnostics, recovery markdown, retry decisions,
  and attempt-history records.
- `py/swarm_do/pipeline/phase_sessions.py` persists phase status, retry state,
  launch metadata, and attempt history in `phase_sessions.v1.json`.
- `phase_recovery._active_phase_decision()` already emits
  `child_process_dead_no_artifacts` for same-host child liveness failures.
- `phase_recovery._artifact_failure_kind()` already emits
  `launcher_nonzero_with_artifacts` when valid result/handoff artifacts exist
  after a non-zero launcher return code.
- `py/swarm_do/pipeline/phase_attempts.py` already provides an attempt summary
  reader with cost, token, permission-denial, failure, and archived-attempt
  handling.
- `py/swarm_do/tui/state.py` and `py/swarm_do/tui/app.py` already surface
  phase-session attempts, costs, failed attempts, and last failure.
- `schemas/phase_sessions.schema.json` has optional attempt-history fields for
  transcript diagnostics, changed files, diff summary, and recovery context.
- `schemas/telemetry/run_events.schema.json` already allows phase-session,
  retry, adoption, and pump events.

The right implementation is therefore a normalization and indexing layer, not a
large new recovery subsystem.

## Final Recommendation

Ship Candidate 1 first as the shared vocabulary. Ship Candidate 2 immediately
after, using the taxonomy fields in the evidence manifest.

Candidate 1 should add a central failure taxonomy registry that documents and
enriches current `failure_kind` strings while keeping historical strings stable.

Candidate 2 should add a per-attempt `evidence.json` manifest in the existing
attempt launch directory:

`data/runs/<run_id>/phase_launches/<phase_id>/attempt-<n>/evidence.json`

The manifest should point to existing evidence files and summarize the attempt.
It should not copy raw prompt text, raw transcript text, full stdout, full
stderr, or environment values.

## Candidate 1 - Failure Taxonomy As A Feature

### Requirement

Make failure kinds understandable and operational. A writer, operator, CLI,
TUI, Beads note, and recovery policy should all use the same names, categories,
retry semantics, and operator messages.

### Current Problems

- Failure-kind strings are produced in multiple places:
  `phase_failure_classifier.py`, `phase_recovery.py`, child phase result JSON,
  artifact-contract validation, and cancellation.
- Retry policy is partly encoded in `_retry_stop_decision()` and partly encoded
  in result/handoff contracts.
- Operator-facing surfaces mostly show raw enum-like strings.
- The schema intentionally allows arbitrary child-reported `failure_kind`
  strings, so making the schema an enum would break compatibility.
- Some values are status or decision labels, not real failure kinds:
  `failed_nonretryable`, `retry_waiting`, `retry_exhausted`, and
  `same_failure_limit` should remain status or policy labels.

### Implementation Decision

Add a registry module:

`py/swarm_do/pipeline/failure_taxonomy.py`

The registry is authoritative for known SwarmDaddy-owned failure kinds, but it
must allow unknown child-reported values. Unknown values are classified as
`child_result` with `retry_class="child_controlled"` unless surrounding evidence
proves a hard contract stop.

Do not rename existing failure kinds in P0. Add aliases only for display or
deprecation notes.

### Registry Shape

Use a small frozen dataclass:

```python
@dataclass(frozen=True)
class FailureKindSpec:
    kind: str
    category: str
    retry_class: str
    operator_title: str
    operator_message: str
    required_evidence: tuple[str, ...]
    examples: tuple[str, ...] = ()
    deprecated: bool = False
    aliases: tuple[str, ...] = ()
```

Supported `category` values:

- `artifact`
- `artifact_contract`
- `child_result`
- `environment`
- `launcher`
- `lifecycle`
- `operator`
- `permission`
- `writer_runtime`

Supported `retry_class` values:

- `adopt`: valid artifacts can be adopted despite launcher anomaly.
- `retry`: retry within normal attempt budget.
- `recovery_retry`: retry with recovery context when dirty, partial, or long.
- `human_gate`: block until an operator decides.
- `terminal`: no automatic retry.
- `child_controlled`: child result fields decide retryability.

`failure_retry_class` and `retry_decision` are intentionally different fields.
`failure_retry_class` is the taxonomy default for a kind. `retry_decision` is
the actual transition decision recorded by recovery after evidence-sensitive
policy checks such as return code, deterministic artifact errors, same-failure
limits, retry budget, and handoff `do_not_retry`.

Export these helpers:

```python
def failure_kind_spec(kind: str | None) -> FailureKindSpec
def failure_kind_details(kind: str | None, evidence: Mapping[str, Any] | None = None) -> dict[str, Any]
def known_failure_kinds() -> tuple[str, ...]
def taxonomy_markdown() -> str
```

Alias semantics:

- `failure_kind_spec(kind)` accepts canonical kinds and aliases. An alias
  resolves to the canonical `FailureKindSpec`; `spec.kind` is always canonical.
- `failure_kind_details(kind)` preserves the raw supplied value in
  `failure_kind` while using the canonical spec for category, retry class,
  title, message, and `failure_known=true`.
- `known_failure_kinds()` returns canonical, non-deprecated kind names only.
  It does not include aliases.
- Registry import/tests must fail if an alias collides with another canonical
  kind or with another alias.
- P0 does not add initial aliases unless implementation discovers an existing
  historical spelling that needs one.

`failure_kind_details()` returns:

```json
{
  "failure_kind": "launcher_nonzero_no_artifacts",
  "failure_category": "launcher",
  "failure_retry_class": "retry",
  "failure_operator_title": "Launcher exited before artifacts",
  "failure_operator_message": "The launcher exited non-zero before valid result and handoff artifacts were available. SwarmDaddy can retry within budget.",
  "failure_known": true
}
```

### Initial Known Failure Kinds

Register these current SwarmDaddy-owned phase-session kinds. "Current" means
emitted by the current phase-session runtime, not necessarily by
`phase_failure_classifier.py`:

Use these exact `required_evidence` token names in the registry. They are
compact evidence labels, not raw file contents:

- `artifact_contract_errors`
- `child_liveness`
- `child_result`
- `command_metadata`
- `execution_workspace_error`
- `launch_dir`
- `lease_ttl`
- `launcher_doctor_report`
- `launcher_result`
- `operator_action`
- `permission_contract_details`
- `prompt_safety_check`
- `returncode`
- `stdout_metrics`
- `stdout_or_outer_json`
- `transcript_diagnostics`
- `valid_handoff_artifact`
- `valid_result_artifact`

| Kind | Category | Retry class | Required evidence | Notes |
| --- | --- | --- | --- | --- |
| `adoptable_artifacts` | artifact | adopt | `valid_result_artifact`, `valid_handoff_artifact` | Valid result/handoff artifacts exist. |
| `launcher_nonzero_with_artifacts` | launcher | adopt | `launcher_result`, `returncode`, `valid_result_artifact`, `valid_handoff_artifact` | Current; emitted by `phase_recovery._artifact_failure_kind()` when artifacts validate after a non-zero launcher result. |
| `partial_artifacts_invalid` | artifact_contract | recovery_retry | `artifact_contract_errors`, `launch_dir` | Retry only unless artifact error is deterministic. |
| `lease_expired_no_artifacts` | lifecycle | retry | `launch_dir`, `lease_ttl` | TTL expired and no valid artifacts exist. |
| `child_process_dead_no_artifacts` | lifecycle | retry | `child_liveness`, `launch_dir` | Current; emitted by `phase_recovery._active_phase_decision()`, not by the classifier. |
| `launcher_nonzero_no_artifacts` | launcher | retry | `launcher_result`, `returncode`, `launch_dir` | Non-zero launcher exit with no valid artifacts. |
| `outer_json_missing_no_artifacts` | launcher | retry | `stdout_or_outer_json`, `launch_dir` | No parseable outer JSON and no artifacts. |
| `outer_json_invalid_no_artifacts` | launcher | human_gate | `stdout_or_outer_json`, `returncode`, `launch_dir` | Human-gated when return code is zero. |
| `outer_artifacts_missing` | artifact_contract | human_gate | `stdout_or_outer_json`, `artifact_contract_errors` | Outer JSON lacks artifact object. |
| `writer_tool_denied_no_artifacts` | writer_runtime | human_gate | `transcript_diagnostics`, `launch_dir` | Transcript shows a denied tool error. |
| `writer_silent_with_turns` | writer_runtime | human_gate | `stdout_metrics`, `transcript_diagnostics`, `launch_dir` | Turns/cost spent, no artifacts, no useful terminal result. |
| `launcher_workspace_error` | environment | human_gate | `execution_workspace_error`, `launch_dir` | Safe workspace/prompt preparation failed. |
| `launcher_prompt_sensitive_path` | permission | human_gate | `prompt_safety_check`, `launch_dir` | Prompt still contained sensitive path spelling. |
| `claude_cli_missing` | environment | human_gate | `command_metadata`, `launch_dir` | Claude CLI unavailable for a claimed attempt. |
| `launcher_ineligible` | environment | human_gate | `launcher_doctor_report` | Launcher doctor says this launcher cannot run. |
| `permission_contract_failure` | permission | human_gate | `permission_contract_details` | Permission contract failed. |
| `structured_retryable_failed` | child_result | child_controlled | `child_result`, `valid_result_artifact`, `valid_handoff_artifact` | Valid child result asked for retry. |
| `operator_cancelled` | operator | terminal | `operator_action` | Operator cancelled the phase session. |

Also register artifact validation `error_kinds` as artifact-contract entries
because they appear in `attempt_history.artifact_error_kinds`:

- `status_mismatch`
- `result_identity_mismatch`
- `prepared_plan_sha_mismatch`
- `phase_content_sha_mismatch`
- `handoff_identity_mismatch`
- `attempt_mismatch`
- `handoff_status_mismatch`
- `completed_work_units_not_prepared`
- `path_escape`

All artifact validation `error_kinds` should use
`required_evidence=("artifact_contract_errors",)`.

### Runtime Wiring

Update `phase_recovery.py`:

- Replace hardcoded descriptive knowledge in `_retry_stop_decision()` with a
  small policy adapter backed by `failure_taxonomy`.
- Keep evidence-sensitive exceptions in recovery code. The registry supplies
  the default `failure_retry_class`; recovery remains responsible for actual
  transition decisions.
- Exact `_retry_stop_decision()` split:
  - Registry-backed, evidence-insensitive human gates:
    `claude_cli_missing`, `launcher_ineligible`,
    `launcher_workspace_error`, `launcher_prompt_sensitive_path`, and
    `permission_contract_failure`.
  - Recovery-owned return-code guards:
    `outer_json_invalid_no_artifacts`, `outer_artifacts_missing`,
    `writer_tool_denied_no_artifacts`, and `writer_silent_with_turns` block
    only when `returncode == 0`; a non-zero return remains retryable within
    budget.
  - Recovery-owned artifact-contract guards:
    deterministic `artifact_error_kinds` continue to trigger
    `deterministic_contract_failure`.
  - Recovery-owned retry budget guards:
    same-failure limits, max attempts, max recovery attempts,
    `_needs_recovery_retry()`, retry-after clamping, and handoff
    `do_not_retry` stay outside the registry.
  - Unknown child-reported kinds with `retry_class="child_controlled"` never
    create a registry-only stop; the child result/handoff contract controls
    retryability.
- Enrich attempt evidence from `_build_attempt_evidence()` with:
  - `failure_category`
  - `failure_retry_class`
  - `failure_operator_title`
  - `failure_operator_message`
  - `failure_known`
- Include those fields in `phase_session_blocked`,
  `phase_attempt_retry_scheduled`, and `phase_attempt_retry_exhausted` event
  details.

Update `phase_sessions.py`:

- Preserve existing `failure_kind` fields.
- Add optional attempt-history fields to `_attempt_record_from_phase()` and
  `schemas/phase_sessions.schema.json`:
  - `failure_category`
  - `failure_retry_class`
  - `failure_operator_title`
  - `failure_operator_message`
  - `failure_known`
- Do not bump `schema_version`; fields are optional and old files should still
  normalize and validate.

Update `phase_attempts.py`:

- Include taxonomy details in every row. Prefer persisted attempt-history
  details when present; otherwise derive them from `failure_kind`.
- Include the same details in `last_failure`.

Update `py/swarm_do/pipeline/cli.py`:

- `bin/swarm phases status --attempts` should print:
  - `failure=<kind>`
  - `category=<category>`
  - `retry_class=<failure_retry_class>`
  - `retry_decision=<retry_decision>` when an actual transition decision is
    present
  - `message=<short operator title>` when available.
- JSON output should include the full taxonomy fields.

Update `py/swarm_do/tui/state.py` and `py/swarm_do/tui/app.py`:

- Add `failure_category` and `failure_operator_title` to phase-session run rows.
- Show raw `failure_kind` plus a compact category/title. Do not show long
  operator messages in dense tables.
- `PhaseSessionRunRow` is a frozen dataclass today, not a `NamedTuple`; append
  new optional fields with defaults at the end and keep all internal
  construction keyword-based. Do not reorder existing fields.

Update `py/swarm_do/pipeline/phase_beads.py`:

- Add `failure_category`, `failure_retry_class`, and
  `failure_operator_title` to note text when present.
- Keep notes compact; never include stdout/stderr, prompt text, or transcript
  excerpts in Beads notes.

Add documentation:

- Generate or hand-maintain `docs/failure-taxonomy.md` from the registry.
- Link it from this plan's implementation PR or `docs/phase-session-durable-recovery-plan.md`.

### Tests

Add `py/swarm_do/pipeline/tests/test_failure_taxonomy.py`:

- Known values return expected category, retry class, and message.
- Unknown child-reported values return `category="child_result"` and
  `retry_class="child_controlled"`.
- `taxonomy_markdown()` includes all registered known values.

Update `test_phase_recovery.py`:

- Retryable launcher failure records category and retry class in attempt
  history and run-event details.
- Human-gated writer tool denial records category `writer_runtime`.
- Deterministic artifact error records category `artifact_contract`.

Update `test_phase_attempts.py`:

- Summary rows include derived taxonomy fields for old attempt records that
  only have `failure_kind`.

Update `py/swarm_do/tui/tests/test_state.py`:

- Phase-session run rows keep the raw last failure and expose a category/title.

### Rejected Alternatives

- Do not convert `schemas/phase_result.schema.json.failure_kind` to an enum.
  Child workers and historical runs must be able to carry custom values.
- Do not rename existing failure kinds in P0. That would break tests, telemetry
  queries, Beads notes, and old run evidence.
- Do not make taxonomy own all retry policy. Recovery still needs evidence such
  as return code, partial artifacts, same-failure count, dirty diff, and handoff
  `do_not_retry`.

## Candidate 2 - Forensic Agent Execution

### Requirement

Make every phase-session attempt explainable after the fact:

- what was asked
- which launcher ran
- where it ran
- which files were expected
- what artifacts were written
- what changed
- what metrics/costs are known
- what failed
- why recovery retried, adopted, blocked, or exhausted

### Current Problems

- Evidence is present but scattered across:
  - `phase_launches/<phase_id>/attempt-<n>/command.json`
  - `dispatcher.launcher.prompt.md`
  - `stdout.txt`
  - `stderr.txt`
  - `phase_results/<phase_id>/attempt-<n>.result.json`
  - `phase_handoffs/<phase_id>/attempt-<n>.handoff.json`
  - `phase_recovery/<phase_id>/attempt-<n>.*`
  - `phase_sessions.v1.json`
  - `telemetry/run_events.jsonl`
- Successful attempts may never get a recovery context or attempt-history row.
- `phase_attempts.py` can summarize attempts, but there is no durable
  per-attempt manifest with pointers to all evidence.
- Support/audit sharing has no redaction contract yet.

### Implementation Decision

Add a manifest writer/reader module:

`py/swarm_do/pipeline/phase_evidence.py`

Write the canonical manifest to the existing launch directory:

`data/runs/<run_id>/phase_launches/<phase_id>/attempt-<n>/evidence.json`

This location wins because:

- it is per-attempt
- it is already archived by `archive_phase_session_evidence()`
- it is already cleaned up by generated-artifact cleanup
- it sits beside `command.json`, `stdout.txt`, `stderr.txt`, and the launcher
  prompt it indexes
- it can exist for successful attempts and recovery attempts

Do not put the canonical manifest only under `phase_recovery/`; that would miss
successful attempts.

Manifest path ownership:

- `evidence.json` in the attempt launch directory is the canonical artifact.
- `evidence_path` is a convenience pointer to that artifact, not a second
  ownership location.
- Persist optional `phase.evidence_path` for the current/latest attempt,
  including normal successful attempts that do not append `attempt_history`.
- Persist optional `attempt_history[].evidence_path` for attempts that do append
  history, such as recovery adoption, retry, block, and retry exhaustion.
- Include `evidence_path` in `_phase_summary()` and
  `schemas/phase_sessions.schema.json` at both the phase level and the
  attempt-history item level.
- `phase_attempts.py` should prefer persisted `evidence_path` when present and
  otherwise derive `launch_dir/evidence.json` when that file exists.

Single writer rule:

- `phase_sessions.py` owns all state-transition-triggered manifest writes and
  all persisted `evidence_path` updates.
- `phase_recovery.py` builds recovery evidence records and passes them into
  phase-session transition functions; it must not write `evidence.json`
  directly.
- `phase_pump.py` creates launch directories, launcher prompts, and
  `command.json`; it must not write `evidence.json` directly.
- `phase_evidence.py` is the pure manifest builder/validator/atomic writer.
  It does not mutate `phase_sessions.v1.json`.
- The normal success path is `record_phase_result()`: after
  `_apply_phase_result()` has populated result/handoff status and before state
  is committed, call the shared best-effort phase-session manifest helper,
  set `phase["evidence_path"]` when successful, and include the same path in
  phase/session events. Do not append an attempt-history row only to store this
  pointer.
- Recovery paths are `adopt_phase_result()`, `abandon_attempt_and_retry()`,
  `mark_phase_blocked()`, and `mark_retry_exhausted()`: each writes or
  refreshes the manifest from the supplied `attempt_record`, then persists the
  same pointer on `phase.evidence_path` and on the appended
  `attempt_history[].evidence_path`.

### Manifest Schema

Add:

`schemas/phase_attempt_evidence.schema.json`

Schema version: `1`.

The manifest schema should use `additionalProperties: false` at the top level
and inside each nested object. Top-level required fields:

```json
{
  "schema_version": 1,
  "run_id": "01...",
  "phase_id": "1",
  "attempt": 1,
  "generated_at": "2026-04-30T00:00:00Z",
  "session_name": "swarmdaddy-...",
  "launcher": "claude-print",
  "status": "retry_waiting",
  "paths": {},
  "hashes": {},
  "process": {},
  "workspace": {},
  "artifacts": {},
  "metrics": {},
  "failure": {},
  "recovery": {},
  "redaction": {}
}
```

Nested object contract:

- `paths`: required object. `launch_dir` and `evidence_path` are required
  non-empty strings. `command_path`, `prompt_path`, `source_prompt_path`,
  `stdout_path`, `stderr_path`, `result_path`, and `handoff_path` are required
  keys whose values may be strings or null.
- `hashes`: required object. `prompt_sha`, `source_prompt_sha`, and
  `settings_sha` are required keys whose values may be SHA-256 strings or null.
- `process`: required object. `parent_pid`, `child_pid`, `process_group_id`,
  `returncode`, `started_at`, `completed_at`, and `elapsed_seconds` are
  required keys and may be null when the launcher did not reach that stage.
- `workspace`: required object. `execution_workspace_mode`, `safe_cwd_enabled`,
  `launcher_cwd`, `launcher_repo_root`, and `real_repo_root_recorded` are
  required keys. Manual and fake-test attempts should set unavailable values to
  null and `real_repo_root_recorded` to false.
- `artifacts`: required object. `result_valid`, `handoff_valid`,
  `partial_artifacts`, `artifact_error_kinds`, `changed_files`, and
  `changed_file_count` are required.
- `metrics`: required object. `total_cost_usd`, `cost_confidence`,
  `input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`,
  `output_tokens`, `duration_ms`, `duration_api_ms`, `num_turns`, and
  `permission_denial_count` are required. Unknown numeric values are null;
  `permission_denial_count` defaults to 0.
- `failure`: required object. `failure_kind`, `failure_category`,
  `failure_retry_class`, `failure_operator_title`,
  `failure_operator_message`, `failure_known`, `retry_decision`,
  `retry_after_seconds`, `blocked_reason`, and `diagnostic_last_error` are
  required keys. Successful attempts should use null failure strings and
  `failure_known=false`.
- `recovery`: required object. `stdout_tail_path`, `stderr_tail_path`,
  `diff_summary_path`, `recovery_context_path`,
  `transcript_diagnostics_path`, `transcript_found`, and `tool_errors_count`
  are required keys whose values may be null when no recovery artifact exists.
- `redaction`: required object. All redaction flags listed below are required
  booleans.

Exact field plan:

```json
{
  "schema_version": 1,
  "run_id": "01K...",
  "phase_id": "2",
  "attempt": 1,
  "generated_at": "2026-04-30T14:00:00Z",
  "session_name": "swarmdaddy-...",
  "launcher": "claude-print",
  "status": "blocked",
  "paths": {
    "launch_dir": "data/runs/.../phase_launches/2/attempt-1",
    "evidence_path": "data/runs/.../phase_launches/2/attempt-1/evidence.json",
    "command_path": "data/runs/.../phase_launches/2/attempt-1/command.json",
    "prompt_path": "data/runs/.../phase_launches/2/attempt-1/dispatcher.launcher.prompt.md",
    "source_prompt_path": "data/runs/.../context/2/dispatcher.prompt.md",
    "stdout_path": "data/runs/.../phase_launches/2/attempt-1/stdout.txt",
    "stderr_path": "data/runs/.../phase_launches/2/attempt-1/stderr.txt",
    "result_path": "data/runs/.../phase_results/2/attempt-1.result.json",
    "handoff_path": "data/runs/.../phase_handoffs/2/attempt-1.handoff.json"
  },
  "hashes": {
    "prompt_sha": "hex...",
    "source_prompt_sha": "hex...",
    "settings_sha": "hex..."
  },
  "process": {
    "parent_pid": 123,
    "child_pid": 456,
    "process_group_id": 456,
    "returncode": 0,
    "started_at": "2026-04-30T13:12:18Z",
    "completed_at": "2026-04-30T13:18:00Z",
    "elapsed_seconds": 342.5
  },
  "workspace": {
    "execution_workspace_mode": "safe-symlink",
    "safe_cwd_enabled": true,
    "launcher_cwd": "...",
    "launcher_repo_root": "...",
    "real_repo_root_recorded": true
  },
  "artifacts": {
    "result_valid": false,
    "handoff_valid": false,
    "partial_artifacts": false,
    "artifact_error_kinds": [],
    "changed_files": ["hooks/run-with-profile.sh"],
    "changed_file_count": 1
  },
  "metrics": {
    "total_cost_usd": 0.73,
    "cost_confidence": "provider_reported",
    "input_tokens": 123,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0,
    "output_tokens": 7986,
    "duration_ms": 123456,
    "duration_api_ms": 120000,
    "num_turns": 14,
    "permission_denial_count": 0
  },
  "failure": {
    "failure_kind": "writer_tool_denied_no_artifacts",
    "failure_category": "writer_runtime",
    "failure_retry_class": "human_gate",
    "failure_operator_title": "Writer tool denied before artifacts",
    "failure_operator_message": "The writer hit a runtime tool error and exited without valid artifacts.",
    "failure_known": true,
    "retry_decision": "deterministic_contract_failure",
    "retry_after_seconds": null,
    "blocked_reason": "retry_policy_human_gate",
    "diagnostic_last_error": "Write tool_disabled: ..."
  },
  "recovery": {
    "stdout_tail_path": "data/runs/.../phase_recovery/2/attempt-1.stdout.tail.txt",
    "stderr_tail_path": "data/runs/.../phase_recovery/2/attempt-1.stderr.tail.txt",
    "diff_summary_path": "data/runs/.../phase_recovery/2/attempt-1.diff-summary.md",
    "recovery_context_path": "data/runs/.../phase_recovery/2/attempt-1.recovery.md",
    "transcript_diagnostics_path": "data/runs/.../phase_recovery/2/attempt-1.transcript-diagnostics.json",
    "transcript_found": true,
    "tool_errors_count": 1
  },
  "redaction": {
    "contains_raw_prompt": false,
    "contains_raw_stdout": false,
    "contains_raw_stderr": false,
    "contains_raw_transcript": false,
    "contains_env": false,
    "path_values_may_be_local": true
  }
}
```

### Redaction Rules

The manifest may contain:

- local file paths
- SHA-256 hashes
- process ids
- return code
- cost/token/turn counts
- changed file paths
- failure kind/category/message
- short diagnostic excerpts already capped by transcript diagnostics

The manifest must not contain:

- full launcher prompt content
- raw transcript lines
- raw stdout content
- raw stderr content
- environment variables
- full command argv copied from `command.json`
- secrets or provider credentials

`command.json`, `stdout.txt`, `stderr.txt`, and the launcher prompt can still
exist as local run evidence. The manifest only indexes them.

TUI and Beads surfaces must use a redacted projection:

- run id
- phase id
- attempt
- status
- launcher
- failure kind
- category
- retry class
- retry decision
- cost/turn summary
- changed file count
- evidence manifest path
- recovery context path when present

### Module Responsibilities

Add a small shared metrics helper:

`py/swarm_do/pipeline/phase_attempt_metrics.py`

Move these current stdout/cost parsing helpers from `phase_attempts.py` into
this module and expose non-underscored names:

- `TOKEN_FIELDS`
- `_stdout_metrics()` -> `stdout_metrics()`
- `_unknown_metrics()` -> `unknown_metrics()`
- `_cost_metrics()` -> `cost_metrics()`
- `_model_usage_cost()` -> `model_usage_cost()`
- `_number_or_none()` -> `number_or_none()`
- `_int_or_none()` -> `int_or_none()`

Keep summary-only helpers in `phase_attempts.py`: `_cost_summary()`,
`_token_summary()`, `_attempt_counts_by_phase()`, `_is_failed_attempt()`,
`_last_failure()`, `_last_error()`, `_recommended_action()`, and event/archive
merge logic. `phase_attempts.py` and `phase_evidence.py` should both import from
the shared helper. `phase_evidence.py` must not import `phase_attempts.py`,
because attempt summaries will also read evidence manifests.

`phase_evidence.py` should provide:

```python
def attempt_launch_dir(data_dir: Path, run_id: str, phase_id: str, attempt: int) -> Path
def attempt_evidence_path(data_dir: Path, run_id: str, phase_id: str, attempt: int) -> Path
def build_attempt_evidence_manifest(
    run_id: str,
    phase: Mapping[str, Any],
    *,
    state: Mapping[str, Any] | None,
    attempt_record: Mapping[str, Any] | None,
    data_dir: Path,
) -> dict[str, Any]
def write_attempt_evidence_manifest(...) -> Path
def read_attempt_evidence_manifest(path: Path) -> dict[str, Any]
def redacted_attempt_evidence(manifest: Mapping[str, Any]) -> dict[str, Any]
```

Implementation notes:

- Reuse the metrics parser logic through `phase_attempt_metrics.py`; do not fork
  a second parser.
- Prefer `command.json` for launch metadata.
- Prefer attempt-history recovery fields for recovery paths.
- Prefer result/handoff paths from phase state or command metadata.
- Validate the manifest against `schemas/phase_attempt_evidence.schema.json`
  before writing.
- Write atomically through the existing `_atomic_json_write()` helper.
- The writer must be best-effort in transition paths: manifest write failure
  should emit a run event and not corrupt phase-session state.

`phase_attempt_evidence_failed` event payload:

```json
{
  "event_type": "phase_attempt_evidence_failed",
  "phase_id": "2",
  "reason": "manifest_write_failed",
  "details": {
    "phase_id": "2",
    "attempt": 1,
    "launcher": "claude-print",
    "transition": "record_phase_result",
    "launch_dir": "data/runs/.../phase_launches/2/attempt-1",
    "evidence_path": "data/runs/.../phase_launches/2/attempt-1/evidence.json",
    "error_class": "ValidationError",
    "error_message": "schema validation failed: ...",
    "manifest_schema_version": 1
  }
}
```

Allowed `transition` values are `record_phase_result`, `adopt_phase_result`,
`abandon_attempt_and_retry`, `mark_phase_blocked`, and
`mark_retry_exhausted`. The payload must not include prompt text, stdout,
stderr, transcript lines, environment values, or argv.

### Runtime Wiring

Update `phase_recovery.py`:

- Do not write `evidence.json` directly. Let `phase_sessions.py` transition
  helpers own manifest writes.
- Pass the attempt evidence dict into
  `abandon_attempt_and_retry()`, `mark_phase_blocked()`,
  `mark_retry_exhausted()`, or `adopt_phase_result()`.
- Add `evidence_path` to recovery action dictionaries and Beads note details.
  Use the updated phase returned by the transition helper as the source of the
  persisted path.

Update `phase_sessions.py`:

- Add optional phase-level `evidence_path` to phase state, `_phase_summary()`,
  and `schemas/phase_sessions.schema.json`.
- Add optional `evidence_path` to `_attempt_record_from_phase()` and
  `attempt_history[]` in `schemas/phase_sessions.schema.json`.
- Add a private helper such as `_write_attempt_evidence_best_effort()` that
  wraps `phase_evidence.write_attempt_evidence_manifest()`, updates the phase
  dict with `evidence_path` on success, and appends
  `phase_attempt_evidence_failed` on failure.
- When `record_phase_result()` records a normal manual/fake/claude attempt,
  call that helper after applying the phase result and store the manifest path
  on `phase.evidence_path`. Do not append a successful-attempt history row just
  to store the pointer.
- Clear `phase.evidence_path` when starting a new attempt or resetting launch
  metadata so a retry cannot show a stale pointer from the previous attempt.
- When `adopt_phase_result()`, `abandon_attempt_and_retry()`,
  `mark_retry_exhausted()`, and `mark_phase_blocked()` append attempt history,
  write or refresh the manifest using the attempt record, then persist the same
  pointer on both `attempt_history[].evidence_path` and `phase.evidence_path`.
- If manifest writing fails, append a `phase_attempt_evidence_failed` event.
  Add that event type to `schemas/telemetry/run_events.schema.json`.

Update `phase_pump.py`:

- Ensure every `claude-print` launcher error includes `launch_dir` in the
  returned launcher result once the directory exists. This closes the current
  `claude_cli_missing` gap.
- Add one shared launcher-prep helper used by `manual`, `fake-test`, and
  `claude-print`:

  ```python
  def _prepare_phase_launch(
      run_id: str,
      phase_id: str,
      phase: Mapping[str, Any],
      *,
      launcher: str,
      source_prompt_path: Path,
      data_dir: Path,
      prompt_text: str | None = None,
      argv: Sequence[str] | None = None,
      settings_path: Path | None = None,
      settings_sha: str | None = None,
      workspace_metadata: Mapping[str, Any] | None = None,
  ) -> dict[str, Any]
  ```

  It creates `phase_launches/<phase_id>/attempt-<n>/`, writes
  `dispatcher.launcher.prompt.md`, writes `command.json`, calls
  `record_launch_metadata()`, and returns `launch_dir`, `command_path`,
  `launcher_prompt_path`, `result_path`, `handoff_path`, `prompt_sha`,
  `source_prompt_sha`, and `metadata`.
- Prompt/hash sources:
  - `source_prompt_path` is `context["prompt_path"]` from
    `render_context_bundle()`.
  - `source_prompt_sha` is `_sha256_file(source_prompt_path)`.
  - `prompt_text` defaults to the bytes read from `source_prompt_path`.
  - `prompt_sha` is `_sha256_file(launch_dir / "dispatcher.launcher.prompt.md")`.
  - `settings_sha` is the writer settings hash for `claude-print`; it is null
    for `manual` and `fake-test`.
- Manual launcher behavior:
  - Create the launch directory before returning `manual_waiting`.
  - Write `dispatcher.launcher.prompt.md` as the exact prompt shown to the
    operator.
  - Write `command.json` with `launcher="manual"`, `prompt_path`,
    `prompt_sha`, `source_prompt_path`, `source_prompt_sha`,
    `result_path`, `handoff_path`, `prompt_delivery="manual"`,
    `env_redacted=true`, and null process/workspace values where unavailable.
  - Return the launcher prompt path in `manual.prompt_path` and keep the same
    follow-up `bin/swarm phases complete ...` command.
- Fake-test launcher behavior:
  - Create the same launch directory shape before writing fake result/handoff
    artifacts.
  - Write `dispatcher.launcher.prompt.md` from the rendered dispatcher prompt
    for auditability, but do not include prompt text in the manifest.
  - Write `command.json` with `launcher="fake-test"`, `prompt_path`,
    `prompt_sha`, `source_prompt_path`, `source_prompt_sha`, `result_path`,
    `handoff_path`, `prompt_delivery="synthetic"`, `returncode=0`,
    `env_redacted=true`, and null workspace/process values where unavailable.
  - Do not fabricate stdout cost, token, duration, turn, or permission metrics.
- Include `evidence_path` in pump/recovery results when present.

Update `phase_attempts.py`:

- Add `evidence_path` to each attempt row.
- If `evidence.json` exists, prefer it for fields that are missing from state.
- Preserve current behavior for old runs where no manifest exists.
- Add `include_evidence=True` option only if needed; default summaries should
  stay compact.

Update `cli.py`:

- Add `bin/swarm phases evidence <run_id> [--phase <phase-id>] [--attempt <n>] [--json]`.
- Text output should list manifest paths and compact redacted summaries.
- JSON output should return redacted manifests by default.
- Add `--raw-local` to print full local manifests. It is valid only with
  `--json`; text output is always redacted. This still does not inline raw
  prompts/stdout/stderr/transcripts because the manifest never contains them.
- Flag and exit-code contract:
  - `--attempt` requires `--phase`; invalid flag combinations exit `1`.
  - `--phase` without `--attempt` selects all manifests for that phase.
  - `--phase` with `--attempt` selects exactly one manifest.
  - No selector lists all discovered manifests for the run.
  - Exit `0` when the run is readable and the command completes; broad run
    queries may return `count=0` for old runs without manifests.
  - Exit `2` when a specific selector is well formed but no manifest matches.
  - Exit `3` when the run state is missing/drifted or a selected manifest is
    unreadable or schema-invalid.
- `bin/swarm phases status --attempts` should include `evidence=<path>` in text
  rows when present.

Update `phase_beads.py`:

- Include `evidence_path` when present.
- Never include raw diagnostic excerpts in Beads notes.

Update `tui/state.py` and `tui/app.py`:

- Add `evidence_path` to attempt rows.
- For `PhaseSessionRunRow`, append optional evidence/taxonomy fields at the end
  of the dataclass with defaults and update construction by keyword only.
- In detail panels, show a compact "Evidence" section with:
  - manifest path
  - recovery context path
  - diff summary path
  - transcript diagnostics path
  - changed file count

### Support Bundle Shape

P0 does not need a tarball. The manifest plus existing archive command is enough
to prove value.

P1/P2 can add:

`bin/swarm phases bundle <run_id> [--phase <phase-id>] [--attempt <n>] [--include-prompts] [--include-raw-streams]`

Default bundle contents:

- `bundle-index.json`
- selected `evidence.json` manifests
- `phase_sessions.v1.json`
- filtered `run_events.jsonl` rows for the run
- result and handoff JSON files
- `command.json`
- recovery markdown
- stdout/stderr tail files
- diff summaries
- transcript diagnostics JSON

Default bundle exclusions:

- raw launcher prompt files
- full stdout/stderr files
- raw Claude transcript JSONL files
- environment values

The bundle should include prompts or raw streams only when an operator passes an
explicit include flag.

### Tests

Add `py/swarm_do/pipeline/tests/test_phase_evidence.py`:

- Manifest path is under the attempt launch directory.
- Manifest validates against `schemas/phase_attempt_evidence.schema.json`.
- Schema rejects unknown manifest fields and requires all top-level and nested
  required keys.
- Successful claude-print fixture writes manifest with result/handoff paths,
  prompt hashes, command path, and metrics.
- Manual and fake-test fixtures write manifests with minimal command metadata,
  null unavailable metrics/workspace fields, and no raw prompt content.
- Non-zero no-artifacts recovery writes manifest with stdout/stderr tail paths,
  diff summary, recovery context, failure taxonomy fields, and retry decision.
- Writer tool-denied transcript fixture writes manifest with transcript
  diagnostics path and no raw transcript content.
- Manifest redaction flags are correct.
- Old runs without manifests still summarize through `phase_attempts.py`.

Update `test_phase_recovery.py`:

- Recovery actions include `evidence_path`.
- Retry, block, and retry-exhausted transitions persist `evidence_path` in
  attempt history.

Update `test_phase_pump.py`:

- Successful claude-print run creates `evidence.json`.
- `claude_cli_missing` launcher error includes a launch directory and can write
  a manifest.
- Manual launcher creates minimal command metadata and manifest.
- Fake-test launcher creates minimal command metadata and manifest.

Update `test_phase_attempts.py`:

- Attempt summaries expose `evidence_path`.
- Attempt summaries derive `launch_dir/evidence.json` when persisted
  `evidence_path` is absent but the manifest exists.
- Summary prefers manifest fields when state is incomplete.

Update `test_phase_sessions.py`:

- `archive_phase_session_evidence()` copies manifests because they live under
  `phase_launches`.
- Optional phase-level and attempt-history `evidence_path` fields validate in
  phase-session state.
- Normal successful result recording stores `phase.evidence_path` without
  appending a synthetic attempt-history row.

Update `py/swarm_do/tui/tests/test_state.py`:

- Phase-session detail rows include evidence paths without requiring raw local
  file reads in dense tables.

### Rejected Alternatives

- Do not store manifests in a new root directory for P0. Existing
  `phase_launches` archive/cleanup behavior already gives the right lifecycle.
- Do not append full manifests to `telemetry/run_events.jsonl`. Run events are
  a ledger, not a document store.
- Do not copy raw transcripts into run directories. Transcript diagnostics are
  enough for the default forensic packet.
- Do not make support bundles the P0 deliverable. The smaller manifest delivers
  most value and reduces privacy risk.

## Ordered Work Breakdown

### P0.1 - Taxonomy Registry

Files:

- `py/swarm_do/pipeline/failure_taxonomy.py`
- `py/swarm_do/pipeline/tests/test_failure_taxonomy.py`
- `docs/failure-taxonomy.md`

Work:

1. Add `FailureKindSpec` and registry helpers.
2. Register current known failure kinds and artifact error kinds.
3. Add markdown rendering.
4. Implement alias lookup semantics exactly as described above.
5. Add tests for known, unknown, alias collision, and markdown coverage.

Acceptance:

- Unknown child failure kinds do not fail validation.
- All current SwarmDaddy-owned failure kinds have category, retry class, title,
  message, and required evidence.
- `child_process_dead_no_artifacts` and `launcher_nonzero_with_artifacts` are
  documented as recovery-owned current kinds, not classifier emissions.

### P0.2 - Taxonomy Runtime Surfacing

Files:

- `py/swarm_do/pipeline/phase_recovery.py`
- `py/swarm_do/pipeline/phase_sessions.py`
- `py/swarm_do/pipeline/phase_attempts.py`
- `schemas/phase_sessions.schema.json`
- `py/swarm_do/pipeline/phase_beads.py`
- `py/swarm_do/pipeline/cli.py`
- `py/swarm_do/tui/state.py`
- `py/swarm_do/tui/app.py`

Work:

1. Enrich attempt records and summaries with taxonomy details.
2. Preserve the exact `_retry_stop_decision()` split between registry-backed
   defaults and recovery-owned evidence-sensitive branches.
3. Add taxonomy details to run events, Beads notes, CLI status, and TUI rows.
4. Keep all new persisted fields optional.
5. Append any new `PhaseSessionRunRow` fields with defaults; do not reorder the
   dataclass.

Acceptance:

- `bin/swarm phases status --attempts` shows kind, category, retry class,
  actual retry decision when present, and compact operator title.
- JSON outputs include taxonomy fields.
- Existing phase-session fixtures without taxonomy fields still load.
- Return-code, artifact-contract, same-failure-limit, retry-budget, and
  child-controlled retry behavior match current tests.

### P0.3 - Evidence Manifest Schema And Writer

Files:

- `py/swarm_do/pipeline/phase_attempt_metrics.py`
- `py/swarm_do/pipeline/phase_evidence.py`
- `py/swarm_do/pipeline/phase_attempts.py`
- `schemas/phase_attempt_evidence.schema.json`
- `py/swarm_do/pipeline/tests/test_phase_evidence.py`
- `py/swarm_do/pipeline/tests/test_phase_attempts.py`

Work:

1. Add manifest build, validation, write, read, and redacted projection helpers.
2. Move shared stdout/cost metric parsing into `phase_attempt_metrics.py` and
   import it from both `phase_attempts.py` and `phase_evidence.py`.
3. Ensure manifests never inline raw prompt/stdout/stderr/transcript content.
4. Keep summary aggregation and archive/event merging in `phase_attempts.py`.

Acceptance:

- Manifest schema validates the expected P0 fields.
- Redacted projection is safe for CLI/TUI/Beads.
- `phase_attempt_metrics.py` owns exactly the helper set named in Module
  Responsibilities.

### P0.4 - Evidence Runtime Wiring

Files:

- `py/swarm_do/pipeline/phase_recovery.py`
- `py/swarm_do/pipeline/phase_sessions.py`
- `py/swarm_do/pipeline/phase_pump.py`
- `schemas/phase_sessions.schema.json`
- `schemas/telemetry/run_events.schema.json`
- `py/swarm_do/pipeline/tests/test_phase_recovery.py`
- `py/swarm_do/pipeline/tests/test_phase_pump.py`
- `py/swarm_do/pipeline/tests/test_phase_sessions.py`

Work:

1. Implement the single writer rule: only `phase_sessions.py` transition
   helpers write or refresh `evidence.json` and persist `evidence_path`.
2. Persist `phase.evidence_path` for current/latest attempts and
   `attempt_history[].evidence_path` for attempts that append history.
3. Add the shared `phase_pump._prepare_phase_launch()` helper and route manual,
   fake-test, and claude-print through it where applicable.
4. Ensure launcher errors include enough launch metadata to write a manifest.
5. Add `phase_attempt_evidence_failed` telemetry event.

Acceptance:

- Successful, retried, blocked, and exhausted attempts produce manifests.
- Successful attempts expose `phase.evidence_path` without requiring an
  attempt-history row.
- Manual and fake-test attempts create launch directories, launcher prompts,
  command metadata, and manifests.
- Manifest write failures do not corrupt phase-session state.
- Manifest write failures emit the specified `phase_attempt_evidence_failed`
  details payload.
- Archive and cleanup behavior remains correct because manifests live in
  `phase_launches`.

### P0.5 - Evidence CLI And UI Surfacing

Files:

- `py/swarm_do/pipeline/cli.py`
- `py/swarm_do/pipeline/phase_attempts.py`
- `py/swarm_do/tui/state.py`
- `py/swarm_do/tui/app.py`
- `py/swarm_do/pipeline/tests/test_phase_cli.py`
- `py/swarm_do/tui/tests/test_state.py`
- `tui/README.md` if operator docs need an update

Work:

1. Add `bin/swarm phases evidence`.
2. Add `evidence_path` to `phases status --attempts`.
3. Add compact evidence details in TUI run detail panels.
4. Cover `phases evidence` selector, `--raw-local`, JSON/text, and exit-code
   behavior.

Acceptance:

- Operators can find a per-attempt evidence manifest without knowing the run
  directory layout.
- TUI does not read or display raw prompt/stdout/stderr/transcript content.
- CLI flag combinations and exit codes match the contract in Runtime Wiring.

### P1 - Support Bundle

Files:

- `py/swarm_do/pipeline/phase_evidence.py`
- `py/swarm_do/pipeline/cli.py`
- `py/swarm_do/pipeline/tests/test_phase_evidence.py`

Work:

1. Add `bin/swarm phases bundle`.
2. Build `bundle-index.json`.
3. Include redacted defaults and explicit raw include flags.

Acceptance:

- Default bundle excludes prompts, raw streams, and raw transcripts.
- Include flags are explicit and covered by tests.

### P2 - Query And Dashboard Polish

Files:

- `py/swarm_do/telemetry/subcommands/report.py`
- `py/swarm_do/tui/state.py`
- `py/swarm_do/tui/app.py`
- `docs/failure-taxonomy.md`

Work:

1. Add report buckets by failure category and retry class.
2. Add TUI filters for failure category.
3. Add docs for common operator actions per category.

Acceptance:

- Operators can answer "what classes of failures cost us money this week?"
  from local telemetry without reading raw logs.

## Validation Commands

Run the focused suite:

```bash
PYTHONPATH=py python3 -m unittest \
  py.swarm_do.pipeline.tests.test_failure_taxonomy \
  py.swarm_do.pipeline.tests.test_phase_evidence \
  py.swarm_do.pipeline.tests.test_phase_recovery \
  py.swarm_do.pipeline.tests.test_phase_attempts \
  py.swarm_do.pipeline.tests.test_phase_cli \
  py.swarm_do.pipeline.tests.test_phase_pump \
  py.swarm_do.pipeline.tests.test_phase_sessions \
  py.swarm_do.tui.tests.test_state
```

Run schema and telemetry coverage:

```bash
PYTHONPATH=py python3 -m unittest \
  py.swarm_do.telemetry.tests.test_schemas \
  py.swarm_do.pipeline.tests.test_resume
```

Run the existing install/repo readiness smoke path:

```bash
bin/swarm selftest --json
```

If the branch intentionally cannot run selftest in the current environment,
record the blocker in the implementation summary.

## Backward Compatibility

- No existing `failure_kind` string is renamed in P0.
- Old phase-session files still load; new fields are optional.
- Existing runs are not migrated.
- `phase_attempts.py` continues to synthesize summaries from old state and old
  launch directories when no `evidence.json` exists.
- Historical queries on `outer_artifacts_missing` should be updated to include
  `writer_tool_denied_no_artifacts` and `writer_silent_with_turns` where they
  mean "missing artifacts after writer runtime problem."

## Risks And Mitigations

| Risk | Mitigation |
| --- | --- |
| Taxonomy becomes too large or noisy | Register only SwarmDaddy-owned failure kinds and artifact error kinds in P0; unknown child values use a generic fallback. |
| Retry behavior changes accidentally | Keep evidence-sensitive policy in `phase_recovery.py`; add tests for current retry/block outcomes. |
| Manifest leaks raw sensitive content | Schema and tests assert manifest contains paths/hashes/metrics only, not raw prompt/stdout/stderr/transcript. |
| Manifest write failure breaks recovery | Treat manifest writes as best-effort after state decision; emit `phase_attempt_evidence_failed`. |
| Duplicate manifest writers diverge | `phase_sessions.py` is the only state-transition writer; recovery and pump only supply evidence inputs and launch metadata. |
| New schema fields break old runs | Add optional fields only; do not bump phase-session schema version. |
| TUI becomes dense or noisy | Dense tables show category/title only; detail views show paths. |
| Support bundle grows into a data dump | Keep bundle P1/P2 and redacted by default. |

## Resolved Questions

| Question | Decision |
| --- | --- |
| What failure kinds exist today? | The initial registry list above covers current SwarmDaddy-owned launcher, lifecycle, writer-runtime, environment, operator, and artifact-contract values. |
| Are `child_process_dead_no_artifacts` and `launcher_nonzero_with_artifacts` current? | Yes. They are current recovery-owned emissions: child liveness in `_active_phase_decision()` and non-zero launcher plus valid artifacts in `_artifact_failure_kind()`. |
| Which failures are retryable, human-gated, or terminal? | Registry supplies default retry class; `phase_recovery.py` applies evidence-sensitive overrides. |
| Which `_retry_stop_decision()` branches move to the registry? | Descriptive defaults move to the registry; return-code guards, deterministic artifact errors, same-failure limits, retry budgets, recovery-retry checks, retry-after clamping, and child-controlled contracts remain in recovery. |
| Should taxonomy live centrally? | Yes, in `failure_taxonomy.py`, with markdown documentation. |
| How do aliases work? | `failure_kind_spec()` accepts aliases but returns the canonical spec; `failure_kind_details()` preserves the raw supplied kind and uses canonical details; `known_failure_kinds()` lists canonical non-deprecated kinds only. |
| Should `failure_kind` become a schema enum? | No. Keep arbitrary child-reported values compatible. |
| Should operator messages differ from enum names? | Yes. Registry stores title and message. |
| Should taxonomy appear in CLI, TUI, Beads, and JSON? | Yes. CLI/TUI/Beads use compact projections; JSON includes full taxonomy fields. |
| What evidence is captured but hard to find? | Command metadata, prompts, stdout/stderr, result/handoff JSON, recovery tails, diff summaries, transcript diagnostics, attempt history, and run events. |
| What should the evidence index contain? | Paths, hashes, process details, metrics, artifact validity, changed-file summary, failure taxonomy, retry decision, and recovery artifact paths. |
| Where should the manifest live? | In the attempt launch directory as `evidence.json`. |
| Where should `evidence_path` live? | The canonical artifact remains launch-dir `evidence.json`; phase state stores `phase.evidence_path` for the current/latest attempt and attempt history stores `attempt_history[].evidence_path` only for attempts that append history. |
| Do successful attempts need synthetic attempt history? | No. Normal successful attempts write the manifest and set `phase.evidence_path`; they do not append history just to store the pointer. |
| Who writes `evidence.json`? | `phase_sessions.py` transition helpers only. `phase_recovery.py` passes attempt records and `phase_pump.py` writes launch metadata. |
| Which launchers must have manifest metadata? | Claude-print, manual, and fake-test attempts all need a launch directory and minimal `command.json` metadata in P0. |
| Do manual and fake-test attempts write launcher prompts? | Yes. Both write `phase_launches/<phase>/attempt-<n>/dispatcher.launcher.prompt.md` from the rendered dispatcher prompt, hash it, and index it by path only. |
| Who owns stdout/cost parsing? | `phase_attempt_metrics.py`; both `phase_attempts.py` and `phase_evidence.py` import the shared helper. |
| What happens when manifest writing fails? | The state transition continues, `phase_attempt_evidence_failed` records transition, phase, attempt, launcher, launch directory, target evidence path, and error metadata. |
| What are `bin/swarm phases evidence` flag semantics? | Broad run queries list all manifests and may return count zero; `--phase` filters a phase; `--attempt` requires `--phase`; `--raw-local` requires `--json`; invalid flags exit 1, selector misses exit 2, drift/read/schema errors exit 3. |
| How strict is the evidence schema? | Top-level and nested objects use `additionalProperties: false`; required objects and nullable required keys are defined in the manifest schema section. |
| Should recovery write a summary alongside markdown? | Recovery should write recovery markdown/tails/diagnostics and pass attempt evidence to `phase_sessions.py`; the phase-session transition writes the launch-dir manifest and links to recovery markdown. |
| What belongs in run events? | Compact transition facts: failure kind/category/retry class, actual retry decision, blocked reason, evidence path. |
| What belongs in local evidence files? | The full manifest index and local paths to artifacts. |
| What redaction is required? | No raw prompt, transcript, stdout, stderr, environment, or copied argv in manifests, TUI, or Beads. |
| What does a support bundle look like? | P1/P2 tarball with manifests, result/handoff JSON, command metadata, recovery tails/context, diff summaries, transcript diagnostics, and run events; raw prompts/streams/transcripts excluded by default. |
| Are there open questions before implementation? | No. The remaining choices are execution details covered by the ordered work breakdown and tests. |
