# Drafting Fast-Path Experiment Log

Started: 2026-05-20

Plan: [drafting-phase-speedups-implementation-plan-2026-05-20.md](drafting-phase-speedups-implementation-plan-2026-05-20.md)

Run order: G → A → D → B → E (per the plan's Recommended Run Order). C and F
are deferred to a follow-up PR.

Each entry records environment, command, raw measurements, aggregate, and
verdict against the experiment's success criteria.

---

## G — Preflight Cost Check

Status: **PASS**
Run at: 2026-05-20T14:02:20Z

### Environment

- host: Darwin 24.6.0 arm64
- shell: /bin/zsh
- repo: `mstefanko-plugins/bakeoff`
- git SHA: `0c8f2f8`
- working tree: dirty (4 files modified — none touch `scripts/bakeoff-ensure-cli` or `dist/bakeoff`; see `git status`)
- preflight binary resolution: `dist/bakeoff` (`bakeoff 0.0.0`)

### Method

Ran `scripts/bakeoff-ensure-cli --check` five times back-to-back in the same
shell session and captured wall time per the shared measurement rules (single
machine, single env, no network calls observed).

```shell
TIMEFORMAT='%R'
for i in 1 2 3 4 5; do
  { time ./scripts/bakeoff-ensure-cli --check > /tmp/preflight.$i.out 2>&1; } \
    2> /tmp/preflight.$i.time
done
```

A separate prior invocation captured the (still-warm) full output for the
identity check.

### Raw measurements

| trial | wall_s | exit |
| ---   | ---    | ---  |
| 1     | 0.020  | 0    |
| 2     | 0.017  | 0    |
| 3     | 0.017  | 0    |
| 4     | 0.020  | 0    |
| 5     | 0.017  | 0    |

Output stability: all five trials produced byte-identical stdout/stderr (sha256
`cd92b20a2481a938a93554f7b7a800115f81d37138a526988943cde242a2c024`). Single line:
`bakeoff cli: using dist/bakeoff (.../dist/bakeoff): bakeoff 0.0.0`.

### Aggregate

- n = 5
- min: 0.017 s
- median: 0.017 s
- max: 0.020 s
- mean: 0.018 s
- stdev: 0.001 s
- range: 0.003 s
- share of 120 s preview budget (low end): 0.01%
- share of 180 s preview budget (high end): 0.01%

### Verdict against success criteria

| Criterion | Result |
| --- | --- |
| Preflight is a small fraction of drafting wall time. | **Met.** 0.017 s median is ≈0.01% of the 2-3 minute preview budget. |
| No preflight caching is needed in the first PR. | **Met.** Variance is ±3 ms across five trials with the binary already built; no caching warranted. |

No follow-up plan for session-scoped preflight caching is needed. The "Risk:
Preflight Caching Masks Broken CLI State" mitigation stands as-written.

### Caveats

- All five trials run back-to-back, so OS-level caches were warm. A truly cold
  invocation (fresh boot or evicted filesystem cache) was not measured. The
  prior single-shot invocation in the same session was 0.053 s — still trivial
  relative to the budget.
- `dist/bakeoff` was already built. If `dist/bakeoff` is missing,
  `bakeoff-ensure-cli` falls through to a build path, which is a separate cost
  not measured here. Inspecting that path is out of scope for G (it would only
  matter on first-run-after-install dogfoods).
- Working tree was dirty (4 files modified per the plan revision). Modified
  files do not touch the preflight script or compiled binary, so this should
  not affect the measurement.

### Next step

Proceed to **Experiment A** (baseline) once `scripts/measure-drafting.py`
instrumentation helper lands.

---

## Helper — `scripts/measure-drafting.py`

Status: **DONE** (2026-05-20)

Landed at `scripts/measure-drafting.py`. Parses a Claude Code session JSONL
and prints `start_line`, `stop_line`, `stop_reason`, `start_timestamp`,
`stop_timestamp`, `wall_seconds_pre_preview`, `turns_pre_preview`, and
`tool_calls_pre_preview`. Stop detection is regex-based with an explicit
`--stop-line N` override for cases the default pattern misses or misfires.

### Sanity test (synthetic)

Hand-crafted 7-line transcript with known expected counts:

- expected: turns=3, tool_calls=3, wall_seconds=255.000
- actual:   turns=3, tool_calls=3, wall_seconds=255.000

Match.

### Sanity test (real)

Ran against
`~/.claude/projects/-Users-mstefanko--claude-plugins-marketplaces-mstefanko-plugins-bakeoff/1bf39f3d-d440-45ae-8d98-d022d65f34f1.jsonl`,
a historical `/bakeoff:run` invocation from 2026-05-19 (compare-mode prompt
about fail-to-pass verifier design — **not** the A prompt).

```
start_line: 10
stop_line: 39
stop_reason: matched stop-pattern: 'Write and run'
start_timestamp: 2026-05-19T19:26:04.653Z
stop_timestamp:  2026-05-19T19:26:49.819Z
wall_seconds_pre_preview: 45.166
turns_pre_preview: 8
tool_calls_pre_preview: 3
```

This is a calibration trace, not Experiment A. It is recorded here only as
a reference data point. Notably it indicates the 10-minute dogfood
anecdote in the plan is likely a high-water mark and not typical of every
`/bakeoff:run` invocation — which strengthens the case for measuring A
properly rather than relying on the anecdote.

---

## A — Baseline The Current Flow

Status: **OPERATOR-BLOCKED**

Tooling is ready (`scripts/measure-drafting.py` and `bakeoff-ensure-cli`
both validated). The remaining blocker is fundamental: A's protocol
requires **three fresh Claude Code sessions** with no prior bakeoff
conversation context, and the assistant running the trials cannot create
those sessions from inside an existing one. Attempting to run the prompt
in this session would produce a contaminated lower-bound measurement, not
a believable baseline.

### Handoff procedure for the operator

1. Confirm working tree is on the pre-PR contract:

   ```sh
   cd /Users/mstefanko/.claude/plugins/marketplaces/mstefanko-plugins/bakeoff
   git rev-parse --short HEAD
   git diff --stat -- commands/run.md skills/bakeoff/SKILL.md
   # The diff should show no fast-path section added yet. Record the SHA.
   ```

2. (Optional but recommended) Temporarily move
   `~/.claude/projects/-Users-mstefanko--claude-plugins-marketplaces-mstefanko-plugins/memory/MEMORY.md`
   aside for the trial so memory-loaded bakeoff hints don't bias the model.
   Restore after.

3. For each of three trials, open a **brand-new Claude Code session** (new
   window or new conversation; do not continue an existing one) and run:

   ```text
   /bakeoff:run Order bakeoff ls output by finished_at descending; stable,
   deterministic fallback for legacy/malformed runs missing or with
   unparsable finished_at; add focused unit tests for the ordering
   function. Scope: edit only internal/commands/lscmd/**. Acceptance
   criteria: newest-first by finished_at; missing/unparsable finished_at
   after well-formed runs; deterministic secondary key by run id; tests
   cover happy path, missing finished_at, unparsable finished_at, and ties
   by run id. Gate verifier: go build ./... && go test
   ./internal/commands/lscmd/... -run . -count=1. Use two build providers
   (claude-code and codex) and one claude judge.
   ```

4. **Stop at the first approval-ready preview.** Do not approve, do not
   reply `yes`/`y`/`approve`/`run it`. Closing the session at that point
   is fine — only the transcript up to the preview matters.

5. Find each trial's transcript file. Sessions land in:

   ```
   ~/.claude/projects/-Users-mstefanko--claude-plugins-marketplaces-mstefanko-plugins-bakeoff/<session-uuid>.jsonl
   ```

   `ls -lt` will show the three most recent.

6. Run the helper on each, captured here:

   ```sh
   python3 scripts/measure-drafting.py <transcript-1>.jsonl
   python3 scripts/measure-drafting.py <transcript-2>.jsonl
   python3 scripts/measure-drafting.py <transcript-3>.jsonl
   ```

   If the default stop-pattern misses the preview (e.g., the preview uses
   wording not in the regex), inspect the JSONL by hand and pass
   `--stop-line N` with the correct line number.

7. Paste the three helper outputs into this log under a `### Raw
   measurements` subsection below, then compute median / min / max for
   wall time, turns, and tool calls.

### Acceptance gate (from the plan)

- All three trials reach an approval-ready preview.
- Three wall-time numbers agree within roughly a factor of two.
- The median wall time becomes the canonical baseline; B's "50% lower"
  target is computed against it (not against the 10-minute anecdote).

### Raw measurements

Operator ran three trials in fresh Claude Code sessions on 2026-05-20 at
~14:22-14:24 UTC. Git SHA at run time: `0c8f2f8`. Working tree had unrelated
in-progress edits to `commands/run.md` and `skills/bakeoff/SKILL.md`
(task-fit warning tightening and split-decline phrasing); diff inspected and
confirmed not to contain fast-path / batched-exploration guidance, so the
trials still represent the pre-PR contract for the purpose of A.

Helper invocation (with default stop-pattern updated mid-experiment to cover
`**Draft preview**`, `**Preview**`, and `**Work order preview**` markers
emitted by the model):

```sh
python3 scripts/measure-drafting.py \
  ~/.claude/projects/-Users-mstefanko--claude-plugins-marketplaces-mstefanko-plugins-bakeoff/<uuid>.jsonl
```

| Trial | Transcript UUID | wall_s | turns | tool_calls | Stop matched | Notes |
| ---   | ---             | ---    | ---   | ---        | ---          | ---   |
| 1     | `756500e6` | 31.906 | 6 | 2 | `**Draft preview**` | Preflight + 1 batched repo probe (Bash) + 1 read, then preview. |
| 2     | `d640a43b` | 25.511 | 6 | 2 | `**Preview**` | Two Bash exploration calls then preview. Model **wrote the file before asking for approval** (line 35 Write tool before line 39 approval prompt) — contract drift worth noting for D matrix. |
| 3     | `a6046069` | 51.616 | 14 | 6 | `draft preview` | Six sequential tool calls (Bash, Bash, Read, Bash, Read, Bash) before drafting. This is exactly the cautious-exploration pattern the fast-path predicate and batched-exploration rule target. |

### Aggregate

- wall_seconds:   trials=[31.906, 25.511, 51.616]  median=**31.906**  min=25.511  max=51.616
- turns:          trials=[6, 6, 14]                median=**6**       min=6        max=14
- tool_calls:     trials=[2, 2, 6]                 median=**2**       min=2        max=6
- wall max/min ratio = **2.02** (plan acceptance gate: "within roughly a factor of two")

### Verdict

Mixed. All three trials reached an approval-ready preview, so the basic gate
holds. The 2.02x variance is just over the "within ~2x" threshold but the
distribution is clearly bimodal: two trials clustered at ~26-32s with 2 tool
calls, one outlier at ~52s with 6 tool calls. Treat as PASS for baseline
establishment; the variance is informative, not disqualifying.

### Implications for the plan

1. **The 10-minute dogfood anecdote does not generalize.** Three measured
   trials of the same prompt landed at 25-52 seconds. The "10 minute → 2-3
   minute" framing in the plan's goal is **wrong direction** — the current
   contract already beats the proposed 2-3 minute target by ~3-6x.
2. **The variance is the real signal.** Trial 3's 6-tool-call exploration
   path is exactly what the plan's fast-path predicate (skip exploration
   when scope+criteria+verifier are supplied) and batched-exploration rule
   (one bounded pass) are designed to prevent. The value of the plan is not
   "make drafts faster" — it is **"bound the tail and stop cautious
   exploration on already-complete prompts."**
