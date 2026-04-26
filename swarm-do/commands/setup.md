---
description: "Open the SwarmDaddy configuration TUI"
argument-hint: ""
---

# /swarmdaddy:setup

Alias for `/swarmdaddy:configure`. Open the SwarmDaddy TUI to choose or fork
presets/pipelines, inspect routes, run provider doctor, and manage active-run
status.

This command does **not** initialize Beads. Use `/swarmdaddy:init-beads` only
when the current repo should get a `.beads/` store.

## Execute

Run via Bash:

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm-tui"
```

Follow the same launch behavior as `/swarmdaddy:configure`: cmux split pane when
available, current terminal when interactive, and manual instructions when no
interactive surface is available.
