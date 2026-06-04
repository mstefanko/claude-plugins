---
description: "Review a diff, plan, or implementation-vs-plan target with curated context and risk-based routing"
argument-hint: "[base-ref|plan-path] [--mode auto|single|focused-swarm|swarm|chunked-swarm] [--intent <text>] [--approved-plan <path>]"
---

# Review Kit Review

Use the `review` skill in this plugin.

Run a read-only review for the current repository. Targets may be code diffs,
plans before implementation, or implementation diffs checked against an
approved plan. Assemble only the context needed for the target, write a
`review-plan` artifact, route by size/risk/user request, then execute the
selected path:

- `single` runs the filled single-agent prompt in-session.
- `focused-swarm`, `swarm`, and `chunked-swarm` compile curated bakeoff work orders and delegate ledgered execution to bakeoff when available.
- High-stakes paths may run fresh-context repeats and a cold-start critic before the final synthesis.

Preserve the user's raw arguments as `command_args` in the review plan. Do not create branches, PRs, commits, implementation plans, or code changes from this command.
Write `approved-plan.md` only when the user explicitly approves a reviewed plan
or selects it as the implementation baseline.
