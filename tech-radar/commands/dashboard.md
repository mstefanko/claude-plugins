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
- Status tabs with counts for All, Watching, Tested, Adopted, and Rejected
- Two-line repo rows: primary repo/growth signals first, muted description and metadata second
- Colored badges for status, category, rising, and under-radar flags
- Detail preview panel with verdicts, project relevance, sparkline history, annotation status, and HN context
- Keyboard-driven annotation workflow (`w`, `t`, `a`, `r`)
- `p` toggles the preview pane, `ctrl+d` / `ctrl+u` scroll it, `P` cycles project filters
- `/` searches repos via FTS5; `?` opens the full keybinding help overlay
