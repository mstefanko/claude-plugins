# ECC Pattern Adoption Plan

Date: 2026-04-28
Reviewed against current codebase: 2026-05-01
Owner: swarm-do runtime and operator experience
Reference repo: <https://github.com/affaan-m/everything-claude-code>
Reference revision inspected: `4e66b2882da9afb9747468b08a253ca2f09c85f3`

## Goal

Adopt the small number of Everything Claude Code patterns that improve
SwarmDaddy's reliability, security posture, and operator ergonomics without
turning SwarmDaddy into a broad harness catalog.

SwarmDaddy's durable advantage is deterministic orchestration: Beads-backed
issues, prepared plans, work-unit schemas, provider evidence, routing
invariants, telemetry contracts, and resume/checkpoint state. ECC is stronger
around the surrounding harness: install/state repair, hook controls, harness
health audits, cross-harness surfaces, and security/config scanning.

The implementation should therefore add a thin operational shell around the
existing SwarmDaddy engine. Do not replace pipeline execution, role contracts,
provider review, or the TUI with ECC-style generic orchestration.

## Current Codebase Review - 2026-05-01

The overall ECC adoption direction still fits SwarmDaddy, but several sections
needed to be re-anchored to the current architecture:

- `bin/swarm selftest` has already shipped in `py/swarm_do/pipeline/selftest.py`
  with fixture-backed tests and README coverage. Treat Phase 1 as landed and
  avoid turning the command into a second validator implementation.
- Hook profile controls have not shipped. `hooks/hooks.json` still invokes
  `hooks/precompact.sh` directly, with no hook ID or profile wrapper. Phase 2 is
  therefore the next P0 before any new hook or hook-enforcing security check.
- Tool/activity analysis already exists as post-run extraction into
  `telemetry/observations.jsonl` using `schemas/telemetry/observations.v2.schema.json`.
  `telemetry/run_events.jsonl` is the orchestration audit log and should not be
  repurposed as the activity stream.
- Work-unit execution now has durable `unit_sessions.v1.json`, data-dir unit
  worktrees, post-writer reports, and TUI/worktree status readers. Any operator
  Markdown snapshots must be derived exports over those records, not a parallel
  source of truth.
- Codex already exists in routing and role overlays (`roles/*/codex.md`,
  `agent-codex-review`, provider-review shims). A Codex emitter would add a new
  config/docs surface before there is a concrete operational gap, so it is cut
  from this active plan.

## Senior Scope Review - 2026-05-01

The high-value remainder of the plan is a guardrail sequence, not a platform
expansion:

1. Land hook profile controls for the one hook that already exists.
2. Add a narrow static security/config audit focused on SwarmDaddy runtime
   risks.
3. Improve post-run activity reporting from the existing observation ledger.
4. Keep Markdown unit snapshots as a deferred, derived-export convenience only.

The following items are cut from the active plan:

- `PostToolUse` activity hook. Existing backend-output extraction already gives
  useful `observations.jsonl` data. A hot-path hook adds latency, privacy risk,
  and operational surprise. Reconsider only if a later proposal names specific
  metrics that cannot be recovered post-run.
- Codex emitter/doctor surface. Codex routing and role overlays already exist.
  Emitted `.codex/swarmdaddy` files would add another config/docs surface to
  keep synchronized without urgent runtime value.
- Optional JSON schemas for `selftest` and `security audit`. Fixtures plus
  focused tests are enough until a real persisted consumer appears.
- CI workflow scanning in the first security audit. It is easy to false-positive
  and is not central to SwarmDaddy's plugin runtime.

## Decision Summary

| Idea from ECC | Decision | Priority | Why |
| --- | --- | --- | --- |
| Deterministic harness audit | Adopt; shipped as `bin/swarm selftest` | P0 done | Existing checks are strong but scattered. Keep extending through small registry checks only. |
| Hook runtime profile and per-hook disable controls | Adopt in small SwarmDaddy-specific form | P0 | Lets us add safety hooks without making every install pay every cost. |
| Security/config scanner | Adopt as narrow local static audit, no network dependency | P1 | Complements role permission contracts by scanning plugin/runtime config risks without becoming a CI scanner. |
| Sanitized tool/file activity telemetry | Adopt by extending current `observations.v2` flow only | P1 | Helps explain token/tool churn and repeated reads without a hot-path hook. |
| Worktree operator snapshots | Keep deferred as derived exports over `unit_sessions.v1.json` | P2 deferred | Useful for humans only when debugging/resume pain is concrete; must never become state authority. |
| Codex-native project surface | Cut from active plan | n/a | Existing Codex routing and role overlays cover current needs; emitter/doctor adds sync burden. |
| Broad agents/skills/rules catalog | Reject | n/a | It dilutes SwarmDaddy's narrow orchestration mission. |
| Generic tmux/dmux orchestrator | Reject as core engine; keep as inspiration | n/a | SwarmDaddy already has stronger deterministic work-unit execution. |
| Large default hook matrix | Reject | n/a | Too much surprise behavior and latency for a Claude plugin focused on orchestration. |

## Design Principles

- Prefer composition over parallel systems. Use existing `preset dry-run`,
  `pipeline lint`, `providers doctor`, `permissions check`, telemetry
  validation, and run-state helpers before adding new validators.
- Keep every new check scriptable and JSON-capable. Operator UIs and dogfood
  reports should consume the same output humans see.
