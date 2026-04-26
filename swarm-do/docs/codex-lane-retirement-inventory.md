# Codex Lane Retirement Inventory

Date: 2026-04-26

This inventory is the R11 gate for replacing or retiring the
`agent-codex-review` lane. The lane must remain in place until the internal
`swarm-review` provider runner preserves the behavioral contract below.

## Current Contract

`agent-codex-review` is a best-effort, blocking-issues-only review lane. Its
scope is intentionally narrower than primary `agent-review`: type errors,
null or edge cases, off-by-one and boundary defects, and security-relevant
bugs. The role emits at most five anchored findings and does not edit files.

Only `CRITICAL` findings are blocking in the role contract. `WARNING` findings
are evidence and do not reject the phase by themselves.

## Runtime Consumers

| Area | Files | Current dependency |
| --- | --- | --- |
| Manual runner | `bin/swarm-run`, `bin/swarm-gpt-review` | Supports `agent-codex-review`, enforces Codex-only use, applies `SWARM_CODEX_REVIEW_TIMEOUT_SECONDS`, discards timeout or backend failures, and invokes findings extraction fail-open. |
| Stock dogfood pipeline | `pipelines/hybrid-review.yaml`, `presets/hybrid-review.toml` | Adds best-effort `codex-review` after `spec-review` while primary `agent-review` and `docs` continue independently. |
| User dogfood pipeline | `data/pipelines/composer-actions-dogfood.yaml` | Contains a user-origin `codex-review-dogfood` stage after `spec-review`. |
| Routing defaults | `py/swarm_do/pipeline/resolver.py` | Default route for `agent-codex-review` is Codex `gpt-5.4` with high effort. |
| Provider review resolver | `py/swarm_do/pipeline/provider_review.py` | Uses the `agent-codex-review` route to resolve the Codex review shim. |
| Role bundles | `role-specs/agent-codex-review.md`, `agents/agent-codex-review.md`, `roles/agent-codex-review/*` | Define the backend-neutral blocking-issues contract and Codex/Claude overlays. |
| Pipeline catalog and TUI | `py/swarm_do/pipeline/catalog.py`, `py/swarm_do/tui/tests/test_state.py`, `py/swarm_do/pipeline/tests/test_pipeline_actions.py` | Exposes a `codex-review` module and tests add/remove/mutation behavior. |
| Telemetry extraction | `bin/extract-phase.sh`, `py/swarm_do/telemetry/extractors/__init__.py`, `py/swarm_do/telemetry/extractors/codex_review.py` | Maps `agent-codex-review` JSON output into `findings.jsonl` fail-open. |
| Telemetry schemas and fixtures | `schemas/telemetry/findings.schema.json`, `schemas/telemetry/findings.v2.schema.json`, `schemas/telemetry/runs.schema.json`, `tests/fixtures/*`, `py/swarm_do/telemetry/tests/*` | Accept and exercise `agent-codex-review` rows in synthetic and parity fixtures. |
| MCO comparison path | `py/swarm_do/pipeline/mco_stage.py`, `schemas/telemetry/provider_findings.schema.json` | The MCO v1 artifact is still role-locked to `agent-codex-review`. |
| Permissions | `permissions/codex-review.json`, `schemas/permissions.schema.json`, `py/swarm_do/pipeline/permissions.py`, `py/swarm_do/pipeline/cli.py` | Keeps a `codex-review` permission profile and CLI role choice. |
| Operator docs | `README.md`, `commands/do.md`, `skills/swarmdaddy/SKILL.md`, `schemas/telemetry/README.md` | Documents the `--codex-review` flag, the dogfood lane, and extraction behavior. |
| Phase 0 harness | `bin/codex-review-phase`, `phase0/*`, `role-specs/agent-codex-review-phase0.md`, `agents/agent-codex-review-phase0.md` | Separate historical experiment. Do not remove as part of lane retirement unless Phase 0 cleanup is explicitly scoped. |

## Parity Checklist

Before `agent-codex-review` is removed, disabled, or replaced in
`hybrid-review`, the `swarm-review` provider path must prove:

- Blocking-issues semantics: provider-review evidence can represent the same
  critical/warning distinction, max-five-findings cap, file-line anchoring, and
  narrow defect classes.
- Timeout and discard behavior: Codex provider timeout or backend failure is
  recorded as discarded or provider-error evidence and does not block the
  pipeline by itself.
- Telemetry continuity: existing `findings.jsonl` consumers either keep
  receiving equivalent `agent-codex-review` rows or are migrated to a documented
  provider-review artifact consumer.
- Hybrid-review UX: operators can still opt into an independent Codex review
  signal after `spec-review`, and primary Claude review remains the final
  synthesis lane.
- Route preservation: Codex provider review continues to use the resolved
  `agent-codex-review` route unless a new route migration is documented.
- Permissions posture: replacement execution is read-only and covered by the
  same or stricter permission checks.
- MCO isolation: any change to the legacy MCO v1 role lock is handled as an MCO
  comparison-path change, not as a side effect of Codex lane retirement.
- Test coverage: focused tests cover timeout discard, malformed Codex output,
  successful anchored findings, no-finding output, telemetry extraction, and
  `hybrid-review` pipeline rendering/mutation.

## Retirement Decision

No runtime rewiring is approved by this inventory. The lane stays live until a
future implementation updates this checklist with passing evidence and names
the exact files being migrated.
