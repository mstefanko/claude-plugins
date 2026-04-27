---
description: "Open the SwarmDaddy TUI configuration console"
argument-hint: ""
---

# /swarmdaddy:configure

Open the SwarmDaddy Textual TUI for inspecting and editing presets, routes,
provider-review settings, provider doctoring, and active-run status.

This is an inspect/edit launcher only. It does not initialize Beads, migrate
presets, or prompt on stdin. Use `/swarmdaddy:quickstart` for guided first-run
bootstrap.

## Execute

Run via Bash:

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm-tui"
```

The launcher handles the environment:

- In cmux, it opens the TUI in a right split pane and prints the pane status.
- In an interactive terminal, it runs the TUI in the current terminal.
- Without cmux or an interactive terminal, it prints the terminal command the
  operator should run.

On first launch, the wrapper may ask to create or update
`${CLAUDE_PLUGIN_DATA}/tui/.venv` from `tui/requirements.lock`. If the operator
wants non-interactive bootstrap, tell them to run:

```bash
SWARM_TUI_AUTO_INSTALL=1 "$CLAUDE_PLUGIN_ROOT/bin/swarm-tui"
```

## Report Back

After the Bash command returns, summarize whether the TUI opened in cmux, is
already running, launched in the current terminal, or printed manual launch
instructions.
