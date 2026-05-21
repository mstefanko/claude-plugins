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
    the prompt as natural language or answer the task directly.

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

- [ ] Remote fork diff gets mechanical prompt repair.
  - Prompt: `/bakeoff:run compare https://github.com/pcvelz/superpowers and https://github.com/obra/superpowers, how much has changed in the fork and what is the difference`
  - Expect: task-fit warning; reason names deterministic fork diff evidence; no
    work order is drafted; `draft anyway` is preserved; one or two labeled
    rewrites identify what they fix plus goal and output shape.

- [ ] Selecting a repair option becomes the narrowed prompt.
  - Prompt: same warning, then user replies `1` or `Behavior impact`.
  - Expect: plugin carries forward the original repos and constraints, treats
    the selected rewrite as the revised natural-language request, re-runs task
    fit once, and proceeds to normal preview approval if it passes. It does not
    show another repair menu for the immediate follow-up.

- [ ] Interpretive compare with criteria drafts normally.
  - Prompt: `/bakeoff:run compare https://github.com/pcvelz/superpowers and https://github.com/obra/superpowers for behavior impact, regression risk, and upstreamability`
  - Expect: plugin treats the request as a Bakeoff-shaped compare because the
    user provided decision criteria where independent readers may disagree. It
    drafts a normal preview rather than showing the deterministic-evidence
    repair menu.

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

- [ ] Duplicate acknowledged explores discoverable missing build fields.
  - Prompt: `/bakeoff:run Implement bakeoff ls ordering by finished_at
    descending, with stable fallback for legacy/malformed runs, and add focused
    tests.`, then reply `draft anyway` to the duplicate or weak-fit warning.
  - Expect: plugin's warning distinguishes `inspect <run-id>` from
    `draft anyway` and does not bundle them as one unclear option. After
    `draft anyway`, plugin treats the warning as satisfied for that turn only,
    performs one narrowly targeted read-only repo pass over the `ls` command,
    nearby tests, and existing work-order history, proposes a verifier and edit
    boundary with evidence, states that proposal is not approval, shows the
    normal preview approval prompt, and writes nothing before approval.

- [ ] Ambiguous verifier target asks after exploration.
  - Prompt: `/bakeoff:run Fix the auth tests flaking in CI.`
  - Expect: plugin performs at most one narrowly targeted read-only repo pass
    if auth-related packages or test commands are findable. If multiple
    verifier scopes are plausible, it asks the user to choose among them and
    drafts nothing.

- [ ] Refactor missing behavioral invariants asks the user.
  - Prompt: `/bakeoff:run Refactor default-value resolution in the build
    command. Keep the existing verifier command if you can find it.`
  - Expect: plugin may explore once to propose a verifier, but it still asks
    for the behavioral invariants to preserve. It does not synthesize
    acceptance criteria as "no behavior change" or "existing tests pass".

- [ ] Metric benchmark names harness but omits protected paths.
  - Prompt: `/bakeoff:run Optimize ledger import performance using the
    benchmark harness in internal/ledger/ledger_test.go.`
  - Expect: plugin explores once for the benchmark command and measuring-stick
    files. If discoverable, it proposes protected paths with evidence before
    preview; if not, it asks for the benchmark command and protected paths. It
    does not draft a metric verifier with unprotected harness or fixture files.

- [ ] Missing acceptance criteria with a named package asks for behavior.
  - Prompt: `/bakeoff:run Improve validation errors in internal/commands/validatecmd.`
  - Expect: plugin may inspect the named package for relevant tests or examples,
    but it asks for observable acceptance criteria and does not treat existing
    tests as the user's desired behavior.

- [ ] Re-narrowing after a task-fit warning re-runs the check.
  - Prompt: `/bakeoff:run improve this`, then after the weak-fit warning reply
    `review the diff against main for security issues`.
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
    provider artifacts, recommends `bakeoff rerun <run-id> --judge-only` only
    for research runs when applicable, and proceeds to part 2.

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

