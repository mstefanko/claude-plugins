# Bakeoff session audit transcript

Compact transcript of a single /bakeoff:run session, 2026-05-23. Goal of the
session: review whether three Bakeoff subsystems (capability cache
invalidation, transient-failure handling, required-scope semantics) are
"strong enough".

## Turn 1 - user
/bakeoff:run with arguments: "research/review whether capability cache
invalidation, transient-failure handling, and required-scope semantics are
strong enough."

## Turn 2 - assistant: drafting preview
Preview table fields: id=bakeoff-robustness-review,
file=./bakeoff-robustness-review.work-order.json, type=gather (facet
code-review), providers=claude/sonnet high + codex/gpt-5.5 high (codebase),
judge=claude/opus xhigh, budget=900s / 60000 bytes, scope_policy=best_effort,
triage=enabled, run cmd=bakeoff research <path>.

Goal: audit robustness of three subsystems.

Focus anchors (three bullets):
- Capability cache - internal/provider/provider.go (CapabilityRegistry,
  capabilityEntry, DetectScopeCapabilities). Cache is sync.Mutex-guarded
  map[string]capabilityEntry; identify whether any invalidation path exists
  (CLI upgrade, version drift, mid-run reinstall, error-state re-probing) and
  whether the lack of invalidation is a real risk.
- Transient-failure handling - internal/runner/classify.go (ClassifyFailure)
  and call sites. Verify which classes drive retry/backoff and which only
  surface in artifacts, whether heuristics over/under-match, and whether
  silent reclassification could mask non-transient failures.
- Required-scope semantics - internal/scope/scope.go (BuildExecution,
  enforcement modes advisory/best_effort, scope kinds mixed/codebase/web).
  Determine whether anything stronger than best_effort exists, whether silent
  fallback when capabilities aren't advertised undermines a user's "codebase"
  or "web" intent, and whether "required" semantics are needed.

Acceptance criteria (three bullets, all observable in the report).

Final ask: "Reply yes / approve / run it to write, validate, and run. Reply
show to print the full JSON. Or tell me what to change (e.g., add a lens,
narrow scope, change providers)."

## Turn 3 - user
"yes"