- Do not auto-install external tools, MCP servers, or Codex config. Emit
  instructions or generated files that the operator can inspect.
- Fail closed only for deterministic local risks. Advisory items should be
  warnings unless the run explicitly opts into a strict profile.
- Redact secrets at the collection boundary. Never rely on downstream reports
  to clean sensitive payloads.
- Keep hooks cheap. Slow checks belong in `selftest`, TUI health, or explicit
  commands, not hot-path hook execution.
- CLI surface convention: a flat verb (`bin/swarm selftest`) when the command
  has one mode; a verb group (`bin/swarm security audit`) when two or more
  sibling verbs are planned. Decide at design time, not after the second verb
  appears.
- Every shipped feature must have an explicit off switch documented in the
  rollback table. "Don't invoke it" is acceptable only for invoke-only
  commands; anything that runs implicitly (hooks, auto-checks) needs an env
  var or profile disable.
- Keep telemetry ledgers role-specific. `run_events.jsonl` is append-only
  orchestration audit; `observations.jsonl` is tool/subprocess activity;
  `runs.jsonl` is the invocation envelope. Do not collapse them unless a
  separate storage migration explicitly changes the source-of-truth contract.

## Resolved Decisions

These were Open Questions in earlier drafts. Locking them now so phases can
be executed without further design rounds.

- **Selftest TUI exposure.** Phase 1 has shipped the `bin/swarm selftest`
  command only. TUI binding remains deferred and must consume the same JSON
  contract rather than parse human text. Rationale: do not couple health checks
  to TUI rendering.
- **Foundation split after implementation drift.** Earlier drafts required
  Phase 1 and Phase 2 to merge together. The current codebase already has Phase
  1 without Phase 2. The updated constraint is: no new default hook and no
  `hook-missing-profile-wrapper` security finding may ship until Phase 2 wraps
  the existing PreCompact hook.
- **Activity telemetry source.** Phase 4 starts with the existing
  `py/swarm_do/telemetry/run_observations.py` post-run extraction into
  `observations.jsonl`. The `PostToolUse` hook is cut from this plan.
  Rationale: use the shipped observation ledger and avoid hot-path latency,
  privacy, and surprise-behavior risk until a concrete missing metric is named.
- **Unit snapshot retention.** Derived unit snapshot exports follow the run
  retention policy in `docs/adr/0001-telemetry-retention.md` — default 30-day
  retention with operator override. Canonical unit state remains
  `unit_sessions.v1.json` plus run/worktree manifests.
- **Markdown snapshot authority.** Phase 5 exports are never read as control
  state. They are disposable views regenerated from `unit_sessions.v1.json`,
  worktree manifests, prepared sidecars, and post-writer/spec-review reports.
  Rationale: avoid the "which file is true?" failure mode.

## Non-Goals

- No adoption of ECC's full skill, rule, command, or agent catalog.
- No generic installer that writes into `~/.claude`, `~/.codex`, Cursor, or
  OpenCode directories.
- No new runtime dependency on Node.js for the Python pipeline. Hook helpers can
  stay shell/Python unless a specific cross-platform need appears.
- No default-on MCP bundle.
- No dashboard replacement for the Textual TUI.
- No Codex emitter/doctor surface in this plan.
- No hot-path PostToolUse activity hook in this plan.

## Phase 0 - Baseline Inventory And Contracts

### Objective

Record current health signals and formalize the output contracts before adding
new command surfaces.

### Current Status

Phase 0 is effectively complete for `selftest`, security-audit, and activity
fixtures. The activity fixture and ADR now describe `observations.v2` rather
than a new run-events activity row; future Phase 4 changes must keep them
aligned with the shipped observation schema.

### Implementation

1. Maintain fixture-backed examples for the target outputs:
   - `docs/examples/selftest.ok.json`
   - `docs/examples/security-audit.warning.json`
   - `docs/examples/activity-observation.jsonl`
2. Keep ADR 0007, or a superseding ADR, aligned with:
   - which checks are hard failures
   - which checks are advisory
   - which paths may contain sensitive diagnostics
3. Confirm the existing command inventory remains the source of truth:
   - `bin/swarm preset dry-run`
   - `bin/swarm pipeline lint`
   - `bin/swarm providers doctor`
   - `bin/swarm permissions check`
   - `bin/swarm-telemetry validate`
   - `bin/swarm-telemetry dogfood-check`
   - `bin/swarm-telemetry experiment-report`

### Files

| File | Change |
| --- | --- |
| `docs/examples/selftest.ok.json` | Existing fixture: shape of `bin/swarm selftest --json` healthy output. |
| `docs/examples/security-audit.warning.json` | Existing fixture: shape of `bin/swarm security audit --json` with one warning. |
| `docs/examples/activity-observation.jsonl` | Existing fixture for one sanitized `observations.v2` activity row. |

### Acceptance

- There is a written schema-level contract for each new output, and shipped
  runtime emitters conform to it.
- No existing command behavior changes when fixture/ADR wording is updated.

## Foundation Follow-Through (Phase 1 Shipped, Phase 2 Pending)

The intended Foundation epic has partially landed: `bin/swarm selftest` exists,
but hook profile controls do not. Do not reopen Phase 1 solely to restore the
old batching model. Instead, land Phase 2 as the follow-through P0 and require
it before any future hook, hook-backed telemetry, or hook-wrapper security
finding.

