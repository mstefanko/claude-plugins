# Fanout Foundations Fix Plan

Status: review-updated; pre-condition for any future fanout run
Date: 2026-05-04
Run-of-record: `01KQSDTRN4HFRRXAVARE8X0QNZ` (ECC pattern adoption attempt)
Companion plans:
- `swarm-do/docs/phase-session-dispatcher-fanout-plan-2026-05-03.md` (research → wiring; partially landed)
- `swarm-do/docs/ecc-pattern-adoption-plan.md` (the user-facing plan blocked by these foundations)

> **Session continuity.** Pick up cold. Every claim has a file path or run-artifact pointer. A fresh agent should be able to verify and execute without re-running the failing dispatch.

---

## 1. Problem Statement

`/swarmdaddy:do --prepared <run-id>` (default `--phase-sessions=fanout`) cannot complete an end-to-end run.

Live evidence from run `01KQSDTRN4HFRRXAVARE8X0QNZ` (ECC plan, 6 phases × 28 work units, $37+ on dispatcher alone before completing 4 of 6 phases):

| Phase | Status reported | Actual on integration branch | Per-unit ledger | Failure |
| ---: | --- | --- | --- | --- |
| 0 | complete | 0 commits | all stages `failed`, `adopted_at: None` | (no-op intended) |
| 1 | complete | 0 commits (2 commits orphaned on unit-1-4, unit-1-5) | all stages `failed`, `adopted_at: None` | adoption miss |
| 2 | complete | 0 commits (3 dirty unit worktrees, never committed by writer) | all stages `failed`, `adopted_at: None` | writer-commit miss + adoption miss |
| 3 | complete | 0 commits (4 commits orphaned on unit-3-{1..4}) | all stages `failed`, `adopted_at: None` | adoption miss |
| 4 | retry_waiting | (interrupted) | n/a | API 429 mid-flight ($5.55 burned) |
| 5 | pending | — | — | — |

Integration branch HEAD: `c6075ef` — identical to `main`. **Zero phase work merged despite four phases reporting `complete`.**

Cost-time signature of the run: dispatcher Phase 3 alone ran 131 tool turns, 1.24M cache reads, $12.14 in provider-reported parent-session telemetry. Per-writer token/cost usage is not directly observable from Claude/Codex and must be treated as nullable/unknown when absent. Writer sub-agents had no deterministic caps; rate limits were hit twice over the course of the run.

---

## 2. Foundation Already Shipped

| Component | Evidence | Status |
| --- | --- | --- |
| Per-unit writer auto-expand (Decision 13 builder helper) | `swarm-do/py/swarm_do/pipeline/stage_invocation.py:329 _auto_expand_writer_per_unit`; commit `c6075ef`; 17/17 fanout tests pass | ✅ shipped |
| Unit worktree materialization | `swarm-do/py/swarm_do/pipeline/execution_worktree.py:materialize_unit_execution_worktree`; called from `phase_pump.py:_prepare_stage_controller` | ✅ shipped |
| StageMarkerProcessor | `swarm-do/py/swarm_do/pipeline/stage_controller.py` (8 outcomes, owner-thread enforcement) | ✅ shipped |
| ClaudeStreamParser | `swarm-do/py/swarm_do/pipeline/claude_stream.py` | ✅ shipped |
| Streaming runner | `phase_pump.py:937` (`output_format = "stream-json"`) | ✅ shipped |
| Per-phase fresh `claude-print` session | `bin/swarm do --prepared --phase-sessions=fanout` (default) | ✅ shipped |
| Handoff payload narrowness (verified) | `phase_handoffs/0/attempt-3.handoff.json` is 2.4KB; schema is summary + decisions + next_phase_context lists | ✅ shipped |

The fanout writer expansion + stream parsing + per-phase isolation + handoff narrowness all work. **What does not work is everything from "writer emits marker" onwards** — result identity, adoption, commit, merge projection, ledger consistency, deterministic caps, prompt economy.

---

## 3. Verified Findings (with evidence pointers)

Every finding here is backed by a file/byte-count/grep on `~/.local/share/swarmdaddy/runs/01KQSDTRN4HFRRXAVARE8X0QNZ/`. Re-run the indicated check to verify on a fresh session.

