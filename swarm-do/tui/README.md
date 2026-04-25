# SwarmDaddy TUI

The operator console is an optional Textual app. The CLI and `/swarmdaddy:do`
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
- Pipelines open a composer workbench: intent-sorted gallery, selectable
  stage rows, focused stage inspector, validation rail, fork-first edit dialog,
  in-memory draft save/discard state, route/module edit controls, and
  undo/redo. MCO provider stages are visibly experimental and read-only.
  Stock pipelines remain read-only; editing starts by forking a pipeline and
  its matching preset into user-owned files.
- The stock `brainstorm`, `research`, `design`, and `review` pipelines are
  runnable through their matching `/swarmdaddy:*` commands. User or experimental
  output-only pipelines remain activation-gated unless their profile is known.

## Composer Flow

On the Pipelines screen:

- Select a pipeline in the left gallery, then select a stage row to inspect the
  read-only stage details.
- Press `f` or `Enter` to begin editing. Stock pipelines open a fork dialog with
  a generated collision-free name; user pipelines open an in-memory draft.
- Press `r` on an agents stage to override the first agent route in the draft.
- Press `b` on a model fan-out stage to edit a branch route. Prompt-variant
  fan-outs stay lens-only and cannot be mixed with per-branch model routes.
- Press `n` on a fan-out or normal agents stage to apply compatible prompt lenses. The modal
  lists each lens id, category, execution mode, output-contract rule, merge
  expectation, and safety note. Lens edits stay in the in-memory draft until
  validation passes and `Ctrl+S` writes the YAML.
- Press `o` on an MCO provider stage to edit selected providers, timeout, and
  failure tolerance. The editor preserves `command=review`, `memory=false`,
  `output=findings`, and strict-contract read-only boundaries.
- Press `d` on an MCO-bearing pipeline to run provider doctor and view local
  provider readiness before activation.
- Press `m` to add a catalog module to the draft, or `Delete` to remove the
  selected stage when nothing still depends on it.
- Press `Ctrl+R` to reset a selected stage route or fan-out routes to resolver
  defaults.
- Press `Ctrl+Z` / `Ctrl+Y` for in-session undo and redo.
- Press `Ctrl+S` to save the current draft. The validation rail blocks hard
  validation errors before writing YAML.
- Press `Esc` to discard the in-memory draft and return to the last saved file.
- Press `s` on the stock `research` pipeline to activate the research profile.
  Preview-only output graphs can still be browsed, forked, linted, and saved,
  but activation is blocked.

Prompt lenses can now target fan-out branches or one normal agents-stage entry.
Normal agents stages accept only singular `lens`; synthesize merge agents still
have no prompt-overlay field.

MCO result previews appear in the stage inspector when a prior
`${CLAUDE_PLUGIN_DATA}/runs/<run-id>/stages/<stage-id>/provider-findings.json`
artifact exists. The preview shows status, provider count, selected providers,
provider errors, and finding count; provider output remains evidence for
downstream Claude-backed stages, not an automatic quality gate decision.

## Invariant Guards

The TUI must share the same hard rejects as pipeline validation. In particular,
`orchestrator`, `agent-code-synthesizer`, and synthesize-merge agents must remain
Claude-backed. There is no force-save path. See `docs/adr/0002-pipeline-invariants.md`.
