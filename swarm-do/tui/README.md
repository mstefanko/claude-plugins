# SwarmDaddy TUI

The TUI is the recommended operator surface for managing SwarmDaddy
configuration. Use it to inspect and edit presets, pipelines, role routes,
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

`/swarmdaddy:setup` is an alias for `/swarmdaddy:configure`. It opens this TUI;
it does not initialize Beads.

## What You Can Manage

- **Dashboard:** active preset/pipeline, validation summary, compact active
  pipeline graph, in-flight runs, recent burn telemetry, latest
  checkpoint/observation, Beads issue open, handoff request, and cancel for
  running `swarm-run` processes.
- **Settings:** framed effective role routes and editable base/user-preset
  route overrides. Stock presets remain read-only; fork first before editing
  their routes.
- **Presets:** stock and user preset browsing, loading, diff preview, and user
  preset deletion.
- **Pipelines:** intent-sorted pipeline gallery, graph-first execution
  workbench, synchronized stage inspector, validation rail, fork-first editing,
  modules, routes, fan-out branch routes, prompt lenses, provider-review
  settings, MCO settings, lint, validation, provider doctor, graph copy, and
  profile activation.

The TUI writes user-owned configuration under `${CLAUDE_PLUGIN_DATA}/presets/`
and `${CLAUDE_PLUGIN_DATA}/pipelines/`. It does not edit stock files in place.

## Navigation

Top-level keys:

| Key | Screen |
|-----|--------|
| `1` | Dashboard |
| `2` | Runs table on Dashboard |
| `3` | Pipelines |
| `4` | Presets |
| `5` | Settings |
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
  selected Beads issue, `f` to request a Codex handoff, and `c` to cancel a
  selected running `swarm-run`.
- Settings edits `${CLAUDE_PLUGIN_DATA}/backends.toml` or user-preset route
  overrides through invariant-checked helpers. Press `Enter` on a route to edit
  it.
- Presets browse stock and user presets; stock presets are read-only. Press `l`
  to load, `v` to view diff, and `x` to delete user presets.
- Pipelines open a graph-first composer workbench: intent-sorted gallery,
  selectable execution graph, focused stage inspector, validation rail,
  fork-first edit dialog, in-memory draft save/discard state, route/module edit
  controls, and undo/redo. Provider-review stages are visibly read-only and may
  skip when no shim is eligible; MCO remains the experimental comparison path.
  Stock pipelines remain read-only; editing starts by forking a pipeline and
  its matching preset into user-owned files.
- The stock `brainstorm`, `research`, `design`, and `review` pipelines are
  runnable through their matching `/swarmdaddy:*` commands. User or experimental
  output-only pipelines remain activation-gated unless their profile is known.

## Composer Flow

On the Pipelines screen:

- Select a pipeline in the left gallery, then select a graph node or edge row
  to inspect the read-only stage details.
- Press `f` or `Enter` to begin editing. Stock pipelines open a fork dialog with
  a generated collision-free name; user pipelines open an in-memory draft.
- Press `r` on an agents stage to override the first agent route in the draft.
- Press `b` on a model fan-out stage to edit a branch route. Prompt-variant
  fan-outs stay lens-only and cannot be mixed with per-branch model routes.
- Press `n` on a fan-out or normal agents stage to apply compatible prompt
  lenses. The modal lists each lens id, category, execution mode,
  output-contract rule, merge expectation, and safety note. Lens edits stay in
  the in-memory draft until validation passes and `Ctrl+S` writes the YAML.
- Press `o` on a provider-review stage to edit selected providers or selection
  mode, timeout, and failure tolerance. The editor preserves `command=review`,
  `memory=false`, `output=findings`, and read-only boundaries.
- Press `Ctrl+D` on a provider-bearing pipeline to run provider doctor and view
  local provider readiness before activation.
- Press `t` to open the secondary topological stage list.
- Press `y` to copy the current graph as plain text.
- Press `m` to add a catalog module to the draft, or `Delete` to remove the
  selected stage when nothing still depends on it.
- Press `Ctrl+R` to reset a selected stage route or fan-out routes to resolver
  defaults.
- Press `Ctrl+Z` / `Ctrl+Y` for in-session undo and redo.
- Press `Ctrl+S` to save the current draft. The validation rail blocks hard
  validation errors before writing YAML.
- Press `Esc` to discard the in-memory draft and return to the last saved file.
- Press `a` on the stock `research` pipeline to activate the research profile.
  Preview-only output graphs can still be browsed, forked, linted, and saved,
  but activation is blocked.

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

The TUI must share the same hard rejects as pipeline validation. In particular,
`orchestrator`, `agent-code-synthesizer`, and synthesize-merge agents must remain
Claude-backed. There is no force-save path. See `docs/adr/0002-pipeline-invariants.md`.