Acceptance for the follow-through: every Phase 2 acceptance criterion passes,
the rollback levers work end-to-end, and one full dogfood pipeline run
completes with `bin/swarm selftest` invoked at start and
`SWARM_HOOK_PROFILE=standard` set throughout.

## Phase 1 - `bin/swarm selftest`

### Objective

Add one deterministic health command that answers: "Is this SwarmDaddy install
and target repo ready to run?"

### Current Status

Shipped in `py/swarm_do/pipeline/selftest.py`, wired through
`py/swarm_do/pipeline/cli.py`, covered by
`py/swarm_do/pipeline/tests/test_selftest.py`, and documented in `README.md`.
Future work should be additive and registry-oriented.

### Recommended Surface

```bash
bin/swarm selftest [--plan <path>] [--preset <name|current>] [--json] [--strict]
```

Default behavior should be safe in any checkout. It should not initialize
Beads, install permissions, create worktrees, call live providers unless the
doctor already does so today, or mutate plugin data except for normal doctor
cache behavior.

### Checks

Hard checks:

- Plugin root and data directory are resolvable.
- Beads rig is present when running in a target repo.
- Active preset loads, or default pipeline lints when no preset is active.
- `pipeline lint` passes for the selected graph.
- `preset dry-run` passes when `--plan` is provided.
- Role permissions fragments load for all registered roles.
- Telemetry schemas and generated docs checks pass.
- `active-run.json` is either absent or valid.

Advisory checks:

- Provider doctor readiness, including review provider eligibility.
- TUI dependency state and lock hash status.
- Latest checkpoint age and active-run freshness.
- Dirty SwarmDaddy plugin checkout when running from a development clone.
- Dogfood telemetry promotion/hold summary when data exists.

### Files

| File | Change |
| --- | --- |
| `py/swarm_do/pipeline/selftest.py` | Existing module with check registry, result dataclasses, JSON/text formatting. |
| `py/swarm_do/pipeline/cli.py` | Existing `selftest` subcommand and argument parsing. |
| `py/swarm_do/pipeline/tests/test_selftest.py` | Existing fixture-backed tests for pass, hard fail, advisory warning, strict mode. |
| `README.md` | Existing command row. |
| `tui/README.md` | Add only if TUI gets a health action backed by this command. |

### Implementation Notes

- Keep checks as small functions returning a normalized row:

  ```json
  {
    "id": "pipeline-lint",
    "severity": "hard",
    "status": "pass",
    "summary": "default pipeline linted",
    "details": {},
    "remediation": null
  }
  ```

- Do not shell out when a Python helper already exists. Import registry,
  validation, permissions, run-state, and telemetry helpers directly.
- For checks that need command parity, use subprocess only at the edge and cap
  output snippets.
- `--strict` should upgrade advisory failures to exit 1, but the JSON should
  still mark their original severity as advisory.

### Acceptance

- `bin/swarm selftest --json` exits 0 for a healthy fixture.
- `bin/swarm selftest --strict --json` exits 1 when an advisory check fails.
- Tests cover no-Beads, bad preset, invalid permission fragment, stale
  active-run, and provider doctor warning paths.
- The TUI can consume the JSON without parsing human text.

## Phase 2 - Hook Runtime Profiles

### Objective

Make current and future hooks controllable through profile and per-hook disable
flags before adding more hook behavior.

### Recommended Surface

Environment variables:

```bash
SWARM_HOOK_PROFILE=minimal|standard|strict
SWARM_DISABLED_HOOKS=precompact
```

Profiles:

- `minimal`: only lifecycle-critical checkpointing.
- `standard`: safe lightweight observations and checkpointing.
- `strict`: security/audit warnings may block when deterministic.

### Files

| File | Change |
| --- | --- |
| `hooks/run-with-profile.sh` | New shell wrapper that enforces profile and disabled-hook IDs. |
| `hooks/precompact.sh` | No behavior change; route through wrapper from `hooks/hooks.json`. |
| `hooks/hooks.json` | Migrate existing direct PreCompact command to wrapper with hook ID and profile. |
| `py/swarm_do/pipeline/tests/test_hooks_profile.py` or shell fixture tests | Validate profile gating and disabled hooks. |
| `README.md` | Document variables after implementation. |

### Hook ID Registry

Hook IDs are passed as the first positional argument to
`hooks/run-with-profile.sh`. The same value is matched (case-insensitive)
against `SWARM_DISABLED_HOOKS`. Claude Code's hook config schema does not
propagate extra metadata fields to invoked commands, so the ID lives at the
call site (the `command` string in `hooks/hooks.json`), not as a separate
JSON field.

Hook profiles form an ordered set `minimal < standard < strict`. Each hook
declares a minimum profile in the registry below; the hook runs when
`current_profile >= min_profile`. The mapping is hardcoded as a small `case`
block in `run-with-profile.sh` until the matrix grows large enough to
justify a manifest file.

| ID | Hook | Min profile | `hooks.json` command |
| --- | --- | --- | --- |
| `precompact` | `hooks/precompact.sh` | `minimal` | `${CLAUDE_PLUGIN_ROOT}/hooks/run-with-profile.sh precompact ${CLAUDE_PLUGIN_ROOT}/hooks/precompact.sh` |

