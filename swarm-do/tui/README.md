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

## Creating A New Preset

The Presets workbench can author a new user preset directly, including its
inline pipeline graph. Two entry points exist on the Presets screen:

- Press **`N`** to open the **New Preset** modal (uppercase or lowercase).
- Press **`M`** (uppercase only) to open the **Add Stack** modal against the
  selected user preset's inline graph.

Lowercase `n` and `m` continue to bind to **Edit Lenses** and **Add Module**
respectively on a selected user preset; the new authoring shortcuts do not
displace those bindings.

### New Preset Modal

Opening the modal seeds the form with sensible defaults so Enter is enough for
the fast path:

- **Kind:** Implementation (default). Output-only kinds expose the matching
  recipe set.
- **Recipe:** `Balanced default` (default for Implementation).
- **Name:** auto-generated through `suggest_user_preset_name("balanced")` so it
  never collides with an existing preset.
- **Preview pane:** shows the resolved graph, routing, provider, and budget
  summary for the chosen recipe, with a validation status badge — **Ready**,
  **Warning**, or **Blocked**.

Confirming the modal:

- **Enter — Create Preset:** writes a user preset carrying `pipeline_inline`,
  refreshes the gallery, selects the new preset, and opens the Overview tab.
- **`A` — Create & Activate:** creates the preset (same as Enter) and then
  activates it for the next `/swarmdaddy:do`. If activation is refused (for
  example, by an invariant or budget gate), the preset is still retained and
  the workbench surfaces a "Preset created, activation refused" message; the
  preset stays selected so you can fix and retry.

The fast paths therefore are:

| Keystrokes | Result |
|------------|--------|
| `N`, Enter | Create preset only |
| `N`, `A`   | Create preset and activate it |

For the full recipe catalog and per-kind defaults, see
[`../docs/new-preset-creation-flow-plan.md`](../docs/new-preset-creation-flow-plan.md).

### Blank Graph Flow

Choosing the **Blank graph** recipe creates an unsaved `PresetCreationDraft`
and switches directly to the Graph tab so you can assemble stages by hand. The
draft surfaces an empty-stages validation error inline until you apply a stack
or add stages; the global validation rail may not yet reflect blank-flow
errors directly, so rely on the draft's own status while building.

### Add Stack (`M`)

`M` on the Presets workbench opens the **Add Stack** modal. Pick a stack id
and a merge mode:

- Stack id: `default-implementation`, `default-research`, `default-design`, or
  `default-review`.
- Mode:
  - `empty` — only allowed when the current graph has no stages.
  - `append-missing` — adds stack stages that are not already present.
  - `replace` — discards the current graph and installs the stack as-is.

`M` is the recommended way to populate a blank-graph draft once you have one
selected.

### Graph Tab Action Strip

The Graph tab exposes the per-graph editing actions as a single action strip:
**Add Stack**, **Add Module**, **Add Agent Stage**, **Add Fan-Out**,
**Add Provider**, **Edit Dependencies**, and **Remove**. These operate on the
selected user preset's inline graph (or on the in-progress
`PresetCreationDraft` after the blank flow).

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
