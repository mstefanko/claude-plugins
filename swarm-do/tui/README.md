# swarm-do TUI

The operator console is an optional Textual app. The CLI and `/swarm-do:do`
continue to work without installing these dependencies.

## Launch

Run:

```bash
bin/swarm-tui
```

The wrapper creates `${CLAUDE_PLUGIN_DATA}/tui/.venv` on first launch, installs
`tui/requirements.lock`, stamps `requirements.lock.hash`, and then runs:

```bash
python -m swarm_do.tui.app
```

Set `SWARM_TUI_AUTO_INSTALL=1` for non-interactive bootstrap in a dev shell.

## Dev Loop

Use Textual's dev console while iterating:

```bash
TEXTUAL=debug,devtools bin/swarm-tui
textual console
```

The Python module lives in `py/swarm_do/tui/`. State readers in `state.py` have no
Textual dependency and should stay unit-testable. Mutations that also need CLI
coverage live in `actions.py`.

## Screens

- Dashboard reads `telemetry/runs.jsonl` and `in-flight/*.lock`.
- Settings edits `${CLAUDE_PLUGIN_DATA}/backends.toml` through invariant-checked helpers.
- Presets browse stock and user presets; stock presets are read-only.
- Pipelines inspect stage graphs and validate via the shared pipeline helpers.

## Invariant Guards

The TUI must share the same hard rejects as Phase 10 validation. In particular,
`orchestrator`, `agent-code-synthesizer`, and synthesize-merge agents must remain
Claude-backed. There is no force-save path. See `docs/adr/0002-pipeline-invariants.md`.
