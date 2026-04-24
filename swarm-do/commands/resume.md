---
description: "Resume a previously interrupted swarm-do pipeline from its BEADS epic issue"
argument-hint: "<bd-id> [--merge]"
---

# /swarm-do:resume

Resume a previously interrupted swarm-do pipeline. The canonical identity is
the BEADS run/epic issue ID, not a telemetry `run_id`.

## Execute

Run:

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/swarm" resume $ARGUMENTS --json
```

Parse the JSON manifest and handle `status` exactly:

- `drift`: stop immediately and surface `drift_keys`; never merge or restart.
- `not-found`: stop and tell the operator no run-events mapping exists for the
  BEADS id.
- `complete`: no-op; summarize the completed run and checkpoint path.
- `ready`: reload the original BEADS epic/thread context, then resume the
  dispatcher from `resume_from.phase_id` and `resume_from.work_unit_id`.

Do not add a second orchestration protocol. Reuse the `/swarm-do:do` dispatch
loop from `skills/swarm-do/SKILL.md`, injecting the manifest as resume context
and skipping work units listed in `completed_units`.

If the operator passed `--merge`, treat it only as permission to merge already
APPROVED completed work after a clean manifest. Resume drift still blocks all
automatic merge behavior.
