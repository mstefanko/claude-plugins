# ECC Pattern Adoption Plan

Date: 2026-04-28
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

## Decision Summary

| Idea from ECC | Decision | Priority | Why |
| --- | --- | --- | --- |
| Deterministic harness audit | Adopt as `bin/swarm selftest` | P0 | Existing checks are strong but scattered. A single health report helps users and dogfood runs. |
| Hook runtime profile and per-hook disable controls | Adopt in small SwarmDaddy-specific form | P0 | Lets us add safety hooks without making every install pay every cost. |
| Security/config scanner | Adopt as local static audit, no network dependency | P1 | Complements role permission contracts by scanning plugin and harness configuration. |
| Sanitized tool/file activity telemetry | Adopt incrementally | P1 | Helps explain token/tool churn and repeated reads without storing sensitive raw payloads. |
| Worktree operator snapshots | Adopt for work-unit status/handoff files | P1 | Makes live and resumed unit state more legible to humans and the TUI. |
| Codex-native project surface | Adopt minimally | P2 | Useful for dogfooding and provider review, but should not install MCPs or change user Codex config automatically. |
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
  has one mode; a verb group (`bin/swarm security audit`, `bin/swarm codex
  emit`) when two or more sibling verbs are planned. Decide at design time,
  not after the second verb appears.
- Every shipped feature must have an explicit off switch documented in the
  rollback table. "Don't invoke it" is acceptable only for invoke-only
  commands; anything that runs implicitly (hooks, auto-checks) needs an env
  var or profile disable.

## Resolved Decisions

These were Open Questions in earlier drafts. Locking them now so phases can
be executed without further design rounds.

- **Selftest TUI exposure.** Phase 1 ships the `bin/swarm selftest` command
  only. TUI binding is deferred to Phase 5, which already touches
  `tui/state.py` and consumes the same JSON contract alongside unit
  snapshots. Rationale: do not couple Foundation to TUI changes.
- **Activity telemetry source.** Phase 4 starts with categorization of
  existing run events only. The `PostToolUse` hook is a Phase 4 follow-up
  PR, gated by `SWARM_HOOK_PROFILE=standard|strict` after Phase 2 controls
  exist. Rationale: ship categorization without taking a hot-path hook
  dependency in the same change.
- **Unit snapshot retention.** Snapshots follow the policy in
  `docs/adr/0001-telemetry-retention.md` — default 30-day retention with
  operator override. Rationale: avoid unbounded plugin-data growth and keep
  one retention story for the project.
- **Codex file location.** Reference content lives at `docs/codex/`. The
  `bin/swarm codex emit` command writes generated copies to an
  operator-chosen path (default `.codex/swarmdaddy/`). Nothing is auto-
  discovered. Rationale: decouple committed reference from emitted artifacts
  and prevent accidental Codex auto-load.

## Non-Goals

- No adoption of ECC's full skill, rule, command, or agent catalog.
- No generic installer that writes into `~/.claude`, `~/.codex`, Cursor, or
  OpenCode directories.
- No new runtime dependency on Node.js for the Python pipeline. Hook helpers can
  stay shell/Python unless a specific cross-platform need appears.
- No default-on MCP bundle.
- No dashboard replacement for the Textual TUI.

## Phase 0 - Baseline Inventory And Contracts

### Objective

Record current health signals and formalize the output contracts before adding
new command surfaces.

### Implementation

1. Create fixture-backed examples for the target outputs:
   - `docs/examples/selftest.ok.json`
   - `docs/examples/security-audit.warning.json`
   - `docs/examples/activity-observation.jsonl`
2. Add a short ADR or section in this plan's implementation PR describing:
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

### Acceptance

- There is a written schema-level contract for each new output before runtime
  code lands.
- No existing command behavior changes in this phase.

## Foundation Epic (Phases 1 + 2)

