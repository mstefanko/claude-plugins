# Investigation: sensitive-path absolute file-path probe result

**Status:** complete - Option B selected.
**Date:** 2026-04-30
**Plan:** `docs/sensitive-path-launcher-hardening-plan.md`

## Probe Result

The Phase 0 absolute path probe was run from the launcher-visible symlink
`/tmp/swarm-do-sensitive-path-probe` pointing at the real checkout:

`<sensitive-source>/swarm-do`

Probe A asked Claude Code to write the real absolute sensitive path:

`<sensitive-source>/swarm-do/probe-abs-sensitive-path.txt`

Result:

- exit code: 0
- file written: no
- output preserved at: `/tmp/swarm-do-probe-real-path.json`
- observed result text: `The Write tool isn't enabled in this context, so I can't create that file.`

Probe B asked Claude Code to write the launcher-visible symlink path:

`/tmp/swarm-do-sensitive-path-probe/probe-safe-sensitive-path.txt`

Result:

- exit code: 0
- file written: yes
- output preserved at: `/tmp/swarm-do-probe-safe-path.json`

## Decision

Probe A failed and Probe B succeeded, so the implementation branch is Option B:

- run `claude-print` from a safe launcher cwd outside `~/.claude/`
- rewrite prompt-visible source-tree paths from the real repo root spelling to
  the launcher-visible symlink spelling
- fail closed before launch when a sensitive real source path remains in the
  assembled prompt

Only the probe files created by this phase should be removed from the checkout;
the `/tmp/swarm-do-probe-*.json` outputs should remain available while this
result is being reviewed.