### Finding F1 — Writer budget placeholders never substituted; deterministic caps not enforced (CRITICAL)

**Bead:** `mstefanko-plugins-kgsw` (P1)

**Symptom:** writers run without concrete prompt caps; rate limits hit; Phase 3 dispatcher ran 131 tool turns / $12.14 in provider-reported parent-session telemetry.

**Evidence:**
```bash
grep -c '${MAX_TOOL_CALLS}\|${MAX_OUTPUT_BYTES}\|${WORK_UNIT_ID}' \
  ~/.local/share/swarmdaddy/runs/01KQSDTRN4HFRRXAVARE8X0QNZ/phase_launches/4/attempt-1/dispatcher.launcher.prompt.md
# → 6
```
The prompt contains literal `${MAX_TOOL_CALLS}` / `${MAX_OUTPUT_BYTES}` / `${WORK_UNIT_ID}` strings that should have been substituted with numeric values from `swarm-do/py/swarm_do/pipeline/budget.py:11-13` (`DEFAULT_MAX_WRITER_TOOL_CALLS = 60`, `DEFAULT_MAX_WRITER_OUTPUT_BYTES = 60_000`).

```bash
grep -rln "MAX_TOOL_CALLS\|MAX_OUTPUT_BYTES" swarm-do/py/
# → no matches
```
No substitution code exists anywhere in the Python tree. The defaults are defined but unused at prompt-render time.

**Fix location:** the per-stage prompt-build site in `swarm-do/py/swarm_do/pipeline/stage_invocation.py` (where the writer's `Agent(...)` prompt is rendered). Pull defaults from `budget.py` (or active preset's `[budget]` section) and `string.replace`/format-substitute the four placeholders before serializing into the dispatcher prompt.

**Budget semantics correction:** placeholder substitution is prompt hygiene and operator signaling, not reliable token/cost enforcement. Claude/Codex do not expose authoritative per-writer token or cost usage to this controller. Treat provider-reported cost/token fields as nullable telemetry only. Enforce only deterministic local controls: dispatcher prompt bytes, phase wall-clock timeout, parent `Agent` call count when available from stream frames, result/output byte caps, merge/adoption state, and structured tool-use event counts when the stream exposes them. Never use writer self-reported `tool_calls` as authoritative; record it as advisory at most.

### Finding F2 — Per-unit merge to integration branch never fires (CRITICAL)

**Bead:** `mstefanko-plugins-y9i1` (P1)

**Symptom:** integration branch has zero phase commits despite 4 phases reporting `complete`.

**Evidence:**
```bash
git -C ~/.local/share/swarmdaddy/worktrees/01KQSDTRN4HFRRXAVARE8X0QNZ/repo log --oneline -1
# → c6075ef wiring (== main HEAD)

git -C ~/.local/share/swarmdaddy/worktrees/01KQSDTRN4HFRRXAVARE8X0QNZ/units/3/unit-3-1/repo log --oneline 45f6a25..HEAD | head -3
# → 6e412b0 security_audit: implement static scanner   (orphaned on unit branch)
```

`merge_unit_execution_worktree()` exists in `swarm-do/py/swarm_do/pipeline/execution_worktree.py` and is reached through `StageMarkerProcessor -> adopt_unit_stage() -> merge_unit_execution_worktree()` before a unit-backed stage is marked adopted. Existing focused tests cover unit commit+merge and journal resume. The live run still produced zero integration merges because adoption failed before the existing adopter path could run (see F3, F4, F5), and the phase result did not project merge state.

**Fix decision (cross-cuts `ykfw`):** keep the existing unit-session adopter as the only merge path. Do not add a second merge call in phase finalization. Gate adoption/merge on writer-success for v1 (per-unit review can layer in later via `ykfw`), ensure live `phase_pump` reaches the existing adopter after valid markers/results, and project merge outcome into the phase result.

### Finding F3 — Stage marker grammar pollution (HIGH)

**Bead:** `mstefanko-plugins-36ir` (P1)

