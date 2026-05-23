---
description: Preview or run one post-run Bakeoff provider escalation
argument-hint: "SOURCE_RUN_ID --provider gemini[:model] --mode independent|witness|dispute [--dry-run] [--run-id ID] [--out runs] [--scope codebase|web|mixed] [--no-triage] [--no-repo-layout]"
allowed-tools: Read, Bash(${CLAUDE_PLUGIN_ROOT}/scripts/bakeoff-ensure-cli:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/bakeoff escalate:*), Bash(bakeoff escalate:*)
---

# /bakeoff:escalate

Use `bakeoff escalate` for this workflow. Always preview with `--dry-run`
unless the user already supplied an explicit mode and clearly approved running
that mode.

Escalation adds one provider to an existing non-build research or code-review
run. It writes a new run directory and never mutates the source run.

Modes:

- `independent`: fresh third answer.
- `witness`: audit the current result.
- `dispute`: focus only on contested points.

Do not offer build escalation, patch application, branch/commit/PR automation,
or a synthesized third patch.
