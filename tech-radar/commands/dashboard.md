---
description: "Launch interactive TUI dashboard for browsing scan results"
---

# Tech Radar Dashboard

Launch the interactive Textual TUI dashboard for browsing scan results, adding annotations, and searching repos.

## Process

**Always use `--web` when launching from Claude Code** — the terminal TUI cannot run inside Claude Code's Bash tool (no stdin forwarding).

Run via Bash:
```
$CLAUDE_PLUGIN_ROOT/scripts/tech-radar dashboard --web
```

This starts a local web server and opens the dashboard in the user's default browser. The Textual app renders identically in the browser via textual-serve.

Features:
- **Repos tab**: DataTable of all repos from the latest scan, sortable by stars/delta/category
- **Verdicts tab**: Browse Claude's evaluation verdicts
- **Search tab**: FTS5 full-text search across repos and verdicts
- Detail panel with sparkline history, annotation status, and HN context
- Keyboard-driven annotation workflow (approve/reject/bookmark)

After launching, tell the user the dashboard is open in their browser. The server runs until the user presses Ctrl+C or you stop the background task.

## Terminal Mode

For direct terminal use (outside Claude Code), the user can run without `--web`:
```
~/.claude/plugins/marketplaces/mstefanko-plugins/tech-radar/scripts/tech-radar dashboard
```
