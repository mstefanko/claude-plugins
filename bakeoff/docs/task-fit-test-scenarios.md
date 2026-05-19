# Task-Fit And Clean-Split Test Scenarios

Date: 2026-05-19

Status: manual regression checklist

Use this checklist after changing `skills/bakeoff/SKILL.md`, `commands/run.md`,
or user-facing Bakeoff drafting docs. These are prompt-only or command-review
checks; the Go CLI does not need new tests for the v1 task-fit and split
behavior.

## Checklist

- [ ] Existing work-order path bypasses advisory checks.
  - Prompt: `/bakeoff:run examples/gather.work-order.json`
  - Expect: plugin runs the existing validate-and-route flow with no task-fit
    warning and no split proposal.

- [ ] Formatter-only work shows the task-fit warning.
  - Prompt: `/bakeoff:run format these files`
  - Expect: plugin says the request may not need Bakeoff, cites formatter-only
    work as the reason, and does not draft JSON until explicit confirmation.

- [ ] Build request with no verifier asks for verifier or confirmation.
  - Prompt: `/bakeoff:run build competing fixes for the cache bug`
  - Expect: plugin asks for a project test command, regression test, benchmark,
    or explicit `draft anyway` confirmation before drafting.

- [ ] Conversational opt-out bypasses only the task-fit warning for the turn.
  - Prompt: `/bakeoff:run build competing fixes for the cache bug`, then reply
    `draft anyway` to the weak-fit warning.
  - Expect: plugin treats the warning as satisfied for that turn, but still
    asks for any missing required build fields such as a gate verifier. There
    is no task-fit flag or persistent opt-out.

- [ ] Weak-fit warning does not also propose a split.
  - Prompt: `/bakeoff:run format these files and update the changelog`
  - Expect: plugin asks for task-fit confirmation or narrowing first, and does
    not propose split work orders in the same response.

- [ ] Normal review drafts a single review work order.
  - Prompt: `/bakeoff:run review this diff against main`
  - Expect: plugin drafts one `type: "gather"` work order with
    `facet.id: "code-review"` and the standard approval prompt.

- [ ] Concrete analyze request drafts a single analyze work order.
  - Prompt: `/bakeoff:run analyze why import retries duplicate receipts; use logs in <path> and files under internal/import`
  - Expect: plugin drafts one `type: "analyze"` work order with the supplied
    symptom, evidence surface, and scope.

- [ ] Two independent research goals trigger a split proposal.
  - Prompt: `/bakeoff:run research where receipt dedupe happens and compare SQLite FTS vs Tantivy for product search`
  - Expect: plugin proposes exactly two independent work orders, asks for
    `split`, and does not show JSON until the split is accepted.

- [ ] Sequential multi-step request does not trigger a split proposal.
  - Prompt: `/bakeoff:run analyze the failing import first, then use that answer to design the fix`
  - Expect: plugin does not split because the second part depends on the first
    result; it either drafts one valid work order or asks for narrowing.

- [ ] Split preview is scan-friendly and explicit.
  - Prompt: accept the independent two-part split.
  - Expect: plugin shows a one-line summary above each JSON block, lists
    filenames like `./<base>.part-1.work-order.json`, lists the commands to run,
    and asks for `write and run` approval.

- [ ] Split filename and run-id collisions apply after `.part-N`.
  - Setup: assume `runs/base.part-1` and `base.part-1.work-order.json` already
    exist.
  - Expect: plugin uses names such as `base.part-1-YYYYMMDD` or
    `base.part-1-2`; it does not use `base-YYYYMMDD.part-1`, and it does not
    overwrite existing files.

- [ ] Split validation failure stops before execution.
  - Setup: make part 2 invalid during command review.
  - Expect: plugin validates all parts before running any; on validation error,
    it reports the failing file and error, repairs the JSON, and shows the full
    final set again before asking for approval.

- [ ] Split execution continues after exit `3`.
  - Setup: part 1 completes with exit `3`.
  - Expect: plugin treats exit `3` as a completed handoff with unresolved
    disagreement and proceeds to part 2.

- [ ] Split execution stops on real failures or interruption.
  - Setup: part 1 exits `1`, `2`, or `130`.
  - Expect: plugin stops before remaining parts, summarizes completed parts and
    the failed or interrupted part, and asks before continuing.

- [ ] Split summary stays separate.
  - Prompt: after all split parts complete.
  - Expect: final response reports each run independently and avoids "overall
    winner", merged patch, merged answer, or cross-run synthesis unless the user
    asks separately.
