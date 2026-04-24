---
description: "Inspect swarm-do resume state from its BEADS epic issue"
argument-hint: "<bd-id> [--merge]"
---

# /swarm-do:resume

Inspect the recovery state for a previously interrupted swarm-do pipeline. The
canonical identity is the BEADS run/epic issue ID, not a telemetry `run_id`.

## Execute

Run:

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/swarm" resume $ARGUMENTS
```

This command currently reports checkpoint mapping, drift status, and whether a
clean merge is even eligible. If drift is reported, stop and surface the
conflicting keys to the operator. Do not merge completed work units unless the
operator passed `--merge` and the resume report is clean.