Any new hook must add a row to this table and update the wrapper's profile
map in the same PR that ships it.

### Implementation Notes

- Wrapper invocation: `run-with-profile.sh <hook_id> <command> [args...]`.
  After gating, the wrapper `exec`s the command so stdin/stdout/stderr and
  exit code pass through byte-for-byte.
- The wrapper preserves stdin and stdout pass-through semantics. PreCompact
  hooks receive a JSON document on stdin from Claude Code; the wrapper must
  use unbuffered byte forwarding (`exec` after profile gating) and must not
  line-buffer or transform the payload.
- Skip semantics: when a hook is gated out (disabled by `SWARM_DISABLED_HOOKS`
  or below the active profile), the wrapper drains stdin to EOF and exits 0.
  Draining prevents SIGPIPE on the parent (Claude Code) which otherwise sees
  a broken pipe when it tries to finish writing the hook payload.
- Invalid profile values fall back to `standard` and log a warning to stderr,
  not fail the hook. Unknown hook IDs (not in the registry's profile map)
  fail closed: exit non-zero with a stderr message, so a typo at the call
  site is loud rather than silent.
- Disabled hook matching is case-insensitive and comma-separated. Whitespace
  around IDs is trimmed.
- Wrapper stays shell-only unless the hook matrix grows enough to justify a
  Python helper.
- Do not add new hooks in the same PR except tests for the existing
  precompact hook. Land the control plane first.

### Acceptance

- Existing PreCompact checkpoint behavior remains unchanged in `standard`
  (i.e. `precompact.sh`'s existing handling of missing `CLAUDE_PLUGIN_DATA`
  and missing `active-run.json` continues to exit 0 as today; the wrapper
  does not duplicate those checks).
- `SWARM_HOOK_PROFILE=minimal` still allows precompact.
- `SWARM_DISABLED_HOOKS=precompact` skips precompact without error and
  drains the stdin payload Claude Code sends to PreCompact.
- Wrapper tests cover: invalid profile (falls back to `standard`, warns on
  stderr), unknown hook ID (fails closed), case-insensitive disabled match,
  comma-separated `SWARM_DISABLED_HOOKS` parsing with surrounding whitespace,
  and stdin drain on skip.

## Phase 3 - Security And Config Audit

### Objective

Add a static local scanner for SwarmDaddy and target-repo harness risks. This
should complement, not replace, role permission fragments.

### Recommended Surface

```bash
bin/swarm security audit [--scope plugin|repo|all] [--json] [--strict]
```

Verb-group form is used because at least one sibling verb is anticipated
(`bin/swarm security explain <finding-id>` for remediation detail). If no
sibling verb has shipped within two phases of this command, collapse to the
flat form `bin/swarm security-audit`.

Initial checks (definitions are normative — fixtures must match them):

- Permission fragment drift:
  - **Role registered but missing fragment.** Role appears in the role
    registry but has no `roles/<role>/permissions.json` (or fragment of the
    canonical name; implementer confirms the exact filename in the registry
    loader).
  - **Fragment role not registered.** A `roles/*/permissions.*` fragment
    exists for a role name not present in the registry.
  - **Allow/deny conflict.** The same exact pattern string appears in both
    `allow` and `deny` for the same role. Pattern equivalence is literal
    (no glob expansion); a separate ticket can extend this to scope-overlap
    detection later.
  - **Broad `Bash` or unscoped write in a read-only role.** "Read-only role"
    is determined by the role registry's read-only flag (the implementer
    confirms the exact field name in `py/swarm_do/.../roles.py`); "broad
    Bash" matches the literal patterns `Bash(*)`, `Bash(**)`, and any
    `Bash(...)` whose argument starts with `*`.
- Hook config risks:
  - **Unset plugin path without fallback.** Hook `command` references
    `${CLAUDE_PLUGIN_ROOT}` or `${CLAUDE_PLUGIN_DATA}` without a `:-`
    fallback or surrounding script that validates the value.
  - **Shell interpolation of hook input.** Hook `command` contains `$(...)`,
    backticks, or `eval` patterns whose operands include hook payload fields.
  - **Hook missing profile wrapper (gated on Phase 2).** Hook `command` does
    not start with `${CLAUDE_PLUGIN_ROOT}/hooks/run-with-profile.sh `.
- Provider-review safety:
  - **Provider not read-only eligible.** Configured review provider lacks
    the read-only eligibility marker in the providers registry.
  - **Secret-shaped argv/manifest field.** Field value matches the canonical
    redaction patterns (see Phase 4 — Redaction). Findings include the
    redacted preview, never the raw value.
  - **Raw sidecar retention warning.** Provider config retains raw sidecars
    beyond the policy in `docs/adr/0001-telemetry-retention.md`.
- Target repo hygiene:
  - **`.claude/settings*.json` broad permissions.** `permissions.allow`
    contains `Bash(*)`, `Bash(**)`, or `Write(**)`-style unscoped entries.
  - **`.mcp.json` shell launcher.** `command` is one of `bash`, `sh`, `zsh`,
    `pwsh`, or has `args` starting with `npx -y`, `pipx run`, `uvx`, or
    contains a piped `curl|sh`/`wget|sh` shape.
  - **Common secret file not ignored.** Any of `.env`, `.env.*` (excluding
    `.env.example` and `.env.sample`), `id_rsa`, `id_ed25519`, `*.pem`,
    `*.key`, `credentials.json`, or `.aws/credentials` exists in the working
    tree without a matching `.gitignore` entry.

