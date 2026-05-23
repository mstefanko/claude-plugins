# Bakeoff session audits — 2026-05-23 — consolidated plan

Five separate `/bakeoff:run` sessions on 2026-05-23 each produced their own
audit. This file deduplicates the findings, ranks them by blast radius +
effort, and records the verification done in the consolidation pass so future
sessions can act on the list without re-investigating false positives.

## Source audits and run IDs

| Audit file | Session topic | Run IDs |
|---|---|---|
| `SESSION-AUDIT-2026-05-23.md` | gate-first / verifier parallelism / cleanup recovery (compare → escalate) | `2026-05-23-e57e` (compare), `2026-05-23-95b9` (escalate/dispute) |
| `SESSION-AUDIT-2026-05-23-bb94.md` | provider failure-artifact handling (compare → escalate) | `2026-05-23-bb94` (compare), `2026-05-23-ee29` (escalate/dispute) |
| `SESSION-AUDIT-2026-05-23-supervisor-bakeoff.md` | supervisor hardening vs. state machine | `2026-05-23-db11` (compare), `2026-05-23-871b` (analyze), `2026-05-23-0aee` (escalate/dispute) |
| `docs/session-audits/2026-05-23-decision-typing-compare.md` | typed decision structs vs. targeted validators | `2026-05-23-1792` (compare) |
| `research/session-audit-2026-05-23.md` | capability cache / transient failure / required-scope review | `2026-05-23-fddc` (gather + code-review), `2026-05-23-276a` (witness), `2026-05-23-b6f3` (dispute) |

Total unique runs referenced: 11.

## Verification approach

Each item was re-verified against current source before inclusion. Items that
the code already addresses are marked **PARTIAL** or **FIXED**. Items the
audits speculated about (`unknown`, `needs confirmation`) were checked and are
marked **CONFIRMED** or **NOT A BUG**.

---

## Tier 0 — Verified user-visible bugs (ship first)

### CLI-1 — Escalation/dispute report renders raw Go `map[...]` literals
**Severity:** High. Affects every dispute escalation that ever ran.
**Audits:** `SESSION-AUDIT-2026-05-23.md §A1`, `SESSION-AUDIT-2026-05-23-bb94.md §3.1`, `SESSION-AUDIT-2026-05-23-supervisor-bakeoff.md §U-6`.
**Runs reproducing:** `2026-05-23-95b9`, `2026-05-23-ee29`, `2026-05-23-0aee` (three independent reproductions across three sessions).
**Verified:** `internal/report/report.go:849-866`, function `genericItemLines`. The map branch calls
`firstString(obj["claim"], obj["description"], obj["loser_note"], fmt.Sprint(obj))`.
The dispute schema emits `{id, resolution, evidence}` — none of those three keys exist in the lookup, so the `fmt.Sprint(obj)` fallback prints `map[evidence:... id:D-001 resolution:...]` directly.
**Other callers that hit the same fallback:** `internal/report/report.go:191` (`resolved_points`), `:193` (`unresolved_points`), `:195` (`new_evidence`).
**Definition of done:**
- `genericItemLines` (or a dispute-specific helper) recognizes the `{id, resolution, evidence}` shape and renders
  `- **D-001** Material. <resolution body>` plus `Evidence: <path>` on the next line.
- Regression test in `internal/report/report_test.go` feeds a dispute-shaped item and asserts no `map[` prefix in output.
- Visual verify: re-render `runs/2026-05-23-ee29/report.md` and `runs/2026-05-23-95b9/report.md`.
**Verifier:** `go test ./internal/report/...`.

### CLI-2 — `runs/latest` symlink not updated by every subcommand
**Severity:** Medium. Silently misleads anyone (incl. tooling) that follows `runs/latest`.
**Audits:** `SESSION-AUDIT-2026-05-23.md §A2`.
**Runs reproducing:** After `2026-05-23-e57e` then `2026-05-23-95b9`, `runs/latest` still pointed at older `2026-05-23-0aee`. **Re-verified at audit-consolidation time:** still pointing at `2026-05-23-0aee` despite `2026-05-23-fddc` and `2026-05-23-b6f3` being newer.
**Verified:** `internal/ledger/ledger.go:15,83` — the symlink-update helper (`latestSymlink`) exists; only `internal/commands/researchcmd/run_test.go:467` asserts it gets set. No call from escalate / triage / show / build paths.
**Definition of done:** every subcommand that finalizes a run dir calls the ledger helper. Or, alternatively, the helper is hoisted into a post-run hook the runner always invokes.
**Verifier:** new tests asserting `runs/latest` updates after `compare`, `escalate`, `triage`, `build`.

