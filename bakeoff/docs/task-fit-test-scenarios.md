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
    warning and no split proposal. It does not summarize or answer from the
    file contents alone.

- [ ] CLI preflight is mandatory.
  - Setup: make `scripts/bakeoff-ensure-cli --check` exit `2`.
  - Expect: plugin stops and directs the user to install Go 1.24+, run
    `/bakeoff:setup`, set `BAKEOFF_GO_BINARY`, or use release setup. It does
    not draft or run.
  - Setup: make `scripts/bakeoff-ensure-cli --check` exit non-zero other than
    `2`.
  - Expect: plugin surfaces the check output as an unexpected CLI resolution
    failure and directs the user to `/bakeoff:doctor`. It does not draft or run.

- [ ] Missing path-like input is a path error only.
  - Prompt: `/bakeoff:run docs/does-not-exist.work-order.json`
  - Expect: plugin reports the missing path-like input and does not reinterpret
    the prompt as natural language or answer inline.

- [ ] Empty request asks for input.
  - Prompt: `/bakeoff:run`
  - Expect: plugin asks for a work-order path or natural-language request. It
    does not infer a task from prior conversation or flags alone.

- [ ] Formatter-only work shows the task-fit warning.
  - Prompt: `/bakeoff:run format these files`
  - Expect: plugin says the request may not need Bakeoff, cites formatter-only
    work as the reason, and does not draft JSON until explicit confirmation.

- [ ] Build request with no verifier asks for verifier or confirmation.
  - Prompt: `/bakeoff:run build competing fixes for the cache bug`
  - Expect: plugin asks for a project test command, regression test, benchmark,
    or explicit `draft anyway` confirmation before drafting.

- [ ] Build request with verifier drafts a build work order.
  - Prompt: `/bakeoff:run build competing fixes for the cache bug; verify with go test ./internal/cache`
  - Expect: plugin drafts one `type: "build"` work order with a gate verifier
    and asks for approval. It does not implement a fix inline.

- [ ] Comparison request drafts a compare work order.
  - Prompt: `/bakeoff:run compare SQLite FTS vs Tantivy for product search using files under internal/search`
  - Expect: plugin drafts one `type: "compare"` work order with the options and
    evidence surface. It does not answer the comparison inline.

- [ ] "Build a comparison/report/matrix" routes to research.
  - Prompt: `/bakeoff:run build a comparison matrix for SQLite FTS vs Tantivy`
  - Expect: plugin treats "build" as a request to produce a research artifact,
    not code patches, and drafts a research-shaped work order unless the user
    explicitly asks providers to edit code.

- [ ] Conversational opt-out bypasses only the task-fit warning for the turn.
  - Prompt: `/bakeoff:run build competing fixes for the cache bug`, then reply
    `draft anyway` to the weak-fit warning.
  - Expect: plugin treats the warning as satisfied for that turn, but still
    asks for any missing required build fields such as a gate verifier. There
    is no task-fit flag or persistent opt-out.

- [ ] Re-narrowing after a task-fit warning re-runs the check.
  - Prompt: `/bakeoff:run improve this`, then after the weak-fit warning reply
    `narrow it to: review the diff against main for security issues`.
  - Expect: plugin re-runs the task-fit check on the narrowed prompt, finds it
    is no longer a weak fit, and proceeds to normal review drafting without
    requiring `draft anyway`.

- [ ] Weak-fit warning does not also propose a split.
  - Prompt: `/bakeoff:run format these files and update the changelog`
  - Expect: plugin asks for task-fit confirmation or narrowing first, and does
    not propose split work orders in the same response.

- [ ] Normal review drafts a single review work order.
  - Prompt: `/bakeoff:run review this diff against main`
  - Expect: plugin drafts one `type: "gather"` work order with
    `facet.id: "code-review"` and the standard approval prompt. It does not
    list findings directly.

- [ ] Single-review approval accepts the cross-mode phrase.
  - Prompt: accept a normal single review preview with `write and run`.
  - Expect: plugin treats it as explicit approval, writes one work-order file,
    validates it, and runs `bakeoff research`. It does not infer a split or
    multi-lens run from the phrase.

- [ ] Single work-order approval accepts plain affirmatives.
  - Prompt: accept a single work-order preview with `yes`, `y`, `approve`, or
    `run it`.
  - Expect: plugin treats each as explicit approval, writes one work-order
    file, validates, and runs. This differs from split and multi-lens, which
    both require the exact `write and run` phrase.

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
    symptom, evidence surface, and scope. It does not explain the root cause
    directly.

- [ ] Two independent research goals trigger a split proposal.
  - Prompt: `/bakeoff:run research where receipt dedupe happens in
    internal/import and compare SQLite FTS vs Tantivy for product search using
    files under internal/search`
  - Expect: plugin proposes exactly two independent work orders, asks for
    `split`, and does not show JSON until the split is accepted. Task-fit
    does not fire because each part names its own scope and evidence surface.

- [ ] Sequential multi-step request does not trigger a split proposal.
  - Prompt: `/bakeoff:run analyze the failing import first, then use that answer to design the fix`
  - Expect: plugin does not split because the second part depends on the first
    result; it either drafts one valid work order or asks for narrowing.