## Continuation Recommendation Scenarios

Date added: 2026-05-21

Status: manual regression checklist, derived from the
[artifact-aware continuation plan](artifact-aware-continuation-implementation-plan-2026-05-21.md).

These scenarios cover the optional post-run recommendation in
`commands/run.md` and `skills/bakeoff/SKILL.md`. They are fixture-style
artifact summaries, not committed run directories. Every recommendation must
name the source run id, name the inspected artifact class (`report`,
`decision`, `triage`, `diagnostics`, or `patch`), preserve exact artifact
paths, and stay within the normal `/bakeoff:run` preview and approval flow.

- [ ] `cont-research-plan` recommends planning, not build.
  - Source artifact summary: `work-order.json.type=gather`;
    `decision.json` is parseable; provider statuses are `ok`; `report.md`
    converges on one product/code direction but names no verifier, edit scope,
    or acceptance criteria.
  - Simulated completed-run state: run id `cont-research-plan`, artifacts at
    `runs/cont-research-plan/report.md` and
    `runs/cont-research-plan/decision.json`.
  - Expected recommendation text: `Recommended next step for
    cont-research-plan: draft an implementation plan from this run. I inspected
    report and decision artifacts; the direction is clear, but build is
    premature without an implementation boundary and verifier.`
  - Forbidden recommendation text: `continue`, `build next`, or any build
    work-order preview.
  - Approval behavior when drafted: the planning follow-up is a normal
    `type: "analyze"` work order citing the report and decision paths in
    `background`; it must be previewed, validated, and approved before running.

- [ ] `cont-research-compare` recommends compare with named options.
  - Source artifact summary: `work-order.json.type=gather`;
    `decision.json` is parseable; provider statuses are `ok`; `report.md`
    leaves two named options unresolved.
  - Simulated completed-run state: run id `cont-research-compare`, artifacts
    at `runs/cont-research-compare/report.md` and
    `runs/cont-research-compare/decision.json`.
  - Expected recommendation text: `Recommended next step for
    cont-research-compare: compare <option A> vs <option B>. I inspected
    report and decision artifacts; the research found two viable approaches and
    did not resolve the tradeoff.`
  - Forbidden recommendation text: `build`, `Want to continue?`, or a generic
    continuation prompt without option names.
  - Approval behavior when drafted: the follow-up is a normal `type: "compare"`
    work order that previews named options and criteria before approval.

- [ ] `cont-research-stop` stops or omits continuation.
  - Source artifact summary: `work-order.json.type=gather`;
    `decision.json` is parseable; provider statuses are `ok`; `report.md`
    answers the user's question completely and no action is requested.
  - Simulated completed-run state: run id `cont-research-stop`, artifacts at
    `runs/cont-research-stop/report.md` and
    `runs/cont-research-stop/decision.json`.
  - Expected recommendation text: `Recommended next step for
    cont-research-stop: no follow-up Bakeoff run recommended. I inspected
    report and decision artifacts; the answer is complete and no obvious next
    work order follows.`
  - Forbidden recommendation text: `continue`, `draft another run`, or any
    blind funnel into more Bakeoff work.
  - Approval behavior when drafted: none; no work order is drafted.

- [ ] `cont-compare-plan` recommends a winner-centered plan.
  - Source artifact summary: `work-order.json.type=compare`;
    `decision.json.canonical_winner` is non-null; provider statuses are `ok`;
    integration details, edit boundary, or verifier remain open.
  - Simulated completed-run state: run id `cont-compare-plan`, artifacts at
    `runs/cont-compare-plan/report.md` and
    `runs/cont-compare-plan/decision.json`.
  - Expected recommendation text: `Recommended next step for
    cont-compare-plan: draft an implementation plan around <winner>. I
    inspected report and decision artifacts; the comparison picked a direction,
    but implementation details still need design.`
  - Forbidden recommendation text: `draft a build work order` when verifier or
    edit scope is absent.
  - Approval behavior when drafted: the follow-up is a normal
    `type: "analyze"` planning work order with the winner and prior artifact
    paths in `background`.

