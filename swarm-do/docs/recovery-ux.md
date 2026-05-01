# SwarmDaddy Recovery UX

Use these commands instead of manual JSON edits or `/tmp` recovery helpers.

## Prepared Dispatch Drift

```bash
bin/swarm prepare refresh-base <run-id>
```

Refreshes the prepared run to the current `git_base_ref` while keeping embedded
work-unit artifacts, sidecar files, and descriptor SHAs in sync. Use
`--to-sha <sha>` for an explicit base, `--phase <id>` for one phase, and
`--dry-run --json` to inspect the planned writes.

## Phase Recovery

```bash
bin/swarm phases doctor <run-id>
bin/swarm phases reset <run-id> --phase <id> --hard
bin/swarm phases redo <run-id> --phase <id> --hard --launcher=claude-print
```

`doctor` is read-only and isolates probe failures as findings. `reset --hard`
uses the in-process phase-session writer and clears the dispatch fields that
used to require `reset-phase2.py`. `redo` runs doctor, optional reset, optional
worktree rebuild, then pumps.

## Worktree Recovery

```bash
bin/swarm worktrees status <run-id>
bin/swarm worktrees reset <run-id> --discard
bin/swarm worktrees reset <run-id> --archive-branch --force
```

Clean unadopted base drift is rebuilt automatically by the launcher path. Dirty
or committed execution work requires an explicit reset. Archive the branch when
there may be useful unadopted work.
