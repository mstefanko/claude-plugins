---
description: "Review the current diff with curated context and risk-based routing"
argument-hint: "[base-ref] [--mode auto|single|focused-swarm|swarm|chunked-swarm] [--intent <text>]"
---

# Review Kit Review

Use the `review` skill in this plugin.

Run a read-only code review for the current repository. Assemble only the context needed for the diff, write a `review-plan` artifact, route by size/risk/user request, then execute the selected path:

- `single` runs the filled single-agent prompt in-session.
- `focused-swarm`, `swarm`, and `chunked-swarm` compile curated bakeoff work orders and delegate ledgered execution to bakeoff when available.
- High-stakes paths may run fresh-context repeats and a cold-start critic before the final synthesis.

Preserve the user's raw arguments as `command_args` in the review plan. Do not create branches, PRs, commits, implementation plans, or code changes from this command.
