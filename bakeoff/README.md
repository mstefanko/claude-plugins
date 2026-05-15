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
bakeoff init {gather|compare|analyze} [--force]
bakeoff validate <work-order>
bakeoff research <work-order> [--out runs] [--run-id ID] [--force] [--quiet]
bakeoff rerun <run-id> [--out runs] [--run-id ID] [--quiet]
bakeoff triage <run-id> [--out runs] [--force] [--dry-run] [--quiet]
bakeoff ls [--out runs]
bakeoff show <run-id> [--judge | --judge-prompt | --triage]
bakeoff doctor [--skip-auth-probe] [--quiet]
```

`bakeoff research` writes a replayable ledger under `runs/<run-id>/`:

- `work-order.json`
- `providers/<id>/{prompt,stdout,stderr,status,final}.json/txt`
- optional `providers/<id>/repair-{prompt,stdout,stderr,status}.json/txt` after a one-shot format retry
- `judge/` prompts and results
- optional `judge/repair-{prompt,stdout,stderr,status}.json/txt` after a gather judge format retry
- optional `judge/repair-{prompt,stdout,stderr,status}-{pass1,pass2}.json/txt` after compare/analyze judge format retries
- `decision.json`
- `report.md`
- optional `triage/{prompt,stdout,stderr,status,final,citation_checks,triage}.json/txt/md`
- optional `triage/finding_index.json` when legacy report bullets need synthesized finding ids
- optional `triage/repair-{prompt,stdout,stderr,status}.json/txt` after a triage format retry

`runs/latest` points at the newest run.

Provider status `ok_after_format_retry` means the original provider call exited
successfully but failed final-json schema validation, then one format-only retry
validated. The retry is auditable through `status.json.format_retry` and the
`repair-*` artifacts. Retries are only attempted for zero-exit `schema_error`;
`timeout`, `output_cap`, and `exit_error` are terminal. Top-level
`wall_seconds`/`output_bytes` include both attempts after a successful retry,
while per-attempt costs live under `format_retry`.

Gather reports render deterministic corroboration from the judge's `sources`
array. `model confidence` reflects the worker/judge assessment of evidence
strength; `corroboration` reflects whether one or both providers surfaced the
claim.

Provider runs emit compact heartbeat lines to stderr by default. Pass `--quiet`
on `research`, `rerun`, `triage`, or `doctor` to suppress them. Set
`budgets.heartbeat_seconds` in a work order to tune heartbeat frequency, or `0`
to disable heartbeat ticks.

`bakeoff triage` is an explicit post-judge verification pass. It writes
advisory artifacts under `runs/<run-id>/triage/`, including harness-side
citation checks against the original run directory, a triage prompt, structured
`final.json`, and `triage.md`.

## Effort Defaults

`bakeoff init` writes conservative per-mode effort defaults. Existing work
orders that omit `effort` still validate to `high`.

| Mode | Workers | Judge | Why |
| --- | --- | --- | --- |
| `gather` | `low` | `low` | Enumeration and dedupe are extraction-shaped tasks. |
| `compare` | `high` | `medium` | Workers defend positions; judge applies a fixed rubric. |
| `analyze` | `high` | `medium` | Workers build a reasoning spine; judge scores and annotates. |

## Notes

- Work orders are JSONC. `bakeoff init` writes commented templates.
- `validate` rejects unedited `TODO-*` ids on purpose.
- Scopes are prompt-advisory in v1; provider CLIs still control their own tools.
- The plugin wrapper remains a launcher-only future layer.
