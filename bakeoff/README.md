# bakeoff

`bakeoff` is a tiny CLI harness for running the same research task through two
heterogeneous providers, judging their artifact outputs, and writing a
replayable report.

The project is CLI-first. The Claude Code plugin wrapper exists only as a future
launcher surface: it may draft or approve work orders and shell out to the CLI,
but orchestration, validation, provider execution, and reports belong in the
Python package.

## Layout

```text
bakeoff/
  .claude-plugin/plugin.json
  bin/bakeoff
  pyproject.toml
  src/bakeoff/
  tests/
  examples/
```

## Development

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e ".[dev]"
bakeoff --help
pytest
```

For plugin dogfood, use the wrapper directly:

```bash
"${CLAUDE_PLUGIN_ROOT:-$PWD}/bin/bakeoff" --help
```

## User Surface

```text
bakeoff
bakeoff init {gather|compare|analyze|review} [--force]
bakeoff validate <work-order>
bakeoff research <work-order> [--out runs] [--run-id ID] [--force] [--quiet] [--no-triage]
bakeoff rerun <run-id> [--out runs] [--run-id ID] [--quiet] [--no-triage]
bakeoff triage <run-id> [--out runs] [--force] [--dry-run] [--quiet]
bakeoff ls [--out runs]
bakeoff show <run-id> [--out runs] [--judge | --judge-prompt | --triage]
bakeoff doctor [--skip-auth-probe] [--quiet] [--json]
```

`bakeoff research` writes a replayable ledger under `runs/<run-id>/`:

- `work-order.json`
- `providers/<id>/{prompt,stdout,stderr,status}.json/txt`
- optional `providers/<id>/final.json` when the provider returned a schema-valid result
- optional `providers/<id>/repair-{prompt,stdout,stderr,status}.json/txt` after a one-shot format retry
- `judge/` prompts and results
- optional `judge/repair-{prompt,stdout,stderr,status}.json/txt` after a gather judge format retry
- optional `judge/repair-{prompt,stdout,stderr,status}-{pass1,pass2}.json/txt` after compare/analyze judge format retries
- `decision.json`
- `report.md`
- optional `triage/{prompt,stdout,stderr,status,final,citation_checks,triage}.json/txt/md`
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
providers. Bakeoff does not compute branch diffs in v1; paste branch, diff,
changed-file, acceptance-criteria, and known-risk context into `background`.
`code-review` runs auto-triage after successful research unless
`bakeoff research --no-triage` or `bakeoff rerun --no-triage` is used.

Provider runs emit compact heartbeat lines to stderr by default. Pass `--quiet`
on `research`, `rerun`, `triage`, or `doctor` to suppress them. Set
`budgets.heartbeat_seconds` in a work order to tune heartbeat frequency, or `0`
to disable heartbeat ticks.

Analyze reports keep descriptive reasoning under `Primary Explanation` and
reserve finding IDs for actionable follow-ups, conflicts, unknowns, and other
sections that should be eligible for triage. This keeps post-judge triage from
spending provider calls on ordinary explanation inventory.

Facet gather runs send all `Findings` entries into triage source selection,
except `Out-of-Facet Claims`, so focused lenses such as `code-review` and
operator UX get verified before humans act on them.

`bakeoff ls` prints a headered table with each run's type, facet, decision, and
triage state. Triage states are `triage:no`, `triage:dry_run`, `triage:yes`,
and `triage:stale`.

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
detect; pass `--json` for a parseable readiness report.

`bakeoff triage` is an explicit post-judge verification pass. It writes
advisory artifacts under `runs/<run-id>/triage/`, including harness-side
citation checks against the original working directory recorded in `meta.json`
(falling back to the current working directory with a caveat), a source finding
filter artifact, a triage prompt, structured `final.json`, and `triage.md`.

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
- The plugin wrapper remains a launcher-only future layer.