Phases 1 and 2 ship as a single epic. Reasoning: shipping `selftest` without
hook profile controls means later hooks (Phase 4) must be added without a
reversible disable path; shipping hook profiles before there is a health
command leaves operators without a single-screen readiness check. The pair
is mutually load-bearing.

Acceptance for the epic: every Phase 1 and Phase 2 acceptance criterion
passes, the rollback levers in both phases work end-to-end, and one full
dogfood pipeline run completes with `bin/swarm selftest` invoked at start
and `SWARM_HOOK_PROFILE=standard` set throughout.

## Phase 1 - `bin/swarm selftest`

### Objective

Add one deterministic health command that answers: "Is this SwarmDaddy install
and target repo ready to run?"

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
| `py/swarm_do/pipeline/selftest.py` | New module with check registry, result dataclasses, JSON/text formatting. |
| `py/swarm_do/pipeline/cli.py` | Add `selftest` subcommand and argument parsing. |
| `py/swarm_do/pipeline/tests/test_selftest.py` | Fixture-backed tests for pass, hard fail, advisory warning, strict mode. |
| `schemas/selftest.schema.json` | Optional if JSON output becomes persisted or consumed by TUI. |
| `README.md` | Add one command row after implementation. |
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
SWARM_DISABLED_HOOKS=precompact,activity-observe
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
| `hooks/hooks.json` | Wrap existing PreCompact command with hook ID and profile. |
| `py/swarm_do/pipeline/tests/test_hooks_profile.py` or shell fixture tests | Validate profile gating and disabled hooks. |
| `README.md` | Document variables after implementation. |

### Hook ID Registry

Hook IDs are declared as the `id` field on each hook entry in
`hooks/hooks.json`. The same value is matched (case-insensitive) against
`SWARM_DISABLED_HOOKS`. Initial registry:

| ID | Hook | Default profile gate |
| --- | --- | --- |
| `precompact` | `hooks/precompact.sh` | minimal+ |
| `activity-observe` | (Phase 4) | standard+ |

Any new hook must add a row to this table in the same PR that ships it.

### Implementation Notes

- The wrapper preserves stdin and stdout pass-through semantics. PreCompact
  hooks receive a JSON document on stdin from Claude Code; the wrapper must
  use unbuffered byte forwarding (`exec` after profile gating) and must not
  line-buffer or transform the payload.
- Invalid profile values fall back to `standard` and log a warning to stderr,
  not fail the hook.
- Disabled hook matching is case-insensitive and comma-separated. Whitespace
  around IDs is trimmed.
- Wrapper stays shell-only unless the hook matrix grows enough to justify a
  Python helper.
- Do not add new hooks in the same PR except tests for the existing
  precompact hook. Land the control plane first.

### Acceptance

- Existing PreCompact checkpoint behavior remains unchanged in `standard`.
- `SWARM_HOOK_PROFILE=minimal` still allows precompact.
- `SWARM_DISABLED_HOOKS=precompact` skips precompact without error.
- Hook tests cover missing `CLAUDE_PLUGIN_DATA`, missing `active-run.json`,
  invalid profile, and disabled ID.

## Phase 3 - Security And Config Audit

### Objective

Add a static local scanner for SwarmDaddy and target-repo harness risks. This
should complement, not replace, role permission fragments.

### Recommended Surface

```bash
bin/swarm security audit [--scope plugin|repo|all] [--json] [--strict]
```

Initial checks:

- Permission fragment drift:
  - role registered but missing fragment
  - fragment role not registered
  - explicit allow/deny conflict
  - broad `Bash(*)` or unscoped write access in read-only roles
- Hook config risks:
  - hook command references unset plugin paths without fallback
  - shell interpolation of hook input
  - hook missing profile wrapper after Phase 2
- Provider-review safety:
  - configured provider not read-only eligible
  - argv or manifest fields that look secret-shaped
  - raw sidecar retention warnings
- Target repo hygiene:
  - `.claude/settings*.json` broad permissions
  - project `.mcp.json` command servers that use `npx -y` or shell launchers
  - common secret files not ignored