- [ ] `cont-review-build-ready` may draft build for approval.
  - Source artifact summary: `work-order.json.type=gather` with
    `facet.id=code-review`; triage artifacts are current; at least one item in
    `triage/final.json` has `classification: "real_issue"`,
    `recommended_action: "fix_now"`, concrete supporting evidence, and narrow
    scope.
  - Simulated completed-run state: run id `cont-review-build-ready`, artifacts
    at `runs/cont-review-build-ready/report.md`,
    `runs/cont-review-build-ready/decision.json`, and
    `runs/cont-review-build-ready/triage/final.json`; the follow-up request
    supplies or repo exploration clearly discovers acceptance criteria and a
    verifier command.
  - Expected recommendation text: `Recommended next step for
    cont-review-build-ready: draft a build work order for approval for the
    triaged finding. I inspected decision and triage artifacts; the issue is
    current, actionable, and narrow, and the follow-up has a verifier.`
  - Forbidden recommendation text: any `bakeoff build` command or file write
    before preview approval.
  - Approval behavior when drafted: the build follow-up must pass all normal
    missing-field checks and require explicit single-work-order approval before
    writing or running.

- [ ] `cont-review-raw` recommends inspect first.
  - Source artifact summary: `work-order.json.type=gather` with
    `facet.id=code-review`; triage is missing, disabled, failed, or stale.
  - Simulated completed-run state: run id `cont-review-raw`, artifacts at
    `runs/cont-review-raw/report.md` and
    `runs/cont-review-raw/decision.json`; no current
    `triage/final.json` is available.
  - Expected recommendation text: `Recommended next step for cont-review-raw:
    inspect this review before drafting build work. I inspected decision and
    triage artifacts; current actionable triage is not available.`
  - Forbidden recommendation text: `draft a build work order` from raw
    findings.
  - Approval behavior when drafted: no build work order is drafted unless the
    user explicitly overrides and supplies the normal build-required fields.

- [ ] `cont-build-winner` recommends selected patch inspection or review.
  - Source artifact summary: `work-order.json.type=build`;
    `decision.json.canonical_winner` is non-null; selected provider has a
    `build/diff.patch` artifact.
  - Simulated completed-run state: run id `cont-build-winner`, artifacts at
    `runs/cont-build-winner/decision.json`,
    `runs/cont-build-winner/diagnostics.json`, and
    `runs/cont-build-winner/providers/claude/build/diff.patch`.
  - Expected recommendation text: `Recommended next step for
    cont-build-winner: inspect or review the selected patch. I inspected
    decision, diagnostics, and patch artifacts; this build already selected a
    winner, so Bakeoff should not apply or rebuild it automatically.`
  - Forbidden recommendation text: `apply`, `merge`, `commit`, `open a PR`, or
    `run another build`.
  - Approval behavior when drafted: a review follow-up is a normal
    `type: "gather"` work order with `facet.id: "code-review"` and a bounded
    patch/diff scope; applying the patch is not part of continuation.

- [ ] `cont-build-unresolved` does not select an arbitrary patch.
  - Source artifact summary: `work-order.json.type=build`;
    `decision.json.canonical_winner` is null; exit code is `3`; provider patch
    artifacts may exist.
  - Simulated completed-run state: run id `cont-build-unresolved`, artifacts at
    `runs/cont-build-unresolved/decision.json` and
    `runs/cont-build-unresolved/diagnostics.json`.
  - Expected recommendation text: `Recommended next step for
    cont-build-unresolved: inspect diagnostics, or run a full build rerun if
    the verifier/provider evidence warrants it. I inspected decision and
    diagnostics artifacts; there is no selected patch.`
  - Forbidden recommendation text: `bakeoff rerun cont-build-unresolved
    --judge-only`, `selected patch`, or treating any provider patch as the
    winner.
  - Approval behavior when drafted: no selected-patch review is drafted unless
    a canonical winner exists.

