# bakeoff

`bakeoff` is a tiny CLI harness for running the same research task through two
heterogeneous providers, judging their artifact outputs, and writing a
replayable report.

The project is CLI-first. Claude Code and Codex plugin wrappers are launcher and
packaging surfaces: they may draft or approve work orders and shell out to the
CLI, but orchestration, validation, provider execution, and reports belong in
the Go CLI.

## Layout

```text
bakeoff/
  .claude-plugin/plugin.json
  .codex-plugin/plugin.json
  bin/bakeoff
  go.mod
  cmd/bakeoff/
  internal/
  tests/parity/
  examples/
```

## Development

```bash
go run ./cmd/bakeoff --help
go test ./...
go test -race ./...
python3 scripts/parity-go.py
```

`bin/bakeoff` is the public launcher. It runs `dist/bakeoff` when a release
binary is present, honors `BAKEOFF_GO_BINARY` for tests and local dogfood, and
falls back to `go run ./cmd/bakeoff` from a checkout. Build a local release
binary with:

```bash
mkdir -p dist
go build -o dist/bakeoff ./cmd/bakeoff
```

The legacy Python CLI has been removed after cutover. The remaining Python files
under `scripts/` and `tests/parity/fakes/` are test harness utilities only.

For plugin dogfood, use the wrapper directly:

```bash
"${CLAUDE_PLUGIN_ROOT:-$PWD}/bin/bakeoff" --help
```

Rollback after this cleanup means reverting the cutover commit or restoring the
legacy Python implementation from git history.

## Plugin Wrappers And Install

Bakeoff ships one implementation and two thin plugin manifests:

- `.claude-plugin/plugin.json` exposes the plugin to Claude Code marketplaces.
- `.codex-plugin/plugin.json` exposes the same plugin root to Codex plugin
  marketplaces.
- `bin/bakeoff` is the shared launcher used from either side.

The wrappers must stay thin. Do not duplicate command behavior, provider
execution, validation, judging, or report generation in plugin-specific code.
Any Claude- or Codex-specific affordance should create or inspect work orders,
then invoke `bin/bakeoff`.

`bin/bakeoff` resolves the plugin root in this order:

1. `BAKEOFF_PLUGIN_ROOT`
2. `CODEX_PLUGIN_ROOT`
3. `CLAUDE_PLUGIN_ROOT`
4. the parent directory of `bin/bakeoff`

It then runs `BAKEOFF_GO_BINARY` when set, `dist/bakeoff` when present, or
`go run ./cmd/bakeoff` as a checkout fallback.

For Claude Code, add the marketplace containing this plugin and install
`bakeoff`. For Codex, add a Codex marketplace entry that points at the same
plugin root and install `bakeoff` from that marketplace. The Codex marketplace
entry should be local, should use `policy.installation: "AVAILABLE"`, and should
not claim separate authentication.

For a local Codex install, prefer a symlink to the same checkout instead of a
second copy. For example, with `~/plugins/bakeoff` pointing at this directory,
`~/.agents/plugins/marketplace.json` can include:

```json
{
  "name": "personal",
  "interface": { "displayName": "Personal" },
  "plugins": [
    {
      "name": "bakeoff",
      "source": { "source": "local", "path": "./plugins/bakeoff" },
      "policy": {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL"
      },
      "category": "Productivity"
    }
  ]
}
```

Bakeoff does not own provider API keys. Auth stays with the underlying provider
CLIs (`claude`, `codex`, and `git` for local review context). `bakeoff doctor`
checks that those CLIs are present and can optionally run auth probes; use
`--skip-auth-probe` when you only want local readiness checks.
`bakeoff doctor --build` runs live edit probes in temporary directories and
treats provider launch, auth/session, network, sandbox, or filesystem failures
as host environment readiness failures. Do not put API keys, session tokens, or
secrets in work orders, backgrounds, generated review context, or provider
output. Bakeoff records prompts, stdout/stderr, status JSON, reports, and
manifests in the run ledger, so any secret printed by a provider can become
part of `runs/<run-id>/`.

## Common Workflows

Create and run a code-review work order:

```bash
bakeoff init review
$EDITOR review.work-order.json
bakeoff validate review.work-order.json
bakeoff research review.work-order.json --base main --diff
```

`bakeoff init review` writes TODO placeholders. Edit them before `validate`;
the validator rejects unedited templates on purpose.

Inspect the newest report:

```bash
bakeoff show latest
```

Rerun a previous work order:

```bash
bakeoff rerun latest
```

Run or dry-run triage:

```bash
bakeoff triage latest --dry-run
bakeoff triage latest --force
```

Verify a run ledger:

```bash
bakeoff runs verify latest
```

## User Surface

