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

## Planned User Surface

```text
bakeoff
bakeoff init {gather|compare|analyze}
bakeoff validate <work-order>
bakeoff research <work-order>
bakeoff rerun <run-id>
bakeoff ls
bakeoff show <run-id>
bakeoff doctor
```