- [ ] `cont-missing-decision` omits continuation.
  - Source artifact summary: `report.md` is readable, but `decision.json` is
    missing or corrupt.
  - Simulated completed-run state: run id `cont-missing-decision`, artifacts at
    `runs/cont-missing-decision/report.md`; `decision.json` cannot be parsed.
  - Expected recommendation text: no continuation recommendation line appears.
    The normal run summary may separately suggest inspecting or verifying
    artifacts because the decision artifact could not be trusted.
  - Forbidden recommendation text: `Recommended next step for
    cont-missing-decision`, or any recommendation inferred from report prose
    alone.
  - Approval behavior when drafted: no follow-up work order is drafted from
    these artifacts.

- [ ] `cont-custom-out` preserves custom output paths.
  - Source artifact summary: completed gather run under custom
    `--out /tmp/example-runs`; `decision.json` is parseable and recommends a
    planning follow-up.
  - Simulated completed-run state: run id `cont-custom-out`, artifacts at
    `/tmp/example-runs/cont-custom-out/report.md` and
    `/tmp/example-runs/cont-custom-out/decision.json`.
  - Expected recommendation text: `Recommended next step for cont-custom-out:
    draft an implementation plan from this run. I inspected report and decision
    artifacts at /tmp/example-runs/cont-custom-out/report.md and
    /tmp/example-runs/cont-custom-out/decision.json.`
  - Forbidden recommendation text: `runs/cont-custom-out/report.md`,
    `runs/cont-custom-out/decision.json`, or any fabricated default run path.
  - Approval behavior when drafted: the follow-up work order cites the exact
    `/tmp/example-runs/cont-custom-out/report.md` and
    `/tmp/example-runs/cont-custom-out/decision.json` artifact paths in
    `background`.

- [ ] Research exit `4` may recommend judge-only rerun.
  - Source artifact summary: research-shaped work order; `decision.json` is
    parseable; all providers are `ok` or `ok_after_format_retry`; structured
    judge status failed or did not converge.
  - Simulated completed-run state: run id `cont-research-exit-4`, exit code
    `4`, artifacts at `runs/cont-research-exit-4/decision.json`.
  - Expected recommendation text: `Recommended next step for
    cont-research-exit-4: rerun the research judge only. I inspected the
    decision artifact; providers succeeded but the judge did not complete.`
  - Forbidden recommendation text: build advice or report-prose-only
    diagnosis.
  - Approval behavior when drafted: no work order is drafted; the suggested
    command is `bakeoff rerun cont-research-exit-4 --judge-only`.

- [ ] Build exit `4` must not recommend judge-only rerun.
  - Source artifact summary: `work-order.json.type=build`; exit code `4`;
    `decision.json` and `diagnostics.json` are present.
  - Simulated completed-run state: run id `cont-build-exit-4`, artifacts at
    `runs/cont-build-exit-4/decision.json` and
    `runs/cont-build-exit-4/diagnostics.json`.
  - Expected recommendation text: `Recommended next step for
    cont-build-exit-4: inspect diagnostics, or run a full build rerun if the
    structured evidence warrants it. I inspected decision and diagnostics
    artifacts; build judge-only rerun is not supported.`
  - Forbidden recommendation text: `bakeoff rerun cont-build-exit-4
    --judge-only`.
  - Approval behavior when drafted: no build follow-up is drafted from exit
    `4` alone.

## Fast-Path Drafting Scenarios

Date added: 2026-05-20

Status: manual regression checklist, derived from the
[drafting-phase speedups plan](drafting-phase-speedups-implementation-plan-2026-05-20.md)
and the [verification cycle log](drafting-fast-path-experiment-log-2026-05-20.md).

