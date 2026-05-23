# Bakeoff session audit — 2026-05-23 (runs `bb94` + `ee29`)

Self-contained handoff. A fresh Claude Code session should be able to read
this file alone and act on every item without needing the original
conversation.

> **Note:** A sibling file `SESSION-AUDIT-2026-05-23.md` already exists in
> this directory; it covers a *different* session on the same day (runs
> `2026-05-23-e57e` + `2026-05-23-95b9`, prompt about gate-first /
> parallelism / cleanup recovery). This file covers the failure-artifact
> compare session. Item §3.1 below (report renderer Go-map leak) overlaps
> with item A1 in the sibling file — same root cause, additional evidence.

## 1. Session context

- **Date:** 2026-05-23
- **Working dir:** `/Users/mstefanko/.claude/plugins/marketplaces/mstefanko-plugins/bakeoff`
- **Command invoked:** `/bakeoff:run compare all-or-nothing trimming against structured compression, section priority, and clearer failure artifacts.`
- **Final narrowing the user accepted:** *compare these four strategies for Bakeoff's provider failure-artifact handling, anchored to `runs/<id>/providers/<p>/...`*

## 2. Runs produced this session

| Run ID | Mode | Providers | Exit | Result | Wall |
|---|---|---|---|---|---|
| `2026-05-23-bb94` | `compare` | `claude/sonnet`, `codex/gpt-5.5`, judge `claude/opus` | 0 | `consensus` | ~6m |
| `2026-05-23-ee29` | `escalation` (`dispute`) | added `gemini/pro` over `bb94` | 0 | `escalation_advisory_supported`, `ok_after_format_retry` | 74s |

**Work order written this session:**
- `./provider-failure-artifact-handling-compare.work-order.json` — kept; usable as a reference template for future failure-artifact work.

**Substantive decision (background, not part of the audit):**
- Both providers + the gemini escalation independently recommend **Strategy 4 — Clearer Failure Artifacts:** write a structured `providers/<id>/failure.json` alongside raw bytes; do not change trim policy.
- 3 of 4 sub-claim divergences resolved by gemini against the codebase:
  - Manifest fingerprint coupling: **B's broader scope wins** — `failure.json` must be added to `providerEvidenceArtifactNames` (`manifest.go:418`).
  - Triage integration depth: **B wins** as a consequence of the manifest finding (triage hashing must include `failure.json`).
  - Schema breadth: **partial** — `failure_kind` can reuse the existing `ClassifyFailure` (`internal/runner/classify.go:5-20`) rather than reinventing classification logic, favoring the leaner schema.
- One divergence still open: whether to keep consecutive-duplicate-line collapsing as a lightweight adjunct to Strategy 4.

**Artifacts to read:** `runs/2026-05-23-bb94/{report.md,decision.json,manifest.json}` and `runs/2026-05-23-ee29/{report.md,decision.json,manifest.json}`. Inspect via `bakeoff show 2026-05-23-bb94` and `bakeoff show 2026-05-23-ee29`.

## 3. Issues found, ranked by tightening value

### 3.1 [HIGH — confirmed code bug] Escalation report renderer leaks Go map literals

This is the **same bug as item A1 in the sibling `SESSION-AUDIT-2026-05-23.md`**, with a second independent reproduction this session. Detailed root cause is included here because the sibling file did not have the source code under it.

- **Where:** `internal/report/report.go:849-866`, function `genericItemLines`.
- **Symptom (observed in `runs/2026-05-23-ee29/report.md`):**
  ```
  - map[evidence:[internal/runner/runner.go:32] id:D-001 resolution:Material...]
    Evidence: internal/runner/runner.go:32
  ```
- **Root cause (confirmed in source):** `genericItemLines` handles map-shaped
  items by calling
  `firstString(obj["claim"], obj["description"], obj["loser_note"], fmt.Sprint(obj))`.
  The dispute escalation schema emits `{id, resolution, evidence}` — none of
  those three keys exist, so the fallback `fmt.Sprint(obj)` prints the raw
  Go map literal.
- **Callers that hit the same fallback (`internal/report/report.go`):**
  - line 191: dispute `resolved_points` — confirmed in this session.
  - line 193: dispute `unresolved_points` — would hit the same fallback when present.
  - line 195: dispute `new_evidence` — strings only in this run, but objects would render the same way.
- **Definition of done:**
  - `genericItemLines` (or a dispute-specific helper) recognizes the
    `{id, resolution, evidence}` shape and renders something like:
    `- **D-001** Material. Strategy 4 improves structured access...`
    with `Evidence: ...` on the next line.
  - Add a regression test in `internal/report/report_test.go` that feeds a
    dispute-shaped item and asserts no `map[` prefix in the rendered output.
  - Visually verify by re-running `bakeoff show 2026-05-23-ee29` after the fix.