## Turn 4 - assistant: write, validate, run
Wrote bakeoff-robustness-review.work-order.json. First validate failed:
"providers[0].id is required". Read examples/review.work-order.json, fixed
shape (added providers[].id, switched budgets to wall_clock_seconds /
max_output_bytes / heartbeat / overrun, changed facet.include/exclude from
file globs to descriptive criteria, added facet.kind=generic). Revalidated:
"valid work order" with one advisory warning about background phrase
"decision/report" being path-like. Proceeded per skill rules ("warnings are
advisory when validation exits successfully"). Launched bakeoff research in
background.

## Turn 5 - assistant: research run completed
Background command exit code 1.

Table:
- run id: 2026-05-23-fddc
- mode: gather (code-review)
- providers: claude ok (19.3 KB, 300s), codex ok (15.1 KB, 192s)
- judge: claude/opus ok (163s), result: structured_union
- source findings: 31 selected before triage
- triage: FAILED (exit_error) - findings unverified
- exit code: 1 because triage failed; research itself succeeded
- report: runs/2026-05-23-fddc/report.md
- triage dir present but only stderr/stdout/status, no final.json

Caveat: 31 findings are raw / unverified.

Single recommended next step: bakeoff triage 2026-05-23-fddc --force.
Note that stderr / status.json would explain the failure on a second attempt.

## Turn 6 - user
"Can we bring in gemini to only do the triage pass"

## Turn 7 - assistant: explained CLI surface, offered witness
Stated: bakeoff triage CLI flags are only --dry-run, --force, --json, --out,
--quiet. No --provider override. Triage uses the work order's judge.

Said the closest fit is a witness escalation, citing the skill's witness
definition ("broad sanity check of the report, decision, judge passes, or
triage"). Offered the dry-run command:

  bakeoff escalate 2026-05-23-fddc --provider gemini --mode witness --dry-run

Did NOT recommend dispute mode first or even mention it as an alternative,
despite the skill defining dispute for "ties, conflicts, unknowns, judge
caveats, kept-from-nonwinner material, or triage gaps". The user's situation
was a triage gap.

## Turn 8 - user
"yes"

## Turn 9 - assistant: witness dry-run preview
Dry-run preview table: mode=witness, provider=gemini/pro, cost=1 provider
call + 0 judge + triage=yes. Asked "Reply approve witness (or yes, run it) to
execute the live escalation. Or change something (e.g., --no-triage to skip
auto-triage, swap to --mode dispute to focus only on the failed triage's
contested points, or pick a different provider)."

(This is where dispute first appears as an alternative.)

## Turn 10 - user
"approve witness"

## Turn 11 - assistant: live witness run completed
Table:
- escalation run id: 2026-05-23-276a
- source run: 2026-05-23-fddc
- mode: witness
- gemini: ok (23.3s), result: escalation_advisory_supported
- triage: succeeded - 0 items, 0 fix-now
- report: runs/2026-05-23-276a/report.md

Interpretation paragraph: escalation triage runs on the escalation provider's
new findings (Gemini's), not the source 31. Witness mode produced no new
disputes, so triage had nothing to score. The source 31 findings remain
unverified per-finding.

Offered three next steps in order of cost: (1) read source report, (2)
bakeoff triage --force, (3) bakeoff escalate ... --mode dispute --dry-run.

## Turn 12 - user
"run a dispute"

## Turn 13 - assistant: dispute dry-run preview
Preview table: mode=dispute, provider=gemini/pro, cost=1 provider + 0 judge
+ triage=yes. Asked "Reply approve dispute (or yes, run it) to execute live.
Triage will run after Gemini's dispute pass and verify per-finding
actionability - this is the closest fit to 'Gemini does the triage' since
the original 31 findings are exactly the contested surface (failed
claude/opus triage left them unverified)."

User: "approve dispute". Ran live.

## Turn 14 - assistant: live dispute run completed
Table:
- dispute run id: 2026-05-23-b6f3
- source run: 2026-05-23-fddc
- mode: dispute
- gemini: ok_after_format_retry (242.7s), result:
  escalation_advisory_supported
- triage: succeeded - 0 items, 0 fix-now

Interpretation paragraph: same shape as witness. Two Gemini escalations both
produced 0 triaged items. Escalation triage operates on the escalation
provider's NEW findings, not the source 31. Gemini did not raise objections,
mild cross-provider corroboration but not a per-finding triage substitute.

Same three next-step list, with bakeoff triage --force as step 2.

## Turn 15 - user
"bakeoff triage 2026-05-23-fddc --force"

## Turn 16 - assistant: triage retry succeeded
Table:
- run: 2026-05-23-fddc
- triage: succeeded (claude/opus xhigh)
- items: 31 triaged, 11 fix-now
- triage md: runs/2026-05-23-fddc/triage/triage.md

Concluded: 11 fix-now items are the prioritized robustness gap list across
the three subsystems. The two Gemini escalations (276a, b6f3) produced zero
new disputes - cross-provider corroboration that the report isn't an outlier.

Closed with "no further Bakeoff actions to recommend".

## Cost summary (provider seconds)
- Initial bake: claude 300s + codex 192s + judge 163s ~= 10.9 min
- Failed triage attempt 1: 180s (~3 min wasted; --force later overwrote
  status, losing forensics)
- Witness escalation: gemini 23s + triage ~120s
- Dispute escalation: gemini 243s + triage ~120s
- Successful triage retry: 180s

Total provider time across the session ~= 25-26 min for a question that, in
retrospect, would have been answered by the initial bake + a single triage
retry (~14 min).