These scenarios cover the `## Drafting Invariants` section of
`commands/run.md` and `skills/bakeoff/SKILL.md` (R1 advisory + R1.6
refactor tightening, R2 no-Write-before-approval, R3 canonical
skeletons, R4 pre-preview validate advisory, R5 embedded backends).
Run them after editing either contract file or after changing any
work-order template referenced by the canonical skeletons.

### Fast-Path Should Trigger

- [ ] Narrow Go package build with explicit AC + gate verifier.
  - Prompt: `/bakeoff:run Order bakeoff ls output by finished_at descending; stable, deterministic fallback for legacy/malformed runs missing or with unparsable finished_at; add focused unit tests for the ordering function. Scope: edit only internal/commands/lscmd/**. Acceptance criteria: newest-first by finished_at; missing/unparsable finished_at after well-formed runs; deterministic secondary key by run id; tests cover happy path, missing finished_at, unparsable finished_at, and ties by run id. Gate verifier: go build ./... && go test ./internal/commands/lscmd/... -run . -count=1. Use two build providers (claude-code and codex) and one claude judge.`
  - Expect: plugin says the request is fast-path-eligible, drafts the
    work order in memory using the **canonical build skeleton**, shows a
    compact preview with a canonical-schema JSON block (`schema_version:
    1` int, `providers[].backend`, `judge.{backend,model,effort}`,
    nested `build` block with `base_ref: "HEAD"` + `verify[].argv:
    ["sh", "-c", ...]` array form, full `budgets` block), and asks for
    `yes` to write+validate+run. Does **not** call `Write` before
    approval. Default-aware notes about non-set fields (e.g.,
    `build.protected_paths`) are allowed in the preview.

- [ ] Single-file change with explicit tests.
  - Prompt: `/bakeoff:run In internal/commands/showcmd/, add a --section flag accepting one of goal|verify|providers|judge that limits which work-order section the command prints. Default output (no flag) must be byte-identical to today. Scope: edit only files inside internal/commands/showcmd/. Acceptance criteria: each --section value prints only the named section; an unknown value exits non-zero with a clear error; with no flag, output equals today's output verbatim. Gate verifier: go build ./... && go test ./internal/commands/showcmd/... -run . -count=1. Use two build providers (claude-code and codex) and one claude judge.`
  - Expect: fast-path preview with canonical schema. No `Write` before
    approval. AC is observable behavior (output byte-identical,
    unknown-value error path), not scope/verifier restatement.

- [ ] Existing matching work-order file is detected and reused.
  - Setup: a `./<id>.work-order.json` already exists on disk that
    matches the request id.
  - Expect: plugin shows the compact preview, notes the file already
    exists with matching content, and offers to reuse it without
    overwriting. No new file is written before approval.

### Fast-Path Fallback Routing (R1 — Missing Required Field)

- [ ] Build request with no gate verifier.
  - Prompt: `/bakeoff:run Add structured logging to internal/commands/buildcmd. Goal: every command path emits a JSON log line with command, exit_code, and duration_ms. Scope: edit only internal/commands/buildcmd/**. Acceptance criteria: every existing command path emits one log line on success, one on failure, and the existing exit codes are unchanged. Use two build providers and one claude judge.`
  - Expect: fast path does not trigger. Because the prompt names a package,
    plugin performs one narrowly targeted read-only pass over
    `internal/commands/buildcmd`, nearby tests, and command conventions, then
    proposes a verifier with evidence. If one verifier is clearly strongest, it
    may use that proposal in a read-only preview; if multiple are plausible, it
    asks the user to choose. It writes nothing before normal approval.

- [ ] Build request with no acceptance criteria (non-refactor).
  - Prompt: `/bakeoff:run Add a --json mode to bakeoff doctor. Scope: edit only internal/commands/doctorcmd/. Gate verifier: go build ./... && go test ./internal/commands/doctorcmd/... -count=1. Use two build providers and one claude judge.`
  - Expect: plugin asks for AC as observable behaviors (e.g., what
    `--json` should emit, exit-code parity, JSON structure
    expectations) and **does not draft** until supplied. Synthesizing
    "no behavior change" or "tests pass" is a contract failure.

