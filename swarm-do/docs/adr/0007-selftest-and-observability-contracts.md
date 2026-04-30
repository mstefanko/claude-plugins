# ADR 0007: Selftest, Security-Audit, and Activity-Observation Output Contracts

- Status: Accepted (Phase 0 baseline; runtime emitters land in later phases)
- Date: 2026-04-30
- Deciders: SwarmDaddy maintainers
- Supersedes: none
- Related: ADR 0002 (telemetry sources of truth), ADR 0006 (prepare gate contract)

## Context

Phases 1, 3, and 4 of the operator-readiness plan introduce three new
machine-readable surfaces:

1. `bin/swarm selftest --json` — a single-screen readiness check that aggregates
   existing inventory commands.
2. `bin/swarm security audit --json` — a static permissions/hook scanner over
   the SwarmDaddy plugin and the active target repo.
3. The `activity-observation` row added to the run-events stream — sanitized
   per-tool-call telemetry written by Claude Code hooks.

We need the output shapes locked before the runtime code lands so consumers
(TUI, dogfood reports, dashboards, CI gates) can be built against fixtures and
so downstream JSON contracts do not churn during phase rollout.

## Decision

The fixtures committed in this phase are the authoritative shape contracts:

- `docs/examples/selftest.ok.json`
- `docs/examples/security-audit.warning.json`
- `docs/examples/activity-observation.jsonl`

Each fixture carries an embedded `_contract` block describing exit-status
rules, severity/check taxonomy, sensitive-field policy, and (where applicable)
scope semantics. Implementations in subsequent phases MUST conform; deviations
require an ADR amendment or supersede.

### Hard vs. advisory checks (selftest)

Hard failures are existing health checks SwarmDaddy already enforces in CI or
inventory commands; their failure means the plugin cannot reliably execute a
swarm:

- `plugin-root-resolvable`, `data-dir-resolvable`, `beads-rig-present`
- `active-preset-loads`, `pipeline-lint`, `preset-dry-run`
- `role-permissions-load`, `telemetry-schemas`, `telemetry-docs-generated`
- `active-run-valid`

Advisory checks surface optional or environmental conditions that should not
block a session by default but should fail under `--strict` (used in CI):

- `provider-doctor`, `review-provider-eligible`
- `tui-deps`, `tui-lock-hash`
- `checkpoint-age`, `active-run-fresh`
- `plugin-clean-checkout`, `dogfood-summary`

`exit_status` rules:

- `0` when all hard checks pass; advisory may be `pass` or `warn` without
  `--strict`.
- `1` when any hard check fails, OR when `--strict` is set and any advisory
  check is `warn`.

### Severity ladder (security audit)

Four-tier severity, with the per-finding kind list locked in the fixture’s
`severity_map`:

- `critical` — fails default exit; e.g., broad Bash/Write in a read-only role,
  hook shell with unscoped input, secret-shaped argv, `pull_request_target`
  checking out the PR head.
- `high` — fails `--strict`; e.g., role registers a missing fragment,
  allow/deny conflict in same role, hook missing profile wrapper, review
  provider not read-only-eligible, project MCP shell launcher.
- `medium` — never fails by itself; reported for operator action.
- `low` — informational only.

Default `exit_status=1` only when a `critical` finding is present;
`--strict` extends failure to `high` as well. `medium` and `low` never fail.

### Sensitive paths (all three surfaces)

Implementations MUST redact secret-shaped substrings before serialization in
every emitted field:

- GitHub tokens (`gh[pousr]_…`), OpenAI/Anthropic keys (`sk-…`, `sk-ant-…`),
  AWS access keys (`AKIA…`), and any `password=`, `token=`, `api_key=`, or
  `Authorization:` value pair.

Per-surface specifics:

- **Selftest** — `details` may contain absolute paths and command snippets.
  The plugin root and data-dir paths are intentionally not redacted, but the
  document as a whole is host-sensitive; consumers publishing it must scrub
  paths themselves. `remediation` is operator-facing prose only and must not
  echo raw command output or unredacted secrets.
- **Security audit** — `location.path` is always relative to scope root;
  absolute paths are never emitted. `location.snippet` is a capped excerpt
  with secret-shaped substrings replaced by `REDACTED` markers.
  `redaction_applied` is required per finding; downstream consumers MAY drop
  any finding with `redaction_applied=true` from public dashboards.
- **Activity observation** — `input_summary` and `output_summary` are bounded
  synopses (≤256 chars) that must not contain raw prompts, raw command output,
  environment variables, or secrets. `file_paths` are repo-relative only.
  When `${CLAUDE_PLUGIN_DATA}/active-run.json` is missing or invalid, the hook
  MUST no-op rather than emit a placeholder row.

### Command inventory remains the source of truth

This phase introduces no new runtime commands. The following inventory is
already authoritative and unchanged:

- `bin/swarm preset dry-run`
- `bin/swarm pipeline lint`
- `bin/swarm providers doctor`
- `bin/swarm permissions check`
- `bin/swarm-telemetry validate`
- `bin/swarm-telemetry dogfood-check`
- `bin/swarm-telemetry experiment-report`

The Phase 1 `selftest` aggregates these; it does not replace them.

## Consequences

- Phase 1, 3, and 4 implementers have a single merge target; any drift from
  these fixtures requires an ADR change in the same PR.
- TUI and dogfood-report consumers can be authored against the fixtures
  immediately, in parallel with runtime work.
- `_contract` metadata blocks live in the fixtures themselves so the contract
  travels with the example. Runtime emitters MUST NOT include the
  `_contract` key in real output; readers MUST tolerate its absence.
- Schema-validation tooling added in later phases will treat the `_contract`
  block as a documentation sentinel and skip it.

## Rollback

Until any of Phases 1, 3, or 4 actually ship runtime code, this ADR can be
withdrawn by deleting the fixtures and this file. Once a runtime emitter
lands, supersede via a follow-up ADR rather than withdrawal.