- [ ] Split preview is scan-friendly and explicit.
  - Prompt: accept the independent two-part split.
  - Expect: plugin shows a compact preview row for each part with id, type,
    goal, providers, and judge; lists filenames like
    `./<base>.part-1.work-order.json`; lists the commands to run; and asks for
    `write and run` approval. Full JSON blocks appear only when the combined
    draft fits the 120-line / 10 KB preview budget; otherwise the plugin says
    the JSON is verbose and lists `show part-N` choices.

- [ ] Split approval requires the exact multi-file phrase.
  - Prompt: accept a split preview with `yes`.
  - Expect: plugin asks for `write and run` because multiple files and runs are
    being approved. It does not write files on plain `yes`.

- [ ] Split filename and run-id collisions apply after `.part-N`.
  - Setup: assume `runs/base.part-1` and `base.part-1.work-order.json` already
    exist.
  - Expect: plugin uses names such as `base.part-1-2`; it does not use date
    suffixes or overwrite existing files.

- [ ] Split with user-supplied `--run-id` appends `.part-N` to that run id.
  - Prompt: accept a two-part split for a prompt that included
    `--run-id custom-base`.
  - Expect: plugin uses run ids `custom-base.part-1` and `custom-base.part-2`,
    work-order ids and filenames matching, and applies the same collision
    policy after appending `.part-N`.

- [ ] Editing one part of a split draft re-shows the full set.
  - Prompt: accept a two-part split preview, then reply
    `change part 2 to use codex only`.
  - Expect: plugin updates part 2, shows the final set again for all parts
    with the same preview rules, and asks for `write and run` approval again.
    It does not carry forward the prior approval.

- [ ] `show part-N` prints one split part when combined JSON is too long.
  - Prompt: after a split preview says full JSON is verbose, reply
    `show part-1`.
  - Expect: plugin prints only the part-1 work-order JSON, lists the other
    available `show part-N` choices, and repeats the `write and run` approval
    question.

- [ ] Split validation failure stops before execution.
  - Setup: make part 2 invalid during command review.
  - Expect: plugin validates all parts before running any; on validation error,
    it reports the failing file and error, repairs the JSON, and shows the
    final set again with the same preview rules (compact rows plus JSON only
    when the combined draft is small enough) before asking for exact
    `write and run` approval.

- [ ] Split execution continues after exit `3`.
  - Setup: part 1 completes with exit `3`.
  - Expect: plugin treats exit `3` as a completed handoff with unresolved
    disagreement and proceeds to part 2.

- [ ] Split execution continues after exit `4`.
  - Setup: part 1 completes with exit `4`.
  - Expect: plugin treats exit `4` as a decision-incomplete handoff with durable
    provider artifacts, recommends `bakeoff rerun <run-id> --judge-only` when
    applicable, and proceeds to part 2.

- [ ] Split execution stops on real failures or interruption.
  - Setup: part 1 exits `1`, `2`, or `130`.
  - Expect: plugin stops before remaining parts, summarizes completed parts and
    the failed or interrupted part, and asks before continuing.

- [ ] Split summary stays separate.
  - Prompt: after all split parts complete.
  - Expect: final response reports each run independently and avoids "overall
    winner", merged patch, merged answer, or cross-run synthesis unless the user
    asks separately.

- [ ] Mixed-type splits route mode-specific flags per part.
  - Prompt: accept a two-part split where part 1 is `build` and part 2 is
    `gather`, with `--keep-worktrees --base main --diff` in the original
    invocation.
  - Expect: plugin passes `--keep-worktrees` only to the build part, passes
    `--base` and `--diff` only to the gather part, and stops before execution
    if a mode-specific flag is supplied for the wrong final type on any part.

- [ ] Ordered gate sequence runs task-fit, then multi-lens, then clean-split.
  - Prompt: `/bakeoff:run improve the API` (a vague request).
  - Expect: plugin surfaces the task-fit warning first and does not propose a
    multi-lens run or split in the same response. After the user narrows the
    request to one that explicitly asks for multi-lens review, plugin shows
    the multi-lens preview without first proposing a generic split. After the
    user narrows the request to two independent research goals, plugin shows
    the clean-split proposal.

- [ ] Multi-lens validation failure stops before execution.
  - Setup: make one generated lens work order invalid during command review.
  - Expect: plugin validates all lens files before running any; on validation
    error, it reports the failing file and error, repairs the JSON, and shows
    the final set again before asking for exact `write and run` approval.

- [ ] Multi-lens `--no-triage` applies to every lens.
  - Prompt: `/bakeoff:run review this diff against main with security and performance as separate lenses --no-triage`
  - Expect: plugin passes `--no-triage` to each lens run, omits verification
    from the cost estimate, and marks final findings raw and unverified.

- [ ] Multi-lens cost estimate handles non-default provider counts.
  - Setup: user asks for a multi-lens review with one provider or three
    providers in the generated draft.
  - Expect: plugin names the provider count in the preview, counts one worker
    phase per lens because providers run in parallel, and does not hardcode
    "two reviewers" in user-facing text.

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
