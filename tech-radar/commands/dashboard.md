---
description: "Launch interactive TUI dashboard for browsing scan results"
---

# Tech Radar Dashboard

Launch the interactive Textual TUI dashboard for browsing scan results, adding annotations, and searching repos.

## Process

Run via Bash:
```
~/.claude/plugins/marketplaces/mstefanko-plugins/tech-radar/scripts/tech-radar dashboard
```

The command auto-detects the environment:
- **In cmux**: opens in a right-split pane automatically
- **Otherwise**: launches a web server and prints a URL to share with the user

Never pass `--web` manually — the command handles detection internally.

**Singleton behavior:** If a dashboard is already running, the command prints the existing URL/pane and exits immediately.

Features:
- **Repos tab**: DataTable of all repos from the latest scan, sortable by stars/delta/category
- **Verdicts tab**: Browse Claude's evaluation verdicts
- **Search tab**: FTS5 full-text search across repos and verdicts
- Detail panel with sparkline history, annotation status, and HN context
- Keyboard-driven annotation workflow (approve/reject/bookmark)
