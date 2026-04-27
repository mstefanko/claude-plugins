---
description: "Open the SwarmDaddy configuration TUI"
argument-hint: ""
---

# /swarmdaddy:setup

Deprecated alias for `/swarmdaddy:configure`.

## Execute

Run via Bash:

```bash
echo "setup is deprecated. Use /swarmdaddy:quickstart for first-run bootstrap, or /swarmdaddy:configure to open the TUI without side effects."
"$CLAUDE_PLUGIN_ROOT/bin/swarm-tui"
```

This command has the same launch behavior as `/swarmdaddy:configure`: no Beads
initialization, no preset migration, and no stdin prompt.