```text
bakeoff
bakeoff init {gather|compare|analyze|review} [--force]
bakeoff validate <work-order>
bakeoff research <work-order> [--out runs] [--run-id ID] [--force] [--quiet] [--no-triage] [--base REF] [--diff] [--changed-files] [--json]
bakeoff rerun <run-id> [--out runs] [--run-id ID] [--quiet] [--no-triage]
bakeoff triage <run-id> [--out runs] [--force] [--dry-run] [--quiet] [--json]
bakeoff runs verify <run-id> [--out runs] [--json]
bakeoff ls [--out runs] [--json] [--facet ID] [--triage-state {no|dry_run|yes|stale}]
bakeoff show <run-id> [--out runs] [--judge | --judge-prompt | --triage]
bakeoff doctor [--build] [--skip-auth-probe] [--quiet] [--json]
```

Exit codes:

| Code | Meaning |
| --- | --- |
| `0` | success |
| `1` | generic runtime or verification failure |
| `2` | usage, config, validation, or missing-input error |
| `3` | completed run with unresolved judge disagreement |

`research --json`, `triage --json`, and `runs verify --json` emit one final
pretty-printed JSON object. `--json` implies effective `--quiet`, so provider
heartbeats and human progress do not appear on stdout. Summary provider status
uses the closed enum `ok | ok_after_format_retry | failed`, with raw Bakeoff
statuses preserved when they differ or fail.

Provider object keys in Go-written JSON and provider sections in reports are
sorted by provider id for deterministic output. The provider order in the work
order still controls judge A/B assignment and position-swap semantics.

`bakeoff research` writes a replayable ledger under `runs/<run-id>/`:

- `work-order.json`
- optional `source-work-order.json` when generated review context was captured
- optional `review-context.md` and `review-context.json` for generated git review context
- `providers/<id>/{prompt,stdout,stderr,status}.json/txt`
- optional `providers/<id>/final.json` when the provider returned a schema-valid result
- optional `providers/<id>/last-message.txt` for Codex final-message capture when the installed CLI supports it
- optional `providers/<id>/repair-{prompt,stdout,stderr,status}.json/txt` after a one-shot format retry
- `judge/` prompts and results
- optional `judge/last-message.txt` or `judge/last-message-{pass1,pass2}.txt` for Codex judges
- optional `judge/repair-{prompt,stdout,stderr,status}.json/txt` after a gather judge format retry
- optional `judge/repair-{prompt,stdout,stderr,status}-{pass1,pass2}.json/txt` after compare/analyze judge format retries
- `decision.json`
- `report.md`
- `meta.json`
- `manifest.json`
- optional `triage/{prompt,stdout,stderr,status,final,citation_checks,triage}.json/txt/md`
- optional `triage/last-message.txt` for Codex triage capture
- optional `triage/source_finding_filter.json` with selected/skipped finding ids
- optional `triage/finding_index.json` when legacy report bullets need synthesized finding ids
- optional `triage/repair-{prompt,stdout,stderr,status}.json/txt` after a triage format retry

`runs/latest` points at the newest run.

Provider status `ok_after_format_retry` means the original provider call exited
successfully but failed final-json schema validation, then one format-only retry
validated. The retry is auditable through `status.json.format_retry` and the
`repair-*` artifacts. Retries are only attempted for zero-exit `schema_error`;
`timeout`, `output_cap`, `scope_error`, `missing_provider`, and `exit_error` are
terminal. Top-level `wall_seconds`/`output_bytes` include both attempts after a
successful retry, while per-attempt costs live under `format_retry`. Provider
status also records `stdout_bytes`, `stderr_bytes`, observed byte counts, and
explicit truncation flags; stderr truncation does not fail a run by itself.
When Codex advertises `--output-last-message`, Bakeoff asks it to write the
final assistant message to `last-message.txt` beside the normal artifacts and
prefers that file for `<final_json>` extraction when it is non-empty. If the
file is unsupported, absent, or empty, Bakeoff falls back to captured stdout.
Provider and judge status metadata may include `final_json_source` with
`stdout` or `last_message`.

`budgets.max_output_bytes` caps retained stdout and stderr payload bytes. Stdout
overflow starts a bounded salvage window controlled by
`budgets.output_cap_grace_seconds` (default `10`) and
`budgets.max_output_overrun_bytes` (default equal to `max_output_bytes`). If the
provider exits during that window and the retained head/tail output contains a
schema-valid final JSON block, the run can still succeed with
`stdout_truncated: true`; otherwise the process group is terminated and, after a
short kill grace, the status is `output_cap`. `max_output_overrun_bytes` is the
number of bytes allowed beyond the capture cap before the salvage window is cut
short; `0` means the first observed stdout byte past the cap hard-stops salvage.

Gather reports render deterministic corroboration from the judge's `sources`
array. `model confidence` reflects the worker/judge assessment of evidence
strength; `corroboration` reflects whether one or both providers surfaced the
claim.

Work orders may include an optional top-level `facet` object. A facet is a
shared task filter applied to both workers and the judge; it is not a persona,
provider-specific lens, new mode, or replacement for `scope`. Facets preserve
the existing citation and schema rules while narrowing what should count as
in-scope evidence.

`bakeoff init review` writes `review.work-order.json`, a normal `type:
"gather"` work order with a `code-review` facet and `codebase` scope for both
providers. Review runs can capture deterministic local git context before
providers launch:

