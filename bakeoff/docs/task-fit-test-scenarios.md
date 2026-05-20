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

- [ ] Multiple review concerns without separate-lens wording stay single-run.
  - Prompt: `/bakeoff:run review this diff against main for security and tests`
  - Expect: plugin drafts one normal `code-review` work order with security and
    tests in the shared focus; it does not draft separate lens files.

- [ ] Explicit two-lens review shows a multi-lens preview.
  - Prompt: `/bakeoff:run review this diff against main with security and tests as separate lenses`
  - Expect: plugin previews two separate review runs, uses filenames and run ids
    like `<base>.security` and `<base>.tests`, includes the cost note with a
    worst-case wall-clock estimate, keeps verification/triage on, and asks for
    `write and run`.

- [ ] `review swarm` without lenses asks for lens names after task fit passes.
  - Prompt: `/bakeoff:run review swarm this PR`
  - Expect: plugin asks which 2-3 lenses to run and suggests common choices. It
    does not ask for lenses if the review scope is missing or unbounded.

- [ ] Casual or domain use of `swarm` does not trigger multi-lens.
  - Prompt: `/bakeoff:run review files under internal/swarm for security and tests`
  - Expect: plugin treats `swarm` as part of the target/domain, not a
    multi-lens request, and drafts one normal review unless the user asks for
    separate lenses.

- [ ] Multi-lens approval requires the exact multi-file phrase.
  - Prompt: accept a multi-lens preview with `yes`.
  - Expect: plugin asks for `write and run` because multiple files and runs are
    being approved. It does not write files on plain `yes`.

- [ ] `show <lens>` prints one lens draft when combined JSON is too long.
  - Prompt: after a multi-lens preview says full JSON is verbose, reply
    `show security`.
  - Expect: plugin prints only the security work-order JSON, lists the other
    available `show <lens>` choices, and repeats the `write and run` approval
    question.

- [ ] Too many lenses requires narrowing or explicit approval.
  - Prompt: `/bakeoff:run review this diff against main with security, performance, UX, tests, and reliability lenses`
  - Expect: plugin warns that this would run five separate review runs, asks the
    user to narrow to 2-3 lenses or say `run all lenses`, and drafts nothing
    until clarified.

- [ ] Unknown lens handling distinguishes narrow from vague.
  - Prompt: `/bakeoff:run review this diff against main with billing invariants as a separate lens`
  - Expect: plugin accepts a custom `billing-invariants` lens.
  - Prompt: `/bakeoff:run review this diff against main with quality as a separate lens`
  - Expect: plugin asks one clarification question because `quality` is vague.

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

- [ ] Multi-lens validation failure stops before execution.
  - Setup: make one generated lens work order invalid during command review.
  - Expect: plugin validates all lens files before running any; on validation
    error, it reports the failing file and error, repairs the JSON, and shows
    the final set again before asking for approval.

- [ ] Multi-lens `--no-triage` applies to every lens.
  - Prompt: `/bakeoff:run review this diff against main with security and performance as separate lenses --no-triage`
  - Expect: plugin passes `--no-triage` to each lens run, omits verification
    from the cost estimate, and marks final findings raw and unverified.

- [ ] Multi-lens execution stops on failed lens and reports progress.
  - Setup: first lens exits `0`, second lens exits `1`, `2`, `4`, or `130`.
  - Expect: plugin summarizes completed and failed lenses and asks before
    continuing. Exit `3`, if encountered, is marked as a completed unusual
    handoff and untriaged unless triage artifacts exist.

- [ ] Completed multi-lens runs produce a persisted summary.
  - Prompt: after approved security/performance/UX lens runs finish.
  - Expect: plugin reads available `report.md`, `decision.json`, and triage
    artifacts; writes `<out>/<base>.multi-lens-summary.md`; reports run ids,
    report paths, triage state/paths, triage counts when available, top
    actionable findings by lens, overlaps, clean lenses, caveats, `bakeoff show`
    commands, and the summary path using the documented summary sections.

- [ ] Partial multi-lens runs produce an explicit partial status.
  - Setup: one lens completed, one lens failed, and one lens was not run.
  - Expect: plugin labels the conversation summary and any written summary file
    as partial, lists completed/stopped/remaining lenses, and asks for
    `continue lenses` before running the remaining lens.

- [ ] Multi-lens synthesis is a separate approval step.
  - Prompt: after the summary, user asks for synthesis.
  - Expect: plugin drafts a normal `type: "analyze"` work order over the
    completed reports and triage files, constrains it to dedupe existing
    findings into one prioritized fix plan, and asks for approval before
    writing or running.