**Symptom:** dispatcher reads `swarm-do/README.md` (which documents the marker grammar), echoing literal `STAGE_COMPLETE` text into the assistant transcript stream. Adoption is non-deterministic.

**Evidence:**
```bash
grep -o 'STAGE_COMPLETE[^"]*' \
  ~/.local/share/swarmdaddy/runs/01KQSDTRN4HFRRXAVARE8X0QNZ/phase_launches/2/attempt-1/stdout.stream.jsonl | head -3
# Many matches show README content like:
#   STAGE_COMPLETE`/`STAGE_FAILED` markers plus\n153\tstructured stage-result JSON, and retries...
```
This is the README (lines ~150-180 documenting marker grammar) being re-emitted by the model as context. The parser cannot distinguish a real marker from a documentation echo.

**Fix scope:** parser must keep the CB-1 binary marker protocol: only `STAGE_COMPLETE {<json>}` and `STAGE_FAILED {<json>}` are accepted. Require markers at start of line, alone on the line, with no `line.strip()` forgiveness for leading prose/whitespace, valid JSON after the marker token, and end-of-line after the JSON. Documentation echoes embedded in prose should never match. Add a parser test that feeds the README text and asserts zero adoptions.

### Finding F4 — Stage result JSON missing controller-required identity fields (HIGH)

**Bead:** `mstefanko-plugins-53ti` (P2)

**Symptom:** writer stage result files lack the controller identity fields required for adoption. The prior review found adoption failed before commit/merge because result JSONs were missing `run_id`, `phase_id`, and `phase_attempt`; they also lacked `work_unit_id` for per-unit attribution.

**Evidence:**
```bash
cat ~/.local/share/swarmdaddy/runs/01KQSDTRN4HFRRXAVARE8X0QNZ/phases/3/stage_results/writer-fanout-1.result.json
# -> {"stage_id": "writer:fanout-1", "status": "complete", "summary": ..., "notes": ...}
# (no run_id, phase_id, phase_attempt, work_unit_id)
```
`StageMarkerProcessor._validate_stage_result()` requires `run_id`, `phase_id`, `phase_attempt`, `stage_id`, and `status`. Writer prompts currently receive `work_unit_id` in the stage contract JSON, but the fanout stage contract must also include `run_id`, `phase_id`, and `phase_attempt`, and the writer must emit all identity fields back in the result.

**Fix location:** fanout stage contract rendering in `swarm-do/py/swarm_do/pipeline/stage_invocation.py`, writer role instructions in `swarm-do/agents/agent-writer.md`, and controller validation in `swarm-do/py/swarm_do/pipeline/stage_controller.py`. Make `run_id`, `phase_id`, `phase_attempt`, `stage_id`, `status`, and `work_unit_id` required for writer results. Validate each value against controller-owned `StageInvocation` / `stage_sessions` data before adoption.

### Finding F5 — Stage adoption ledger inconsistent with phase result file (HIGH)

**Bead:** `mstefanko-plugins-x27i` (P2)

**Symptom:** ledger and result disagree about what happened.

**Evidence:**

`phases/3/stage_sessions.v1.json`:
- All stages (research, analysis, clarify, writer:fanout-{1..4}, provider-review, spec-review, review, docs) have `status: failed, adopted_at: None`.

`phase_results/3/attempt-1.result.json`:
- `status: complete, completed_work_units: ['unit-3-1', 'unit-3-2', 'unit-3-3', 'unit-3-4']`.

Phase 2 has the same ledger shape but its result reports `completed_work_units: []`. The result-population path is non-deterministic relative to the ledger.

**Fix:** make `stage_sessions.v1.json` plus adoption journals the single source of truth for phase-result status, completed/failed/blocked units, merge status, commit SHA, and summary. If the controller terminal state is failed/partial/blocked, the phase result must not remain `status: complete` just because the dispatcher wrote a complete result file. The controller must either overwrite the dispatcher-written result with a ledger-derived projection or reject the phase result and fail loudly with both ledger and result values logged. This finding is downstream of F3/F4 (fix marker pollution and result identity -> ledger correctly populated -> result derived from ledger).

### Finding F6 — Dispatcher prompt duplicates writer role brief N× (MEDIUM)

**Bead:** no stable standalone bead found yet. The role-brief bug text appears in BEADS output, but the visible open issue title did not match this scope. Create or split a dedicated bead before Phase 3 execution.

**Symptom:** prompt size grows linearly with fanout count.

**Evidence:** Phase 4 prompt is 110,259 bytes; the `## Work Units To Dispatch` section is 94,967 bytes (86%). `grep -c 'name: agent-writer'` returns **6** — one per fanout. The role brief (~8KB) is inlined per branch when it should be loaded once by each sub-agent.