- [ ] Refactor request without behavioral invariants (R1.6 edge case).
  - Prompt: `/bakeoff:run Refactor internal/workorder/workorder.go to extract default-value resolution into a small helper. Scope: edit only internal/workorder/workorder.go. Gate verifier: go build ./... && go test ./internal/workorder/... -count=1. Use two build providers and one claude judge.`
  - Expect: plugin cites the refactor-edge-case rule by name
    (paraphrases such as "the contract's refactor-edge-case rule",
    "the contract's load-bearing refactor edge case", or "the contract
    flags refactors as a known soft spot" are all acceptable), and asks
    for **specific behavioral invariants** (public API unchanged,
    byte-identical defaults, resolution order preserved, test
    coverage). Does **not** synthesize "no behavior change", "existing
    tests pass", or "single responsibility" as AC — those are the
    anti-synthesis patterns. May offer multi-select options or a
    "paste exact behaviors" escape hatch.

- [ ] Metric benchmark with no protected paths.
  - Prompt: `/bakeoff:run Improve the performance of bakeoff ls when there are thousands of runs in the ledger. Goal: median latency under 200ms for 5000 runs. Gate verifier: go test ./internal/commands/lscmd/ -bench=. -benchmem. Scope: edit only internal/commands/lscmd/**. Use two build providers and one claude judge.`
  - Expect: fast path does not trigger. Plugin performs one narrowly targeted
    read-only pass to identify benchmark harness, fixture, golden, or generated
    expected-output files. If found, it proposes protected paths with evidence
    and may use them in a read-only preview; if not found, it asks for the
    measuring-stick files or a verifier setup choice. It does not draft a metric
    verifier with unprotected harness or fixture files, and writes nothing
    before approval.

- [ ] Vague target ("the auth thing", "the slow part").
  - Prompt: `/bakeoff:run Fix the auth thing that's been flaky. Acceptance criteria: auth doesn't flake. Gate verifier: the auth tests. Use two build providers.`
  - Expect: plugin surfaces a task-fit warning naming the vague target,
    the AC-circularity ("auth doesn't flake" restates the goal), and
    the unspecified verifier ("the auth tests" is not concrete). Asks
    for a concrete file/route/symptom, real AC, and exact verifier
    argv before drafting.

### Fast-Path Must NOT Trigger (Routing / Mode Conflicts)

- [ ] "Build a comparison matrix" routes to compare, not build.
  - Prompt: `/bakeoff:run Build a comparison matrix of three approaches we could take to running provider sandboxes (local container, ephemeral worktree, remote VM). Include build/run isolation, secret handling, and rollback story. Use two providers.`
  - Expect: plugin classifies as `type: "compare"` research, not
    build mode. Drafts a compare work order with the named dimensions
    as the evidence surface. Does not draft `type: "build"` even
    though the verb "build" appears in the prompt.

- [ ] Review of the codebase with no bounded target.
  - Prompt: `/bakeoff:run Review the codebase for security issues. Use two providers and one judge.`
  - Expect: task-fit warning naming the unbounded scope ("the codebase
    doesn't name a branch, PR, diff, file set, or local-change
    scope"). Offers narrowing options (local changes, recent diff,
    file set, subsystem). Does not draft until narrowed.

- [ ] Explicit multi-lens review goes through the multi-lens preview.
  - Prompt: `/bakeoff:run Multi-lens code review of the current local changes: security, performance, design clarity. Use four providers and one claude judge.`
  - Expect: multi-lens preview, not single-work-order fast path.
    Three separate work-order files staged, cost-note included,
    `write and run` approval phrase, per-lens `bakeoff research`
    commands listed.

- [ ] Obvious 2-3 independent parts trigger a split proposal.
  - Prompt: `/bakeoff:run Three independent changes I want done in parallel: (1) add --json to bakeoff doctor; (2) order bakeoff ls by finished_at descending; (3) add --limit N to bakeoff ls. Each has its own acceptance criteria and tests. Use two build providers and one claude judge.`
  - Expect: split proposal preview AND missing-field check stacked on
    top (verifier argv per part + AC-as-behaviors per part). Plugin
    does not draft until both information needs are answered.

- [ ] Path-like missing input is a CLI path error.
  - Prompt: `/bakeoff:run ./missing.work-order.json`
  - Expect: plugin verifies the file is absent (e.g., `ls -la`),
    reports the path error per contract, and lists the two paths
    forward: provide an existing work-order path, or describe the
    task in natural language without the `./` prefix or `.json`
    suffix. **Does not** reinterpret the path as a natural-language
    request.

- [ ] `scope: web` on a build prompt rejects or routes to gather.
  - Prompt: `/bakeoff:run Crawl the latest Go release notes and write a summary of breaking changes that affect this repo. Scope: web. Acceptance criteria: a docs/go-release-summary.md file listing breaking changes. Gate verifier: go build ./.... Use two build providers and one claude judge.`
  - Expect: plugin cites the contract rule ("Reject or repair build
    work orders with any provider scope: 'web'."), notes the gate
    verifier doesn't verify the deliverable, and offers three
    narrowings: `draft anyway` (with override caveats), research
    framing (`type: "gather"` with providers browsing/citing
    sources), or a stronger verifier + local source. **Does not**
    silently coerce `scope: web` to `scope: codebase`.

### R2/R3/R5 Always-On Invariants (Sanity Checks)

- [ ] No `Write` before approval, fast path or careful.
  - Prompt: any of the positive fast-path prompts above.
  - Expect: in the transcript, no `Write` tool call appears before
    the approval line in the model's response. The first mutating
    tool call is after the user's affirmative reply.

- [ ] Canonical schema verbatim — no invented fields.
  - Prompt: a positive fast-path prompt that produces a preview JSON
    block.
  - Expect: the preview JSON uses `schema_version: 1` (int),
    `providers[].backend` (not `kind`/`name`/`provider`),
    `providers[].scope: "codebase"` (not `"local"`/`"repo"`/`"worktree"`),
    `judge: {backend, model, effort}` (not `{id, kind, role}`), nested
    `build.verify[].argv` array (not top-level `gates`/`verifiers` with
    `command` string), full `budgets` block (with
    `max_output_bytes`/`heartbeat_seconds`/etc), and **no** top-level
    `acceptance_criteria` or `scope` fields. Background contains the
    AC as bullets.

- [ ] No CLI probing during drafting.
  - Prompt: any of the prompts above.
  - Expect: in the transcript, the model does not invoke
    `bakeoff providers list`, `bakeoff --help`, `bakeoff init`, or
    `bakeoff doctor` from the drafting flow. Backends (`claude`,
    `codex`) and schema are taken from the embedded skill text.

### R4 Pre-Preview Validate (Advisory)

- [ ] Pre-preview validate is encouraged but not required.
  - Prompt: a positive fast-path prompt.
  - Expect: the model **may** invoke `bakeoff validate` against an
    in-memory JSON (via `/tmp/...` temp file) before showing the
    preview. If skipped, the post-write `bakeoff validate` step
    catches any schema drift before `bakeoff build` or
    `bakeoff research` runs. **Either ordering is acceptable** — the
    user-visible safety net is the post-write validate, not the
    pre-preview one.

### Known Soft Spot (Documented; Not A Bug)

- [ ] Refactor + missing AC: model may synthesize even with R1.6.
  - Expected behavior under R1.6 is the model asks (verified n=3 on
    2026-05-20T18:15Z, see experiment log). **However**, if the model
    ever does synthesize on a refactor anyway (with self-labeling),
    the operator should reject the preview and supply explicit
    behavioral invariants. This is documented as a known limitation
    backstopped by the preview-then-approve flow.
