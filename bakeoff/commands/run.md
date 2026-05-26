---
description: Draft a work order, preview it, then validate and run on approval
argument-hint: "<work-order-path | request> [--run-id ID] [--out runs] [--base REF] [--diff] [--changed-files] [--quiet] [--keep-worktrees] [--no-triage] [--no-repo-layout]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(${CLAUDE_PLUGIN_ROOT}/scripts/bakeoff-ensure-cli:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/bakeoff draft-build:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/bakeoff validate:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/bakeoff research:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/bakeoff build:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/bakeoff rerun:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/bakeoff escalate:*), Bash(bakeoff draft-build:*), Bash(bakeoff validate:*), Bash(bakeoff research:*), Bash(bakeoff build:*), Bash(bakeoff rerun:*), Bash(bakeoff escalate:*), Bash(git status:*), Bash(git diff:*), Bash(git rev-parse:*)
---

# /bakeoff:run

Use the `bakeoff-run` skill for the entire workflow. Treat this command's
arguments and the user's request as input to that skill.

Keep route-advisor wording and mode-routing examples in the skill/docs; this
shim only delegates to `bakeoff-run`.

Do not satisfy the requested research, review, comparison, analysis, or build
inline. Do not call provider CLIs directly; only the Bakeoff CLI may launch
providers. If the `bakeoff-run` skill is unavailable, stop and report that the
plugin install or routing is incomplete.