- CI workflow risks if `.github/workflows` exists:
  - privileged checkout of untrusted PR head in `pull_request_target` or
    `workflow_run`

### Files

| File | Change |
| --- | --- |
| `py/swarm_do/pipeline/security_audit.py` | New static scanner and result formatting. |
| `py/swarm_do/pipeline/cli.py` | Add `security audit` subcommand group. |
| `py/swarm_do/pipeline/tests/test_security_audit.py` | Fixtures for permission, hook, MCP, provider, and workflow findings. |
| `schemas/security_audit.schema.json` | Optional if JSON output is persisted. |
| `README.md` | Document command after implementation. |

### Severity Map

Findings ship with one of four severities. `--strict` upgrades high/critical
to exit 1; medium/low remain advisory regardless of `--strict`.

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
| `pull_request_target` checkout of PR head | critical |

These severities ship in `schemas/security_audit.schema.json` once the
fixtures stabilize. Severity tuning during implementation is allowed; the
table above is the merge target.

### Implementation Notes

- Stay dependency-free. Use JSON parsing and small YAML-like text checks
  where needed; do not add a full workflow YAML parser unless false
  positives become painful.
- Redact secret-shaped values before adding them to findings.
- Treat repo-local scans as advisory by default (medium/low). A user may
  have intentionally broad local settings.
- `--strict` fails on high/critical findings only.
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
persisting raw prompts, raw command output, or secrets.

### Event Shape

Add or extend observation rows with:

```json
{
  "schema_version": 2,
  "run_id": "run-...",
  "phase_id": "phase-1",
  "work_unit_id": "unit-parser",
  "source": "claude-hook",
  "tool_category": "read|search|shell|edit|test|git|provider|unknown",
  "tool_name": "Read",
  "file_paths": ["py/swarm_do/pipeline/cli.py"],
  "action": "read|modify|create|delete|execute",
  "input_summary": "Read py/swarm_do/pipeline/cli.py",
  "output_summary": "120 lines",
  "redaction_applied": true
}
```

### Schema Migration

Activity fields extend the existing
`schemas/telemetry/run_events.schema.json` rather than introducing a
parallel `observations.v2` stream. Strategy:

- Add `tool_category`, `file_paths`, `action`, `redaction_applied`,
  `input_summary`, `output_summary` as optional fields on the existing
  event schema.
- Bump the schema's `version` field. Old readers ignoring unknown fields
  keep working; new readers tolerate missing fields by defaulting
  `tool_category` to `"unknown"` and `file_paths` to `[]`.
- `experiment_report` treats absent categorization as `"unknown"` and
  continues to render the report. No mixed-stream logic, no dual files.
- Phase 4 lands in two PRs: (a) categorization on existing events, then
  (b) the optional `PostToolUse` hook with `id: activity-observe`. PR (b)
  cannot land until Phase 2 ships.

### Files

| File | Change |
| --- | --- |
| `schemas/telemetry/run_events.schema.json` | Extend with optional activity fields; bump version. |
| `py/swarm_do/telemetry/run_observations.py` | Add categorization and repeated-read support. |
| `py/swarm_do/telemetry/subcommands/experiment_report.py` | Consume categories for scorecards; default missing to `"unknown"`. |
| `hooks/activity_observe.py` or `hooks/activity-observe.sh` | Optional Phase 4b hook gated on `standard+` profile. |
| `py/swarm_do/telemetry/tests/test_run_observations.py` | Add redaction and categorization fixtures. |
| `py/swarm_do/telemetry/tests/test_experiment_report.py` | Add repeated-read, first-test-position, and missing-category fixture coverage. |

### Implementation Notes

- Prefer collecting from existing SwarmDaddy-owned run events first. Add a
  Claude hook only for data not otherwise visible.
- If a hook is needed, make it `standard` or `strict` profile only and cap stdin
  reads at a small size.
