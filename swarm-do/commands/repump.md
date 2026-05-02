---
description: "Pump one healthy SwarmDaddy phase and show updated status"
argument-hint: "<run-id>"
---

# /swarmdaddy:repump

Use this when doctor is clean and the run only needs another foreground pump
tick.

Plain repump is a happy-path pump tick and does not create an operator decision
record; mutating recovery choices do create audit rows.

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/swarm" phases pump $ARGUMENTS --launcher=claude-print --max-phases=1 --json
"${CLAUDE_PLUGIN_ROOT}/bin/swarm" phases status $ARGUMENTS --attempts --cost --events --json
```