**Fix location:** `swarm-do/py/swarm_do/pipeline/stage_invocation.py:_render_fanout_orchestrator_brief` should emit the per-unit *contract* (`run_id`, `phase_id`, `phase_attempt`, `stage_id`, `work_unit_id`, `allowed_files`, `acceptance_criteria`, expected result path, worktree path, bead id, and caps) and rely on `Agent(subagent_type="swarmdaddy:agent-writer")` to load the role brief once per sub-agent invocation.

### Existing related beads (not duplicates; track separable scope)

- `mstefanko-plugins-ykfw` (P2) — Reviewer-per-unit fan-out (Decision 13 second half). Necessary for review parity but **not** required before the v1 writer-success merge gate.
- `mstefanko-plugins-sn6b` (P2) — Make fanout adoption crash-safe between marker and merge. Becomes meaningful only after F2 + F3 + F5.
- `mstefanko-plugins-f685` (P2) — Unit-level partial-phase redispatch. Useful operator surface; not a foundation blocker.
- `mstefanko-plugins-s4pv` (P2) — Phase 7 fanout regression coverage. Defensive; not a foundation blocker.
- `mstefanko-plugins-0uqy` (P2) — Decide dispatcher posture migration and auto-mode deprecation.
- `mstefanko-plugins-ucqz` (P2) — Decide CB-1 status protocol grammar for dispatcher fanout.

---

## 4. Beads Issue Index (all open, P1 first)

| ID | Pri | Title | Type | This plan |
| --- | --- | --- | --- | --- |
| `kgsw` | P1 | Writer budget placeholders never substituted in dispatcher prompt — writers wander unbounded | bug | **Phase 1** |
| `y9i1` | P1 | Per-unit merge to integration branch never fires | bug | **Phase 2** |
| `36ir` | P1 | Stage marker grammar pollution: dispatcher Read of docs echoes STAGE_COMPLETE into stream | bug | **Phase 1** |
| `53ti` | P2 | Stage result JSON missing work_unit_id field — per-unit attribution broken | bug | **Phase 2** |
| `x27i` | P2 | Stage adoption ledger inconsistent with phase result file: ledger `failed`, result claims complete | bug | **Phase 2** |
| TBD | P2 | Dispatcher prompt duplicates writer role brief N× per fanout | bug | **Phase 3** |
| `ykfw` | P2 | Reviewer-per-unit fan-out (Decision 13 second half) | feature | **Phase 4** |
| `sn6b` | P2 | Fanout adoption crash-safe between marker and merge | feature | **Phase 4** |
| `f685` | P2 | Unit-level partial-phase redispatch for fanout runs | feature | optional |
| `s4pv` | P2 | Fill remaining Phase 7 fanout regression coverage | task | optional |

To re-fetch IDs and confirm whether F6 has been split into a standalone bead:
```bash
bd list --status=open --json | jq '.[] | select(.title | test("work_unit_id|ledger inconsistent|role brief|prompt duplicates")) | {id, title}'
```

---

## 5. Phased Implementation Plan

Sequential phases. Each phase has a single clear objective; do not start phase N+1 before phase N's acceptance gate is green.

### Phase 1 — Stop the Bleeding (P1 fixes that prevent rate-limit blowout and false adoption)

**Beads:** `kgsw`, `36ir`

**Objective:** make a fanout dispatch stay within deterministic local caps and adopt only real binary markers.

**Work units:**

