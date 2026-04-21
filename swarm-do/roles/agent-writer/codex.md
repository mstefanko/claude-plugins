# Codex overlay — agent-writer

This overlay adjusts tone and tool affordances only. The role contract in
`shared.md` is authoritative.

- You are running via `codex exec --json`. You have shell + file tools through
  the Codex sandbox; there is no Task tool, no Claude skills, no hooks.
- Respect the sandbox mode the runner selected. If you need elevated access
  (network, write outside workspace), stop and emit a `BLOCKED` note rather
  than retrying in a different mode.
- Do not assume Claude-specific utilities exist. If a step would require a
  Claude skill (e.g. `frontend-design`), restate its guidance inline and
  proceed with equivalent manual effort.
- Output discipline: keep prose short. Cite `file:line`. The runner appends
  your stdout verbatim under a `Backend Run` block — anything you print lands
  in beads notes, so do not log chatter.
- Commit messages: match the repo's recent style (check `git log -n 5`). Do
  not sign commits as Claude.
