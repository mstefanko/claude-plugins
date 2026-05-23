# Session Audit — 2026-05-23 — `decision-typing-vs-validators-compare`

Audit of a single `/bakeoff:run` invocation: comparison of typed decision
structs + stricter JSON decoding vs. smaller targeted validators around the
existing `map[string]any` flow. The run itself succeeded; this file captures
orchestration friction, CLI false positives, and a missed escalate
recommendation that should be addressed before the next session.

## Run Information

| Field | Value |
|---|---|
| Run id | `2026-05-23-1792` |
| Work order | `bakeoff/decision-typing-vs-validators-compare.work-order.json` |
| Mode | `compare` |
| Exit | `0` |
| Decision kind | `consensus` (judge ran both passes ok) |
| Providers | `claude/sonnet` ok 185.5s · `codex/gpt-5.5` ok 199.7s |
| Judge | `claude/opus` xhigh — pass1 54.9s, pass2 48.9s |
| Run dir | `runs/2026-05-23-1792/` |
| Report | `runs/2026-05-23-1792/report.md` |
| Manifest | `runs/2026-05-23-1792/manifest.json` |
| Decision | `runs/2026-05-23-1792/decision.json` |

Outcome of the comparison itself: both providers recommend **Option B
(targeted boundary validators preserving `map[string]any`)** with overlapping
reasoning around `decision.json` structural polymorphism, the `workorder.go`
validator precedent, the `DisallowUnknownFields` forward-compat hazard, and
field-sparse display consumers. Substantive agreement; non-trivial
disagreements on migration scope and validator shape — see "Issue 3" below.

## Issues To Fix (Ordered By Impact)

### Issue 1 — Skill: `escalate` not offered despite eligible artifacts (high)

**Where**: `skills/bakeoff-run/SKILL.md`, "Execution And Summary" section,
recommendation-shape rules.

**Symptom**: This run ended `decision_kind: consensus`, exit `0`, but
`decision.json.consensus_disagreements` contains 7 explicit items (migration
scope estimate, validator placement detail, lsManifest precedent framing,
characterization of the workorder pattern, compile-time-typo concession, etc.).
The skill's `--mode dispute` description names exactly these conditions:
*"use when artifacts expose ties, conflicts, unknowns, judge caveats,
kept-from-nonwinner material, or triage gaps."*

The continuation actually offered was `bakeoff triage` (echoing the CLI's
suggestion — see Issue 2). `bakeoff escalate ... --mode dispute --dry-run` was
never surfaced.

**Why it matters**: A "consensus with named disagreements" is the highest-value
escalate case — a fresh peer (Gemini) can arbitrate specifically the points
the original two providers split on, at the cost of one provider call. Missing
it leaves the user with no signal that a third opinion is cheap and targeted.

**Fix**: In the artifact-aware recommendation logic, treat
`decision_kind == "consensus"` with non-empty `consensus_disagreements` as an
explicit trigger for an `escalate --mode dispute` recommendation. Suggested
heuristic precedence for `compare`/`analyze`/`gather`:

```
if decision_kind in {"unresolved", "disagreement"}:        recommend escalate --mode dispute
if decision_kind == "decision_incomplete":                 recommend judge-only rerun, then escalate --mode independent
if consensus AND len(consensus_disagreements) >= 3:        recommend escalate --mode dispute (NEW)
if consensus AND consensus_disagreements is empty:         stop / inspect only
```

**Acceptance**: A consensus run with N>=3 disagreement items prints exactly one
recommendation, and that recommendation is an `escalate --provider <peer>
--mode dispute --dry-run` line. Threshold is tunable.

### Issue 2 — CLI: false-positive triage suggestion on non-review runs (high)

**Where**: Bakeoff CLI's post-run "recommended" line emitter
(grep `"report mentions invalid"` in the Go source — likely
`internal/commands/researchcmd/run.go` or a shared summary writer).

**Symptom**: This run printed:
```
recommended: bakeoff triage 2026-05-23-1792  (report mentions invalid - verify before fixing)
```
The match came from the literal phrase *"fallback to empty map on **invalid**
decision reads"* inside `report.md` (a quoted F-002 finding). This was a
`compare` run, not `gather` + `code-review`, so triage does not apply at all.

**Why it matters**: Wrong continuation. Triage is a code-review tool. Pointing
a `compare`/`analyze` user at it is a wrong tool, and the substring match makes
the heuristic noisy in any narrative that quotes the word.

**Fix**:
1. Gate the "report mentions invalid" trigger on `type == "gather"` and
   `facet.id == "code-review"`. For any other mode, suppress this
   recommendation entirely.
2. Even within code-review runs, restrict the substring match: skip matches
   inside fenced quotes, finding text bodies (lines starting with `**F-`), or
   inside `consensus_strongest` echoes. A simple "word in unquoted prose"
   filter is a reasonable start.

**Acceptance**: Re-running this exact work order prints no `bakeoff triage`
recommendation. A synthetic `code-review` `gather` run whose report mentions
the word "invalid" in prose still does suggest triage.

### Issue 3 — CLI: prose-path validator false positives (medium)

**Where**: Validator that emits the `<context-root>` warnings during
`bakeoff validate`. From the error output: this run produced

```
warning: goal references "decision/manifest/triage" which does not exist
   under <context-root>; did you mean one of: internal/triage/?
warning: background references "files/tests" which does not exist under
   <context-root>; did you mean one of: tests/?
```

The matched substrings are English phrases — `"decision/manifest/triage"` is
a slash-joined list of concepts, `"files/tests"` is the tail of "in named
files/tests". Neither is a path the work order is referencing.

**Why it matters**: Warnings appear on otherwise clean drafts. Skill
instructions tell the assistant to surface validator output verbatim, which
forces hand-waving like *"warnings are advisory false-positives"* — that
dismissal removes user agency to judge.