Explicitly out of scope for the first security audit:

- CI workflow scanning (`pull_request_target`, `workflow_run`, checkout of PR
  heads). It may be useful later, but it is noisy and not central to
  SwarmDaddy's local plugin runtime.

### Files

| File | Change |
| --- | --- |
| `py/swarm_do/pipeline/security_audit.py` | New static scanner and result formatting. |
| `py/swarm_do/pipeline/cli.py` | Add `security audit` subcommand group. |
| `py/swarm_do/pipeline/tests/test_security_audit.py` | Fixtures for permission, hook, MCP, provider, and target-repo config findings. |
| `README.md` | Document command after implementation. |

### Severity Map

Findings ship with one of four severities. Critical findings fail by default.
`--strict` also fails on high findings. Medium/low remain advisory regardless
of `--strict`.

| Finding | Default severity |
| --- | --- |
| Role registered, fragment missing | high |
| Fragment role not registered | medium |
| Allow/deny conflict in same role | high |
| `Bash(*)` or unscoped write in read-only role | critical |
| Hook missing profile wrapper (after Phase 2) | high |
| Hook command shell-interpolates unscoped input | critical |
| Provider not read-only eligible | high |
| Secret-shaped argv/manifest field (post-redaction) | critical |
| Project `.claude/settings.json` broad permission | medium |
| Project `.mcp.json` shell launcher / `npx -y` | high |
| Common secret file not gitignored | low |

These severities are fixture-backed until there is a real persisted consumer.
Do not add a `schemas/security_audit.schema.json` file just to make the surface
look formal; fixtures plus tests are enough for an invoke-only command.

### Implementation Notes

- Stay dependency-free. Use JSON parsing and small YAML-like text checks
  where needed; do not add a full workflow YAML parser unless false
  positives become painful.
- Redact secret-shaped values before adding them to findings. Canonical
  patterns are defined in Phase 4 — Redaction. Because Phase 3 ships before
  Phase 4 in rollout, the Phase 3 PR creates the shared module
  `py/swarm_do/util/redaction.py` (or equivalent) and Phase 4 imports the
  same module rather than duplicating regexes.
- Treat repo-local scans as advisory by default (medium/low). A user may
  have intentionally broad local settings.
- Default mode fails on critical findings. `--strict` fails on high and
  critical findings.
- Scope semantics:
  - `--scope plugin`: `scope_root` is the SwarmDaddy plugin root
    (`$CLAUDE_PLUGIN_ROOT`, or the resolved repo root when running from a
    development clone of `swarm-do/`).
  - `--scope repo`: `scope_root` is the working directory's git toplevel
    (`git rev-parse --show-toplevel`); error if not in a git repo.
  - `--scope all` (default): both scope roots are scanned independently and
    the findings are merged into one result set, each finding tagged with
    its originating scope.
- Path containment is enforced at every read: resolve the candidate via
  `Path(p).resolve(strict=False)` and reject unless
  `resolved.is_relative_to(scope_root.resolve())`. Symlink escapes are
  rejected, not followed.

### Acceptance

- Finds a broad read-only role permission fixture.
- Finds a hook command fixture with unsafe interpolation.
- Finds a project `.mcp.json` fixture using shell/npx risk patterns.
- Redacts secret-shaped fixture values.
- Produces stable JSON for TUI and dogfood consumption.

## Phase 4 - Sanitized Activity Telemetry

### Objective

Capture enough tool/file activity to explain run efficiency and safety without
persisting raw prompts, raw command output, or secrets. This phase is limited
to post-run extraction and reporting over existing `observations.jsonl` rows.

### Current Architecture

Activity data already belongs to the observation ledger:

- `py/swarm_do/telemetry/run_observations.py` derives tool buckets, repeated
  reads, first-edit/test positions, output-byte summaries, token usage, and
  markers from backend output streams after a run.
- `schemas/telemetry/observations.v2.schema.json` is the shipped schema for
  those rows.
- `py/swarm_do/telemetry/subcommands/experiment_report.py` joins
  `runs.jsonl`, `observations.jsonl`, and `run_events.jsonl`.
- `run_events.jsonl` remains the orchestration audit log for checkpoint,
  prepare, phase, handoff, and worktree events.

### Observation Shape

Extend or preserve rows shaped like:

```json
{
  "ts": "2026-04-29T18:40:12.483Z",
  "run_id": "01KQD670S0SGHNE54D0TA7174K",
  "phase_id": "phase-1",
  "event_type": "backend_output_analyzed",
  "source": "swarm-run-exit",
  "tool": null,
  "file_paths": [],
  "details": {
    "role": "agent-writer",
    "stage_id": "writer",
    "unit_id": "unit-parser",
    "tool_call_count": 12,
    "tool_category_counts": {
      "read": 3,
      "search": 1,
      "shell-rg": 2,
      "shell-bd": 0,
      "shell-git": 1,
      "shell-test": 1,
      "edit": 2,
      "web": 0,
      "skill": 0
    },
    "repeated_read_histogram": [
      {"file_path": "py/swarm_do/pipeline/cli.py", "count": 2}
    ],
    "first_edit_tool_call_index": 7,
    "first_test_tool_call_index": 11
  },
  "schema_ok": true
}
```