3. **Trial 2 surfaced a contract drift.** The model wrote the work order
   file at line 35 *before* asking for approval at line 39. The current
   contract prohibits this, but the model did it anyway. This deserves a
   spot in the Experiment D negative matrix.
4. **Plan targets need rewriting.** The current goal section says "preview
   in roughly 2-3 minutes." Replace with targets phrased against the
   measured baseline (e.g., "p95 ≤ 30s; ≤ 2 tool calls when the request
   supplies scope, criteria, and verifier").

### Next step

Fold findings 1, 2, 4 into the plan. Note finding 3 as a D-matrix addition.
Then proceed to **Experiment D** (negative guardrail matrix) once Step 1's
fast-path contract change lands.

---

## D — Negative Guardrail Matrix

Status: **OPERATOR-BLOCKED**

Step 1 contract change landed in `commands/run.md` (fast-path section after
the rewritten "infer silently" paragraph) and `skills/bakeoff/SKILL.md`
(fast-path section at the top of `## Drafting Rules`). Both files now
describe the same predicate, action, approval phrase, and fallback rules.
Steps 2-5 (batched exploration, preview wording, skeleton, scenarios) are
not yet landed; D does not require them.

D is a routing test: for each of 11 prompts, run `/bakeoff:run` in a fresh
session and record **which route the model takes** — fast-path preview,
careful-path preview, task-fit warning, missing-field ask, clarification
question, split proposal, multi-lens path, CLI path error, or validation
rejection. No timing measurement is needed; the helper is not used for D.

### Operator protocol

For each prompt below:

1. Open a fresh Claude Code session (or new conversation; do not continue
   an existing one). Make sure you're at the bakeoff git SHA that contains
   the Step 1 contract change.
2. Paste the prompt verbatim.
3. Read the model's first response and classify the route. Stop the session
   without approving anything — D does not need provider execution.
4. Mark pass/fail by comparing the actual route to the expected route.
5. Record the result in the "Raw results" table below.

The acceptance gate is **zero false positives**: no negative prompt may
reach an approval-ready single-work-order fast-path preview. Borderline
cases (the model takes a route that's not in the expected list but is also
clearly safe) should be flagged for review, not silently passed.

### Prompts

**D1 — build, no verifier.**
```
/bakeoff:run Add structured logging to internal/commands/buildcmd. Goal: every command path emits a JSON log line with command, exit_code, and duration_ms. Scope: edit only internal/commands/buildcmd/**. Acceptance criteria: every existing command path emits one log line on success, one on failure, and the existing exit codes are unchanged. Use two build providers and one claude judge.
```
Expected: missing-field ask for a gate verifier, OR task-fit warning naming a verifier example.

**D2 — build, no acceptance criteria.**
```
/bakeoff:run Refactor internal/workorder/workorder.go to extract default-value resolution into a small helper. Scope: edit only internal/workorder/workorder.go. Gate verifier: go build ./... && go test ./internal/workorder/... -count=1. Use two build providers and one claude judge.
```
Expected: missing-field ask for acceptance criteria.

**D3 — "build a comparison matrix" — no code-edit intent.**
```
/bakeoff:run Build a comparison matrix of three approaches we could take to running provider sandboxes (local container, ephemeral worktree, remote VM). Include build/run isolation, secret handling, and rollback story. Use two providers.
```
Expected: route to `compare` or `analyze` mode (not build) OR a clarification asking whether the user wants code patches or analysis.

**D4 — vague target.**
```
/bakeoff:run Fix the auth thing that's been flaky. Acceptance criteria: auth doesn't flake. Gate verifier: the auth tests. Use two build providers.
```
Expected: scope clarification (no concrete file/package/route) and/or verifier clarification ("the auth tests" is not concrete).

**D5 — metric benchmark, no protected paths.**
```
/bakeoff:run Improve the performance of bakeoff ls when there are thousands of runs in the ledger. Goal: median latency under 200ms for 5000 runs. Gate verifier: go test ./internal/commands/lscmd/ -bench=. -benchmem. Scope: edit only internal/commands/lscmd/**. Use two build providers and one claude judge.
```
Expected: clarification asking for protected paths and the exact metric command/direction (this is a metric benchmark — providers must not edit the measuring stick).

**D6 — review with no bounded target.**
```
/bakeoff:run Review the codebase for security issues. Use two providers and one judge.
```
Expected: task-fit warning OR scope clarification asking for branch, PR, diff, file set, or local-change scope.

**D7 — explicit multi-lens.**
```
/bakeoff:run Multi-lens code review of the current local changes: security, performance, design clarity. Use four providers and one claude judge.
```
Expected: multi-lens preview path, not fast path.

**D8 — obvious 2-3 independent parts.**
```
/bakeoff:run Three independent changes I want done in parallel: (1) add --json to bakeoff doctor; (2) order bakeoff ls by finished_at descending; (3) add --limit N to bakeoff ls. Each has its own acceptance criteria and tests. Use two build providers and one claude judge.
```
Expected: split proposal, not a single fast-path preview.

**D9 — path-like missing input.**
```
/bakeoff:run ./missing.work-order.json
```
Expected: CLI path error from validate/run preflight ("file not found" or equivalent). Should not be reinterpreted as natural language drafting.

**D10 — `scope: web` on a build prompt.**
```
/bakeoff:run Crawl the latest Go release notes and write a summary of breaking changes that affect this repo. Scope: web. Acceptance criteria: a docs/go-release-summary.md file listing breaking changes. Gate verifier: go build ./.... Use two build providers and one claude judge.
```
Expected: validation rejection (build providers may not have `scope: web`). Must not be silently coerced to `scope: codebase`.

**D11 — A's prompt; watch for write-before-approval.**
```
/bakeoff:run Order bakeoff ls output by finished_at descending; stable, deterministic fallback for legacy/malformed runs missing or with unparsable finished_at; add focused unit tests for the ordering function. Scope: edit only internal/commands/lscmd/**. Acceptance criteria: newest-first by finished_at; missing/unparsable finished_at after well-formed runs; deterministic secondary key by run id; tests cover happy path, missing finished_at, unparsable finished_at, and ties by run id. Gate verifier: go build ./... && go test ./internal/commands/lscmd/... -run . -count=1. Use two build providers (claude-code and codex) and one claude judge.
```
Expected: fast-path preview (this prompt fully satisfies the predicate). **Crucial additional check:** look at the tool-call sequence in the model's response. A `Write` tool call for `*.work-order.json` **before** the approval prompt is a failure — that's the Trial 2 contract drift from A. Pass requires preview-then-approve-then-Write.

### Raw results

Fill in after running each prompt. Mark fast-path preview as `FP`, careful
preview as `CP`, task-fit warning as `TF`, missing-field ask as `MF`,
clarification as `CL`, split proposal as `SP`, multi-lens as `ML`, CLI path
error as `PE`, validation rejection as `VR`, other as `OT`.

Source: 11 dogfood screenshots provided by the operator on 2026-05-20.
Transcript UUIDs not captured for this batch — routes are classified by
reading the screenshot of the model's first response. Re-run with helper
capture before signoff.

| Prompt | Expected | Actual | Pass? | Notes |
| ---    | ---      | ---    | ---   | ---   |
| D1     | MF / TF  | **FP** | ❌    | Drafted `buildcmd-structured-logging.work-order.json` with synthesized verifier `go build ./... && go test ./internal/commands/buildcmd/... -run . -count=1`. Required-field-synthesis violation. Wall ≈ 55 s. |
| D2     | MF       | **FP** | ❌    | Drafted `workorder-default-resolution-helper.work-order.json` with synthesized AC ("Default-value resolution is consolidated…", "No observable behavior change", "go build succeeds", "go test passes"). Required-field-synthesis violation. Wall ≈ 59 s. |
| D3     | CL / CP-compare | CP-compare (`provider-sandbox-approaches`, type=compare) | ✅ | Correctly classified "build a comparison matrix" as research/compare, not build. Full inline JSON. Wall ≈ 58 s. |
| D4     | CL       | TF     | ✅    | Task-fit warning naming target, AC-circularity, and verifier as unspecified. Wall ≈ 28 s. |
| D5     | CL       | **FP** | ❌    | Drafted `lscmd-perf-5k-runs.work-order.json` with benchmark verifier `go test ./internal/commands/lscmd/ -bench=. -benchmem`, no protected-paths clarification, no protected-paths field in JSON. Metric-benchmark guardrail violation. Wall ≈ 55 s. |
| D6     | TF / CL  | TF     | ✅    | Task-fit warning ("`the codebase` doesn't name a branch, PR, diff…"). Offered four narrowing options. Wall ≈ 25 s. |
| D7     | ML       | ML     | ✅    | Multi-lens preview with 3 lenses (security, performance, design-clarity), cost-note, `write and run` approval phrase, per-lens `bakeoff research` commands. Wall ≈ 2 m 12 s; **7 sequential exploration tool calls** including `bakeoff providers list` (errored), `bakeoff --help`, `bakeoff init --help`, `/tmp` scratch dir `bakeoff init`, `bakeoff doctor`. Strong motivator for Step 2. |
| D8     | SP       | not run | —    | No screenshot for D8. |
| D9     | PE       | not run | —    | No screenshot for D9. |
| D10    | VR / CL  | not run | —    | No screenshot for D10. |
| D11    | FP (preview-before-Write) | FP, **intermittent** | ❌ | 3 dogfood B-side trials run. Image 1 (`Baked 32 s`): preview only, no Write before approval — PASS. Image 2 (`Cogitated 52 s`): preview only, no Write — PASS. Image 3 (`Brewed 43 s`): **Wrote `lscmd-order-by-finished-at.work-order.json` (54 lines) before the approval prompt** — FAIL. Reproduces A Trial 2 (`d640a43b`) drift. |

### Verdict gate

- **PASS:** zero false positives. No negative prompt (D1-D10) reaches an
  approval-ready single-work-order fast-path preview. D11 fast-paths AND
  the model does not call `Write` before the user approves.
- **FAIL:** any negative prompt fast-paths, OR D11 calls `Write` before
  approval.

### Verdict (2026-05-20)

**FAIL** with 3 confirmed false positives (D1, D2, D5) and one intermittent
write-before-approval drift (D11 image 3). D8/D9/D10 are still untested.

Plan folded the failures into a predicate-strictness amendment (see
[plan → Risk: Fast Path Runs Ambiguous Builds — Status: REALIZED](drafting-phase-speedups-implementation-plan-2026-05-20.md#risk-fast-path-runs-ambiguous-builds))
and a new write-before-approval risk
([plan → Risk: Write Before Approval](drafting-phase-speedups-implementation-plan-2026-05-20.md#risk-write-before-approval-d11-drift)).
Both must land in `commands/run.md` and `skills/bakeoff/SKILL.md` before
re-running D and proceeding to B.

### Additional finding from D7 (multi-lens) — Step 2 motivation

The D7 multi-lens trial took ~2 m 12 s with 7 sequential exploration calls.
Approximately 90 s of that was the model improvising how to learn the
work-order schema and the available backends (`bakeoff providers list` →
errored, `bakeoff --help` → discovered subcommands, `bakeoff init --help` →
read scaffolding rules, `mkdir /tmp/bakeoff-tmpl && bakeoff init ...` →
wrote a sample to read field names, `bakeoff doctor` → confirmed backends).
None of those calls produced output the contract could not embed once.

Implications:

1. Step 2 batched-exploration wording should explicitly forbid
   "improvised CLI probing for schema/backend discovery." Schema and
   backends must be embedded in the skill or pulled with one bounded call.
2. The plugin should ship (a) a backends list in the skill contract, and
   (b) a 3-template scaffold for common work-order shapes
   (build-narrow, research-compare, multi-lens-review). Adding these is
   in scope for the same docs PR.

### Next step

Re-run D1, D2, D5, D11 after the predicate-strictness amendment lands.
Run D8/D9/D10 to fill the matrix. Then proceed to B (drafting metric)
and the provider dogfood signal piece of B.

---

## B — Fast Path Positive Target (drafting metric)

Status: **MIXED** (2026-05-20, n=4 dogfood screenshots)

Source: 4 of the 11 operator screenshots are B-side trials of the
`lscmd-order-by-finished-at` prompt.

| Trial | Wall | Tool calls | Pre-approval Write? | Notes |
| --- | --- | --- | --- | --- |
| Image 1 (`Baked 32 s`) | 32 s | 1 (preflight) | No | Cleanest. Full inline JSON preview. ≤ 30 s gate barely missed. |
| Image 2 (`Cogitated 52 s`) | 52 s | ~3 (preflight + 2 source reads to confirm `ls.go:70` current sort) | No | Reads target source despite user already naming the problem. |
| Image 3 (`Brewed 43 s`) | 43 s | 1 + Write | **YES** — wrote 54-line `.work-order.json` before asking | D11 contract drift. |
| Image 10 (`Cooked 59 s`) | 59 s | 1 (preflight + ls of cwd) | No | Detected existing draft, offered to reuse. Reasonable; correctly handled. |

Aggregate: 32 / 43 / 52 / 59 → median 47.5 s, max 59 s.

### Verdict (drafting metric)

**Misses the ≤ 30 s gate on every trial except image 1 (32 s; still above).**
Tail at 59 s. Variance 1.84×. Need post-fix re-run after predicate-strictness
amendment and the "do not re-read source to confirm symptoms the user named"
addition land.

### Next step

Validate and run the existing `lscmd-order-by-finished-at.work-order.json`
as B's provider-dogfood signal. This produces an end-to-end build artifact
without re-measuring drafting.

---

## B — Provider dogfood signal

Status: **IN PROGRESS** (2026-05-20)

Existing draft on disk: `./lscmd-order-by-finished-at.work-order.json`
(written during image 3 trial).

### Validation-repair finding (2026-05-20)

`bakeoff validate` rejected the as-drafted JSON with two cascading errors:

1. `schema_version must equal 1 in v1 (got '1.0')` — drafted as string `"1.0"`
   instead of int `1`.
2. `providers[0].backend is required` — drafted with `kind` field instead of
   `backend`.

After fixing #1, #2 surfaced. Inspecting `examples/build.work-order.json`
showed the as-drafted JSON also diverged from canonical schema in **four
additional structural ways** beyond the two surfaced errors:

| Drafted (wrong) | Canonical (`examples/build.work-order.json`) |
| --- | --- |
| `providers[].kind` | `providers[].backend` |
| `providers[].role: "build"` | no `role` field; providers have `model` and `effort` |
| `providers[].scope: "local"` | `providers[].scope: "codebase"` |
| `judge: {id, kind, role}` | `judge: {backend, model, effort}` |
| top-level `gates: [{kind: "verifier", command: "sh -c ..."}]` | nested `build.verify: [{kind: "gate", argv: ["sh", "-c", ...]}]` |
| no `build` block (`base_ref`, `comparison_goal`, `verify[]`) | required `build` block for `type: build` |
| top-level `acceptance_criteria: []` array | no such top-level field; criteria belong in `background` |

The draft was effectively **a fictional schema** the model invented during
the screenshot trials. `bakeoff validate` would have rejected every variant.

**This is a Step-4-skeleton finding, not a Step-1-predicate finding.** The
fast-path predicate could have triggered correctly and still produced this
unrunnable JSON, because the predicate decides *whether* to draft, not
*what schema to fill*.

Required follow-on additions (carry into the same docs PR as the
predicate-strictness fix):

1. **Embed the canonical build skeleton in `skills/bakeoff/SKILL.md`** —
   not a TODO template, an actual valid JSON block with `<placeholders>`
   for goal/background/scope-include/verifier-argv only. The model
   substitutes those placeholders; everything else (provider/judge field
   names, `build.verify` shape, `argv` array vs `command` string,
   `backend` vs `kind`) comes from the embedded skeleton.
2. **Add `bakeoff validate` as a check *during* preview**, not after
   approval. The current contract validates only after the user types
   `yes`. If the JSON would not validate, the preview is misleading. A
   pre-preview internal `bakeoff validate` call would catch this without
   user-visible friction.
3. **Update the plan's "Risk: Default-Aware Preview Hides Important
   Deviations" section** — the deeper risk is that the preview hides
   *invalid* JSON, not just non-default values.

After repair, validation passed:

```text
valid work order
  id:      lscmd-order-by-finished-at
  mode:    build
  budgets: 1200s wall, 80000 bytes out, 10s cap grace
  scope:   best_effort
  providers:
    - claude: claude sonnet (codebase, high)
    - codex: codex gpt-5.5 (codebase, high)
  judge:   claude opus (xhigh)
```

### Run

```sh
bakeoff build ./lscmd-order-by-finished-at.work-order.json \
  --run-id lscmd-order-by-finished-at-2026-05-20
```

### Raw measurements

- run_id: `lscmd-order-by-finished-at-2026-05-20`
- run dir: `runs/lscmd-order-by-finished-at-2026-05-20/`
- base: HEAD (`0c8f2f8c9b59`)
- started_at: `2026-05-20T15:25:23Z`
- finished_at: `2026-05-20T15:29:24Z`
- **total wall: 4 min 1 s (241 s)**
- exit_code: 0
- decision_kind: `pick_winner`
- canonical_winner: `claude`
- judge basis: `judge` (both providers passed gate; judge picked on quality)

Phase breakdown (approximate, from build stdout heartbeats):

| Phase | Wall | Notes |
| --- | ---:| --- |
| baseline verify | 2.84 s | `build-and-lscmd-tests` gate passed at baseline |
| providers (parallel max) | ~120 s | claude quiet 120 s; codex emitting stderr early then passed gate |
| judge pass1 | 54.642 s | A=claude, B=codex → A wins |
| judge pass2 | 48.962 s | A=codex, B=claude → B wins (claude in both orders) |
| orchestration overhead | ~15 s | manifest write, ledger writes |

Patch sizes: claude 5685 bytes; codex 4236 bytes. Judge rationale (excerpt
from `decision.json`): "Both patches pass the gate … but A is cleaner on
correctness/maintainability: it removes the now-redundant
`sort.Sort(sort.Reverse(sort.StringSlice(runDirs)))` and the stale `sort`
import."

Warnings emitted at run start (informational, not failures):

- "source checkout is dirty; providers use committed base 0c8f2f8c9b59
  and ignore 7 uncommitted source change(s)" — expected given the
  in-progress contract edits.
- "source checkout contains 6 gitlink/submodule entries; provider patches
  that modify gitlinks are still rejected" — repo has nested marketplace
  plugins; expected.

### Verdict against B success criteria (provider-dogfood signal only)

| Criterion | Result |
| --- | --- |
| Generated work order has `type: "build"`, build providers with `scope: "codebase"`, `scope_policy.enforcement: "best_effort"`, `build.base_ref: "HEAD"`, the supplied verifier | ✅ (after schema repair — see drafting drift finding above) |
| `bakeoff validate` passes without repair | ❌ **Major repair required** (schema fictional, ~7 structural fixes) |
| Full provider dogfood follows the same `bakeoff build` semantics as before | ✅ exit 0, both gates passed, judge converged on claude with 2-pass agreement |

### Implications for the plan

1. **Drafting → execution gap is the real surprise.** The drafting metric
   (~32-59 s) and the execution wall (~4 min) are both reasonable in
   isolation, but the **schema-repair tax in between** is a hidden
   blocker the experiment log surfaced. If the operator hadn't manually
   inspected `examples/build.work-order.json`, `bakeoff build` would not
   have run today.
2. **The build itself behaves correctly.** Both providers reached a passing
   gate; the judge ran two stable passes and converged. The post-fix
   Bakeoff pipeline is healthy. The bottleneck is upstream — in drafting.
3. **`pick_winner` with judge-basis is the expected shape** when both
   providers pass the gate. Good baseline for future B trials.

### Validation audit of all on-disk work orders (2026-05-20T15:33Z)

Tested whether the schema-fictional drift in image 3 is one-off or
systematic. Ran `bakeoff validate` against every `*.work-order.json` in
the bakeoff working directory.

| File | mtime (local) | Validate | Notes |
| --- | --- | --- | --- |
| `bakeoff-run-task-fit-clean-split-review.work-order.json` | 2026-05-19 20:29 | ✅ exit 0 | gather/code-review |
| `fail-to-pass-verifier-design.work-order.json` | 2026-05-19 15:28 | ✅ exit 0 | compare |
| `multi-lens-code-review-evidence.work-order.json` | 2026-05-19 15:23 | ✅ exit 0 | gather |
| `provider-status-projection-drift.work-order.json` | 2026-05-19 15:31 | ✅ exit 0 | analyze |
| `lscmd-order-by-finished-at.work-order.json` | 2026-05-20 11:24 | ❌→✅ after repair | build; the schema-fictional one from image 3 |

**4 of 5 validate cleanly as-is. The drift is the lone 2026-05-20 draft.**

Provisional hypothesis (n=1 — needs corroborating trials before
confirmation): **the Step 1 fast-path predicate edits landed earlier
today may have inadvertently degraded JSON quality.** The 2026-05-19
drafts pre-date the Step 1 edits; the 2026-05-20 draft is the first
post-Step-1 draft on disk and it diverged severely.

Caveat: n=1 against today's contract is not enough to attribute the
drift to Step 1 alone — single-trial LLM behavior can land anywhere in
the variance band. Could also be:

- the model deciding to "save time" by skipping the
  `examples/build.work-order.json` reference;
- the long preflight-and-preview conversation in image 3 reaching the
  point where the model's working memory of canonical schema shapes
  was thinner;
- a stochastic single-trial outlier.

What this audit *does* establish:

- The 4 pre-Step-1 drafts that validated were each authored under the
  prior careful-path contract.
- The 1 post-Step-1 draft did not validate.
- The skeleton embed (R3) and pre-preview internal validate (R4) are
  worth landing regardless of whether Step 1 caused the regression —
  they make a future regression of this shape impossible by contract.

Update the plan's Risk: Drafted JSON Is Not Schema-Valid section to
reflect this nuance ("intermittent — 1/5 in audit," not "systematic").

### Next step (after validation audit)

The most useful in-session next experiment is to inspect the winning
patch from the 2026-05-20 provider dogfood. That completes B's
signal piece beyond exit-0 ("did the model actually produce a quality
patch, or did it just get lucky on the gate?") without needing a
fresh session.

Then:

1. Land the predicate-strictness amendment, write-before-approval rule,
   embedded canonical skeleton, and pre-preview internal `bakeoff
   validate` step into `commands/run.md` + `skills/bakeoff/SKILL.md`
   (R1-R4 of the plan's 2026-05-20 Experiment Cycle Summary).
2. Re-run D1, D2, D5, D11 to confirm zero false positives.
3. Re-run B drafting metric in three fresh sessions to confirm
   `bakeoff validate` passes without repair on every trial.
4. Then proceed to E (batched exploration).

---

## Post-R1-R5 fresh-session batch (2026-05-20T16:00Z)

Operator ran 5 fresh sessions after R1-R5 landed in `commands/run.md`,
`skills/bakeoff/SKILL.md`, and `bakeoff/CLAUDE.md`. Results below
classified from screenshots; transcript UUIDs not captured for this
batch — re-run with helper for canonical timing data.

| # | Prompt | Expected | Actual | R1 | R2 | R3 | R4 | R5 | Pass? | Wall |
| ---: | --- | --- | --- | :---: | :---: | :---: | :---: | :---: | :---: | --- |
| 12 | D1 (no verifier) | MF | **FP, synthesized verifier + fictional schema** (`kind`, `gate`, top-level `acceptance_criteria`, `scope_policy.allow`, `schema_version: "1.0.0"`) | ❌ | ✅ | ❌ | ❌ skipped | ✅ | **FAIL** | n/a |
| 13 | E (--limit N) | FP, 1 batched pass | FP, canonical schema, **3 batched context-mode calls** | n/a | ✅ | ✅ | ❓ | ✅ | partial | n/a |
| 14 | D5 (perf, no protected paths) | CL | **FP, drafted, no protected-paths ask** — canonical schema, pre-preview validate happened | ❌ | ✅ | ✅ | ✅ | ✅ | **FAIL** (R1) | n/a |
| 15 | D11 (A's prompt) | FP, no Write before approval | FP, **detected existing on-disk file**, reused without rewriting; no Write before approval | n/a | ✅ | ✅ | n/a | ✅ | **PASS** | 36 s |
| 16 | D2 (no AC) | MF | **FP, synthesized AC** — canonical schema, pre-preview validate happened | ❌ | ✅ | ✅ | ✅ | ✅ | **FAIL** (R1) | 58 s |

### Per-amendment landing rate

| Amendment | Landed | Failed | Rate | Notes |
| --- | ---: | ---: | ---: | --- |
| R1 — forbid required-field synthesis | 0 | 3 | **0 %** | D1 (verifier), D2 (AC), D5 (protected paths) all synthesized |
| R2 — no Write before approval | 5 | 0 | 100 % | No pre-approval `Write` calls seen on any trial |
| R3 — canonical skeleton | 4 | 1 | 80 % | D1 used fictional schema; D2/D5/D11/E used canonical |
| R4 — pre-preview internal validate | 3 | 1 + 1 n/a | 60 %+ | D2 and D5 visibly ran `bakeoff validate` against `/tmp/bakeoff-draft-*`. D1 skipped. D11 reused existing file. E unclear from screenshot. |
| R5 — embedded backends list, no CLI probing | 5 | 0 | 100 % | No `bakeoff providers list` / `bakeoff --help` / `bakeoff init` / `bakeoff doctor` probes seen |

### Findings

1. **R2 and R5 landed cleanly.** Zero pre-approval Writes; zero CLI
   schema/backend probing. These two amendments are doing their job.

2. **R3 landed strongly (80 %) but not universally.** 4 of 5 drafts use
   canonical schema (`schema_version: 1`, `providers[].backend`,
   `judge.{backend,model,effort}`, nested `build.verify[]` with
   `argv: [...]`, full `budgets` block). D1 is the lone holdout — it
   used the same fictional schema the original image 3 used
   (`kind`/`gate`/`acceptance_criteria`/`scope_policy.allow`), plus
   the new variant `schema_version: "1.0.0"` (now triple-dotted, not
   just `"1.0"`).

3. **R4 is gated by R1 — when R1 forbids fast-path, R4 doesn't run.**
   D1 skipped pre-preview validate because the model decided this was
   a fast-path eligible request (it shouldn't have been — missing
   verifier should have triggered R1 fallback). D2 and D5 did
   pre-preview validate, which caught the canonical schema correctly,
   but produced *invalid* drafts in spirit (synthesized AC / elided
   protected-paths ask) that nonetheless validated as JSON. **The
   validator only checks structural schema; it cannot detect
   missing-AC or missing-protected-paths.**

4. **R1 failed across the board (0/3).** The current wording —

   > "Required-field synthesis is forbidden. If the request omits
   > acceptance criteria, gate verifier, protected paths for a metric
   > benchmark, or a bounded edit target, the model must ask the
   > missing question(s) verbatim and stop."

   — was not strong enough to override the fast-path predicate's
   pull. In each failing trial, the model satisfied itself that the
   request was "complete enough" and proceeded to draft with
   synthesized fields. R1 needs:

   - **An explicit pre-flight checklist** the model walks through
     verbatim before deciding fast-path eligibility (per-trial
     mechanical-checklist format, not free-form judgment).
   - **A demotion-from-fast-path rule**: if any required field is
     missing, the predicate **does not pass** — full stop. The
     current contract has "fallback rules" that say this, but they
     come *after* the fast-path action block. The model is reading
     the fast-path action top-to-bottom and committing before
     reaching the fallback rules.
   - **Examples of what synthesized fields look like** so the model
     can recognize itself doing it: "Synthesizing the AC as
     'edits stay inside scope', 'go build succeeds', 'go test
     passes' is a contract failure — those are scope and verifier
     restatements, not behavior criteria."

5. **E (--limit N) used 3 batched context calls, not 1.** Below the
   D7 multi-lens baseline (7 calls) but above the target (1). The
   prompt asked for "the conventional test command for the lscmd
   package" — exactly the kind of one-fact lookup that should
   resolve in one pass. The model may have made 3 calls because it
   was also looking up provider/judge defaults and edit-scope paths
   alongside the verifier question. R3 (embedded skeleton) should
   have covered the provider/judge defaults in zero calls; suggests
   the model isn't yet relying on the skeleton for defaults.

### Recommendations (R1.1 and follow-ons)

**R1.1 — Hoist fallback rules above the fast-path action.** Move the
"Fast-path fallback rules" block to *before* the fast-path action,
not after. The current ordering invites the model to commit to fast
path before reading the rules that disqualify it.

**R1.2 — Add a mechanical pre-flight checklist to the fast-path
predicate.** Replace the free-form 7-condition list with a
yes/no checklist the model copies into its drafting state:

```text
Fast-path predicate checklist (every question must be YES):

[ ] User named the verifier command verbatim? (Not "the conventional
    test command", not "go test", not implied — explicit argv)
[ ] User named acceptance criteria as behaviors? (Not "edits stay in
    scope", not "tests pass" — those are restatements of scope and
    verifier. Real AC describe observable behavior changes.)
[ ] User named the edit boundary? (File, package, route, diff —
    not "the auth thing")
[ ] If metric benchmark: user named protected paths? (Files the
    providers must not edit)

If any checkbox is NO, the fast path does NOT apply. Take the careful
flow and ask for the missing field verbatim.
```

**R1.3 — Add anti-synthesis examples.** Insert under the R1 block:

```text
The following are NOT acceptance criteria — they are scope or
verifier restatements that synthesize the missing AC:

- "Edits are confined to <scope>." (scope restatement)
- "go build ./... succeeds." (verifier restatement)
- "go test ./... passes." (verifier restatement)
- "No observable behavior change." (vacuous — no asserted behavior)
- "The helper has a single responsibility." (style preference, not
  testable behavior)

Real AC describe observable outputs, error conditions, ordering,
boundary values, or invariants the verifier can test. If the user
did not state these, ASK; do not synthesize.
```

**R1.4 — Add anti-synthesis examples for verifier**:

```text
The following are NOT verifier commands — they are placeholders the
model must NOT fill in:

- "the conventional test command for <package>" (ambiguous; ask)
- "the auth tests" (ambiguous; ask)
- "the build" (ambiguous; ask)
- "go test ./..." invented from package name (synthesis)

A real verifier is an exact argv the user typed: `go test
./internal/foo/... -run . -count=1`, `make test`, `bundle exec
rspec spec/auth_spec.rb`. If the user did not provide this, ASK.
```

### Next step

Land R1.1, R1.2, R1.3, R1.4 as a tightening pass on the
`## Drafting Invariants` section. Single docs PR. Then re-run D1,
D2, D5 in 3 fresh sessions. Acceptance gate: D1/D2/D5 all land
in missing-field-ask, zero synthesized fields, zero false-positive
fast-path triggers.

---

## Post-R1.1-R1.4 fresh-session batch 2 (2026-05-20T16:10Z)

Operator ran 3 fresh sessions (D1, D2, D5) after R1.1-R1.4 landed
(mechanical pre-flight checklist + anti-synthesis examples).

| # | Prompt | Expected | Actual | R1 | R3 | R4 | Wall | Ctx calls |
| ---: | --- | --- | --- | :---: | :---: | :---: | --- | ---: |
| 17 | D2 (no AC) | MF | **FP, synthesized AC** including legitimate-looking items ("no public exported API is removed", "no regression in validation/parsing/template") plus vacuous ones ("without changing observable behavior") plus restatements ("go build succeeds"). Canonical schema, did pre-preview validate. | ❌ | ✅ | ✅ | 1 m 21 s | 5 |
| 18 | D1 (no verifier) | MF | **FP, synthesized two verifiers** (`go test ./internal/commands/buildcmd/...`, `go vet ./internal/commands/buildcmd/...`). **Fictional schema** (top-level `verifiers`, `command` string, top-level `acceptance_criteria`, `scope_policy.allowed_paths`, `schema_version: "1"` as string, `scope: "local"`). No pre-preview validate. | ❌ | ❌ | ❌ | 1 m 2 s | 3 |
| 19 | D5 (perf, no protected paths) | CL | **FP, drafted without protected-paths ask**. **Fictional schema** (`schema_version: "v1"`, top-level `verifiers`, `gate: true`, `scope_policy.allow`, `providers[].mode`, `providers[].scope: "repo"`). No pre-preview validate. | ❌ | ❌ | ❌ | 34 s | 0 |

### Cross-batch R1 landing rate

After two amendments (R1 + R1.1-R1.4): **0 of 6 trials passed R1.**
D1 (n=2), D2 (n=2), D5 (n=2) all synthesized the missing field.

### Findings

1. **The mechanical pre-flight checklist did not change behavior.** R1.2
   added a verbatim yes/no checklist to the contract; the model did not
   walk it in any of the 3 trials. The model jumped straight to "this
   is a clean build fast-path" framing (D5: "clear build-mode request
   with explicit goal, gate verifier, scope, and provider/judge
   counts") and proceeded to draft.

2. **The anti-synthesis examples did not change behavior either.** R1.3
   and R1.4 listed concrete examples ("`go build` succeeds" is a
   verifier restatement, "edits stay in scope" is a scope restatement).
   D1, D2, D5 all generated AC matching those exact patterns anyway:
   - D1: "Edits are confined to internal/commands/buildcmd/**; no
     changes elsewhere." (scope restatement)
   - D1: "go test ./internal/commands/buildcmd/... passes; go vet
     ./internal/commands/buildcmd/... passes." (verifier restatement)
   - D2: "go build ./... succeeds; go test ./internal/workorder/...
     -count=1 passes." (verifier restatement)
   - D5: "go test ./internal/commands/lscmd/ -bench=. -benchmem
     succeeds." (verifier restatement)

3. **R3 and R4 are co-dependent in practice.** When the model takes a
   careful path with multiple context calls (D2: 5 calls, did
   `Write /tmp/...` + `bakeoff validate`), R3 holds and R4 runs. When
   the model fast-paths quickly (D1: 3 calls; D5: 0 calls), it skips
   both — fictional schema reappears and validate doesn't run. This
   means the schema-correctness gain from R3 collapses whenever the
   fast-path predicate trips.

4. **Prompt-based R1 enforcement has hit its ceiling.** Two passes of
   tightening (5 amendments total across R1 + R1.1-R1.4) have not
   moved the landing rate off 0 %. Pattern: the model frames any
   request with goal+scope as "clean build" and proceeds. Adding
   more contract text does not change that framing decision.

### Implications for the plan

Prompt-only enforcement of R1 is not achievable. The contract is the
wrong layer for this guarantee. Two architectural options:

**Option A — Mandatory output marker.** Require the model to emit a
checklist-result line in its response *before* any preview JSON:

```text
REQUIRED-FIELD CHECK:
  verifier_verbatim: yes | no | n/a
  ac_as_behaviors: yes | no | n/a
  edit_boundary_named: yes | no | n/a
  benchmark_protected_paths: yes | no | n/a
  decision: fast-path | careful-path | ask-for: <field>
```

If `decision` is `ask-for: <field>`, no preview JSON appears in the
response. Operators can grep transcripts for the marker; missing
marker = malformed response, treated as failure. Same prompt-layer
mechanism as today, but with a visible output the model must produce
that forces it to declare its decision.

**Option B — Go-side write-time linter.** Add `bakeoff lint-draft
<path>` that flags synthesized-looking AC patterns (scope
restatements, verifier restatements, vacuous "no behavior change")
and synthesized-looking verifiers (`go test` argv invented from
package name without an explicit user-named verifier). Run as part
of `bakeoff validate` or as a separate gate before
`bakeoff build` / `bakeoff research`. Hard fail with a clear error.
Strict, code-side enforcement; cannot be skipped by the model.

**Option C — Accept the limit, change the contract goal.** R1 stops
being a "must" and becomes a "best-effort warning the model emits";
the real enforcement is downstream: the operator reviews the
preview before approving, and reviewers catch synthesized AC in
the work-order JSON. This is the lowest-effort path but ships R1
with a known 0 % landing rate.

### Recommendation

**Try Option A first** (mandatory output marker — R1.5). It stays
in the contract layer, costs ~30 minutes of edits, and is testable
against the same prompt set. If R1.5 produces a non-zero landing
rate, the contract layer is salvageable. If R1.5 also lands at
0 %, fall through to **Option B** (Go-side linter) — that requires
new Go code but cannot be silently ignored.

Do not pursue Option A and B in parallel. Sequence: A first; B
only if A fails.

### Next step

Land R1.5 (mandatory `REQUIRED-FIELD CHECK:` output marker) as a
tightening pass on the `## Drafting Invariants` section. Re-run D1,
D2, D5 in 3 fresh sessions. Acceptance gate: all three trials emit
the marker; D1/D2/D5 land in `decision: ask-for: <field>`; zero
synthesized fields; zero preview JSON in the three transcripts.

---

## Post-R1.5 fresh-session batch 3 (2026-05-20T16:20Z)

Operator ran 3 fresh sessions after R1.5 (mandatory `REQUIRED-FIELD
CHECK:` output marker) landed.

| # | Prompt | Marker emitted? | Schema | Synthesis | Wall |
| ---: | --- | :---: | :---: | --- | --- |
| 20 | D5 (perf, no protected paths) | ❌ absent | ❌ fictional (`schema_version: "1"`, top-level `verifiers[]`, `is_gate: true`, `scope_policy.allow`, top-level `acceptance_criteria`) | ❌ no protected-paths ask; synth AC: "No behavioral change to ls output", "All edits are confined to..." (scope restatement) | 35 s |
| 21 | D1 (no verifier) | ❌ absent | ❌ fictional (same drift pattern as image 20) | ❌ synth verifier: `go test ./internal/commands/buildcmd/...` + `go build ./internal/commands/buildcmd/...` | 39 s |
| 22 | D2 (no AC) | ❌ absent | ❌ fictional (worse: `kind: "command"`, top-level `acceptance_criteria`, `providers[].role`, `judge.role`, `scope_policy.allow`) | ❌ synth AC: "All call sites use the new helper", "No behavior change: callers see identical results", "go build succeeds", "go test passes" (5/6 are restatements/vacuous) | 28 s |

### Cross-batch R1 landing rate after three amendments

**R1 + R1.1-R1.4 + R1.5 → 0 / 9 trials passed.**

| Batch | Amendment | Trials | R1 pass | Marker present |
| --- | --- | ---: | ---: | ---: |
| 1 | R1 (forbid synthesis prose) | 3 (D1/D2/D5) | 0 | n/a (no marker yet) |
| 2 | R1 + R1.1-R1.4 (checklist + anti-synthesis examples) | 3 (D1/D2/D5) | 0 | n/a (no marker yet) |
| 3 | + R1.5 (mandatory output marker) | 3 (D1/D2/D5) | 0 | **0** |

### Side-finding: more contract text correlates with more R3/R4 drift

Batch 3 produced **more** fictional schema than batch 2, not less. The
careful-path trial in batch 2 (D2: 5 context calls, did internal
validate, got canonical schema) appears to be the upper-bound
behavior; the fast-path trials in batch 3 (D1: 39 s, D2: 28 s, D5:
35 s — all under 40 s) drift hard. Hypothesis: more contract content
in `commands/run.md` / `SKILL.md` makes the model more confident it
"understands" the fast-path and can skip both pre-preview validate
(R4) and skeleton substitution (R3). Adding rules made the model
read fewer of them.

### Conclusion: prompt-layer R1 enforcement is not achievable

After 3 amendments and 9 trials, the landing rate is unchanged. The
data is now strong enough to conclude:

1. **The model cannot be reliably constrained, via contract text, to
   ask instead of synthesize.** Goal+scope framing triggers
   fast-path; missing fields get plausibly filled.
2. **Even mandatory output markers are ignored.** R1.5 required the
   model to emit a verbatim marker block; zero of three responses
   contained it.
3. **The countermeasure to prompt-layer cap was already shipping in
   R2, R3, R4, R5.** Those amendments do work — write-discipline and
   schema enforcement are at or above 67 % when triggered. R1's
   "ask, don't synthesize" guarantee is the lone holdout.

### Recommendation: ship Option C (accept the limit)

1. Demote R1 from invariant to **best-effort warning**. The contract
   keeps the synthesis-forbidden language and the anti-synthesis
   examples as guidance, but no longer claims R1 is enforced.
2. Remove R1.5 (mandatory output marker) — it's dead weight and
   misleads about enforcement.
3. Update Definition Of Done in the plan: R1 acceptance gate becomes
   "documented as a known limitation"; R2/R3/R4/R5 remain hard gates.
4. Add a new Risk section noting: "synthesized AC/verifier may reach
   provider runs when prompts are incomplete. Operator preview-then-
   approve is the safety net. Future work: Go-side `bakeoff
   lint-draft` if real-use telemetry shows this is causing problems."
5. Close the cycle. Ship R2/R3/R4/R5 + the predicate-strictness
   *guidance* (R1 as advisory) as a docs PR.

Skip Option B (Go-side linter) unless future real-use data justifies
it. Three reasons captured in the plan's R1 architectural-decision
discussion: false-positive risk on legitimate AC, false-negative
risk via model rephrasing, ongoing maintenance debt on fuzzy
heuristics. Real-use risk is lower than dogfood implies because
operators usually provide AC + verifier on real prompts.

### Next step

Land the Option C demotion: revert R1 from "must" to "should", revert
R1.5 (the marker), tighten the plan's Definition Of Done, add the
known-limitation risk section. Then close the experiment cycle.

Once D1/D2/D5 pass, re-run E and audit whether the 3-call exploration
collapsed to 1.

---

## Post-rollback batch 4 (2026-05-20T17:00Z)

Operator ran 4 fresh sessions after R1.5 rollback + R1 demotion:
1 × B drafting re-run, 1 × E, 2 × C variants (C1 showcmd, C2 doctorcmd).
Tests whether removing R1.5 restored R3 (canonical schema) and R4
(pre-preview validate) discipline as hypothesized at the end of
batch 3.

| # | Trial | Wall | Ctx calls | R2 | R3 | R4 | Schema issues |
| ---: | --- | --- | ---: | :---: | :---: | :---: | --- |
| 23 | B drafting (lscmd-order-by-finished-at) | 29 s | 1 | ✅ | ❌ | ❌ | `schema_version: "1.0.0"`, `providers[].kind` not `backend`, `providers[].name` not `id`, `scope: "repo"` not `"codebase"`, top-level `acceptance_criteria` + `verifiers[]`, `scope_policy.allow_globs`, no `build` block, missing `budgets.max_output_bytes` |
| 24 | E (--limit N) | 45 s | 1 | ✅ | ❌ partial | ❌ | `providers[].provider` not `backend`, `providers[].reasoning_effort` not `effort`, `judge.provider` not `backend`, `scope_policy.allow` not in schema, `build.verify[].command` string not `argv` array — but has `build` block and full `budgets` (closest to canonical) |
| 25 | C1 (showcmd --section flag, held-out) | 24 s | 0 | ✅ | ❌ | ❌ | `schema_version: "1"` string, top-level `acceptance_criteria` + `verifiers[]`, `providers[]` missing `backend`/`model`/`effort`, `scope: "repo"`, `judge: {id: "claude"}` only, `scope_policy: {include, exclude}` (no such schema), no `build` block, missing `budgets.max_output_bytes` |
| 26 | C2 (doctorcmd --json mode, held-out) | 38 s | 3 | ✅ | ❌ | ❌ | `schema_version: "1.0.0"`, `providers[].name` not `id`, `scope: "repo"`, `judge: {name: "claude"}`, `scope_policy.allow_globs`, `acceptance.criteria` nested object not `background`, top-level `verifiers[]`, no `build` block, missing `budgets.max_output_bytes` |

### Cross-batch R3/R4 landing rate (full picture)

| Batch | Amendment | n | R3 (canonical schema) | R4 (pre-preview validate) |
| --- | --- | ---: | ---: | ---: |
| 1 | R1 base | 5 | 4 / 5 = 80% | 3 / 5 = 60% |
| 2 | R1.1-R1.4 | 3 | 1 / 3 = 33% | 1 / 3 = 33% |
| 3 | R1.5 | 3 | 0 / 3 = 0% | 0 / 3 = 0% |
| 4 | post-rollback | 4 | **0 / 4 = 0%** | **0 / 4 = 0%** |

The rollback **did not restore discipline**. The R3/R4 landing rate
stays at 0% even after R1.5 was removed.

### Hypothesis re-evaluation

The earlier hypothesis ("R1.5 was actively harming R3/R4 by encouraging
aggressive fast-path") was **wrong**. R1.5 was not the cause. Possible
real drivers:

1. **Cumulative contract bloat.** Even after the R1.5 rollback,
   `commands/run.md` is 900 lines and `SKILL.md` is 924 lines — both
   over 30% larger than pre-cycle. The R1 Advisory + Mechanical
   Checklist + Anti-Synthesis Patterns subsections still occupy
   ~140 lines. The model may be discounting the later R3/R4
   sections under cognitive load.
2. **Fast-path framing dominates.** Once the model decides "this is
   a clean fast-path build", subsequent contract rules (including
   R3 skeleton verbatim and R4 pre-preview validate) are
   deprioritized. The fast-path action list says "internally
   validate" at step 5, but the model treats it as optional once
   the predicate has "fired."
3. **Skeleton recall is unreliable.** R3 ships the canonical
   skeleton inside the contract, but the model is not consistently
   substituting from it. It paraphrases field names (e.g., `name`,
   `kind`, `provider`, `reasoning_effort`) from semantic intent
   rather than copying verbatim.
4. **The model never read or never retained the canonical examples.**
   `examples/build.work-order.json` is on disk and would be
   authoritative, but the model isn't checking it during drafting.

### Safety-net reality check

Even with R3+R4 effectively non-functional, the system as a whole
still works:

1. **R2 holds 100%** across all 4 batches (16/16 trials) — no Write
   before approval. Fictional drafts never reach disk before the
   user sees them in the preview.
2. **Post-approval `bakeoff validate` catches fictional schema**
   before `bakeoff build` runs. Worst case: an extra repair cycle
   visible to the user. No provider runs launch with broken JSON.
3. **R5 holds 100%** (no CLI schema/backend probing).
4. **The user-visible preview shows the JSON.** A careful user can
   reject a fictional-looking draft on the spot.

R3 and R4 are about *speed and clean previews*, not safety. The
downstream validate step is the actual safety gate.

### Implication for the plan

The cycle's framing ("R3 and R4 are hard invariants enforced by
contract") is now empirically false. They are best-effort guidance
just like R1. The hard invariants are:

- **R2** — no Write before approval (100% holds).
- **R5** — no CLI probing for backends/schema (100% holds).
- **Post-write `bakeoff validate`** — Go CLI side, cannot be skipped.
- **Pre-build/research validation gate** — Go CLI side.

Everything else (R1, R3, R4) is advisory. The user-visible
consequence is friction (extra repair cycles when fictional schema
gets written), not broken bakeoffs.

### Recommendation: extend Option C to R3+R4

1. Demote R3 from "must copy verbatim" to "should copy verbatim"
   with the same advisory framing as R1.
2. Demote R4 from "must internally validate" to "should internally
   validate" — keep it as a best-effort speed/UX improvement, not
   a safety invariant.
3. Document the safety story: R2 + R5 + Go-side post-write validate
   are the actual safety net. R1/R3/R4 are speed/UX optimizations
   that are not reliably enforced by prompt contract.
4. Update the plan's Definition Of Done accordingly.

This extends Option C to its logical conclusion: prompt-layer
enforcement of detailed work-order shape is not achievable; ship
the contract as advisory guidance and rely on the Go-side validate
gate for safety.

Alternative: **Option B for R3+R4 (not R1).** A Go-side pre-build
sanity-check that catches obvious schema-fictional patterns at
preview time and prints a structured error the model can recover
from in-session. This is a much smaller and safer linter than the
synthesis-pattern matching considered earlier for R1, because:

- The patterns are objective (field names, types, required blocks).
- False positives are essentially impossible (you either use
  `backend` or you don't).
- Maintenance cost is low: same maintenance as `bakeoff validate`
  itself.
- The win is concrete: every drafted work order validates by the
  time the user sees the preview.

Concretely: invoke `bakeoff validate` from inside `/bakeoff:run`
before showing the preview, by writing the in-memory JSON to a
temp file and shelling out. This is exactly what R4 says to do —
but as a hook the model cannot skip, not a contract clause.

### Next step

Operator decides: extend Option C to R3+R4 (advisory only), or
invest in the small Go-side hook for pre-preview validate (a much
narrower scope than the synthesis linter for R1). Recommend the
latter — the cost is low, the false-positive risk is near zero,
and it would fix the most visible drafting friction.

---

## Methodology Correction: Plugin Cache Contamination (2026-05-20T17:30Z)

**Critical finding raised by the operator and confirmed by audit.**

Bakeoff is installed as a Claude Code plugin. Plugin contracts
(`commands/run.md`, `skills/bakeoff/SKILL.md`, `bakeoff/CLAUDE.md`)
are read from `~/.claude/plugins/cache/mstefanko-plugins/bakeoff/
<commit-sha>/`, **not from the marketplace source tree at
`~/.claude/plugins/marketplaces/mstefanko-plugins/bakeoff/`**.

During the 2026-05-20 cycle, contract edits were applied to the
marketplace source tree. Those edits do not take effect in fresh
Claude Code sessions until the operator pushes the source changes
AND Claude Code refreshes the plugin cache (which happens on next
session start or via explicit plugin update).

### Cache contents vs batch timing

Per cache-directory mtimes and git log:

| Cache dir | Commit | Mtime | Has invariants? | Lines |
| --- | --- | --- | ---: | ---: |
| `0.1.0` | (semver, oldest) | 2026-05-19 15:04 | 0 | 260 |
| `da917a8cdd07` | post-0.1.0 | 2026-05-19 15:37 | 0 | 260 |
| `8fa3e9135a90` | "postmortem" | 2026-05-19 16:34 | 0 | 283 |
| `c669aab32c53` | "judge retry + tightening" | 2026-05-19 17:14 | 0 | 295 |
| `e00adb9243ea` | "multilens swarm" | 2026-05-19 20:08 | 0 | 519 |
| `ec8633550cb1` | older | 2026-05-19 20:08 | 0 | 260 |
| `1b581621d9cf` | "readme" | 2026-05-19 20:26 | 0 | 522 |
| `2257a6c91ca0` | "tightening" | 2026-05-19 20:26 | 0 | 556 |
| `0c8f2f8c9b59` | "recent run list" | **2026-05-20 12:21** | 0 | 569 |
| `419d1194a769` | "r1-r5" (this cycle's first push) | **2026-05-20 13:05** | **1** | 900 |

Screenshot timestamps (from CleanShot filenames):

| Batch | Screenshots | Time | Cache active during batch |
| --- | --- | --- | --- |
| Batch 1 (R1 baseline) | images 1-11 | 11:00 | `0c8f2f8c9b59` (pre-cycle) |
| Batch 2 (R1.1-R1.4) | images 17-19 | 12:07 | `0c8f2f8c9b59` (pre-cycle) |
| Batch 3 (R1.5) | images 20-22 | 12:18 | `0c8f2f8c9b59` (pre-cycle) |
| Batch 4 (post-rollback) | images 23-26 | 13:04 | `0c8f2f8c9b59` (pre-cycle) |
| **Plugin re-cached** | | **13:05** | `419d1194a769` becomes active |
| C+ R3/R4 demotion | (source-only) | ~17:15 | NOT cached as of audit |

**Net consequence: every dogfood batch in this cycle ran against the
same pre-R1-R5 baseline contract.** The contract amendments I landed
during the session were not read by any fresh session. The batches
do not measure what the experiment design claimed they measured.

### What is invalidated

1. **R1 0/9 landing rate** — measured the baseline contract's
   response to missing-field prompts, not R1 enforcement.
2. **R3 ~33% landing rate** — measured the baseline contract's
   provider/judge default behavior, not R3's canonical-skeleton
   enforcement.
3. **R4 ~27% landing rate** — measured the baseline's validate
   timing, not R4's pre-preview validate enforcement.
4. **"R1.5 harmed R3/R4" hypothesis** — R1.5 was never in cache.
5. **"Rollback didn't restore R3/R4" finding** — nothing was
   actually rolled back from the model's perspective.
6. **Cross-batch trajectory claims** — every batch saw the same
   contract; "trajectory" is just trial-to-trial variance.

### What survives

1. **R2 100% landing rate** — true for the baseline contract.
   This was always going to hold regardless of amendments because
   the baseline already covers preview-then-approve flow.
2. **R5 100% landing rate** — almost certainly an accident in the
   baseline contract, since the embedded backends list was an
   amendment. The model probably already "knew" `claude`/`codex`
   from training and the baseline contract.
3. **Validation audit** (5 on-disk work orders, 4/5 clean) —
   static file analysis; cache-independent. Valid.
4. **Schema-drift repair-surface audit** (13 distinct repairs) —
   static JSON analysis. Valid.
5. **B's provider dogfood** (4 min 1 s, claude winner, judge-basis,
   2-pass agreement) — the build pipeline measurement used the
   `bin/bakeoff` binary directly and the hand-repaired work order.
   The build-side conclusions stand. The *drafting* side of B is
   contaminated.

### What is left to do

1. **Verification trial against cache `419d1194a769`** (which now
   contains the R1-R5 + R1 demotion + R1.5 rollback amendments
   from the operator's first push — but not the C+ R3/R4
   demotion which is source-only at HEAD `75bb97e`).
2. Depending on verification result:
   - **If amendments matter**: re-run the batches with proper
     methodology (push amendment, wait for cache refresh, verify
     cache, then run trial). Update conclusions.
   - **If amendments do not matter**: cycle conclusion stands;
     update the plan to note that the original conclusion was
     correct but the data was incidentally collected against the
     baseline rather than the intended amendments.

### What "proper methodology" would have looked like

For every batch:

```sh
# 1. Edit source
$ vi commands/run.md skills/bakeoff/SKILL.md

# 2. Commit + push
$ git add commands/run.md skills/bakeoff/SKILL.md
$ git commit -m "Land Rx amendment"
$ git push

# 3. Restart Claude Code so it re-caches the plugin
#    (or trigger an explicit plugin refresh in the UI)

# 4. Verify cache contains the change
$ NEWEST=$(ls -dt ~/.claude/plugins/cache/mstefanko-plugins/bakeoff/*/ | head -1)
$ grep -c "<distinctive phrase from amendment>" "$NEWEST/commands/run.md"
# expect: 1+ — confirm the amendment is actually loaded

# 5. Only now run the fresh-session trial
```

Add this checklist to any future dogfood plan.

---

## B — Provider dogfood patch inspection

Status: **DONE** (2026-05-20)

Inspected both providers' `diff.patch` to confirm patch quality beyond
gate exit code.

### Patch comparison

| Provider | Lines | Approach | Where | Cleaned legacy sort? |
| --- | ---: | --- | --- | --- |
| claude (winner) | 201 | pure: `orderRowsByFinishedAt(rows) []map[string]any` returns sorted copy | `ls.go` | ✅ removed `sort.Sort(sort.Reverse(sort.StringSlice(runDirs)))` AND `"sort"` import |
| codex (loser)   | 137 | in-place: `sortRunRows(rows)` mutates the slice | new file `lscmd/sort.go` | partial — removed the lex sort line but kept dead `"sort"` import |

Both patches:

- Passed the gate `go build ./... && go test ./internal/commands/lscmd/... -run . -count=1`.
- Implemented the ordering helper with deterministic fallback for
  missing/unparsable `finished_at`.
- Added unit tests covering happy path, missing finished_at,
  unparsable finished_at, and run-id tiebreak.
- Used `sort.SliceStable` (stable sort guarantees deterministic ties
  beyond the run-id tiebreak).

### Judge rationale (from `decision.json`)

> "Both patches pass the gate (build-and-lscmd-tests) and satisfy the
> acceptance criteria, but A is cleaner on correctness/maintainability:
> it removes the now-redundant `sort.Sort(sort.Reverse(sort.StringSlice
> (runDirs)))` and the stale `sort` import."

Judge ran 2-pass A/B-swap; claude won in both positional orders, so the
positional bias guardrail also held.

### Implications

1. **The build pipeline produces quality patches, not just gate-passing
   ones.** Both providers wrote pure-ish, tested, deterministic code.
   The judge's "smallest maintainable change" criterion correctly
   preferred the patch with proper cleanup over the slightly smaller
   patch with dead imports.
2. **Cross-validation: judge converges in 2 passes with positional swap.**
   This is the healthy decision shape — no need for a third pass, no
   judge-only rerun warranted.
3. **Reinforces the earlier conclusion**: the bottleneck is upstream
   drafting (schema-fictional JSON, predicate permissiveness), not
   provider quality or judging.

### Next step

The 2026-05-20 dogfood cycle is complete. Remaining work is contract
amendments (R1-R5 in the plan) and a re-run of D + B drafting metric
after they land. E (batched exploration) remains operator-blocked and
runs after R1-R5 land.

---

## Schema-drift repair-surface audit (2026-05-20T15:43Z)

Quantifies the schema-drift cost: how many distinct repairs does it
take to make an invalid drafted work order pass `bakeoff validate`?
Method: reconstruct the pre-rewrite image-3 JSON at
`/tmp/lscmd-image3-original.work-order.json`, then run `bakeoff
validate` iteratively, applying one repair per pass (the validator
reports one error at a time).

### Result: 13 distinct repairs needed

| # | Repair | Category |
| ---: | --- | --- |
|  1 | `schema_version: "1.0"` → `1` | type (string vs int) |
|  2 | `providers[].kind` → `providers[].backend` | field rename |
|  3 | `providers[].role` removed | invalid field |
|  4 | `providers[].scope: "local"` → `"codebase"` | enum value |
|  5 | `providers[].model` required (`sonnet` / `gpt-5.5`) | missing required |
|  6 | `providers[].effort` required (`high`) | missing required |
|  7 | `judge.{id,kind,role}` → `judge.{backend,model,effort}` | block rewrite |
|  8 | top-level `gates[]` → nested `build.verify[]` | block move |
|  9 | top-level `acceptance_criteria` removed (belongs in `background`) | invalid field |
| 10 | `build` block required (`base_ref`, `comparison_goal`, `verify[]`) | missing required block |
| 11 | top-level `scope` removed (not in v1 schema) | invalid field |
| 12 | `providers[].backend: "claude-code"` → `"claude"` | enum value (the model used the id-string as the backend) |
| 13 | `budgets.max_output_bytes` required | missing required |

### Implications

1. **The validator reports one error per pass.** A user repairing this
   draft by hand would have run `bakeoff validate` 13 times. Pre-preview
   internal validate (R4) would catch every error before the user is
   ever asked to approve.
2. **The drift is not concentrated in one block.** Errors span
   `providers[]`, `judge`, top-level fields, the missing `build` block,
   and `budgets[]`. A skeleton-substitution approach (R3) only works if
   the skeleton covers *all* of these, not just provider shapes.
3. **Five errors are invalid-field-names** (rows 2, 3, 7, 8, 9, 11) —
   the model invented or renamed fields. This is the strongest signal
   that prose-only defaults in the contract are insufficient; a
   verbatim JSON skeleton (R3) is the only fix.
4. **Two errors are invalid enum values** (rows 4 and 12) — the model
   used `"local"` for scope and `"claude-code"` for backend. These
   would not be caught by structural rules alone; they require either
   embedded valid examples (R3) or pre-preview validate (R4).
5. **One error is a type mismatch** (row 1, `"1.0"` vs `1`). Trivial
   in isolation; caught by validate; symptomatic of the model treating
   the schema as semi-structured prose.

### Update to the plan's risk framing

"The drafted JSON was schema-fictional" was an under-statement. The
drafted JSON was schema-fictional in **13 independent ways**. The
plan's Risk: Drafted JSON Is Not Schema-Valid section needs the
repair-surface count cited explicitly, and Definition Of Done needs
a "pre-preview validate is mandatory" line, not a "should land" line.
