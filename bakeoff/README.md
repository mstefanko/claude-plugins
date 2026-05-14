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
bakeoff research <work-order> [--out runs] [--run-id ID] [--force]
bakeoff rerun <run-id>
bakeoff ls [--out runs]
bakeoff show <run-id> [--judge | --judge-prompt]
bakeoff doctor [--skip-auth-probe]
```

`bakeoff research` writes a replayable ledger under `runs/<run-id>/`:

- `work-order.json`
- `providers/<id>/{prompt,stdout,stderr,status,final}.json/txt`
- `judge/` prompts and results
- `decision.json`
- `report.md`

`runs/latest` points at the newest run.

## Notes

- Work orders are JSONC. `bakeoff init` writes commented templates.
- `validate` rejects unedited `TODO-*` ids on purpose.
- Scopes are prompt-advisory in v1; provider CLIs still control their own tools.
- The plugin wrapper remains a launcher-only future layer.