- **Recommended pump:** small `build` work order. Verifier:
  `go test ./internal/report/...`. Tiny, concrete, verifier-ready — meets the
  fast-path criteria.

### 3.2 [HIGH — UX gap, no code bug] `escalate` was not offered as a continuation when it was the obvious choice

- **Where:** `/bakeoff:run` skill's post-run summary logic, applied this session
  after the compare exited `consensus`.
- **What happened:** Turn 3 post-run summary listed four sub-claim divergences
  inside the consensus, then recommended only `analyze`. The user had to
  discover `escalate --mode dispute` themselves in the next turn. `dispute`
  mode is built for "consensus + visible disagreements".
- **What the skill already allows:** "Allowed recommendation shapes are stop,
  inspect, judge-only rerun for research, **escalation preview for non-build
  research/review**, draft an implementation plan..." So this is a behavior
  gap in applying the skill, not a missing affordance.
- **Definition of done (skill-level, no code change required):**
  - When the post-run summary is for a non-build research run with
    `decision_kind == "consensus"` AND `consensus_disagreements` is non-empty,
    the recommended continuation should be
    `bakeoff escalate <run-id> --provider <peer> --mode dispute --dry-run`,
    with `analyze` mentioned as a secondary path.
  - Same for `compare` with `decision_kind` in {`unresolved`, `disagreement`}
    where `dispute` or `independent` is appropriate.
- **Where to edit:** `skills/bakeoff-run/SKILL.md`, the "Execution And
  Summary" section. The change is a clarification of the
  continuation-recommendation logic, not a contract change.

### 3.3 [MEDIUM — code + reporting gap] Codex stderr trimmed by ~88% during a *successful* run

- **Observed (`runs/2026-05-23-bb94/providers/codex/`):**
  - `stderr.txt` on disk: 60,049 bytes.
  - `decision.json.provider_statuses.codex.io.stderr_observed_bytes`: 492,580
    bytes.
  - `stderr_truncated: true`, `stderr_kind: diagnostic`, `status: ok`.
- **Cross-reference with sibling audit:** sibling §B1 documents the same
  pattern across `0aee`, `1792`, `bb94`, `db11`, `e57e`, `fddc`. The codex
  CLI echoes the prompt + full transcript + final JSON to stderr; ~349 KB of
  it is noise, with the only real error line buried near the start.
- **Why this matters here:** ironic given the topic — the session's own
  research evidence was itself partially discarded by the policy being
  studied. Confirms a healthy run can drop ~432 KB of diagnostic output
  silently from the operator perspective (the truncation is recorded in JSON
  but not surfaced in `report.md` provider rows).
- **Definition of done (reporting half — small, ship-with-§3.1):**
  `report.md` provider rows for any stream where `*_truncated == true` should
  include a small one-token marker (e.g.,
  `stderr: 58.6 KB (trunc, +432 KB)`) so an operator scanning the report
  sees that signal without reading `decision.json`.
- **Definition of done (filtering half — sibling §B1):** filter codex stderr
  at capture time to lines matching
  `^\d{4}-\d{2}-\d{2}T.*\b(ERROR|WARN|FATAL)\b` plus process metadata.

### 3.4 [MEDIUM — operator clarity] Status strings undefined in user-facing output

- **Where:** `bakeoff` summary output and `report.md`.
- **Strings the operator sees without inline explanation:**
  - `ok_after_format_retry` — gemini's status in `2026-05-23-ee29`. Per
    `internal/runner/runner_test.go:152` and `StatusOKAfterFormatRetry`, it
    means the first attempt failed schema validation and a format-retry
    recovered. Operator-visible only as the final status string.
  - `escalation_advisory_supported` — escalation decision kind. Means the
    escalation supports the source decision and is advisory only.
  - `consensus` vs. the rarer `consensus_disagreements` array — both are in
    `decision.json`, but the report does not call out the difference between
    "providers agree on the headline" and "providers agree but argue
    sub-claims".
- **Definition of done:** Either a one-line gloss next to each status string
  in `report.md` and `bakeoff show`, or a `bakeoff explain <token>` subcommand
  the operator can run. Lighter touch is the inline gloss.

### 3.5 [LOW — environment, not Bakeoff] `context-mode` MCP is broken on this machine