### Schema Migration

Activity fields extend `schemas/telemetry/observations.v2.schema.json`, not
`schemas/telemetry/run_events.schema.json`. Strategy:

- Keep `run_events` limited to orchestration lifecycle events.
- Extend `observations.v2` details for any missing aggregate fields rather than
  adding per-tool rows to `run_events`.
- Keep `docs/examples/activity-observation.jsonl` and
  `docs/adr/0007-selftest-and-observability-contracts.md` aligned with the
  observation ledger. If the row shape changes materially, amend or supersede
  ADR 0007 rather than silently diverging from it.
- `experiment_report` treats absent categorization as unknown and continues to
  render the report.
- Phase 4 lands as categorization and reporting improvements on existing
  observations only. No `PostToolUse` hook is part of this plan.

### Files

| File | Change |
| --- | --- |
| `schemas/telemetry/observations.v2.schema.json` | Extend details object only for missing aggregate fields. |
| `py/swarm_do/telemetry/run_observations.py` | Existing categorization/repeated-read extractor; extend here first. |
| `py/swarm_do/telemetry/subcommands/experiment_report.py` | Consume categories for scorecards; default missing to `"unknown"`. |
| `docs/examples/activity-observation.jsonl` | Maintain fixture for `observations.v2` row shape. |
| `docs/adr/0007-selftest-and-observability-contracts.md` | Maintain or supersede activity-observation contract. |
| `py/swarm_do/telemetry/tests/test_run_observations.py` | Add redaction and categorization fixtures. |
| `py/swarm_do/telemetry/tests/test_experiment_report.py` | Add repeated-read, first-test-position, and missing-category fixture coverage. |

### Implementation Notes

- Collect from existing SwarmDaddy-owned backend output. Do not add a Claude
  `PostToolUse` hook in this phase.
- Schema posture: the default expectation is reporting-only. The Phase 4 PR
  must list every new field added to `observations.v2` (if any) in its
  description; silent schema extension is not allowed. If no new fields are
  needed, the PR touches only the report consumers and tests.
- Redaction (canonical — also referenced by Phase 3). The shared module
  `py/swarm_do/util/redaction.py` (created by Phase 3) is the single home
  for these patterns; Phase 4 imports rather than duplicates. Redact at the
  collection boundary, before any row is serialized to disk:
  - **GitHub tokens.** `gh[pousr]_[A-Za-z0-9_]{20,}` and
    `github_pat_[A-Za-z0-9_]{20,}`.
  - **OpenAI-style keys.** `sk-[A-Za-z0-9-_]{20,}` and
    `sk-proj-[A-Za-z0-9-_]{20,}`.
  - **Anthropic-style keys.** `sk-ant-[A-Za-z0-9-_]{20,}`.
  - **AWS access keys.** `(AKIA|ASIA)[A-Z0-9]{16}` and the matching
    secret-access-key shape (40 base64-ish characters following an
    `aws_secret_access_key`/`AWS_SECRET_ACCESS_KEY` marker).
  - **Generic credential markers.** Case-insensitive matches for
    `password=`, `passwd=`, `token=`, `api[_-]?key=`, `secret=`, and the
    HTTP header `Authorization:` followed by a value. The value (not the
    marker) is replaced with `<redacted>`.
  - **JWT-shaped tokens.** Three base64url segments separated by dots, each
    ≥ 16 chars, with a `eyJ`-prefixed first segment.
  Replacement string is the literal `<redacted>`. Length-preserving masking
  is not required; reports show counts and the redaction marker, not
  partial reveals.
- Store summaries and relative paths, not full command output.
- If a later proposal reintroduces hook capture, it must first identify the
  missing metric, cap stdin reads, join through
  `${CLAUDE_PLUGIN_DATA}/active-run.json`, and no-op without an active run.

### Acceptance

- Experiment report can show tool calls by category per role/work unit from
  `observations.jsonl`.
- Repeated source reads by file can be computed from fixture data.
- Secret-shaped fixture input is redacted before any observation row is
  serialized.
- No hot-path hook is added.

## Phase 5 - Work-Unit Operator Snapshots

### Objective

Make each work unit legible on disk for humans, resume tooling, and the TUI.
ECC's useful pattern is not tmux itself; it is the simple task/status/handoff
artifact set.

### Current Recommendation

Defer implementation until there is concrete operator pain that the existing
structured surfaces do not solve. The value is real but ergonomic: faster human
inspection, easier handoff review, and simpler copy/paste into recovery notes.
It does not make orchestration more correct. That means the design must be
cheap to remove, cheap to regenerate, and impossible to confuse with state.

### Current Architecture

Canonical unit state already exists in plugin data:

```text
${CLAUDE_PLUGIN_DATA}/runs/<run_id>/unit_sessions.v1.json
${CLAUDE_PLUGIN_DATA}/worktrees/<run_id>/manifest.json
${CLAUDE_PLUGIN_DATA}/worktrees/<run_id>/units/<phase_id>/<unit_id>/repo/
${CLAUDE_PLUGIN_DATA}/telemetry/run_events.jsonl
```

Post-writer reports, spec-review verdicts, merge state, worktree paths, and
cleanup state are recorded in `unit_sessions.v1.json` and related manifests.
Markdown snapshots must therefore be generated mirrors, not authority.

