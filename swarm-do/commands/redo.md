---
description: "Reset and repump a SwarmDaddy phase after running recovery diagnostics"
argument-hint: "<run-id> [--phase N]"
---

# /swarmdaddy:redo

Run recovery diagnostics first and choose the safest redo path from the findings.

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/swarm" phases doctor $ARGUMENTS --json
```

If the doctor is clean, run:

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/swarm" phases redo $ARGUMENTS --json
```

When a specific phase is redone, the command records an operator decision audit
row before mutating phase-session state.

If the doctor reports a finding with multiple safe resolutions, ask one
`AskUserQuestion` before mutating state:

- A: Reset the requested phase and repump.
- B: Rebuild/archive the worktree, then reset and repump.
- C: Abort and inspect.

Never add `--rebuild-worktree`, `--archive-branch`, `--force`, or `--hard`
without either an explicit user choice from that question or the same flag
already present in `$ARGUMENTS`. After the chosen command finishes, summarize
the doctor finding, command run, audit/result status, and the next recommended
command if one remains.