**Fix**:
- Require a leading path separator, a directory prefix from the workspace root
  (e.g. `internal/`, `cmd/`, `docs/`), or a known file suffix
  (`.go`, `.json`, `.md`) before a slash-bearing token is treated as a path
  reference.
- Exclude phrases that contain whitespace-adjacent commas or start with a
  lowercase word followed by a slash and another lowercase word (e.g.
  `files/tests`, `read/write`, `pass/fail`).
- If the change is too invasive, demote these warnings to debug-only output or
  hide them behind `--strict-paths`.

**Acceptance**: This work order revalidates clean with no warnings. A real
broken path like `internal/decicision/decision.go` still warns.

### Issue 4 — Skill drafting + Plugin hooks: context-mode MCP is dark, hooks still nag (medium)

**Where**:
- Local machine: context-mode MCP server's `better-sqlite3` was built against
  `NODE_MODULE_VERSION 131`; current Node is 147. Every
  `ctx_batch_execute` / `ctx_execute` call fails with that mismatch.
- Bakeoff plugin's PreToolUse Bash hook (`/Users/mstefanko/.claude/plugins/.../bakeoff/CLAUDE.md`)
  keeps injecting `<context_guidance>` suggesting `ctx_batch_execute` even
  after MCP failed twice.

**Symptom**: Drafting required ONE batched context pass. I attempted MCP
batch_execute first, got an ABI error, retried with `ctx_execute` (same
error), then fell back to a single bounded Bash command. The hook then
re-suggested MCP on every subsequent Bash call. No real harm — just noise and
two wasted MCP attempts.

**Why it matters**: When MCP is dark, every Bash call gets a stale "use MCP
instead" reminder that contradicts the only working tool. Future sessions on
this machine will hit the same loop until context-mode is rebuilt.

**Fix** (two layers):
1. **Local**: rebuild context-mode MCP against the current Node ABI:
   ```
   cd ~/.claude/plugins/cache/context-mode/context-mode/1.0.14
   npm rebuild better-sqlite3
   ```
   Verify with `/context-mode:ctx-doctor`.
2. **Plugin hook**: skip the `<context_guidance>` injection when the MCP
   server has reported a startup or runtime error in the current session.
   Hook can stat a sentinel the MCP writes on first successful boot, or check
   `claude` runtime state for the server's connect status. Falling back to
   silent injection beats nagging the assistant to use a broken tool.

**Acceptance**: With MCP healthy, drafting can use one
`ctx_batch_execute`. With MCP unhealthy, the hook stops suggesting it.

### Issue 5 — UX: assistant-side response patterns to tighten (low → medium)

**Where**: `skills/bakeoff-run/SKILL.md` preview, validation, and final
summary templates — or the assistant's adherence to them. Findings from
`ux-researcher` agent run during this session.

**A. Compact preview is missing affordances.**
- Three synonymous approval verbs (`yes` / `approve` / `run it`) are listed
  without explaining they are synonyms or which is canonical.
- The work-order file path (`./<id>.work-order.json`) was mentioned but
  not visually anchored as "this is what will be written on approval".
- The run id is not shown pre-write; the user can't reference future
  artifacts until after the run.
- No explicit "cancel" / "abort" wording is offered.

**Fix**: In the preview template, (1) collapse approval verbs to a single
canonical `yes` with the others listed as accepted aliases; (2) bold or
underline the target file path as the mutation target; (3) say "Run id will
be assigned by the CLI on launch — preview-time id is the file basename";
(4) add an explicit "Reply `cancel` to discard this draft."

**B. Validation message dismisses warnings without listing them.**
The phrase *"warnings are advisory false-positives"* asks the user to trust
the assistant's judgment without showing the warnings. When warnings are
genuinely benign (Issue 3 above), they still belong in the message verbatim
so the user can disagree.

**Fix**: In the post-validate template, always print each warning on its own
line, with a one-line assistant gloss after. Never elide.

**C. Final summary's one continuation should be unhedged.**
The phrase *"for a pure design comparison this is usually optional"*
contradicts the recommendation it accompanies. Either recommend cleanly or
don't — the hedge invites re-reading.

**Fix**: Pick the recommendation based on artifact signals (Issue 1) and
state it without softening. If the artifact signal is weak, recommend
`stop / inspect only`.

**Acceptance**: A representative preview reads without ambiguity in a
single pass; the post-validate message lists each warning; the final summary
contains exactly one unhedged continuation.

## Items Not To Fix (Logged For Awareness)

- **Codex stderr volume.** This run captured 393KB observed / 60KB persisted
  stderr against 13.7KB stdout. `stderr_kind: diagnostic`, not an error, and
  the persistence cap behaved correctly. No action.
- **Decision content.** The comparison concluded in favor of Option B
  (targeted validators). That is the substantive answer to the original
  question and is not part of this audit. Acting on it is a separate task.

## Suggested Follow-Up Order

1. **Open the report** to read the full comparison:
   `bakeoff show 2026-05-23-1792`
2. **Run the missed escalate** (one provider call) to get Gemini's adjudication
   of the 7 named disagreements before deciding implementation scope:
   ```
   bakeoff escalate 2026-05-23-1792 --provider gemini --mode dispute --dry-run
   ```
   Approve the previewed work order, then drop `--dry-run` to execute.
3. **File Issue 1 + Issue 2** in the bakeoff repo with this audit attached —
   both are gating quality bugs for the `compare` and `analyze` modes.
4. **Rebuild context-mode MCP** locally (Issue 4 step 1) so the next session
   regains the batched context tool.
5. **Triage Issues 3 and 5** as polish work for the next skill / CLI
   tightening pass.