### Derived Export Layout

Use plugin data for optional operator-facing exports:

```text
${CLAUDE_PLUGIN_DATA}/runs/<run_id>/unit_snapshots/<phase_id>/<unit_id>/
  task.md
  status.md
  handoff.md
```

No per-unit `events.jsonl` is needed unless a later design explains why
`run_events.jsonl` plus `unit_sessions.v1.json` is insufficient.

### Authority Contract

The export has one rule: Markdown is never true. It only describes truth held
elsewhere.

- `unit_sessions.v1.json` owns unit status, post-writer status, spec-review
  status, merge state, worktree paths, cleanup state, and timestamps.
- Prepared work-unit sidecars own unit task definition, allowed files, blocked
  files, validation commands, dependencies, and expected results.
- Post-writer and spec-review reports own evidence, validation outcomes,
  changed files, and gate reasons.
- `run_events.jsonl` owns append-only orchestration audit events.
- Markdown files own no fields. A missing, stale, or deleted snapshot must not
  change any command behavior.

To make that hard to violate:

- Never parse Markdown snapshots in `resume`, TUI, recovery commands, or tests
  except tests that verify export text.
- Include a generated header in every Markdown file:
  `Generated view. Do not edit; canonical state is <path>.`
- Include canonical source paths and source mtimes/hashes in the snapshot body
  so stale exports are obvious to humans.
- Provide one regeneration entry point, for example
  `bin/swarm work-units snapshots <run-id> [--apply]`, instead of writing from
  many call sites by default.
- Prefer on-demand generation first. Auto-generation after every unit-session
  mutation may be added later only if the operator need is proven.

### Files

| File | Change |
| --- | --- |
| `py/swarm_do/pipeline/unit_snapshots.py` | New derived-export renderer and atomic Markdown writer. |
| `py/swarm_do/pipeline/unit_sessions.py` | Source canonical unit status and paths; no Markdown authority. |
| `py/swarm_do/pipeline/cli.py` | Add an explicit snapshot export/regenerate command if implementation proceeds. |
| `py/swarm_do/pipeline/post_writer.py` | Provide bounded report summaries consumed by snapshot renderer. |
| `py/swarm_do/pipeline/resume.py` | Include latest snapshot paths only as optional operator hints. |
| `py/swarm_do/tui/state.py` | Prefer structured `unit_sessions.v1.json`; do not parse Markdown snapshots. |
| `py/swarm_do/pipeline/tests/test_unit_snapshots.py` | Add derived-export fixtures and disabled-mode coverage. |

### Atomicity And Concurrency

- All Markdown status writes use tmp + `os.replace` in the same directory. No
  partial files are visible to readers.
- Snapshot generation reads canonical state under the existing
  `unit_sessions.v1.lock` when unit-session consistency matters, then writes
  derived Markdown after releasing the lock. It never mutates canonical state.
- `run_events.jsonl` remains the append-only audit ledger. Readers tolerate a
  truncated final line as they do today.
- Crash recovery: `unit_sessions.v1.json`, prepared work-unit sidecars, and
  post-writer/spec-review reports are authoritative. Missing or stale Markdown
  exports are regenerated from structured state.

### Implementation Notes

- Do not make Markdown snapshots authoritative over JSON state. They are
  operator-facing mirrors over `unit_sessions.v1.json`.
- Status is generated from structured unit-session fields, especially
  `writer_status`, `post_writer_status`, `spec_review_status`, and
  `merge_state`. Snapshot labels may normalize those into operator-facing
  states such as `pending`, `running`, `needs_context`, `handoff_requested`,
  `approved`, `merged`, and `failed`, but the labels must be derived rather
  than stored as a second status source.
- Handoff includes only bounded summaries, changed file paths, validation
  commands/results, remaining risks, and next action.
- Include source artifact paths in `task.md`, not copied phase text when the
  source is large.
- Snapshot exports are allowed to be absent by default. Commands must degrade
  to structured-state behavior when exports are missing.

### Acceptance

- Prepared work-unit fixture writes stable `task.md` and initial `status.md`
  from prepared sidecars plus `unit_sessions.v1.json`.
- Writer completion updates `handoff.md` and `status.md` atomically from
  post-writer/spec-review structured state.
- Resume JSON includes latest snapshot paths only when exports exist.
- TUI state tests display unit status from structured data, with snapshots
  absent.
- A test deletes all snapshot files and proves resume/TUI/worktree status
  behavior is unchanged.
- A test edits `status.md` by hand and proves no command reads the edited
  Markdown as authority.

## Cut Scope And Reconsideration Triggers

The following ideas are deliberately out of this plan. They can return only
with a short proposal that names the missing capability and expected consumer.

| Cut item | Why cut now | Reconsider when |
| --- | --- | --- |
| `PostToolUse` activity hook | Existing post-run extraction covers current reporting needs without hot-path latency or privacy risk. | A specific metric cannot be recovered from backend output and materially changes a decision. |
| Codex emitter/doctor | Codex routing and overlays already exist; emitter files add another sync surface. | Operators repeatedly need project-local Codex artifacts and the generated content can be derived automatically from role specs. |
| `selftest`/`security audit` JSON schemas | Fixtures and tests are enough for invoke-only commands. | A TUI, CI gate, or persisted artifact validates the JSON by schema. |
| CI workflow scanner | Noisy and not central to SwarmDaddy local runtime. | Security audit grows a dedicated repo-hardening profile with clear false-positive handling. |

