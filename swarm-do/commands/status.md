---
description: "Diagnose a SwarmDaddy phase-session run and show the next recovery step"
argument-hint: "<run-id>"
---

# /swarmdaddy:status

Run the recovery doctor and phase status for the supplied run id.

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/swarm" phases doctor $ARGUMENTS --json
"${CLAUDE_PLUGIN_ROOT}/bin/swarm" phases status $ARGUMENTS --attempts --cost --events --json
"${CLAUDE_PLUGIN_ROOT}/bin/swarm" worktrees status $ARGUMENTS --json
```

Summarize the doctor result first. If `recommended_command` is present, show it
as the next step.
