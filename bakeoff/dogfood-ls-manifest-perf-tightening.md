# Bakeoff CLI/plugin + `/bakeoff:run` UX tightening — dogfood findings

## Run context

| Field | Value |
| --- | --- |
| Run id | `dogfood-ls-manifest-perf` |
| Date | 2026-05-24 |
| Mode | `build` |
| Providers | `claude/sonnet` (high) + `codex/gpt-5.5` (high), both `scope: codebase` |
| Judge | `claude/opus` xhigh |
| Base ref | `HEAD` (81c636115e3e) |
| Gate | `manifest-lscmd-tests` → `go test ./internal/manifest ./internal/commands/lscmd -count=1` |
| Exit | `3` (completed, decision_kind=`tie`, canonical_winner=`null`) |
| Position-swap | pass1 → tie; pass2 → codex (judge rationale argued for claude) |

**Key artifacts**

- Work order: `dogfood-ls-manifest-perf.work-order.json`
- Run dir: `runs/dogfood-ls-manifest-perf/`
- Report: `runs/dogfood-ls-manifest-perf/report.md`
- Decision JSON: `runs/dogfood-ls-manifest-perf/decision.json`
- Diagnostics: `runs/dogfood-ls-manifest-perf/diagnostics.json`
- Build CLI output (tmp): `/private/tmp/claude-501/-Users-mstefanko--claude-plugins-marketplaces-mstefanko-plugins-bakeoff/ebcb3812-f571-4460-95bb-ba08f685227b/tasks/bjebo7pbd.output`
- Skill source: `/Users/mstefanko/.claude/plugins/cache/mstefanko-plugins/bakeoff/81c636115e3e/skills/bakeoff-run/SKILL.md`

---

## P1 — must-fix

### 1. `draft-build` flag discoverability footgun

- **Where:** `internal/commands/draftbuildcmd/draft_build.go:64-65`
- **Observed:** Drafting tried `--edit-scope` (rejected: `unknown flag: --edit-scope`); the correct flag is `--scope`. The "edit boundary" wording in the help text aliases neither `--edit-scope` nor `--edit-boundary`. User sees a visible self-correction in the live transcript.
- **Fix:**
  - Add hidden aliases via `cmd.Flags().SetNormalizeFunc` mapping `edit-scope`/`edit-boundary` → `scope`.
  - Install `cmd.SetFlagErrorFunc` that does a Levenshtein over the flag set and emits `did you mean --scope?`.
  - Document the canonical `draft-build` flag set (`--scope`, `--gate`, `--accept`, `--base`, `--provider`, `--protected-path`) in SKILL.md under "Single Work-Order Drafting" so the model does not have to discover them at runtime.

### 2. Codex worker stderr banner noise misclassified as worker output

- **Where:** Codex adapter (under `internal/provider/`)
- **Observed:** `diagnostics.json` records `output_truncation.observed_bytes: 279254, retained_bytes: 80000` for the codex provider. Heartbeats during launch read `[codex] running t=60s/1200s out=0.0KB err=76.0KB last=4s` — looks like a stuck/erroring worker. The 280 KB is the deterministic `OpenAI Codex v0.125.0 ... workdir/model/provider/approval/sandbox/reasoning ...` banner block before the first prompt response.
- **Fix:** Classify the well-known Codex banner (`OpenAI Codex v...` up to first blank line) in the launcher and either drop it or fold into `provider_statuses[].codex_banner`. Stops the false stderr surge AND fixes the misleading heartbeat output.

### 3. Preview "Run id (on launch)" line is ambiguous when `--run-id` was supplied

- **Where:** SKILL.md drafting/preview block (`Single Work-Order Drafting` section)
- **Observed:** The preview emitted `Run id (on launch): dogfood-ls-manifest-perf (from your --run-id)`. SKILL.md says "preview-time id is the file basename" and "the run id is assigned by the CLI on launch unless a `--run-id` was supplied" — so when supplied, the run id IS known at preview time and should not be hedged.
- **Fix:** Two distinct lines:
  - When `--run-id` supplied: `Run id: <supplied>`
  - Otherwise: `Run id (assigned on launch from filename): <basename>`

---

## P2 — worth-doing

### 4. Judge family advisory wording diverges between commands

- **Where:**
  - `internal/commands/doctorcmd/doctor.go:594` — "default judge claude shares provider-family metadata with a selected provider; ready non-contestant judge backends: …. Advisory only; no defaults changed."
  - `internal/commands/validatecmd/validate.go:256` — "judge family advisory: judge claude shares provider-family metadata with …; for high-stakes judge-heavy runs, run bakeoff doctor to check ready non-contestant judge backends. Advisory only; validation still succeeds."