- Redact before write:
  - GitHub tokens
  - OpenAI/Anthropic-style API keys
  - AWS access keys
  - generic `password=`, `token=`, `api_key=`, `Authorization:` values
- Store summaries and relative paths, not full command output.
- Join to active run state through `${CLAUDE_PLUGIN_DATA}/active-run.json`.
  If there is no active run, no-op.

### Acceptance

- Experiment report can show tool calls by category per role/work unit.
- Repeated source reads by file can be computed from fixture data.
- Secret-shaped fixture input is redacted at write time.
- Hook disabled/profile tests prove activity capture can be turned off.

## Phase 5 - Work-Unit Operator Snapshots

### Objective

Make each work unit legible on disk for humans, resume tooling, and the TUI.
ECC's useful pattern is not tmux itself; it is the simple task/status/handoff
artifact set.

### Artifact Layout

Use plugin data, not the repo worktree, as the canonical location:

```text
${CLAUDE_PLUGIN_DATA}/runs/<run_id>/units/<unit_id>/
  task.md
  status.md
  handoff.md
  events.jsonl
```

Optional export into `.swarm-do/worktrees/...` can come later if a worker
process needs local copies.

### Files

| File | Change |
| --- | --- |
| `py/swarm_do/pipeline/run_state.py` | Add snapshot path helpers and atomic status writes. |
| `py/swarm_do/pipeline/executor.py` | Render task/status skeletons from work-unit artifacts. |
| `py/swarm_do/pipeline/post_writer.py` | Write handoff summaries after writer completion. |
| `py/swarm_do/pipeline/resume.py` | Include latest unit snapshot in resume manifests. |
| `py/swarm_do/tui/state.py` | Surface latest unit statuses. |
| `py/swarm_do/pipeline/tests/test_run_state.py` or existing resume tests | Add snapshot fixtures. |

### Atomicity And Concurrency

- All Markdown status writes use tmp + `os.replace` in the same directory.
  No partial files visible to readers, no fsync per write.
- `events.jsonl` is append-only with `O_APPEND`. Readers tolerate a
  truncated final line (last record may be lost on crash).
- A single writer per unit. The executor holds a per-unit advisory lock
  (`fcntl.flock` on `units/<unit_id>/.lock`) so concurrent post-writer and
  resume operations cannot interleave handoff updates.
- Crash recovery: JSON state is authoritative; resume reconstructs Markdown
  snapshots from `events.jsonl` if they are missing or older than the last
  recorded event.

### Implementation Notes

- Do not make Markdown snapshots authoritative over JSON state. They are
  operator-facing mirrors.
- Status is generated from structured state:
  - `pending`
  - `running`
  - `needs_context`
  - `handoff_requested`
  - `approved`
  - `merged`
  - `failed`
- Handoff includes only bounded summaries, changed file paths, validation
  commands/results, remaining risks, and next action.
- Include source artifact paths in `task.md`, not copied phase text when the
  source is large.

### Acceptance

- Prepared work-unit fixture writes stable `task.md` and initial `status.md`.
- Writer completion updates `handoff.md` and `status.md` atomically.
- Resume JSON includes latest snapshot paths.
- TUI state tests can display unit status from structured data.

## Phase 6 - Minimal Codex Surface

### Objective

Make SwarmDaddy easier to dogfood from Codex without modifying user-global
Codex config.

### Recommended Surface

Add project-local reference files and an emitter command:

```bash
bin/swarm codex emit --output .codex/swarmdaddy
bin/swarm codex doctor --json
```

Generated/reference content:

- `AGENTS.md` supplement describing SwarmDaddy's role boundaries.
- reviewer/explorer/provider-review role prompts translated from existing role
  specs.
- optional `config.toml` snippet that documents sandbox and approval settings.

### Files

