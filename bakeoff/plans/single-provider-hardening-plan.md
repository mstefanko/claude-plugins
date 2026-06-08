# single_provider — hardening plan (post live-test)

Findings from a live test of the recently added `single_provider` run mode.
Each item lists file:line evidence and a concrete investigation step so a fresh
agent can confirm or refute the claim before changing code.

## Source run (for investigation)

- **Run id:** `live-v2-single-provider-artifacts`
- **Run dir:** `runs/live-v2-single-provider-artifacts/`
- **Work order:** `./live-v2-single-provider-artifacts.work-order.json`
  (`type: analyze`, `run_mode: single_provider`, one provider)
- **Command used:** `bakeoff research ./live-v2-single-provider-artifacts.work-order.json --run-id live-v2-single-provider-artifacts --force`
  (the `--force` was required because a prior aborted launch left an orphan run dir — see P1)
- **Provider:** codex / gpt-5.5, scope codebase, effort high — `status: ok`, exit 0, 222.5s, 17.6 KB stdout
- **Decision:** `decision_kind: single_provider_result`, `canonical_winner: null`, `judge_ran: false`
- **Key artifacts:** `decision.json`, `manifest.json`, `report.md`, `providers/codex/{final.json,stdout.txt,stderr.txt,status.json,prompt.txt}`
- **Experiment metadata:** id=`bakeoff-live-runmode-v2`, task_id=`single-provider-artifact-contract`, condition_id=`codex-single-analyze`, run_kind=`single_agent_baseline`, repetition_index=1
- **Inspect:** `bakeoff show live-v2-single-provider-artifacts`