### CLI-3 — Codex stderr blows through the cap on a majority of runs
**Severity:** Medium. Wastes ~290–432 KB per codex run; buries the only real error line.
**Audits:** `SESSION-AUDIT-2026-05-23.md §B1`, `SESSION-AUDIT-2026-05-23-bb94.md §3.3`, `SESSION-AUDIT-2026-05-23-supervisor-bakeoff.md §W-2`.
**Runs reproducing:** `0aee`, `1792`, `bb94`, `db11`, `e57e`, `fddc` (all hit the same 60049-byte truncation). `bb94` observed 492,580 bytes; `db11` observed ~286 KB; `0aee` capped too.
**Verified:** Codex CLI is echoing the full prompt + transcript + final JSON to stderr. The only buried real error line in the audited samples was a benign `failed to record rollout items: thread ... not found` warning.
**Two-part fix:**
- **Filter at capture time** (`internal/provider/` codex backend): keep only lines matching `^\d{4}-\d{2}-\d{2}T.*\b(ERROR|WARN|FATAL)\b` plus initial/final process metadata. Expected reduction: 350 KB → ~1 KB.
- **Surface in `report.md`** (independent fix): provider rows for any stream where `*_truncated == true` should include a one-token marker like `stderr: 58.6 KB (trunc, +432 KB)` so operators don't have to read `decision.json` to spot truncation.
**Side-investigation:** confirm the codex `failed to record rollout items` warning is harmless before silently filtering it out.

