---
description: "Launch interactive TUI dashboard for browsing scan results"
---

# Tech Radar Dashboard

Launch the interactive Textual TUI dashboard for browsing scan results, adding annotations, and searching repos.

## Prerequisites

Requires `textual` Python package: `pip3 install textual`

## Process

Run via Bash:
```
$CLAUDE_PLUGIN_ROOT/scripts/tech-radar dashboard
```

This opens a full-screen terminal UI with:
- **Repos tab**: DataTable of all repos from the latest scan, sortable by stars/delta/category
- **Verdicts tab**: Browse Claude's evaluation verdicts
- **Search tab**: FTS5 full-text search across repos and verdicts
- Detail panel with sparkline history, annotation status, and HN context
- Keyboard-driven annotation workflow (approve/reject/bookmark)

The dashboard is interactive and blocks the terminal. Tell the user it's launching and let them interact with it directly.