- **Fix:** Extract a shared formatter `func FormatJudgeFamilyAdvisory(surface string, …)` returning identical prefix (`judge family advisory:`) and identical "Advisory only" suffix; vary only the call-to-action clause per surface.
- **Also:** the `/bakeoff:run` preview surfaces a third variant ("a ready non-contestant provider-family judge exists"). Have the skill consume the validate-warning string verbatim once instead of paraphrasing — and either suppress the post-validate echo or label it `Warning (validate, same as preview advisory):`.

### 5. CLI build tail hides exit code and decision substate

- **Where:** `internal/commands/buildcmd/run.go:294-300`
- **Observed:** Tail prints `result: tie, winner=none, basis=none` → `selected patch: no selected patch` → `next: bakeoff show …`. Never surfaces exit code `3` or `decision.json.stalled_at: "selection"`. Reader has to open `decision.json` to learn ties got exit 3.
- **Fix:** Add `status: stalled at selection (exit 3)` line. Decide the recovery verb in coordination with item #6 — currently `bakeoff escalate` is *forbidden* in build mode by SKILL.md, so the CLI tail must NOT recommend it for build.

### 6. SKILL/CLI mismatch: build escalation policy

- **Where:** SKILL.md "Drafting Invariants" (`Do not offer build escalation`) vs CLI's general escalation surface.
- **Observed:** CLI tail (if extended per item #5) wants `bakeoff escalate <run-id>` as the recovery verb on ties; SKILL forbids it. The dogfood post-run summary therefore had no allowed "next step" verb for a tie outcome and improvised "draft a tiebreaker test" (also disallowed — not in {stop, inspect, judge-only rerun [research only], escalation [non-build], draft analyze, gather, compare, review, draft build}).
- **Fix:** Pick one direction:
  - Either remove the "no build escalation" restriction from SKILL and let `bakeoff escalate --mode witness` work on build runs as an advisory third-opinion (cannot pick a new winner — same as research advisory escalations).
  - Or keep the restriction and explicitly enumerate the allowed tie-recovery shapes for build (`inspect <run-id>`, `draft analyze comparing patches`, `draft build with stronger gate`). Whichever is chosen, update both SKILL.md and the CLI tail copy.

### 7. Position-swap disagreement silently absorbed into "tie"

- **Where:** `internal/commands/buildcmd/run.go:233` and surrounding judge orchestration
- **Observed:** Build output only printed `[judge] verifier evidence inconclusive; running swapped build judge...`. `decision.json` shows `judge_passes.pass1.canonical_winner: null`, `pass2.canonical_winner: "codex"`. Caveat captured in JSON but absent from CLI tail.
- **Fix:** Emit `[judge] swapped pass disagreed (pass1=tie, pass2=codex) -> tie` on the CLI before the result line so users see the rationale-vs-verdict mismatch without parsing JSON.

### 8. `--gate <id>=<command>` shorthand is rigid

- **Where:** `internal/commands/draftbuildcmd/draft_build.go:158-178`
- **Observed:** Bare `--gate "go test ./..."` errors `--gate[0] must use <id>=<command>` with no suggestion.
- **Fix:** Auto-name `gate-N` when `=` is absent and emit a stderr note `note: --gate missing id; using "gate-1"`. Alternatively, strengthen the error to suggest a concrete fix (`tests=<your command>`).

### 9. Accept-token list mixes approval and non-approval tokens

- **Where:** SKILL.md "Single Work-Order Drafting" choice conventions
- **Observed:** The dogfood preview listed `yes` / `approve` / `run it` (approve) alongside `show` (prints JSON) and `cancel` (discards) on the same closing line, blurring intent.
- **Fix:** Render two lines:
  - `Approve: yes | approve | run it`
  - `Other: show (print JSON), cancel (discard)`

### 10. Post-run summary verdict vocabulary

- **Where:** SKILL.md "Execution And Summary" section, `Decision:` line contract.
- **Observed:** Dogfood emitted `Decision: tie — no canonical winner`. SKILL contract allows `X wins | consensus | unresolved`; `tie` is not in the vocabulary.
- **Fix:** Map decision_kind=`tie` (canonical_winner=`null`) to `unresolved` in the lead line and put the tie nuance on the decision-kind line:
  ```
  Decision: unresolved — position-swapped judge could not pick a stable winner
  Decision kind: tie (judge rationale favored claude; pass2 swapped positions and flipped)
  ```

### 11. Continuation recommendation cap

- **Where:** SKILL.md "Execution And Summary" — "At most one artifact-aware continuation recommendation is allowed."
- **Observed:** Dogfood summary recommended `bakeoff show ...` AND "draft a follow-up build work order with a stale-triage divergence test." Two recommendations; the second is also not in the allowed shape set.
- **Fix:** Cap at one. For this case the right single recommendation is `inspect` (read both `providers/<id>/build/diff.patch`) or `draft analyze` comparing the two patches. The stale-triage test idea belongs in the actionables file (separate from /bakeoff:run flow).

---

## P3 — polish

### 12. Long quiet stretches have no stuck-detector copy

- **Where:** `internal/runner/runner.go:1004` (`quietThreshold`)
- **Observed:** Claude provider hit `quiet t=600s/1200s out=0.0KB err=0.0KB last=600s` — 11 consecutive minutes of zero output. CLI just keeps ticking with no escalation.
- **Fix:** After N (e.g. 5) consecutive quiet ticks, emit one informational line: `[claude] long quiet (10+ minutes, no stdout/stderr); workers can be slow on opus/xhigh — Ctrl-C to abort`. Once per worker per run.

### 13. Gitlink/submodule warning fires unconditionally

- **Where:** `internal/commands/buildcmd/helpers.go:214-220`
- **Observed:** Build prints `source checkout contains 6 gitlink/submodule entries; provider patches that modify gitlinks are still rejected` even when no provider attempted a gitlink modification (`provider_build.*.gitlink_change_rejected: false` for both providers in this run).
- **Fix:** Demote to `info` log level, or gate display on actual rejection. Keep dirty-checkout as a `warning` (it changes base ref semantics).

### 14. Claude heartbeat reads as deadlock to users

- **Where:** Heartbeat formatting (`runner.go` near `quietThreshold`)
- **Observed:** `[claude] quiet t=...s/1200s out=0.0KB err=0.0KB last=...s` for the entire 11-minute window. SDK output is buffered until completion.
- **Fix:** When the worker uses a non-pty buffered transport (claude SDK), append `(buffered, output expected at completion)` to the first quiet heartbeat per worker.

### 15. `capture.json` vs `final.json` field overlap

- **Where:** `runs/<id>/providers/<id>/`
- **Observed:** Both files are ~1 KB JSON and share `patch_digest`, `exit_code`, and similar worker-outcome fields. `meta.json` references a third concept `final_json_source: "stdout"`.
- **Fix:** Document which is canonical, or merge `final.json` into `capture.json` and have `meta.json.final_json_source` point at it.

### 16. Missing `references/run-appendix.md`

- **Where:** `/Users/mstefanko/.claude/plugins/cache/mstefanko-plugins/bakeoff/81c636115e3e/skills/bakeoff-run/`
- **Observed:** SKILL.md repeatedly cites `references/run-appendix.md` (split proposal templates, lens presets, summary template, repair menu). The file is absent from the cached skill directory.
- **Fix:** Ship the appendix in the plugin payload. Without it, split and multi-lens drafting paths reference content that does not exist and would silently fail or improvise.

### 17. SKILL.md does not enumerate `draft-build`'s actual flag names

- **Where:** SKILL.md "Single Work-Order Drafting"
- **Observed:** Tells the model to use `bakeoff draft-build` but never lists `--id`, `--goal`, `--acceptance`, `--scope`, `--gate`, `--protected-path`, `--base-ref`, `--provider`. Discovery happens at runtime via `--help` (which the dogfood transcript shows).
- **Fix:** Add a one-paragraph reference block in SKILL.md naming the canonical flags, the `--gate <id>=<command>` form, and the canonical provider override pattern.

---

## Clean / verified during audit

- Artifact tree under `runs/dogfood-ls-manifest-perf/` is consistent: `baseline/verify/`, `providers/{claude,codex}/{prompt,stdout,stderr,status,final,build/{diff,diffstat,changed-files,test-files,benchmark-files,capture,workspace,verify/...}}`, `judge/{prompt,result,status,stdout,stderr}-pass{1,2}`, `decision.json`, `diagnostics.json`, `meta.json`, `manifest.json`, `report.md`, `work-order.json`, `build-context.json`. Nothing orphaned.
- Doctor's `judge_family_advisory: {relation: same_as_some, ready_non_contestant_judges: […], advisory_only: true}` is well-structured.
- Both worker patches applied cleanly inside their worktrees; scope enforcement metadata complete for both backends.
- `Why this loop: build-verifier path` line was present in the preview as SKILL requires.

---

## Cross-cutting top three

1. **Codex stderr banner classification** — single fix in codex adapter cleans up diagnostics AND heartbeats AND `output_truncation` metrics.
2. **`draft-build` flag aliases + SKILL flag reference** — eliminates the visible self-correction in drafting.
3. **Tie handling for build mode** — resolve the SKILL-vs-CLI escalation mismatch, fix verdict vocabulary, surface position-swap disagreement on the CLI.