### CLI-4 — Validator emits false-positive `<context-root>` warnings on prose tokens
**Severity:** Low (advisory; doesn't block runs) but creates user friction every draft.
**Audits:** `SESSION-AUDIT-2026-05-23.md §C1`, `decision-typing-compare.md Issue 3`.
**Runs reproducing:** `e57e` (warned on `"build/research"` in the noun phrase *"competitive build/research work orders"*), `1792` (warned on `"decision/manifest/triage"` and `"files/tests"` — both prose, not paths).
**Verified:** `internal/commands/validatecmd/validate.go:165-170` formats the warning message; the path detector is `repocontext.ValidateProsePaths`. The substring match is too loose — slash-bearing English fragments are treated as paths.
**Definition of done:** require one of:
- leading `./`, `/`, or `../`,
- a leading known workspace directory (`internal/`, `cmd/`, `docs/`, `internal/...`),
- or a known file suffix (`.go`, `.json`, `.md`)
before flagging a slash-bearing token. Phrases with whitespace-adjacent commas, or two lowercase words joined by a single slash (`files/tests`, `read/write`, `pass/fail`, `build/research`), should be excluded. If the change is invasive, demote to debug-only or `--strict-paths`.
**Verifier:** revalidate `bakeoff-orchestration-compare.work-order.json` and `decision-typing-vs-validators-compare.work-order.json` — both should warn clean. A real broken path like `internal/decicision/decision.go` must still warn.

### CLI-5 — False-positive `bakeoff triage` recommendation on non-review runs
**Severity:** High. Wrong continuation — points compare/analyze users at a code-review tool.
**Audits:** `decision-typing-compare.md Issue 2`.
**Runs reproducing:** `2026-05-23-1792` emitted `recommended: bakeoff triage 2026-05-23-1792 (report mentions invalid - verify before fixing)` on a `compare` run, because the literal phrase *"fallback to empty map on invalid decision reads"* appeared in a quoted F-002 finding inside `report.md`.
**Verified:** emission sites are `internal/commands/researchcmd/run.go:376` (auto-triage path) and `:722` (`recommended: triage` appended in `researchResultLine`). The trigger is `triagepkg.ShouldRecommendTriage(wo.Raw, decisionDoc, reportText)`. The substring search needs both (a) mode gating and (b) prose-vs-quoted-text discrimination.
**Definition of done:**
1. Gate `ShouldRecommendTriage` on `type == "gather"` and `facet.id == "code-review"` (or equivalent). Suppress entirely for compare / analyze.
2. Even within code-review runs, skip substring matches inside fenced quotes, finding bodies (lines starting with `**F-`), and `consensus_strongest` echoes.
**Verifier:** re-running the `1792` work order prints no triage recommendation. A synthetic code-review run whose report mentions the word "invalid" in prose still does.

### CLI-6 — Zero-byte provider termination classified as generic `exit_error`
**Severity:** Medium (operator clarity — the session's own subject caught itself).
**Audits:** `research/session-audit-2026-05-23.md §2 / CLI-1`.
**Runs reproducing:** triage child of `2026-05-23-fddc` exited non-zero after 120 s with zero stdout and zero stderr; classified as `exit_error`.
**Verified:** `internal/runner/classify.go` switches on `status` first (`StatusTimeout`, `StatusOutputCap`, etc.) then falls through to text-substring matching of stdout/stderr. With zero I/O, no string match fires; the result is whatever the default branch returns — generic, not the runner's specific `wedged` shape.
**Definition of done:** add a `wedged_no_output` class (or fold into `timeout` when the runner deadline expired) when `stdout_bytes == 0 && stderr_bytes == 0 && wall_seconds > heartbeat * N`. Surface the class in the heartbeat tail so CLI prints "triage timed out: no provider output" instead of `exit_error`.
**Verifier:** `go test ./internal/runner/...` with a new unit case for zero-byte non-zero termination.

### CLI-7 — `triage --force` clobbers prior triage forensics on **successful** retry
**Severity:** Medium. Operators lose debugging context for the prior failure.
**Audits:** `research/session-audit-2026-05-23.md §3 / CLI-2`.
**Runs reproducing:** `2026-05-23-fddc` retry — after the second triage succeeded, the original `triage/status.json` and `stderr.txt` were no longer recoverable.
**Verified — partial fix already exists:** `internal/commands/triagecmd/triage.go:128-149` stages a new triage in `.triage-<rand>/` and only swaps in on success. `TestForceTriageProviderFailurePreservesPreviousTriage` confirms the **failure** case preserves the prior `triage/`. **Success** case still replaces (and discards) the prior failed-run forensics.
**Definition of done:** when `--force` replaces an existing `triage/` directory **on success**, move (not delete) the prior contents to `triage.failed-<RFC3339>/` first. Add a user-visible "archived prior triage to ..." line. Add a regression test mirroring the existing failure-preservation test but for the success-replaces path.

### CLI-8 — `bakeoff show` triage-failed run cards omit the stderr tail
**Severity:** Low. Operator-friendliness only.
**Audits:** `research/session-audit-2026-05-23.md CLI-3`.
**Verified:** UX feature gap, not a regression.
**Definition of done:** when `triage/status.json` shows non-`ok`, embed the last ~20 lines of `triage/stderr.txt` (or "no stderr captured" if empty) in the rendered card.

### CLI-9 — `quiet_tick_count` semantics don't match the field name
**Severity:** Low (observability only) — but the metric is either buggy or misnamed.
**Audits:** `SESSION-AUDIT-2026-05-23.md §B2`.
**Runs reproducing:** `e57e` decision.json had `quiet_tick_count: 3` with `quiet_threshold_seconds: 120` and claude wall time 249.7s. Three disjoint 120 s windows cannot fit in 249 s.
**Verified:** `internal/runner/runner.go:754,765` increments `quietTickCount` every heartbeat tick where `LastOutputAge >= quietThresholdSeconds`. So the value is "ticks observed in quiet phase," not "disjoint quiet windows." Also: claude consistently trips this; codex never does — threshold may be calibrated to codex's chattier output.
**Definition of done:** pick one:
- rename the field to `quiet_window_observations` (or `quiet_tick_observations`),
- or change the increment to track disjoint windows by tracking the last-observed quiet-period start,
- or apply per-backend defaults for `quiet_threshold_seconds`.
Document the chosen semantics next to the field in the schema.

### CLI-10 — `ledger.jsonl` referenced in docs but never written
**Severity:** Low / doc cleanup.
**Audits:** `SESSION-AUDIT-2026-05-23.md §D2`.
**Verified:** No `ledger.jsonl` exists under any `runs/<id>/` directory. No code in `internal/` or `cmd/` writes a file named `ledger.jsonl`. The `internal/ledger/` package handles run-finalization (manifest + latest symlink), not a JSONL ledger. **Not a runtime bug** — but if any skill/doc text mentions `ledger.jsonl` it should be cleaned up to avoid implying a missing artifact.
**Definition of done:** grep `skills/`, `docs/`, and `README` for `ledger.jsonl`; either implement the artifact (if intended) or remove the references.

### CLI-11 — Status strings appear in user-facing output without inline gloss
**Severity:** Medium operator clarity.
**Audits:** `SESSION-AUDIT-2026-05-23-bb94.md §3.4`.
**Runs reproducing:** `ee29` (`ok_after_format_retry`, `escalation_advisory_supported`), `bb94` (`consensus` vs. `consensus_disagreements`).
**Verified:** `StatusOKAfterFormatRetry` is defined; the strings flow into `report.md` and `bakeoff show` without any next-to-it explanation.
**Definition of done:** either a one-line gloss in `report.md` provider/status rows, or a `bakeoff explain <token>` subcommand. Lighter touch is the inline gloss.

### CLI-12 — Unified finding-numbering / section-naming across modes
**Severity:** Low. Cognitive load for operators reading multiple reports.
**Audits:** `SESSION-AUDIT-2026-05-23-supervisor-bakeoff.md §U-7`.
**Verified:** `internal/triage/state.go:186-187` and `internal/report/report.go:21-22` both treat "Kept From Nonwinner" (compare) and "Additions From Loser" (analyze) as distinct section headers for the same concept. Findings use `F-NNN`, rationale `R-NNN`, dispute `D-NNN`.
**Definition of done:** either (a) unify on one section name and one numbering prefix across modes, or (b) add a one-line glossary block at the top of every report mapping the three prefixes. Smallest fix is the glossary block.

---

## Tier 1 — Verified skill (`/bakeoff:run`) tightenings

All targets are `skills/bakeoff-run/SKILL.md` unless noted. No Go changes
required for any item in this tier.

### SKILL-1 — Recommend `escalate` when the artifact signals support it
**Severity:** High UX. Three independent reproductions.
**Audits:** `SESSION-AUDIT-2026-05-23-bb94.md §3.2`, `decision-typing-compare.md Issue 1`, `SESSION-AUDIT-2026-05-23-supervisor-bakeoff.md §U-1`.
**Runs reproducing:** `bb94` (consensus with sub-claim divergences — escalate not offered), `1792` (consensus with 7 `consensus_disagreements` — only triage suggested), `e57e` (compare with non-empty `Kept From Nonwinner` — only `plan it`/`inspect` offered).
**Definition of done:** the "Execution And Summary" section's post-run recommendation logic gains explicit triggers:
- `decision_kind == "consensus"` AND `consensus_disagreements` non-empty (especially N≥3) → recommend `bakeoff escalate <run-id> --provider <peer> --mode dispute --dry-run`.
- `decision_kind` ∈ {`unresolved`, `disagreement`} → recommend dispute or independent as appropriate.
- compare/analyze report contains a non-empty `Kept From Nonwinner` / `Additions From Loser` block → recommend dispute escalation.
Update the "Allowed recommendation shapes" list so escalation previews are clearly in-scope for non-build research/review post-run summaries.

### SKILL-2 — Approval verb / choice-label normalization
**Severity:** Low UX, real consistency issue. Five reproductions.
**Audits:** `SESSION-AUDIT-2026-05-23.md §E2`, `SESSION-AUDIT-2026-05-23-bb94.md §3.6`, `decision-typing-compare.md Issue 5A`, `research/session-audit-2026-05-23.md §6 / SKILL-5`, `SESSION-AUDIT-2026-05-23-supervisor-bakeoff.md §U-4`.
**Definition of done:** add a "Choice-label conventions" subsection to the skill:
- `yes`, `approve`, `run it` are accepted on every preview, single or multi-mode.
- Mode-specific aliases (`approve witness`, `run dispute`) are optional and shown only as "or" alongside the base verbs — never required.
- `show` is a print action, not an accept token; group it on its own line.
- Cancel/abort: every preview ends with "Reply `cancel` to discard this draft."
- Scoped variants follow `<verb>: <scope>` (e.g. `build: phase 1-2`); avoid mixing verb forms (`build it` vs `build phase 1-2`).
- Reconcile `show` (prints JSON) vs `inspect` (opens the report) — pick one or define both with non-overlapping verbs.

### SKILL-3 — Escalation router: triage gaps + scope disclosure
**Severity:** High (UX miss + provider waste).
**Audits:** `research/session-audit-2026-05-23.md §4 / SKILL-2, SKILL-3`, `SESSION-AUDIT-2026-05-23-supervisor-bakeoff.md §U-2`.
**Runs reproducing:** `fddc` (failed triage → witness offered, then dispute offered — neither addresses the triage problem; correct answer was `bakeoff triage --force`), `871b` (dispute pitch failed to disclose advisory-only constraint up front).
**Definition of done:**
- When the source run has a failed or missing triage, the **first** recommendation is `bakeoff triage <id> --force` with one-line rationale ("retry — first failure is most often transient"). Escalation is a fallback when retry also fails.
- The dispute / witness preview disclosure must state, before approval: "advisory only — cannot pick a new winner" and "escalation triage operates on the escalation provider's new findings, not the source run's findings."
- Mode mapping: phrases mentioning triage / verification / "is this finding real" → `dispute`. Phrases about "is the conclusion sound / sanity check" → `witness`. Phrases about "fresh independent answer / second opinion" → `independent`.
- When recommending a mode, list **all three** with equal-shape one-liners (when-to-use + cost) and put the recommendation at the top with a `recommended:` prefix.

### SKILL-4 — Drafting checklist for canonical work-order fields
**Severity:** Medium (one wasted Write/Validate round-trip per drift).
**Audits:** `research/session-audit-2026-05-23.md §1 / SKILL-1`.
**Runs reproducing:** `fddc` drafting required a re-write because `providers[]` lacked `id`, `budgets` used `wall_seconds`/`output_bytes` instead of `wall_clock_seconds`/`max_output_bytes`/`heartbeat_seconds`/`output_cap_grace_seconds`/`max_output_overrun_bytes`, and `facet.include`/`facet.exclude` held globs instead of descriptive criteria.
**Definition of done:** the skill body lists these canonical fields as an explicit drafting checklist (not "see examples"):
- `providers[].id` is required.
- `budgets` keys: `wall_clock_seconds`, `max_output_bytes`, `heartbeat_seconds`, `output_cap_grace_seconds`, `max_output_overrun_bytes`.
- `facet.include`/`facet.exclude` are descriptive criteria, not paths.
- `facet.kind: "generic"` for code-review.

### SKILL-5 — Never invent provider/model variants outside the catalog
**Severity:** High (correctness).
**Audits:** `SESSION-AUDIT-2026-05-23-supervisor-bakeoff.md §U-3`.
**Runs reproducing:** session preceding `871b` invented a "gemini-pro variant" in an `AskUserQuestion`. **Verified catalog:** `internal/provider/provider_test.go:24` — `ValidBackend("gemini")`/`ValidBackend("copilot")`. The four backends are exactly `claude`, `codex`, `gemini`, `copilot`. Nothing else exists.
**Definition of done:**
- The skill explicitly states the four-backend catalog in the provider-pair extraction rules.
- When a user names one provider as a replacement after a just-completed run, the default behavior is "swap the non-winner" and the preview shows that pair inline; only ask if ambiguous.
- Never list a model variant unless it appears in the catalog.

### SKILL-6 — AskUserQuestion framing for "add provider" cross-mode redirects
**Severity:** Medium UX (user could approve a wrong-shape option).
**Audits:** `SESSION-AUDIT-2026-05-23.md §E1`.
**Runs reproducing:** user asked "bring gemini in to do the analyze" after a compare; assistant offered three options under the false-framing question "How should Gemini fit into the analyze?" with C being "escalate the compare instead" buried at the end.
**Definition of done:** when the user's add-provider intent collides with a just-finished run, the framing question must acknowledge the redirect:
> "Two ways to bring Gemini in. You asked about analyze, but the compare just finished — so a third-opinion escalation is also on the table. Pick the shape: A. New analyze: Claude + Gemini. B. New analyze: Codex + Gemini. C. Escalate the compare with Gemini — no new work order. Adds Gemini as a third opinion. Advisory only — does not change the existing winner."
Option labels use parallel grammatical form (all noun-phrase action labels), not a mix of "A/B nouns + C verb." Mode terms (independent / witness / dispute) get one-line definitions inline.

### SKILL-7 — Preview affordances: cancel, target path, run id
**Severity:** Low → Medium UX.
**Audits:** `decision-typing-compare.md Issue 5A`.
**Definition of done:** the compact preview template gains:
- bold/visually-anchored target file path (`./<basename>.work-order.json`) as the mutation target.
- a "Reply `cancel` to discard this draft" line.
- a note that the run id is assigned by the CLI on launch; preview-time id is the file basename.

### SKILL-8 — Validation output must list each warning verbatim
**Severity:** Low UX. Skill instructions tell the assistant to surface validator output verbatim, but in `1792` the warnings were dismissed in-line as "advisory false-positives."
**Audits:** `decision-typing-compare.md Issue 5B`.
**Definition of done:** the post-validate template prints each warning on its own line and never elides; the assistant's gloss follows on a separate line. (Pairs with CLI-4 — once the validator stops emitting noise, this becomes a non-issue.)

### SKILL-9 — Final summary continuation must be unhedged
**Severity:** Low UX. *"For a pure design comparison this is usually optional"* contradicts the recommendation it accompanies.
**Audits:** `decision-typing-compare.md Issue 5C`.
**Definition of done:** pick the recommendation based on artifact signals (SKILL-1) and state it without softening. If signals are weak, recommend `stop / inspect only` cleanly.

### SKILL-10 — Triage-failure report card template
**Severity:** Medium UX.
**Audits:** `research/session-audit-2026-05-23.md §5 / SKILL-4`.
**Definition of done:** when triage fails on an otherwise-successful run, the post-run card layout is:
1. Run table with `triage: failed (<class>)`.
2. stderr tail (or "no stderr captured").
3. Caveat line: "Report is durable; only triage failed. N findings are present but unverified."
4. Primary recommendation: `bakeoff triage <id> --force` with one-sentence why.
5. Secondary options under a `<details>` block or "Other options" sub-bullet, not sibling-weight.

### SKILL-11 — De-duplicate session-level caveats
**Severity:** Low UX. The "findings are unverified per-finding until triage runs" caveat appeared at Turn 11 and Turn 14 in the `fddc` session.
**Audits:** `research/session-audit-2026-05-23.md §7 / SKILL-6`.
**Definition of done:** state once per session and refer back; don't restate on every escalation summary.

### SKILL-12 — Final-pass output check (no stub sentences, no contradictions)
**Severity:** Low UX (credibility). Turn 11 of the `fddc` session contained the stub "Both Gemini escalations would…" mid-paragraph.
**Audits:** `research/session-audit-2026-05-23.md §8 / SKILL-7`.
**Definition of done:** a lightweight self-review pass before emitting — no half-finished sentences, no internal phrase markers, no header/body contradictions.

### SKILL-13 — Lead post-run summaries with the verdict, not the run id
**Severity:** Low UX.
**Audits:** `SESSION-AUDIT-2026-05-23-supervisor-bakeoff.md §U-5`.
**Definition of done:** post-run summary template opens with `Decision: <X wins | consensus | unresolved> — <one-line position>`, then run-id / inspect command second.

### SKILL-14 — Collapse dispute/witness escalate to one confirm
**Severity:** Low UX.
**Audits:** `SESSION-AUDIT-2026-05-23-supervisor-bakeoff.md §U-8`.
**Definition of done:** for `dispute` and `witness` modes (cheap, advisory-only), embed the cost line into the first preview and accept on a single `yes`. Drop the dry-run/cost-preview second gate. `independent` mode retains the full two-gate flow.

---

## Tier 2 — Environment (not a Bakeoff change)

### ENV-1 — context-mode MCP `better-sqlite3` ABI mismatch (NODE_MODULE_VERSION 131 vs 147)
**Severity:** Medium (blocks the "one batched context pass" invariant for drafting; forces bash fallback and triggers nag-hook loops).
**Audits:** `SESSION-AUDIT-2026-05-23.md` (implied), `SESSION-AUDIT-2026-05-23-bb94.md §3.5`, `decision-typing-compare.md Issue 4`, `SESSION-AUDIT-2026-05-23-supervisor-bakeoff.md §W-1`. Four independent sessions all hit the same error.
**Re-verified in consolidation session:** ToolSearch for the ctx tools returns "No matching deferred tools found" — MCP is still unhealthy this session.
**Cascading failures observed:**
- `/context-mode:ctx-upgrade` itself failed because of a global git hook `/Users/mstefanko/.git-hooks/post-checkout:30` that unconditionally reads `.overcommit.yml` and crashes on any clone where that file is absent. The upgrade fell back to "reconfigure hooks only" and did not rebuild the native module.
- After MCP fails, the PreToolUse Bash hook keeps suggesting `ctx_batch_execute` on every short Bash call — nagging the assistant to use a broken tool.
**Definition of done (environment, not Bakeoff):**
1. Guard `/Users/mstefanko/.git-hooks/post-checkout` so a missing `.overcommit.yml` does not crash.
2. `npm rebuild better-sqlite3` inside `/Users/mstefanko/.claude/plugins/cache/context-mode/context-mode/1.0.14/` — or re-run `/context-mode:ctx-upgrade` after the git hook is fixed.
3. Restart Claude Code; verify `/context-mode:ctx-doctor` shows `FTS5 / better-sqlite3: PASS`.
4. PreToolUse hook in `bakeoff/CLAUDE.md` should suppress the `<context_guidance>` injection when the MCP server reported an error this session (stat a sentinel, or check server connect status).

---

## Tier 3 — Cosmetic / housekeeping

### HOUSEKEEPING-1 — 18 work-order files at repo root
**Severity:** Cosmetic. Works; pollutes `ls`.
**Audits:** `SESSION-AUDIT-2026-05-23.md §D1`.
**Verified:** `ls *.work-order.json | wc -l` = 18 at consolidation time.
**Definition of done:** move existing work orders to `work-orders/`. Update any examples / docs that imply repo-root is the convention. Optionally add a `.gitignore` entry for repo-root `*.work-order.json` to discourage drift.

### HOUSEKEEPING-2 — Avoid clever one-liners in Bash heredocs
**Severity:** Trivial. One Python heredoc in the `db11` session sliced `print(...)[:200]` (None-slice). Cost ~10 s.
**Audits:** `SESSION-AUDIT-2026-05-23-supervisor-bakeoff.md §W-3`.
**Definition of done:** noted in the skill review checklist; no code change.

---

## Items intentionally dropped (false positives or out of scope)

- **"ledger.jsonl missing"** was unknown in the source audit. **Verified not a bug** — no consumer requires it. Demoted to CLI-10 as a doc cleanup.
- **"triage --force deletes failure forensics" (general)** — **PARTIALLY ADDRESSED**. The failure-case preservation already exists (`TestForceTriageProviderFailurePreservesPreviousTriage`). Only the success-replaces path needs the archive (CLI-7).
- **Codex stderr volume as "no action" item** in `1792` audit — superseded by CLI-3 (multiple reproductions across runs warrant action).
- **Substantive technical follow-ups from the runs themselves** (kill-after-reap design conflict, `goleak` dep, Windows job object handle storage, Strategy 4 implementation): these are user-facing implementation decisions on top of run outputs, **not** bakeoff/skill issues. They live in the source audits' "P3 substantive technical follow-ups" sections and should be tracked separately by the user as feature work, not as bakeoff bugs.

---

## Suggested execution order

Ranked by user-visible blast radius × inverse effort. CLI items pair well into batched PRs as noted.

| # | Item | Severity | Effort | Notes |
|---|---|---|---|---|
| 1 | CLI-1 — dispute report map literal leak | High | S | Confirmed bug, three runs reproduce. Tiny `report.go` fix + unit test. |
| 2 | CLI-11 — status-string glosses | Medium | S | Same `report.md` rendering area as CLI-1; ship together. |
| 3 | CLI-3 (reporting half) — truncated-stderr marker in `report.md` | Medium | S | Same area; ship with CLI-1 + CLI-11. |
| 4 | SKILL-1 — recommend escalate when artifact signals support it | High UX | S | Skill-only. Three reproductions. |
| 5 | SKILL-5 — never invent provider/model variants | High | S | Skill-only. Correctness. |
| 6 | CLI-5 — false-positive triage recommendation | High | S | Mode gating + substring-context filter in `triagepkg.ShouldRecommendTriage`. |
| 7 | CLI-2 — `runs/latest` symlink update across all subcommands | Medium | M | Audit each command path; centralize in a post-run hook. |
| 8 | CLI-3 (capture half) — filter codex stderr at capture time | Medium | M | Drops 350 KB → ~1 KB. Surfaces buried errors. |
| 9 | SKILL-3 — escalation router: triage gaps + scope disclosure | High UX | S | Skill-only. |
| 10 | CLI-4 — validator prose-path false positives | Low (high-frequency) | S | Pairs with SKILL-8 — fix the validator first, then the skill template. |
| 11 | SKILL-2 — approval-verb / choice-label normalization | Low UX | S | Skill-only. Five reproductions. |
| 12 | CLI-7 — `triage --force` archive on success | Medium | S | Test pattern already exists; mirror it for the success path. |
| 13 | SKILL-4 — canonical work-order field drafting checklist | Medium | S | Skill-only. |
| 14 | CLI-6 — classify zero-byte termination | Medium | M | New class in `classify.go` + runner integration. |
| 15 | SKILL-10 — triage-failure report card template | Medium UX | S | Skill-only. |
| 16 | SKILL-6 — AskUserQuestion framing for add-provider redirects | Medium UX | S | Skill-only. |
| 17 | SKILL-13 — lead post-run summaries with verdict | Low UX | S | Skill-only. |
| 18 | SKILL-7 / 8 / 9 — preview affordances, warning verbatim, unhedged final | Low UX | S | Skill-only; bundle. |
| 19 | CLI-8 — `bakeoff show` stderr tail on failed triage | Low | S | |
| 20 | CLI-9 — `quiet_tick_count` semantics | Low | S | Decide rename vs. fix after reading the increment site again. |
| 21 | SKILL-11 / 12 / 14 — caveats dedup, final-pass output check, dispute single-confirm | Low UX | S | Skill-only; bundle. |
| 22 | CLI-12 — unify finding numbering / section names | Low | S | Smallest fix is the glossary block. |
| 23 | CLI-10 — `ledger.jsonl` doc cleanup | Trivial | S | Grep docs/skills; remove or implement. |
| 24 | HOUSEKEEPING-1 — move work orders to `work-orders/` | Cosmetic | S | Optional. |
| 25 | ENV-1 — context-mode MCP rebuild | Medium | S | Independent of Bakeoff; handle whenever. |

---

## Inputs a fresh session needs

- This file.
- The five source audits listed at the top.
- `internal/report/report.go:849-866` and `internal/report/report_test.go` (CLI-1).
- `internal/report/report.go:191-195` (CLI-1 sibling fallbacks).
- `internal/ledger/ledger.go:15,83` (CLI-2).
- `internal/provider/` codex backend stderr capture (CLI-3).
- `internal/commands/validatecmd/validate.go:140-200` + `repocontext.ValidateProsePaths` (CLI-4).
- `internal/commands/researchcmd/run.go:376,722` + `triagepkg.ShouldRecommendTriage` (CLI-5).
- `internal/runner/classify.go` (CLI-6).
- `internal/commands/triagecmd/triage.go:128-149` + `triage_test.go:54` (CLI-7).
- `internal/runner/runner.go:84,97,754,765` (CLI-9).
- `internal/triage/state.go:186-187` + `internal/report/report.go:21-22` (CLI-12).
- `internal/provider/provider_test.go:24` (SKILL-5 catalog).
- `skills/bakeoff-run/SKILL.md` (every SKILL-* item).
- `runs/2026-05-23-{e57e,95b9,bb94,ee29,db11,871b,0aee,1792,fddc,276a,b6f3}/` (artifacts for each reproduction).

End of consolidated plan.