1.1 **`kgsw`: substitute writer budget placeholders.**
- File: `swarm-do/py/swarm_do/pipeline/stage_invocation.py`
- Find the per-unit writer prompt-build site (the function that produces the `Agent(...)` prompt JSON for a writer stage).
- Pull defaults from `swarm-do/py/swarm_do/pipeline/budget.py` (`DEFAULT_MAX_WRITER_TOOL_CALLS`, `DEFAULT_MAX_WRITER_OUTPUT_BYTES`, `DEFAULT_MAX_HANDOFFS`). Resolve from active preset's `[budget]` section if set; fall back to defaults.
- Substitute `${MAX_TOOL_CALLS}`, `${MAX_OUTPUT_BYTES}`, `${MAX_HANDOFFS}`, `${WORK_UNIT_ID}` (the four declared in `swarm-do/agents/agent-writer.md:101-106`). Use stable substitution that won't accidentally match other tokens.
- Add deterministic enforcement/telemetry surfaces where the controller can actually observe them:
  - cap rendered dispatcher prompt bytes and fail before launch if exceeded;
  - cap phase wall-clock with the existing launcher timeout;
  - count parent `Agent` tool_use frames when the stream exposes them;
  - cap result JSON bytes and preserved stream bytes;
  - record provider-reported cost/token usage as nullable `provider_reported` telemetry only.
- Do not treat writer-reported `tool_calls`, token counts, or cost as authoritative. If captured, store them as advisory self-report with a warning when no structured stream count exists.
- **Test (allowed_files: `swarm-do/py/swarm_do/pipeline/tests/test_stage_invocation.py` plus telemetry tests if needed):** add a test that builds a writer invocation, renders the prompt, asserts no `${...}` placeholders remain and the numeric values match `budget.py` defaults. Add a telemetry test that missing provider usage remains `null`/`unknown`, not zero or synthesized dollars.
- **Acceptance:** `grep '${MAX_TOOL_CALLS}\|${MAX_OUTPUT_BYTES}\|${WORK_UNIT_ID}\|${MAX_HANDOFFS}' <prompt>` returns 0 in any future run, deterministic caps are recorded in launch metadata, and absent cost/token usage stays unknown.

1.2 **`36ir`: tighten marker parser to reject documentation echoes.**
- File: `swarm-do/py/swarm_do/pipeline/orchestrator_stream.py` (where `parse_stage_marker_line` lives).
- Require the v1 binary protocol only: line starts with `STAGE_COMPLETE ` / `STAGE_FAILED ` (no leading whitespace, no preceding text), followed by valid JSON, followed by end-of-line. Reject any candidate that has surrounding text, backticks, or leading whitespace. Keep `complete_with_concerns`, `blocked`, `failed`, and `needs_input` in the stage result JSON status field, not in marker tokens.
- **Test (allowed_files: `swarm-do/py/swarm_do/pipeline/tests/test_dispatcher_fanout.py` or new `test_marker_parser.py`):** feed the parser the README text from `swarm-do/README.md:150-180` (which documents the grammar), assert zero matches. Feed it a clean stream containing real `STAGE_COMPLETE {...}` lines, assert the expected matches.
- **Acceptance:** real markers parse; documentation prose containing the marker words does not.

**Phase 1 acceptance gate (run before starting Phase 2):**
- A smoke fanout run on a small two-unit fixture (not the full ECC plan) terminates within local caps: prompt bytes, wall-clock timeout, result/output bytes, and parent `Agent` call count when observable.
- Adoption ledger entries match the actual emitted binary markers (no false-positive adoptions from prose, no false-negatives from prose).
- Cost/token telemetry is either provider-reported with confidence metadata or `null`/`unknown`; no local heuristic or writer self-report is presented as actual spend.

### Phase 2 — Restore Per-Unit Truth (ledger + result + merge)

**Beads:** `y9i1`, `53ti` (stage-result identity), `x27i` (ledger/result consistency)

**Objective:** every unit's outcome is recorded in the ledger; the merge step fires; integration branch reflects merged work.

**Work units:**