```bash
bakeoff init review
bakeoff research review.work-order.json --base main --diff
```

Any of `--base`, `--changed-files`, or `--diff` enables generated review
context. `--base REF` alone records metadata, diffstat, and changed files
against `REF`; `--changed-files` and `--diff` use `HEAD` when `--base` is not
provided. `--diff` also includes a bounded unified patch. Generated context is
appended to the effective `work-order.json`; the original input is preserved as
`source-work-order.json`, and the generated inputs are written to
`review-context.md` and `review-context.json`.
`code-review` runs auto-triage after successful research unless
`bakeoff research --no-triage` or `bakeoff rerun --no-triage` is used.

Provider runs emit compact heartbeat lines to stderr by default. Pass `--quiet`
on `research`, `rerun`, `triage`, or `doctor` to suppress them. Set
`budgets.heartbeat_seconds` in a work order to tune heartbeat frequency, or `0`
to disable heartbeat ticks. A heartbeat line looks like:

```text
[codex] running t=60s/900s out=13.5KB err=58.6KB last=14s
```

`running` or `quiet` is subprocess output phase, `t` is elapsed time over the
wall-clock budget, `out` and `err` are retained stdout and stderr bytes, and
`last` is seconds since the last stdout or stderr. This is process telemetry,
not semantic model progress; some provider CLIs buffer useful work until their
final output.

Analyze reports keep descriptive reasoning under `Primary Explanation` and
reserve finding IDs for actionable follow-ups, conflicts, unknowns, and other
sections that should be eligible for triage. This keeps post-judge triage from
spending provider calls on ordinary explanation inventory.

Facet gather runs send all `Findings` entries into triage source selection,
except `Out-of-Facet Claims`, so focused lenses such as `code-review` and
operator UX get verified before humans act on them.

`bakeoff ls` prints a headered table with each run's type, facet, decision, and
triage state. Triage states are `triage:no`, `triage:dry_run`, `triage:yes`,
and `triage:stale`. `bakeoff ls --json` scans `manifest.json` files and falls
back to legacy rows for older runs; `--facet` and `--triage-state` filter both
table and JSON output.

## Scope Policy

Worker scopes default to best-effort enforcement with advisory fallback:

```json
"scope_policy": { "enforcement": "best_effort" }
```

Allowed values are:

- `advisory`: prompt instructions only.
- `best_effort`: apply local provider controls where the installed CLI exposes
  them, and record any fallback in provider status and `meta.json`.
- `required`: fail the provider with `scope_error` if a requested scope cannot
  apply its expected local controls.

Best-effort enforcement is intentionally staged. For `codebase`, Bakeoff tries
to disable web search/fetch controls and uses read-only Codex sandboxing where
available. For `web`, Bakeoff runs the provider from a private temporary
working directory and cleans it up after the provider exits while applying
web-tool allowlisting where available. `mixed` scope is recorded but not
narrowed. `bakeoff doctor` prints the installed CLI controls that Bakeoff can
detect; pass `--json` for a parseable readiness report. `doctor --build`
additionally verifies that Claude can edit a temporary workspace and that Codex
advertises and can use `--sandbox workspace-write`.

`bakeoff show <run-id> --out runs` prints the report from the default ledger;
`--judge`, `--judge-prompt`, and `--triage` select individual artifacts.

`bakeoff triage` is an explicit post-judge verification pass. It writes
advisory artifacts under `runs/<run-id>/triage/`, including harness-side
citation checks against the original working directory recorded in `meta.json`
(falling back to the current working directory with a caveat), a
`source_finding_filter.json` artifact, a triage prompt, structured `final.json`,
and `triage.md`. `bakeoff triage --dry-run` writes the prompt, status, citation
checks, and source filter without invoking a provider; `bakeoff ls` reports that
state as `triage:dry_run`.

`bakeoff runs verify <run-id>` checks `manifest.json`, required artifacts, and
recorded SHA-256/size fingerprints for one run ledger. Stale triage is reported
with a recovery hint but does not make ledger verification fail.

## Effort Defaults

`bakeoff init` writes quality-first per-mode effort defaults for dogfooding.
Workers default to `high`; judges default to `xhigh` for the generated
Claude Opus 4.7 judge. Existing work orders that omit `effort` still validate
to `high`.

| Mode | Workers | Judge | Why |
| --- | --- | --- | --- |
| `gather` | `high` | `xhigh` | Facets and triage dogfood need stronger enumeration before cost tuning. |
| `compare` | `high` | `xhigh` | Workers defend positions; judge quality is the primary control point. |
| `analyze` | `high` | `xhigh` | Workers build a reasoning spine; judge needs deeper synthesis and audit. |

## Notes

- Work orders are JSONC. `bakeoff init` writes commented templates.
- `validate` rejects unedited `TODO-*` ids on purpose.
- Scope enforcement is best-effort unless a work order sets `advisory` or
  `required`.
- Output is plain text; `NO_COLOR=1` remains ANSI-free.
- The plugin wrapper remains a launcher-only future layer.
