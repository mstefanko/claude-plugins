# SwarmDaddy TUI

The TUI is the recommended operator surface for managing SwarmDaddy
configuration. Use it to inspect and edit presets, role routes,
provider-review settings, provider readiness, and active-run state. The
`/swarmdaddy:configure` slash command opens this console; the CLI remains the
scriptable surface and other `/swarmdaddy:*` commands remain the dispatch
surface.

## Launch

From an installed plugin:

```text
/swarmdaddy:configure
```

That slash command delegates to:

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/swarm-tui"
```

From this repository checkout:

```bash
bin/swarm-tui
```

The wrapper creates `${CLAUDE_PLUGIN_DATA}/tui/.venv` on first launch, installs
`tui/requirements.lock`, stamps `requirements.lock.hash`, and then runs:

```bash
python -m swarm_do.tui.app
```

Set `SWARM_TUI_AUTO_INSTALL=1` for non-interactive bootstrap in a dev shell.

When `CMUX_WORKSPACE_ID` is present and `cmux` is on `PATH`, the wrapper opens
the TUI in a right split pane and records the pane under
`${CLAUDE_PLUGIN_DATA}/tui/cmux-pane.surface` so repeated launches reuse the
existing pane. Set `SWARM_TUI_CMUX_PANE=1` only when intentionally running the
TUI inside the pane and avoiding recursive split creation.

`/swarmdaddy:setup` is deprecated. Use `/swarmdaddy:quickstart` for first-run
bootstrap or `/swarmdaddy:configure` for this inspect-only TUI.

## What You Can Manage

- **Dashboard:** active preset, validation summary, compact active graph board,
  in-flight runs, recent burn telemetry, latest
  checkpoint/observation, Beads issue open, handoff request, and cancel for
  running `swarm-run` processes.
- **Settings:** framed effective role routes and editable base/user-preset
  route overrides. Stock presets remain read-only; fork first before editing
  their routes.
- **Presets:** stock and user preset browsing, Overview/Graph/Routing/Budget &
  Policy tabs, user preset editing, activation, diff preview, provider health,
  and user preset deletion.

The TUI writes user-owned configuration under `${CLAUDE_PLUGIN_DATA}/presets/`.
It does not edit stock files in place.

## Navigation

Top-level keys:

| Key | Screen |
|-----|--------|
| `1` | Dashboard |
| `2` | Runs table on Dashboard |
| `3` | Presets |
| `4` | Settings |
| `Ctrl+P` | Command palette |
| `?` | Contextual help |
| `q` | Quit |

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

- Dashboard reads `telemetry/runs.jsonl`, `telemetry/run_events.jsonl`,
  `telemetry/observations.jsonl`, and `in-flight/*.lock`. Press `o` to open the
  selected run's Beads issue, `f` to request a Codex handoff, `c` to cancel a
  selected running `swarm-run`, and `Ctrl+H` for provider health.
- Settings edits `${CLAUDE_PLUGIN_DATA}/backends.toml` or user-preset route
  overrides through invariant-checked helpers. Press `Enter` on a route to edit
  it.
- Presets browse stock and user presets; stock presets are read-only. The
  inspector has Overview, Graph, Routing, and Budget & Policy tabs. Graph edits
  on stock-following user presets ask to detach to an inline snapshot first;
  routing and policy edits preserve the stock graph reference. Press `A` to
  activate for the next `/swarmdaddy:do`, `v` to view diff, `x` to delete user
  presets, and `Ctrl+H` (formerly `Ctrl+D`) to run provider doctor.
- The stock `brainstorm`, `research`, `design`, and `review` presets are
  runnable through their matching `/swarmdaddy:*` commands. User or experimental
  output-only graphs remain activation-gated unless their profile is known.

## Preset Flow

- Select a preset in the left gallery to inspect its Overview, Graph, Routing,
  and Budget & Policy tabs.
- Press `A` or `a` to use the selected preset for the next `/swarmdaddy:do`.
  Stock presets are materialized as user presets first, preserving their stock
  graph reference.
- Press `Ctrl+H` to run provider doctor. `Ctrl+D` still works for one release
  and shows a deprecation notice.
- User presets can follow a stock graph with `pipeline = "default"` or carry an
  edited graph in `[pipeline_inline]`.

Prompt lenses can now target fan-out branches or one normal agents-stage entry.
Normal agents stages accept only singular `lens`; synthesize merge agents still
have no prompt-overlay field.

Provider result previews appear in the stage inspector when a prior
`${CLAUDE_PLUGIN_DATA}/runs/<run-id>/stages/<stage-id>/provider-findings.json`
artifact exists. The preview shows status, provider count, configured and
selected providers, provider errors, and finding count; provider output remains
evidence for downstream Claude-backed stages, not an automatic quality gate
decision.

## Invariant Guards

The TUI must share the same hard rejects as preset validation. In particular,
`orchestrator`, `agent-code-synthesizer`, and synthesize-merge agents must remain
Claude-backed. There is no force-save path. See `docs/adr/0002-pipeline-invariants.md`.