2.1 **`53ti` / writer-result identity contract.**
- Update fanout stage contract rendering in `swarm-do/py/swarm_do/pipeline/stage_invocation.py` so every `Stage contract JSON` includes controller-issued `run_id`, `phase_id`, `phase_attempt`, `stage_id`, `result_path`, and, for unit-backed writer stages, `work_unit_id`.
- Update writer role brief in `swarm-do/agents/agent-writer.md` to require the same identity fields in the result JSON it writes. The writer may report summary/status, but it may not invent or omit controller identity.
- Update/confirm controller validation in `swarm-do/py/swarm_do/pipeline/stage_controller.py`: missing or mismatched `run_id`, `phase_id`, `phase_attempt`, `stage_id`, `result_path`, `work_unit_id`, `worktree_path`, `bead_id`, or `allowed_files` rejects before `adopt_unit_stage`, commit, merge, BEADS close, or phase-result projection.
- **Test:** feed the controller writer results missing each required identity field (`run_id`, `phase_id`, `phase_attempt`, `stage_id`, `status`, `work_unit_id`) and assert rejection before adoption. Feed a valid writer result and assert adoption proceeds to the existing unit-session adopter.
- **Acceptance:** every writer result file in a fanout phase contains non-null `run_id`, `phase_id`, `phase_attempt`, `stage_id`, `status`, and `work_unit_id` matching the dispatched values.

2.2 **`x27i` / ledger-derived phase result.**
- Audit `swarm-do/py/swarm_do/pipeline/phase_pump.py` result finalization and the streaming path that writes or preserves `phase_results/<phase>/attempt-N.result.json`.
- Replace any non-ledger source with a projection from `stage_sessions.v1.json` plus adoption journals. The projection must cover:
  - `status` / terminal state (`complete`, `partial_success`, `failed`, `blocked`, `needs_input`);
  - `completed_work_units`, `failed_work_units`, `blocked` / `needs_input`;
  - `merge_status` per unit;
  - `commit_sha`, changed files/worktree diff when available;
  - phase summary and blockers.
- If the dispatcher already wrote a `status: complete` result but the controller ledger is failed, partial, blocked, or empty, overwrite with the ledger projection or reject the phase result before advancing. Do not leave a stale dispatcher-authored complete result in place.
- Add an integrity assertion: at finalize, result fields equal the ledger projection. Fail loudly on mismatch with both values logged.
- **Test:** synthesize a ledger with 3 adopted writers + 1 failed; finalize; assert result status is `partial_success` and has exactly the 3 adopted unit ids plus the failed unit. Synthesize an all-failed ledger with an existing dispatcher `status: complete` result; assert final result is not complete.
- **Acceptance:** phase result status and unit lists always agree with the ledger/adoption journals.

2.3 **`y9i1` / prove and project the existing per-unit merge path.**
- Do **not** add a second `merge_unit_execution_worktree()` call in phase finalization. The intended path is already `StageMarkerProcessor -> adopt_unit_stage() -> merge_unit_execution_worktree() -> record_stage_adopted`.
- Fix the upstream blockers (F3/F4) so the live streaming `phase_pump` path reaches `adopt_unit_stage()` for valid writer markers/results.
- Ensure adoption records an explicit merge outcome per unit (`merged`, `failed`, `skipped`) in run events, stage controller summary, and the ledger-derived phase result.
- Decide failure handling: a single unit's merge conflict marks the unit failed/blocked and stops further merges in that phase; the operator must reset/retry.
- **Test:** integration test the live streaming/phase-pump path with a 2-unit fanout phase and fake writers producing two non-conflicting commits; after controller adoption, integration branch contains both commits and `result.merge_status` is populated from adoption state. Add an idempotence test that a resumed adoption journal does not duplicate merge commits/events.
- **Acceptance:** after a fanout phase completes, `git -C <safe_git_worktree_root> log` shows merge commits for each adopted unit, and the result's `merge_status` matches unit-session merge state.

**Phase 2 acceptance gate:**
- A two-phase smoke fixture runs end-to-end through the live `phase_pump` / `StageMarkerProcessor` path. Phase 1 finalizes with both units adopted and merged into integration. Phase 2 picks up that integration as base, merges its own units. Final integration branch HEAD is `git log --oneline base..HEAD` showing both phases' commits.
- A negative smoke fixture with invalid/missing result identity fields rejects before adoption and produces a non-complete phase result.
- A ledger/result mismatch fixture proves stale dispatcher-authored `status: complete` output cannot advance a failed controller ledger.