Source files in scope (from the run's own analysis):
`internal/decision/decision.go`, `internal/summary/summary.go`,
`internal/manifest/manifest.go`, `internal/commands/researchcmd/run.go`,
`internal/commands/lscmd/ls.go`, `internal/verify/verify.go`,
`internal/workorder/workorder.go`.

---

## P1 — Orphan run dir + unsafe `--force` (observed live)

**Claim.** The run dir is created and `work-order.json` copied *before* any
provider launches. An aborted launch leaves an orphan dir containing only
`work-order.json` (no `decision.json` / `manifest.json`). Re-running then
demands `--force`, and `--force` does a blind `os.RemoveAll(runDir)` that cannot
distinguish an empty aborted scaffold from a completed run with real results —
so the documented recovery command is also the command that would destroy a
finished run.

**Evidence.**
- `internal/commands/researchcmd/run.go:61-63` — `os.Stat(runDir)` exists + `!opts.Force` → `"%s already exists; use --force to replace"`.
- `internal/commands/researchcmd/run.go:94` — `os.RemoveAll(runDir)` on force, unconditional.
- `internal/commands/researchcmd/run.go:98` — `os.MkdirAll(runDir, 0o700)` happens early, before provider launch.
- Live repro: after the first launch aborted, `runs/live-v2-single-provider-artifacts/` contained only `work-order.json`; the second launch failed with the `already exists` error and required `--force`.

**Investigate.**
1. Confirm the order of operations: does the work-order copy / dir creation
   happen before the first provider process starts? (Trace `RunResearch` →
   dir setup → provider launch.)
2. Reproduce: create `runs/<id>/` with only `work-order.json`, run
   `bakeoff research ... --run-id <id>` and confirm the `already exists` error.
3. Confirm `--force` deletes a *completed* run dir (with `decision.json`)
   without warning.

**Options to harden (pick one).**
- Detect incomplete runs (missing `decision.json`/`manifest.json`) and reclaim
  them with a distinct message instead of demanding `--force`.
- Make `--force` refuse or require confirmation when the target contains a
  `decision.json` (i.e. real results).
- Build into a temp dir and `rename` into place on success, so an aborted
  launch never leaves a blocking orphan.

---

## P2 — Divergent run-dir collision guards

**Claim.** There are two run-dir existence checks with different behavior; one
has no `--force` escape, so recovery may be inconsistent across run types.

**Evidence.**
- `internal/commands/researchcmd/run.go:61-63` — honors `opts.Force`.
- `internal/commands/researchcmd/run.go:248-249` — hard error `"%s already exists"` with **no force handling**.

**Investigate.**
1. Determine which run types / code paths reach line 248 vs line 61.
2. Confirm whether the 248 path is reachable for `single_provider` or any
   research/build mode in a way the user cannot recover from with `--force`.
3. Decide whether both guards should share one helper with identical behavior.

---

## P3 — Stale pairwise wording in the single-provider report (contract drift)

**Claim.** The single-provider `report.md` still prints pairwise-only glossary
text and the judge/escalation legend, none of which apply when there is one
provider and `judge_ran=false`. This is the exact drift the run was hunting,
and it appeared in the run's own report.

**Evidence.**
- `runs/live-v2-single-provider-artifacts/report.md` Glossary: *"Kept-from-nonwinner / additions-from-loser sections are material from the non-selected provider that the report preserved."* — there is no non-selected provider in single-provider mode.
- Glossary also defines `R-NNN` (judge rationale) and `D-NNN` (escalation dispute) legend lines although no judge ran and no escalation occurred.
- `internal/summary/summary.go:55-59` and `:263-267` — the struct already carries `run_mode` / `single_provider`, so the data needed to gate the text is present; the glossary/legend output is currently unconditional.

**Investigate.**
1. Locate where the Glossary string and the `F/R/D` legend are emitted in
   `summary.go` (search `nonwinner`, `additions-from-loser`, `R-NNN`, `Glossary`).
2. Confirm they are not gated on `run_mode == single_provider`.
3. Gate the nonwinner/loser line and the `R-NNN`/`D-NNN` legend on run mode and
   on whether a judge actually ran / escalation exists.

**Severity:** cosmetic/contract — no data corruption, but it is reader-facing
drift and undermines the single-provider contract.

---

## Verified OK during this run (no change needed — re-confirm if touched)

- **manifest winner is null, not phantom.** `internal/manifest/manifest.go:588-593`
  (`telemetryWinnerBackend`) reads `decision["canonical_winner"]` (null for
  single_provider) → `winner_backend` / `winner_family` (lines 446-449, 476-477)
  emit null. `run_mode` / `single_provider` serialized at lines 103-104, 169-170,
  983-984, 1089-1101.
- **decision.json shape is correct.** Keys: `canonical_winner:null`,
  `selection_basis:none`, `judge_attempted/completed/ran:false`,
  `single_provider:codex`. Matches `internal/decision/decision.go:93-114`
  (`SingleProviderResult` / `SingleProviderFailed`).
- **routing is correct.** `internal/commands/researchcmd/run.go:160-172` routes
  `single_provider` away from the judge to `SingleProviderResult`; the degraded
  pairwise path (one provider succeeds in a pairwise run) stays distinct as
  `single_provider_only` at `:174-177`.
- **output caps held.** codex emitted ~895 KB stderr (`stderr_observed_bytes:
  895730`, kind `diagnostic`) vs 17.6 KB stdout; cap held at `stderr_bytes:
  60000`, `status: ok`, report shows `58.6 KB (trunc, +816.1 KB)`.

---

## P4 — Minor wording polish (optional)

CLI launch line `result: single-provider result=codex` and report Outcome
`Result: single-provider result` read redundantly. Consider
`result: single-provider (codex)`.

---

## Missing tests to add (called out by the run)

Confirm coverage exists for single-provider representation across each surface;
add where missing:
- `decision.json`: `single_provider_result` and `single_provider_failed` shapes
  (kinds, null winner, judge flags false, `stalled_at` on failure).
- `manifest.json` + `bakeoff ls --json`: `run_mode`/`single_provider` populated,
  `canonical_winner`/`winner_backend`/`winner_family` null.
- `report.md`: glossary/legend gated on run mode (guards against P3 regressing).
- Collision/force behavior (guards against P1/P2 regressing): incomplete-run
  reclaim vs completed-run protection.