- **Symptom:** every `ctx_batch_execute` / `ctx_search` / `ctx_execute` call
  fails with:
  ```
  better-sqlite3/build/Release/better_sqlite3.node was compiled against
  a different Node.js version using NODE_MODULE_VERSION 131. This version of
  Node.js requires NODE_MODULE_VERSION 147.
  ```
- **Effect on this session:** forced bash fallback for all context gathering;
  the `PreToolUse` hook then fired the "may produce large output" warning on
  every single bash call, including short ones. Noisy but not damaging.
- **Cascading problem:** `/context-mode:ctx-upgrade` itself failed in this
  session because the user has a global git hook
  (`/Users/mstefanko/.git-hooks/post-checkout:30`) that unconditionally reads
  `.overcommit.yml` and crashes on any clone where that file is absent. The
  upgrade fell back to "reconfigure hooks only" and did not rebuild the
  native module.
- **Definition of done (not a Bakeoff item — captured here only for the
  handoff):**
  - Fix or guard `/Users/mstefanko/.git-hooks/post-checkout` so a missing
    `.overcommit.yml` does not crash the hook.
  - `npm rebuild better-sqlite3` inside
    `/Users/mstefanko/.claude/plugins/cache/context-mode/context-mode/1.0.14/`
    (or re-run `/context-mode:ctx-upgrade` after the git hook is fixed).
  - Restart Claude Code.
  - Verify `/context-mode:ctx-doctor` reports `FTS5 / better-sqlite3: PASS`.

### 3.6 [LOW — UX] Approval verbs proliferate in single-WO previews

- **Observed (Turn 2 preview wording):**
  `reply 'show' to print it, 'yes' / 'approve' / 'run it' to write+validate+run, or tell me what to change`.
- **Why it is fine but worth tightening:** four accept-tokens for the same
  action, plus an open-ended fifth ("tell me what to change") that loops
  back to another preview. The skill itself prescribes `yes`, `approve`, or
  `run it` — already three. `show` is a separate action, not an
  accept-token. The wording in this session conflated them in the same
  sentence.
- **Sibling §E2** documents the same pattern in escalate previews.
- **Definition of done:** skill prompt or the assistant template should
  group accept-tokens together and put `show` on its own line.

## 4. Things that worked and should not be regressed on

- **Turn 1 task-fit refusal** named the three missing axes (target, decision,
  evidence surface) before offering narrowings. The user's reply was one
  short sentence — that's the right outcome for a vague initial prompt.
- **Escalate-mode side-by-side fit table** made the choice defensible in one
  glance even without full mechanical definitions of each mode.
- **No wasted runs.** Compare ran once, escalation ran once dry + once live.
  No reruns, no judge retries, no orphaned children. Total ~6 minutes of
  provider/judge wall time.

## 5. Suggested execution order for a fresh session

| # | Item | Why this order |
|---|---|---|
| 1 | §3.1 — report renderer Go-map leak | Confirmed bug, sibling §A1 corroborates, tiny fix, verifier-ready. Pump as a `build` WO with `go test ./internal/report/...`. |
| 2 | §3.4 — status-string glosses | Cheap; ships in the same area as §3.1. |
| 3 | §3.3 — truncated-stderr marker in `report.md` | Small, intersects with the Strategy 4 plan. |
| 4 | The Strategy 4 implementation plan itself | Draft an `analyze` work order over `runs/2026-05-23-bb94/` and `runs/2026-05-23-ee29/`. Open question: yes/no on duplicate-line collapsing adjunct. |
| 5 | §3.2 — skill clarification for escalate-as-continuation | Skill-level only, ride along with the next `/bakeoff:run` skill edit. |
| 6 | §3.6 — approval-verb cleanup | Skill-level only. |
| 7 | §3.5 — context-mode rebuild | Independent of Bakeoff; handle whenever. |

## 6. Inputs a fresh session needs

- This file.
- `runs/2026-05-23-bb94/{report.md,decision.json,manifest.json}`
- `runs/2026-05-23-ee29/{report.md,decision.json,manifest.json}`
- `internal/report/report.go:849-866` (and `internal/report/report_test.go`)
- `internal/runner/classify.go:5-20` (`ClassifyFailure`, referenced by gemini)
- `internal/manifest/manifest.go:418-432` (`providerEvidenceArtifactNames`)
- `internal/triage/citation.go:50` (per-provider `final.json` glob)
- `internal/artifact/artifact.go:159-178` (success-only `final.json` write)
- `internal/decision/decision.go:32` (existing `stderr_path` contract)
- `skills/bakeoff-run/SKILL.md` (for §3.2 and §3.6)
- `SESSION-AUDIT-2026-05-23.md` (sibling audit; corroborates §3.1 and §3.3)

End of audit.
