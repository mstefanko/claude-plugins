---
description: "Launch interactive TUI dashboard for browsing scan results"
---

# Tech Radar Dashboard

Launch the interactive Textual TUI dashboard for browsing scan results, adding annotations, and searching repos.

## Process

Run via Bash:
```
$CLAUDE_PLUGIN_ROOT/scripts/tech-radar dashboard
```

**cmux (automatic):** When running inside cmux, the dashboard opens in a right-split pane automatically — no flags needed. The TUI runs in its own pane next to Claude Code. Close the pane when done.

**`--web` (fallback):** If not in cmux, use `--web` to launch via textual-serve in the browser. The terminal TUI cannot run inside Claude Code's Bash tool (no stdin forwarding).

```
$CLAUDE_PLUGIN_ROOT/scripts/tech-radar dashboard --web
```

Features:
- **Repos tab**: DataTable of all repos from the latest scan, sortable by stars/delta/category
- **Verdicts tab**: Browse Claude's evaluation verdicts
- **Search tab**: FTS5 full-text search across repos and verdicts
- Detail panel with sparkline history, annotation status, and HN context
- Keyboard-driven annotation workflow (approve/reject/bookmark)

## Terminal Mode

For direct terminal use (outside Claude Code), the user can run without `--web`:
```
~/.claude/plugins/marketplaces/mstefanko-plugins/tech-radar/scripts/tech-radar dashboard
```
