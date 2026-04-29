---
description: "Resume a previously interrupted SwarmDaddy pipeline from its BEADS epic issue"
argument-hint: "<bd-id> [--merge]"
---

# /swarmdaddy:resume

Resume a previously interrupted SwarmDaddy pipeline. The canonical identity is
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
- `prepared`: reload the prepared run record and resume at the plan-prepare
  gate before creating Beads child issues. If `phase_session.status` is
  `not_initialized`, run the manifest's `phase_session.recommended_command`
  before launching a phase.
- `complete`: no-op; summarize the completed run and checkpoint path.
- `ready`: reload the original BEADS epic/thread context, then resume the
  dispatcher from `resume_from.phase_id` and `resume_from.work_unit_id`. If the
  manifest includes `phase_session`, use its `recommended_command` instead of
  recomputing the next phase. For phase-session `ready`, run
  `bin/swarm do --prepared <run-id> --phase-sessions auto` so reconciliation
  happens before any new phase claim.

Phase-session resume states are read-only in this command. `resume` reports
`ready`, `stale`, `blocked`, `needs_input`, `retry_waiting`,
`retry_exhausted`, `failed_nonretryable`, or `complete` from
`phase_sessions.v1.json`, but only `bin/swarm phases ...` and
`bin/swarm do --prepared ... --phase-sessions auto` may mutate that file.
Use `bin/swarm phases recover <run-id> --json --dry-run` to inspect recovery
actions without mutation.

Active unexpired leases from another host are treated conservatively as still
alive until their lease expires. Same-host recovery can use recorded child PID
and process-group evidence; cross-host recovery waits for the persisted TTL
rather than guessing from unavailable process state.

Do not add a second orchestration protocol. Reuse the `/swarmdaddy:do` dispatch
loop from `skills/swarmdaddy/SKILL.md`, injecting the manifest as resume context
and skipping work units listed in `completed_units`.

If the operator passed `--merge`, treat it only as permission to merge already
APPROVED completed work after a clean manifest. Resume drift still blocks all
automatic merge behavior.
