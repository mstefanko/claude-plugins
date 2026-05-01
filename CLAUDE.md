# mstefanko-plugins

This repo is a **Claude Code plugin marketplace**, not a single project. Each top-level dir is an independent plugin with its own README. Treat them as separate codebases — don't refactor across plugin boundaries unless the user asks.

## Plugins

Source of truth: `.claude-plugin/marketplace.json`.

| Plugin name      | Directory         | Purpose                                                    |
|------------------|-------------------|------------------------------------------------------------|
| `swarmdaddy`     | `swarm-do/`       | Beads-backed multi-agent orchestration. The big one.       |
| `obsidian-notes` | `obsidian-notes/` | Save/search notes in an Obsidian vault.                    |
| `tech-radar`     | `tech-radar/`     | Scan trending repos against the user's stack.              |

**Gotcha:** the plugin is `swarmdaddy`; the directory is `swarm-do/`. Slash commands and skill IDs use `swarmdaddy:*`; filesystem paths use `swarm-do/`.

## Where to look first

- **swarmdaddy work** → `swarm-do/README.md` (architecture, pipelines, presets, Phase-0, agents)
- **CLI** → `swarm-do/bin/swarm` (canonical from a shell)
- **Python package** → `swarm-do/py/swarm_do/`
- **Tests** → from `swarm-do/`: `PYTHONPATH=py python3 -m unittest ...`

## Non-plugin directories

These are scratchpads, not shipping code:

- `plans/` — implementation plans for in-flight work
- `research/` — research memos and notes
- `DESIGN.md` — top-level design doc

Don't ship code from them. Don't mistake them for a fourth plugin.

## Beads

Issue tracking is via the `bd` CLI; the SessionStart hook loads the workflow contract. Create a beads issue before writing code; close on completion; `bd sync` at session end.
