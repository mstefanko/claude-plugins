# Session Audit — Supervisor Bakeoff (2026-05-23)

This file is a portable handoff. Open it in a new session and work the
**Action Items** section. Everything else is context.

---

## 1. What happened

User invoked `/bakeoff:run` with: *"compare hardening the current supervisor
versus introducing an explicit process-state machine with race/leak tests."*

Three runs executed in sequence:

| # | Run id | Type | Elapsed | Providers | Winner / Result | Notes |
|---|---|---|---|---|---|---|
| 1 | `2026-05-23-db11` | compare | 371s | claude/sonnet, codex/gpt-5.5 | claude | judge converged across both passes |
| 2 | `2026-05-23-871b` | analyze | 350s | claude/sonnet, gemini/gemini-2.5-pro | claude | `swap_agreement` tiebreak (strongest signal) |
| 3 | `2026-05-23-0aee` | escalation | 57s | codex/gpt-5.5 (dispute on #2) | `escalation_advisory_supported` | confirmed source decision |

### Per-provider status

| Run | Provider | Status | Wall | Stdout | Stderr | Retries |
|---|---|---|---|---|---|---|
| db11 | claude | ok | 151.1s | 10179 B | 0 B | 0 |
| db11 | codex | ok | 259.4s | 11144 B | **60000 B (cap hit, ~286 KB observed)** | 0 |
| 871b | claude | ok | 231.9s | 17290 B | 0 B | 0 |
| 871b | gemini | ok | 106.4s | 4462 B | 847 B | 0 |
| 0aee | codex | ok | 56.4s | 2615 B | **60000 B (cap hit)** | 0 |

All three runs exited 0. No format retries. No provider failures. Judges ran
cleanly. The session output is sound — the issues below are about *waste,
clarity, and consistency*, not correctness.

### What the runs produced (preserved for context)

- **Compare verdict:** Approach A (incremental hardening of `internal/runner/`)
  beats Approach B (typed state machine). Existing `sync.Mutex` + `sync.Once`
  guards already serialize state; B introduces a migration-period race window
  the rewrite is supposed to prevent.
- **Analyze output:** 7-phase plan, ~370 LOC, no public API changes. Phases
  1–3 are independent (goleak `TestMain`, `context.AfterFunc` backstop,
  delete kill-after-reap call). Phase 7 (Windows job objects) is orthogonal.
- **Escalation:** codex resolved two factual unknowns (no `TestMain`/goleak
  present in test file; `go.uber.org/goleak` not in `go.mod`). Left open:
  Windows job-handle storage mechanism + the **kill-after-reap design
  conflict** (delete the dead path vs. add atomic `reaped` flag) — not a
  fact question, so dispute mode wouldn't touch it.

Work orders written this session:
- `supervisor-harden-vs-state-machine.work-order.json`
- `supervisor-harden-implementation-plan.work-order.json`

---

## 2. What went wrong / wasted time

### W-1 — context-mode MCP is broken on this host
**Severity:** medium (blocks "one batched context pass" invariant)

```
The module 'better-sqlite3/build/Release/better_sqlite3.node'
was compiled against a different Node.js version using
NODE_MODULE_VERSION 131. This version of Node.js requires
NODE_MODULE_VERSION 147.
```

`ctx_batch_execute` failed on first call. I fell through to ~6 separate
`Bash` probes during drafting (file find, package list, doctor JSON, examples
list, Python parse, etc.), each triggering the context-guidance reminder
hook. This violates the skill's **"one batched context pass during drafting"**
invariant.

**Fix:** run `/context-mode:ctx-upgrade` (or `npm rebuild better-sqlite3` in
`~/.claude/plugins/cache/context-mode/context-mode/1.0.14/`) before the next
bakeoff session.

### W-2 — codex stderr blew through the cap in two of three runs
**Severity:** medium (provider hygiene; potential CLI bug)

Codex emitted 286.9 KB of stderr in run `db11` (capped at 60 KB) and capped
again in `0aee`. Tagged `stderr kind: diagnostic`; judge ignored it; no harm
done. But it's consistent across runs and probably reflects codex's
tool-call / heartbeat logging being too chatty. Worth a diagnostic pass.

**Fix:** open `runs/2026-05-23-db11/providers/codex/stderr.txt` and classify
the noise. If it's tool-call traces, gate them behind a verbosity flag. File
a bakeoff bead.

### W-3 — minor self-inflicted shell error
**Severity:** trivial

A Python heredoc had `print(...)[:200]` (slicing the return of `print()`,
which is `None`). Cost ~10s. Not worth fixing systemically, but flag the
"avoid clever one-liners in Bash heredocs" pattern when reviewing the skill.

---

## 3. UX issues to address

These came from a parallel `ux-researcher` audit of the session transcript.

### U-1 — `escalate` should have been offered after the compare run
**Severity:** high (new feature, mis-pitched)

After run #1 (compare), I offered only `plan it` / `inspect`. The compare
report had a 6-item `Kept From Nonwinner` block (Windows job objects,
WaitDelay/StdoutPipe contracts, lifecycle invariants) — explicit signal that
the loser had decision-relevant points the winner only partially engaged
with. That's textbook escalation territory.

**Fix in skill:** *Any non-empty `Kept From Nonwinner` section in a compare/
analyze report should trigger a visible `escalate` option in the
"Next step" block.* Update `skills/bakeoff-run/SKILL.md`'s "Execution And
Summary" section.

### U-2 — `escalate` after the analyze run was correct but under-explained
**Severity:** medium

I pitched dispute mode as "focused only on contested points" but did NOT say
up front that it is **advisory-only and cannot pick a new winner**. The user
discovered that constraint only when reading the result.

**Fix in skill:** when offering a dispute escalation preview, state the
advisory-only constraint in the preview itself, not after the run.

### U-3 — the "gemini + gemini-pro variant" option was invented
**Severity:** high (correctness)

In turn 3, I asked the user via `AskUserQuestion` whether Gemini should pair
with claude, codex, or "gemini-pro variant." Bakeoff's catalog backends are
`claude`, `codex`, `gemini`, `copilot` — there is no "gemini-pro" backend.
That option was a hallucination.

Worse, the question was probably avoidable. The user said "bring in gemini to
handle the analyze." Prior pair: claude+codex. The natural default is
**swap the non-winner (codex) for gemini**, giving claude+gemini, and
confirm inline.

**Fix in skill:** when a user names one provider as a replacement after a
just-completed run, default to swapping the non-winner and show that pair in
the preview, only asking if ambiguous. Never offer model variants that aren't
in the catalog.

### U-4 — choice-label drift across turns
**Severity:** medium

Labels the user saw across turns: `yes`, `show`, `plan it`, `build it`,
`build phase 1-2`, `inspect`, `escalate`, `escalate independent`, `stop`.

Problems:
- `show` (prints JSON) and `inspect` (opens the report) overlap semantically.
  Pick one.
- `build it` vs `build phase 1-2` inconsistently scopes (verb vs verb+scope).
  Pattern should be `<verb>` for default, `<verb>: <scope>` when narrowed.
- `escalate independent` (mode-suffixed only sometimes) — either always
  suffix the mode or never.

**Fix in skill:** add a "Choice-label conventions" subsection to the
bakeoff-run skill with the canonical verbs and scoping pattern.

### U-5 — summaries lead with run-id, not the verdict
**Severity:** low

My post-run summaries opened with run-id + exit code. The user's first
question is *what did it decide?* — that should be line 1.

**Fix in skill:** in the post-run summary template, lead with `Decision: X
wins — <one-line position>`, then run-id/inspect command second.

### U-6 — hostile CLI output in escalation report
**Severity:** high (bakeoff CLI bug, not skill)

The escalation `report.md` (`2026-05-23-0aee/report.md`) emits raw Go
`fmt`-style maps:

```
- map[answer:... id:D-001 verdict:resolved]
- What changed: map[evidence:[...] point_id:D-001] (+2 more)
- Still unresolved: map[answer:... id:D-002 verdict:unresolved] (+1 more)
```

That's `fmt.Sprintf("%v", m)` on a `map[string]any` leaking through to a
user-facing markdown report. The `(+N more)` truncation also forces the
user to open the file to see the rest.

**Fix in bakeoff CLI:** the escalation report renderer should pretty-print
dispute points as a list of struct fields, not raw maps. File a bead.

### U-7 — three parallel numbering schemes
**Severity:** low

Reports use `F-NNN` (findings), `R-NNN` (rationale), and `D-NNN` (dispute).
Compare uses `Kept From Nonwinner`; analyze uses `Additions From Loser` for
the same concept. The user has to maintain three mental indexes.

**Fix in bakeoff CLI:** unify on one numbering scheme and one section name
across modes, or document the mapping in a glossary at the top of every
report.

### U-8 — escalate has one too many steps for dispute mode
**Severity:** low

Cycle was: preview → dry-run → cost preview → `yes` → run. Dispute mode is
cheap (1 provider call, 0 judge passes, advisory) — the dry-run/cost-preview
gate adds friction without proportional safety.

**Fix in skill:** for `dispute` and `witness` modes, collapse to a single
confirm with cost embedded in the first preview.

---

## 4. Action Items (work this list in the new session)

Prioritized. Tag each with bead id when created.

### P0 — correctness

- [ ] **U-3** Fix skill: never invent provider model variants. When user adds
  one provider after a just-completed run, default to swapping the
  non-winner and confirm inline. Edit `skills/bakeoff-run/SKILL.md`
  "Provider-pair extraction rules."
- [ ] **U-6** File bakeoff CLI bug: escalation report renderer leaks raw Go
  `map[...]` strings into markdown. Fix in escalation report writer (search
  for `fmt.Sprintf` or `fmt.Fprintln` of map values in
  `internal/.../escalation`).

### P1 — UX

- [ ] **U-1** Skill: trigger `escalate` option whenever `Kept From Nonwinner`
  is non-empty on compare/analyze.
- [ ] **U-2** Skill: state "advisory-only, cannot pick new winner" in
  dispute/witness escalation previews.
- [ ] **U-4** Skill: add "Choice-label conventions" subsection. Reconcile
  `show` vs `inspect`. Settle on `<verb>: <scope>` for scoped variants.
- [ ] **U-5** Skill: lead post-run summary with `Decision: ...`, not run-id.

### P2 — diagnostics / hygiene

- [ ] **W-1** Fix host: `/context-mode:ctx-upgrade` to repair the
  `better-sqlite3` ABI mismatch.
- [ ] **W-2** Investigate codex stderr blowout. Read
  `runs/2026-05-23-db11/providers/codex/stderr.txt` and classify. If it's
  routine tool-call traces, file a bakeoff bead to gate behind a verbosity
  flag.
- [ ] **U-7** Bakeoff CLI: unify finding numbering schemes or add a glossary
  block at the top of every report.
- [ ] **U-8** Skill: collapse `dispute`/`witness` escalate to single-step
  confirm.

### P3 — substantive technical follow-ups from the runs themselves

Not session issues — these are real work the runs identified that the user
will eventually act on. Listed here so they aren't lost:

- [ ] **F-001 conflict** Resolve kill-after-reap design choice (delete dead
  path vs. add atomic `reaped` flag) before Phase 3 lands. Codex dispute mode
  declined to weigh in because it's a design choice. May warrant an
  `independent` escalation on `2026-05-23-871b`.
- [ ] **F-002** `go.uber.org/goleak` needs to be added to `go.mod` before
  Phase 1. Confirmed absent by codex (D-003).
- [ ] **F-003** Decide Windows Job Object handle storage mechanism (package
  map by PID, wrapper type, or `SysProcAttr` extension). Codex dispute mode
  confirmed the gap but declined to pick (D-002).

---

## 5. Quick reference

- Bakeoff binary: `/Users/mstefanko/.claude/plugins/data/bakeoff-mstefanko-plugins/bin/bakeoff`
- Skill: `/Users/mstefanko/.claude/plugins/cache/mstefanko-plugins/bakeoff/a40c1fcdf102/skills/bakeoff-run/SKILL.md`
- Inspect any run: `bakeoff show <run-id>`
- Run dirs: `runs/2026-05-23-db11/`, `runs/2026-05-23-871b/`, `runs/2026-05-23-0aee/`