| File | Change |
| --- | --- |
| `codex/AGENTS.md` or `docs/codex/AGENTS.swarmdaddy.md` | Reference Codex instructions. |
| `codex/agents/*.toml` or `docs/codex/agents/*.toml` | Reference role configs, not auto-installed. |
| `py/swarm_do/pipeline/codex_surface.py` | Emit and doctor helpers. |
| `py/swarm_do/pipeline/cli.py` | Add `codex emit` and `codex doctor`. |
| `py/swarm_do/pipeline/tests/test_codex_surface.py` | Path containment and generated content tests. |

### Implementation Notes

- Do not ship MCP server defaults.
- Do not write to `~/.codex`.
- Do not pin a Codex model in generated config unless the user passes an
  explicit `--model` flag.
- Reuse existing role specs instead of inventing Codex-only role behavior.
- `doctor` detects Codex via `shutil.which("codex")`. Missing Codex reports
  `installed: false` as advisory (never a hard failure). On platforms where
  the Codex CLI is not supported, `doctor` reports
  `unsupported_platform: true` and skips installation checks. Doctor never
  requires Codex for normal SwarmDaddy usage.
- Reference content under `docs/codex/` is committed; emitted artifacts
  under `.codex/swarmdaddy/` are operator-controlled and gitignored by the
  emit command's generated `.gitignore` stub.

### Acceptance

- `bin/swarm codex emit --output <tmp>` writes deterministic files.
- `bin/swarm codex doctor --json` reports missing Codex as advisory.
- Generated role files include read-only guidance for explorer/reviewer and do
  not grant broad write permissions.

## Rollout Order

1. **Foundation epic:** Phase 1 selftest + Phase 2 hook profiles, merged
   together. See Foundation Epic section above.
2. Phase 3 security audit.
3. Phase 4a activity telemetry — categorization on existing events.
4. Phase 4b activity telemetry — `PostToolUse` hook, gated on Phase 2.
5. Phase 5 unit snapshots (TUI binding lands here).
6. Phase 6 Codex surface.

This order matters. Foundation gives SwarmDaddy a health baseline and a
reversible disable path before any new behavior ships. Security audit and
activity telemetry then become observable without surprising every install.
Unit snapshots and Codex support are operator-experience improvements once
the guardrails are in place.

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
- Phase 4: telemetry fixture reports for repeated reads and tool categories.
- Phase 5: resume tests with unit snapshot paths.
- Phase 6: generated Codex files in a temp output directory.

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
| 4a categorization | Data-driven; absent categories degrade reports gracefully — no env flag required. |
| 4b activity hook | `SWARM_DISABLED_HOOKS=activity-observe` |
| 5 unit snapshots | `SWARM_UNIT_SNAPSHOTS=off` env flag; defaults on. JSON state remains authoritative regardless. |
| 6 Codex surface | Invoke-only commands; nothing is installed by default. |

## Risks

- Selftest can become a junk drawer. Keep it a registry of existing checks plus
  small glue, not a second implementation of every validator.
- Hooks can surprise users. Land profile controls first, keep defaults small,
  and document every blocking condition.
- Security scanners can create false positives. Prefer clear remediation text
  and strict-mode opt-in.
- Activity telemetry can leak sensitive data if raw payloads are stored. Redact
  before writing and cap all snippets.
- Codex support can drift from role specs. Generate or derive from role specs
  where possible.

## Open Questions

None blocking. All forks present at the design stage are recorded in the
Resolved Decisions section above. New questions raised during
implementation should be answered in the implementing PR or appended here
with their resolution.

## Final Recommendation

Land the Foundation epic (Phase 1 + Phase 2 together) as the first PR.
`selftest` gives SwarmDaddy a single health signal; hook profiles make
later observability and security hooks safe to adopt. The two are
mutually load-bearing — splitting them creates a window where Phase 1
ships without a reversible disable path for the hooks Phase 4 will add.

After Foundation merges and dogfoods cleanly for at least one full
pipeline run, Phase 3 (security audit) ships next, then Phases 4a/4b, 5,
and 6 in order. Defer Codex files until health and security commands
exist; otherwise cross-harness support risks becoming another config
surface without enough guardrails.