### Phase 3 — Prompt Economy (reduce per-launch token tax)

**Beads:** F6 (P2 role brief duplication; create/split a stable bead before execution)

**Objective:** dispatcher prompt size is roughly constant in fanout count instead of linear.

**Work units:**

3.1 **F6 / stop inlining writer role brief per fanout.**
- File: `swarm-do/py/swarm_do/pipeline/stage_invocation.py:_render_fanout_orchestrator_brief`.
- Per-unit section emits the minimal controller contract: `run_id`, `phase_id`, `phase_attempt`, `stage_id`, `work_unit_id`, `allowed_files`, `acceptance_criteria`, `expected_result_path`, `worktree_path`, `bead_id`, and budget caps. NOT the role brief.
- Sub-agent resolves the role brief via `Agent(subagent_type="swarmdaddy:agent-writer")` — this already works (Claude Code's native registry).
- **Test:** add a property test that a phase with N writer fanouts produces a prompt where the substring `# agent-writer` appears at most once (or zero times).
- **Acceptance:** Phase-4-shaped fixture (6 fanouts) produces a dispatcher prompt under 30KB instead of 110KB.

**Phase 3 acceptance gate:**
- Run the smoke fixture from Phase 2; compare the dispatcher prompt sizes pre/post — sublinear in fanout count.

### Phase 4 — Per-Unit Review + Crash-Safe Adoption (foundation feature parity)

**Beads:** `ykfw`, `sn6b`

**Objective:** spec-review/review/docs run per-unit; adoption survives crashes between marker and merge.

These are larger pieces and may need their own plan documents; treat this phase as a placeholder pointing at the existing beads. Do not block Phase 1-3 on them. Once 1-3 are green, the pipeline can complete a working run; Phase 4 brings it to design parity.

**Phase 4 acceptance gate:** existing `ykfw` and `sn6b` close cleanly with their own tests.

---

## 6. Decisions Pinned

D1 — **Merge path.** Phase 2 work unit 2.3 uses the existing unit-session adopter path only: `StageMarkerProcessor -> adopt_unit_stage() -> merge_unit_execution_worktree() -> record_stage_adopted`. It gates v1 merge on writer-success only (no per-unit spec-review verdict). Per-unit spec-review (`ykfw`) layers on later before or around the same adopter path. Rationale: unblocks a working pipeline now without creating a second merge path.

D2 — **Ledger as single source of truth.** Phase 2 work unit 2.2: phase-result `status`, unit lists, merge status, commit SHA, blockers, and summary are projections of `stage_sessions.v1.json` plus adoption journals. No alternate code path may author those fields. Rationale: F5 root cause is divergent truth stores; eliminate by construction.

D3 — **Marker grammar discipline.** Phase 1 work unit 1.2: marker lines must be alone on the line and remain binary: `STAGE_COMPLETE {<json>}` or `STAGE_FAILED {<json>}` with a trailing newline; no surrounding prose and no leading whitespace. Rich status (`complete_with_concerns`, `blocked`, `needs_input`, `failed`) lives in result JSON. Rationale: F3 evidence shows prose echoes are common, and CB-1 deliberately avoids a second status source.

D4 — **Budget defaults pulled from preset; fall back to constants.** Phase 1 work unit 1.1: preset's `[budget]` section wins; fall back to `swarm-do/py/swarm_do/pipeline/budget.py` defaults. Rationale: presets like `composer-fanout-dogfood` already have `max_writer_tool_calls = 60`; honor them in prompts and deterministic caps.

D5 — **Cost/token usage is nullable telemetry.** Claude/Codex do not provide controller-visible per-writer actual cost/token usage. Provider-reported parent-session cost/token fields may be recorded with confidence metadata when present; absent values remain `null`/`unknown`. Do not synthesize dollars from prompt bytes, wall time, turns, or writer self-report.

D6 — **Stage result identity is mandatory.** Writer result JSON must include `run_id`, `phase_id`, `phase_attempt`, `stage_id`, `status`, and `work_unit_id` for unit-backed writer stages. Missing or mismatched identity rejects before adoption/commit/merge.

D7 — **Do not rescue run `01KQSDTRN4HFRRXAVARE8X0QNZ`.** The orphaned commits and dirty worktrees are forensic evidence. Hand-merging unreviewed work is high risk and doesn't fix the underlying defects. Re-run the ECC plan only after Phase 1 + Phase 2 acceptance gates are green. Use `bin/swarm worktrees reset <run-id> --archive-branch --force` (preserves everything as `archive/...` branches) when starting fresh.

---

## 7. Pre-Acceptance Pause for ECC Run

Before re-launching `bin/swarm do --prepared <run-id>` against the ECC plan or any other plan, all of the following must be true:

- `kgsw` closed; placeholder substitution test green.
- `36ir` closed; marker parser test green against the README echo fixture.
- `53ti` closed; valid writer results include `run_id`, `phase_id`, `phase_attempt`, `stage_id`, `status`, and `work_unit_id`; invalid identity rejects before adoption.
- `x27i` closed; phase result `status`, unit lists, and merge status are ledger/adoption-journal projections.
- `y9i1` closed; smoke fixture reaches the existing adopter path and shows merge commits on integration with no duplicate merge on resume.
- Smoke fanout fixture (2 phases x 2 units) runs end-to-end with no operator intervention. Provider cost, if present, is under $5; if absent, it is reported as unknown, not zero. Wall clock under 30 min.

If those gates pass, re-prepare the ECC plan (`/swarmdaddy:prepare swarm-do/docs/ecc-pattern-adoption-plan.md`) — the existing prepared artifact `01KQSDTRN4HFRRXAVARE8X0QNZ` may be stale on git base by then; fresh prepare is cheap.

Test environment note: the prior review validated the focused fanout tests with global Git hooks disabled (`GIT_CONFIG_GLOBAL=/dev/null uv run pytest ...`, 43 passed). The first run failed because a global pre-commit hook expected `.overcommit.yml` inside temp repos. Treat that as an environmental fixture-hardening follow-up, not a product blocker; tests for this plan should isolate temp repos from global hooks.

---

## 8. Telemetry to Capture On Next Run

After Phase 1-2 land, the next fanout run should emit (and an operator should sample):

- Per-phase dispatcher prompt size (target < 30KB regardless of fan-out count after Phase 3).
- Per-writer deterministic caps rendered in prompt: max tool-use guidance, max result/output bytes, max handoffs, and timeout.
- Parent-session `Agent` tool_use count and structured tool-use counts when stream frames expose them; `unknown` otherwise.
- Provider-reported token/cost usage only when present; nullable/unknown otherwise. No synthesized dollars and no writer self-report as actual usage.
- Adoption ledger vs result-file equality for `status`, `completed_work_units`, `failed_work_units`, `blocked` / `needs_input`, `merge_status`, and commit SHA.
- Integration branch commits per phase (target == adopted unit count).
- Run total cost and phase max cost only when provider-reported.

Owners of the budget caps must inspect at least one writer's prompt manually to confirm placeholders were substituted to numbers and identity fields are present, not just that grep found zero literals (an empty file would also pass that grep).

---

## 9. Out of Scope For This Plan

- Reviewer-per-unit fan-out (`ykfw`) — Phase 4 placeholder.
- Crash-safe adoption between marker and merge (`sn6b`) — Phase 4 placeholder.
- The ECC plan itself. This plan unblocks it; it does not implement it.
- Changes to the prepare gate or work-unit decomposition logic. Those are working as designed and produced a clean prepared artifact for the failing run.

## 10. Shipped vs Deferred (2026-05-05)

Phases 1-3 landed for this plan. Phase 4 remains deferred to `ykfw` and `sn6b`.
The residual `y9i1` review gap was the missing live `pump_phases` two-unit
happy-path proof; it is now covered by a test that drives pump -> marker ->
adopter -> unit merge and asserts integration-branch merge commits for both
units.