## Rollout Order

1. **Foundation follow-through:** Phase 2 hook profiles, because Phase 1
   selftest is already shipped. See Foundation Follow-Through section above.
2. Phase 3 narrow security audit.
3. Phase 4 activity telemetry — improve categorization/reporting on existing
   `observations.jsonl` rows.
4. Stop and reassess.
5. Phase 5 derived unit snapshot exports only if concrete operator pain remains
   after TUI/worktree/status surfaces are exercised.

This order matters. Selftest already gives SwarmDaddy a health baseline, but
Phase 2 is still needed before any hook behavior becomes more configurable.
Security audit and activity telemetry then improve operator confidence without
surprising every install. Markdown exports are intentionally not part of the
core guardrail sequence.

## Test Strategy

Minimum test commands for each implementation PR:

```bash
PYTHONPATH=py python3 -m unittest discover -s py -p 'test_*.py'
PYTHONPATH=py python3 -m swarm_do.telemetry.gen readme-section --check
PYTHONPATH=py python3 -m swarm_do.telemetry.gen docs --check
```

Additional targeted checks by phase:

- Phase 1: `bin/swarm selftest --json` against temp plugin data fixtures.
- Phase 2: shell/hook tests with profile and disabled-hook env vars.
- Phase 3: security audit fixtures with redacted secret-shaped values.
- Phase 4: observation fixture reports for repeated reads and tool categories.
- Phase 5: unit-session-derived snapshot tests plus resume tests with optional
  snapshot paths.

## Definition Of Done (per phase)

A phase is not merged until all of the following pass:

- `cd swarm-do && PYTHONPATH=py python3 -m unittest discover -s py -p 'test_*.py'`
- `cd swarm-do && PYTHONPATH=py python3 -m swarm_do.telemetry.gen readme-section --check`
- `cd swarm-do && PYTHONPATH=py python3 -m swarm_do.telemetry.gen docs --check`
- All phase-specific Acceptance criteria above
- README and CLI help updated for any new command surface
- One dogfood pipeline run completes against a real plan with the new
  feature exercised
- Rollback lever from the table below is documented in the README and
  exercised in at least one test

## Rollback And Disable Levers

Every phase ships with an off switch. If a feature misbehaves in the field,
operators turn it off without redeploying the plugin.

| Phase | Disable mechanism |
| --- | --- |
| 1 selftest | Invoke-only command. No implicit caller in Foundation; if Phase 5 wires a TUI auto-run, it must respect `SWARM_SELFTEST_AUTO=off`. |
| 2 hook profiles | `SWARM_HOOK_PROFILE=minimal` or `SWARM_DISABLED_HOOKS=<id>` |
| 3 security audit | Invoke-only. Add `SWARM_SECURITY_AUDIT_AUTO=off` for any caller (TUI, dogfood) that auto-runs it. |
| 4 categorization | Data-driven observations; absent categories degrade reports gracefully — no env flag required. |
| 5 unit snapshot exports | `SWARM_UNIT_SNAPSHOT_EXPORTS=off` if auto-generation ever ships; on-demand export can be disabled by not invoking it. Structured JSON state remains authoritative regardless. |

## Risks

- Selftest can become a junk drawer. Keep it a registry of existing checks plus
  small glue, not a second implementation of every validator.
- Hooks can surprise users. Land profile controls first, keep defaults small,
  and document every blocking condition.
- Security scanners can create false positives. Prefer clear remediation text
  and strict-mode opt-in.
- Activity telemetry can leak sensitive data if raw payloads are stored. Redact
  before writing and cap all snippets.
- Activity telemetry can drift if some reports read `run_events` while others
  read `observations`. Keep the ledger boundary explicit in schemas, fixtures,
  and ADR text.
- Markdown snapshot exports can confuse authority. Keep them generated,
  disposable, absent-safe, and unread by control-plane commands.

## Open Questions

None blocking. All forks present at the design stage are recorded in the
Resolved Decisions section above, including:

- Hook ID propagation mechanism — passed as the wrapper's first positional
  argument; not a JSON field. Profile ordering is `minimal < standard <
  strict` with each hook declaring a minimum.
- "Allow/deny conflict", "broad Bash", "shell launcher", and "common secret
  file" definitions — pinned to literal patterns/lists in Phase 3.
- Canonical redaction patterns — defined in Phase 4 and referenced from
  Phase 3 so the two phases cannot drift.
- `security audit` scope semantics — `plugin` vs `repo` vs `all` resolve to
  explicit roots with path containment.

New questions raised during implementation should be answered in the
implementing PR or appended here with their resolution.

## Final Recommendation

Land Phase 2 hook profiles next. `selftest` already gives SwarmDaddy a single
health signal; hook profiles make later observability and security hooks safe
to adopt. The old Foundation epic split has already happened, so the practical
goal is to close the remaining reversible-disable gap before adding new hook
behavior.

After Phase 2 dogfoods cleanly for at least one full pipeline run, ship the
narrow Phase 3 security audit, then Phase 4 observation/reporting improvements.
Stop there and reassess. Phase 5 Markdown exports stay deferred until the
operator pain is concrete enough to justify an export layer, and even then they
must remain disposable generated views over structured state.
