# Phase Session Dispatcher Fan-Out Plan

Status: implementation in progress — Phases 0–4 substantially landed (see STATUS notes inline); Phases 2 reviewer-per-unit fan-out, 3, 5, 6, 6.5, 7, 8 still outstanding
Date: 2026-05-03
Companion plans:
- `swarm-do/docs/phase-session-live-stage-marker-streaming-plan.md` (foundation; ~80% shipped)
- `research/swarmdaddy-autonomous-fanout-architecture-2026-05-03.md` (architecture investigation)
- `research/ecc-pattern-adoption-worktree-review-2026-05-02.md` (forensic review of failed run)

> **Session continuity:** Pick up cold. Every claim has a file path or experiment cite. A new session can verify without re-tracing.

---

## 1. Problem State

`/swarmdaddy:do <plan>` has two CLI-selectable modes today and **neither produces autonomous, full-swarm runs**:

| Mode | Default? | What happens | Why unusable |
| --- | --- | --- | --- |
| `--phase-sessions=off` | yes (`cli.py:3407 default="off"`) | `_print_prepared_dispatch` prints `Status: READY_FOR_DISPATCH` and exits 0 | Operator must hand-pump every phase via `swarm phases pump`, `swarm stages signal-*`, `swarm operator-decision apply` |
| `--phase-sessions=auto` | no | One `claude-print` session per phase | The session prompt (`context_bundle.py:516`) emits `## Informational Decomposition` with the rule (`phase_artifact_contract.py:79`) that `completed_work_units` *must stay empty*. A single Claude does Write/Edit/Bash directly. No child BEADS. No reviews. No fan-out. |

The recent ECC run `01KQJF1R90B5AYZCCYX7TYYB3B` confirms the auto-mode shape: `child_bead_ids: []`, `completed_work_units: []`, writer-only, 582 lines uncommitted. Documented behaviour, not a bug.

**Goal:** make `--phase-sessions=auto` (or a new `=fanout` mode) run the actual swarm — per-phase Claude session acts as a *dispatcher*, fans out to specialized sub-agents (writer / spec-review / code-review / codex-review / docs) via the `Agent` (formerly `Task`) tool, controller side-effects BEADS lifecycle / commits / handoffs from streamed `STAGE_COMPLETE` markers, and the run completes end-to-end with no operator pumping.

> **Tool name note (CONFIRMED, Anthropic docs).** Claude Code v2.1.63 renamed `Task` → `Agent`. Both names alias for parser compatibility; this plan uses `Agent` as the canonical tool name and `Task` only as a parser/legacy alias. The auto-mode failure analysis below is unchanged by the rename.

---

## 2. Foundation Already Shipped

The companion streaming plan (`phase-session-live-stage-marker-streaming-plan.md`) is mostly delivered. From the audit on 2026-05-03:

| Phase | Status | Evidence |
| --- | --- | --- |
| 1. `StageMarkerProcessor` | ✅ shipped | `swarm-do/py/swarm_do/pipeline/stage_controller.py` (20 KB, all 8 outcomes incl. `amended`/`pending`, `_owner_thread` enforcement, `_retry_pending`) |
| 2. `ClaudeStreamParser` | ✅ shipped | `swarm-do/py/swarm_do/pipeline/claude_stream.py` (frame kinds: `assistant_text`, `result`, `ignored`, `malformed`; metadata counters) |
| 3. Streaming runner | ✅ shipped | `phase_pump.py:937` (`output_format = "stream-json" if real_streaming else "json"`); queue+threads at 1204/1214/1220; 64 MiB cap at 1589 (`_STDOUT_STREAM_CAP_BYTES`); legacy fallback regex at 1668 |
| 4. capability + metadata | ⚠️ partial | command.json fields shipped (1689–1705); `--help` probe in `session_capabilities.py` and `test_session_capabilities` should be re-verified |
| 5. integration tests | ❌ missing | `tests/test_phase_pump.py` does not exist; the 9 CI-provable streaming cases listed in the plan are unwritten |
| Step 6 dogfood | ❌ unverified | "Multi-stage with deliberately slow later stage to prove early adoption" not run end-to-end |

**Implication:** the receiving half is operational; the dispatcher skeleton is also in tree from `274ab18`; this plan extends both halves with per-unit beads/worktrees, typed `subagent_type`, and the four-status marker grammar.

The streaming plan's missing tests + dogfood are listed in §6 of this plan as Phase 0 — close them before adding new behaviour.

### 2.1 Dispatcher Skeleton (commit 274ab18, 2026-05-02)

Commit `274ab18` ("putting quality lanes back") shipped the dispatcher skeleton in tree. The fan-out work is **extension** of `274ab18`, not parallel construction. Files shipped:

- `swarm-do/agents/agent-dispatcher.md`
- `swarm-do/role-specs/agent-dispatcher.md`
- `swarm-do/permissions/dispatcher.json`
- `swarm-do/py/swarm_do/pipeline/stage_invocation.py`
- `swarm-do/py/swarm_do/pipeline/stage_sessions.py`
- `swarm-do/py/swarm_do/pipeline/orchestrator_stream.py`
- `swarm-do/schemas/stage_sessions.schema.json`
- phase-pump integration + tests

Gap matrix from research §5:

| Component | Current state | Fan-out gap |
| --- | --- | --- |
| `stage_invocation.py` | preset graph stages, fan-out, provider, merge stages, lenses, expected result paths | missing `subagent_type`, `worktree_path`, `bead_id`, `allowed_files`, `acceptance_criteria` fields |
| `render_orchestrator_brief()` | renders `Task(subagent_type="general-purpose", prompt=...)` + `STAGE_COMPLETE` | hardcodes `general-purpose`; no per-unit worktree prompts |
| `stage_sessions.py` | durable per-stage ledger | adequate as ledger |
| `orchestrator_stream.py` | parses bounded `STAGE_COMPLETE`/`STAGE_FAILED` | adequate; needs `Agent` tool-name awareness |
| `phase_pump.py` `_prepare_stage_controller()` | initializes ledger, creates stage BEADS children when epic exists | doesn't call `materialize_unit_execution_worktree()` |
| `execution_worktree.py` | `materialize_unit_execution_worktree()` + `merge_unit_execution_worktree()` exist | not wired from phase dispatcher prep |
| `permissions/dispatcher.json` | allows `Task` | should use `Agent`; consider `Agent(<allowed types>)` |
| `parse_transcript_task_invocations()` | recognizes `Task` only | also recognize `Agent` (alias) |

The current plan's Phase 2 ("Prompt template swap in `context_bundle.py:516`") is wrong target — the brief already renders through `render_orchestrator_brief()` in `stage_invocation.py`. The current plan's Phase 4 ("Per-work-unit BEADS + worktrees in `_prepare_stage_controller`") is partly wrong — `materialize_unit_execution_worktree()` already exists in `execution_worktree.py`; phase dispatcher prep just doesn't call it. Phases 2 and 4 below have been rewritten to reflect that.

---

## 3. Verified Facts From Experiments (2026-05-03)

Four experiments run against `claude 2.1.126 (Claude Code)` at `/Applications/cmux.app/Contents/Resources/bin/claude`. All cites refer to captured stream files in `/tmp/swarmdaddy-experiments/{e1,e23,e4}/stream.jsonl` (gone on next reboot — re-run if needed).

### E1 — Task tool inside `claude -p --output-format stream-json`

Prompt instructed dispatcher to make one `Task` call (`subagent_type: general-purpose`) and emit a `STAGE_COMPLETE` marker.

- ✅ **Task fires.** Tool name surfaces in the stream as **`Agent`**, not `Task`. Input schema: `{description, subagent_type, prompt}`.
- ❌ **No `cwd` parameter.** Not in the input schema.
- ❌ **No `settings` / `permission_mode` parameter.** Sub-agent inherits parent's flags.
- ✅ **Sub-agent's *final output* returns as a `tool_result` user frame** in the parent stream, with `tool_use_id` matching the `Agent` tool_use.
- ✅ **Dispatcher can synthesize markers.** After the `tool_result`, the dispatcher's next assistant text frame contained `STAGE_COMPLETE {"stage_id":"e1","result_path":"none"}` verbatim.
- Cost: **$0.34 / 41.9 s / 2 turns / 35 frames.** Frame counts: `system: 29, assistant: 2 (tool_use: 1, text: 1), user: 2, rate_limit_event: 1, result: 1`.

### E2 — Per-work-unit cwd handoff

Sub-agent prompt asked it to `pwd` via Bash. Both sub-agents reported cwd `/tmp/swarmdaddy-experiments/e23` — the *parent's* cwd.

- ❌ **Task has no `cwd` parameter.** Confirmed twice (E1 and E2).
- ✅ **Workaround:** prepend `cd <worktree-path>` to the sub-agent's prompt and trust it. Brittle for hostile prompts but acceptable for our trusted dispatcher.
- ⚠️ Open: an alternative is to spawn each sub-agent in a separate `git worktree add` *before* the dispatcher launches, then have the dispatcher pass the path via prompt. The Phase 4 design picks one.

### E3 — Parallel Tasks

Two `Task` calls in one assistant message (`msg_015xbQyp5H`, frames 28 and 31) — the well-documented "parallel tool calls in one block" pattern.

- ✅ **They are truly concurrent.** Wall time: **44.4 s for 2 parallel Tasks vs 41.9 s for 1**. Negligible delta.
- ✅ **Cost scales sub-linearly:** $0.346 for 2 vs $0.341 for 1. Most cost is dispatcher overhead, not per-sub-agent. **Caveat 5k of the research memo is mild, not critical.**
- ✅✅ **With `--verbose`, sub-agent INTERNAL frames surface in the parent stream** with `parent_tool_use_id` linking back to the `Agent` tool_use_id (frames 36 and 39 carry `parent=toolu_01U4yQz9` and `parent=toolu_015pnrd4` respectively, matching the two Task IDs). **This is the most consequential discovery:** the existing `claude_stream.py` parser sees sub-agent activity for free if we want per-unit progress events.

### E4 — Concurrent BEADS writes

Ten parallel `bd create` calls in one process group → 10 unique IDs in 3.89 s, zero stderr, `bd doctor` clean.

- ✅ **`bd` is safe under bursts.** Caveat 5j of the research memo is closed.

### Total experiment cost: ~$0.69.

### 3.5 Confirmed from Anthropic docs (2026-05-03)

These facts are CONFIRMED by the merged external research (`swarm-do/docs/session-dispatcher-fanout-external-research-merged-2026-05-03.md`) and authoritative Anthropic sub-agent / SDK docs. They are load-bearing for §4–§6 below.

- **Tool rename `Task` → `Agent` in v2.1.63.** Both names alias for parser compatibility (Anthropic SDK explicitly recommends matching both).
- **Sub-agent tool inventory = `intersect(parent_inventory − disallowedTools, frontmatter.tools)`.** A sub-agent's frontmatter `tools` is intersected with the parent's tool pool, **never added to**. A writer sub-agent that lists `Write`/`Edit` cannot Write/Edit if the dispatcher launched without them.
- **Sub-agent permission mode inheritance.** Parent `bypassPermissions` / `acceptEdits` / `auto` cannot be overridden per-agent; graduated trust per role is impossible under a bypassed parent.
- **Plugin sub-agents** specifically ignore `permissionMode`, `hooks`, and `mcpServers` fields in their frontmatter.
- **Sub-agent output contract.** Only the final assistant message becomes the parent's `tool_result`. Intermediate sub-agent reasoning/tool_uses are not surfaced to the parent except via `--verbose` `parent_tool_use_id` linkage.
- **`parent_tool_use_id` is OBSERVED only** — keep parser tolerant (best-effort observability, not contract).
- **`subagent_type` lookup order.** Managed (built-in) > Project > User. Built-ins (`Explore`, `Plan`, `general-purpose`) always available. `--add-dir` directories are NOT scanned for sub-agent definitions.
- **Native `isolation: worktree` exists** but creates a Claude-managed temp worktree — wrong abstraction for controller-prescribed paths. Do not use.
- **Sub-agent Bash working directory does NOT persist between tool calls** (CONFIRMED). Each Bash invocation must self-establish cwd via `cd <abs> && ...`, `git -C <abs>`, or absolute paths. Drives Decision 14.

---

## 4. Decision

Three commitments anchor the design:

1. **Mode name.** Add a new dispatch mode `--phase-sessions=fanout` (unchanged from the prior draft).
2. **Foundation policy.** Extend the `274ab18` dispatcher skeleton (§2.1); do not introduce parallel orchestration modules. Targets: `stage_invocation.py`, `stage_sessions.py`, `orchestrator_stream.py`, `phase_pump.py`, `execution_worktree.py` (already shipped — wire it).
3. **Mental model.** Adopt LangGraph `Send` / `Command(goto=[Send,...])` as the canonical reasoning primitive. Each `Agent` tool call carries a typed payload; the controller pre-computes the payload; the dispatcher LLM cannot forge or mutate metadata fields (see Decision 11).

The flow per phase:

1. Per phase, launches **one** `claude-print` session whose prompt is the `agent-dispatcher` role (`swarm-do/role-specs/agent-dispatcher.md`), populated with a `## Work Units To Dispatch` section instead of `## Informational Decomposition`. Brief is rendered via `render_orchestrator_brief()` in `stage_invocation.py` (not `context_bundle.py:516`).
2. The dispatcher uses the `Agent` (formerly `Task`) tool to delegate each work unit to a typed sub-agent (`subagent_type: swarmdaddy:agent-writer`, `swarmdaddy:agent-spec-review`, etc. — verify resolution in Phase 1 / E6).
3. After each sub-agent's `tool_result` arrives in the parent stream, the dispatcher synthesizes a marker on its own assistant text channel — one of the four-status grammar tokens (Decision 3).
4. The already-shipped `claude_stream.py` + `stage_controller.py` adopt those markers live: BEADS close, commit, `stage_adopted` run-event, ledger update.
5. Per-work-unit BEADS issues are created **controller-side** in `_prepare_stage_controller` *before* the dispatcher launches (the dispatcher cannot create them; role spec forbids it).
6. Per-work-unit worktrees are created controller-side via the already-shipped `materialize_unit_execution_worktree()` and their paths are inlined into each sub-agent's prompt as a `cd <abs-path> && ...` preamble (Decision 14).

Keep `auto` mode in tree as a degraded "single Claude does everything" path until `fanout` is dogfood-proven, then deprecate.

Keep `off` mode unchanged — it remains the pre-prepared-only artifact emitter for users wiring their own dispatch.

---

## 5. Resolved Decisions (MUST)

1. **Dispatcher launch contract.** The single most consequential decision in v1. Two viable postures:

   - **(a) Bypass-cascade (v1 default).** Dispatcher launches with `--dangerously-skip-permissions`. Every sub-agent inherits bypass. Pro: writer sub-agents have Write/Edit/Bash without further plumbing. Con: no graduated trust per role.
   - **(b) Allowlist-superset (future).** Dispatcher launches in `default` mode with `--allowedTools` = union of every role's needed tools (e.g. `Agent,Read,Write,Edit,Bash,Grep,Glob`). Sub-agent frontmatter narrows further. Pro: graduated trust per role. Con: writer's Write/Edit must be in dispatcher's pool.

   **Pick (a) for v1.** Capture (b) as a future ticket gated by a hardening pass. Rationale: tool-inventory inherit-only-narrow rule (CONFIRMED, §3.5) and permission-mode-precedence rule (CONFIRMED, §3.5) make graduated trust impossible under a bypassed parent; choosing (a) consciously trades trust for shipping speed. E13 (§6 Phase 1) provides the empirical A/B that locks this in.

2. **Sub-agent tool inventory.** Inherited from parent's pool, intersected with frontmatter `tools`, minus `disallowedTools`. Plugin sub-agents ignore `permissionMode` / `hooks` / `mcpServers` (§3.5); if per-role permission mode matters in v2, copy roles into project/user scope or use `--agents '<json>'`.

3. **Marker synthesis (four-status vocabulary).** Dispatcher emits one marker per `tool_result`:

   - `STAGE_COMPLETE` (alias `DONE`) — sub-agent succeeded, result file written.
   - `STAGE_DONE_WITH_CONCERNS` — succeeded but flagged follow-ups; controller adopts and queues a `notes` artifact.
   - `STAGE_FAILED` (alias `BLOCKED`) — sub-agent failed; controller routes by `failure_kind`.
   - `STAGE_NEEDS_CONTEXT` — sub-agent reports missing context; controller re-dispatches with augmented prompt (cap 3 cycles, fresh sub-agent each time per metaswarm anti-anchoring rule, see Decision 12).

   Wire markers into `StageMarkerProcessor` outcomes; map four statuses to existing eight-outcome vocabulary in `stage_controller.py`. Implementation surface for the new tokens vs a binary-marker-with-structured-status alternative is a competitive build (Decision 15 / CB-1 in §13).

4. **Result path discipline.** Each sub-agent's prompt includes the controller-prescribed `expected_result_path` and a directive: "Before finishing, write your result JSON to `<path>` exactly. Do not return success without writing." The dispatcher's marker carries that same `result_path`. The existing `StageMarkerProcessor._validate_stage_result` rejects mismatches. **Unchanged.**

5. **Worktree assignment.** Each work unit gets `<run-root>/units/<unit-id>/repo` via `materialize_unit_execution_worktree()` (already shipped in `execution_worktree.py`). Sub-agent prompt opens with `cd <abs-path>` (no `cwd` parameter on the `Agent` tool, CONFIRMED). Add:

   - **Atomic rollback** — if any setup step fails (worktree create, branch alloc, coord-dir mkdir), undo previous steps in reverse. Steal pattern from everything-cc `rollbackCreatedResources` (~30 LoC).
   - **Branch-collision pre-flight** — `git branch --list` check before `git worktree add`. Steal from everything-cc.
   - **Optional `overlaySeedPaths`** — `shutil.copy2` for sharing uncommitted plan docs into worktrees, with `path-stays-inside-repo` validation guard.

   The phase's "main" worktree (for the dispatcher itself) stays at `…/<run-id>/repo` and is read-only at the file level (only `Read`/`Bash` diagnostics).

6. **Failure marker payload — adopt mco failure taxonomy.**

   - **Retryable:** `RETRYABLE_TIMEOUT`, `RETRYABLE_RATE_LIMIT`, `RETRYABLE_TRANSIENT_NETWORK`.
   - **Non-retryable:** `NON_RETRYABLE_AUTH`, `NON_RETRYABLE_INVALID_INPUT`, `NON_RETRYABLE_UNSUPPORTED_CAPABILITY`, `NORMALIZATION_ERROR`.
   - **`PARTIAL_SUCCESS`** — real terminal state for "some stages adopted, some blocked"; phase result preserves both sets, not an error.

   `notes` is the first 500 chars of the sub-agent's `tool_result.snippet`. The controller maps `failure_kind` to `failure_retry_class` per existing policy.

7. **Parallelism cap.** Cap at **8** concurrent sub-agents per dispatcher message until measured (was 3). Anthropic docs explicitly endorse parallelism with no documented hard cap; OBSERVED 2 is fine; ship E17 stress test for N ∈ {2, 4, 8, 16} (realistic-N writer/reviewer payloads, not toy `echo` prompts) before raising further.

8. **`--verbose` is required.** Without it, sub-agent internal frames don't surface and the live progress story degrades. Set in `phase_pump.py` argv assembly for `fanout` mode. Note: `parent_tool_use_id` is OBSERVED-only (§3.5); treat as best-effort observability, not contract.

9. **Tool name `Agent` everywhere.** Rename in `permissions/dispatcher.json`, `role-specs/agent-dispatcher.md` prose, `render_orchestrator_brief()` template, dispatcher prompt instructions. Keep `Task` as a parser alias for stream-fixture compatibility — Anthropic SDK explicitly recommends matching both.

10. **`StageInvocation` field set.** Extend the existing dataclass with: `subagent_type: str`, `worktree_path: pathlib.Path`, `bead_id: str | None`, `allowed_files: list[str]`, `acceptance_criteria: str`. Default `subagent_type` from `agent_role`. Render all fields into the per-unit prompt block.

11. **Curated context principle (controller-managed metadata).** Borrow OpenAI Swarm's `context_variables` shape: controller renders per-WU metadata into the dispatcher prompt; the dispatcher LLM cannot forge or mutate `bead_id`, `worktree_path`, `expected_result_path`, `allowed_files`. Controller only trusts metadata it reads back from BEADS or filesystem, never what the dispatcher prose writes.

12. **Fresh-reviewer rule (anti-anchoring).** On re-review after FAIL, controller MUST spawn a brand-new review sub-agent with **no prior findings** in the prompt. Cap retry cycles at 3 before BEADS-blocked + human escalation. Verbatim from metaswarm anti-anchoring discipline.

13. **Stage ⇄ work-unit identity bridge.** `StageInvocation` is generated from the active preset graph; `materialize_unit_execution_worktree()` is keyed by prepared-plan `unit_id`. These were conflated in the original draft. Resolution:

    - Add `work_unit_id: str | None` to `StageInvocation`. Required for writer/implementer stages; nullable for aggregator stages (merge, gate).
    - Mapping rule: review stages and re-review stages share the **parent writer unit's** `work_unit_id` (so they materialize against the same per-unit worktree). Merge/integration stages carry `work_unit_id = None` and operate on the phase workspace, not a per-unit worktree.
    - Document the mapping in `stage_invocation.py` docstring. Add a builder helper that derives `work_unit_id` from preset metadata + prepared-plan registry; reject ambiguous cases at preflight rather than runtime.
    - Tests: `test_stage_invocation_work_unit_mapping` covers writer→reviewer same-id, merge→None, ambiguous→preflight error.

14. **Sub-agent Bash working-directory discipline.** Sub-agent Bash cwd is **not** persisted between tool calls (CONFIRMED, §3.5). The dispatcher prompt must mandate one of:

    - `cd <abs-worktree-path> && <command>` per Bash invocation, **or**
    - `git -C <abs-worktree-path> <subcommand>` for git operations, **or**
    - absolute paths for everything else (no relative `./foo`).

    Render this rule into the per-unit prompt block alongside `worktree_path`. Test (`test_subagent_bash_cwd_persistence`): synthetic stream where a sub-agent issues two Bash calls; assert second call still touches the unit worktree (i.e. parser/prompt would not let it drift to repo root).

15. **Marker grammar protocol — competitive build (CB-1, see §13).** Two designs, both viable:

    - **(a) Token expansion.** Add `STAGE_DONE_WITH_CONCERNS` and `STAGE_NEEDS_CONTEXT` markers to parser, ledger enum, stage-result schema, phase-result mapping, retry policy, and JSON schemas. Six-surface migration.
    - **(b) Binary markers + structured result.** Keep parser at `STAGE_COMPLETE`/`STAGE_FAILED`. Add a `status` field to the result-artifact JSON schema (enum: `done|done_with_concerns|blocked|needs_context`). Controller reads the result file post-marker and routes off `status`. Two-surface migration; promotable to (a) later if measurement shows we want it in the marker stream.

    **Default v1 to (b)** unless the competitive build proves (a) is worth the schema/state-machine churn. (a) buys earlier signal — controller knows status before reading the artifact — at the cost of grammar/schema migration on six surfaces.

---

## 6. Implementation Phases

### Phase 0 — Close streaming-plan gaps first (blocker)

Before the dispatcher work, finish the foundation:

- Add `swarm-do/py/swarm_do/pipeline/tests/test_phase_pump.py` with the 9 CI-provable cases listed at `phase-session-live-stage-marker-streaming-plan.md:564-602`.
- Verify `_claude_print_capability` (`session_capabilities.py:136`) has the `--help` probe with 5 s timeout, sets `details["stream_json_supported"]`, caches per `claude_path`. Add `test_claude_print_stream_json_probe_{supported,unsupported}` if missing.
- Run the dogfood from work order step 6: one short multi-stage phase, assert by timestamp that stage 1 ledger transition (`stage_adopted` event) happens before phase exit.

Phase 0 is a hard blocker — without test_phase_pump.py we cannot verify any new dispatcher behaviour through the existing CI.

### Phase 0.5 — Dispatcher launch-contract validation (blocker)

Before E5–E8 / E13–E17, run a permission-mode probe that decides Decision 1 in practice.

- Launch dispatcher with `--dangerously-skip-permissions`; confirm sub-agent Bash + Write + Edit succeed end-to-end (write a file, edit it, run `git status`).
- Launch dispatcher in `default` mode with `--allowedTools="Agent,Read,Bash,Write,Edit,Grep,Glob"`; confirm sub-agent Write succeeds (proves the inherit-then-narrow rule in practice).
- Record actual inherited tool inventory from the sub-agent's transcript, not assumed.

Outcome locks v1 posture. Default per Decision 1: bypass-cascade. Phase 0.5 must run before any code change in Phases 2–5, since phases below depend on a known-good launch contract.

### Phase 1 — Experiments E6–E17

Follow-up experiments split into **resolution/parallelism** (E6–E12) and **research-driven decisives** (E13–E17). Run E6–E12 first (cheap, ~$3–$5); run E13–E17 to settle Decisions 1, 13–15 and feed CB-1/CB-2 (~$5–$8).

**E6 — `subagent_type: swarmdaddy:agent-writer` resolution** (~$0.30):

```
claude -p --output-format stream-json --verbose --dangerously-skip-permissions \
  'Use Agent with subagent_type "swarmdaddy:agent-writer" and prompt "Print SWARM_WRITER_RESOLVED and exit."'
```

✅ if the writer agent's role definition is loaded; ❌ → fall back to inlining the role spec (~2 KB per delegation).

**E9 — Parallel fanout cap** — measure dispatcher context usage / wall time at N ∈ {2, 4, 8, 16} on toy `echo` prompts. Feeds Decision 7. Superseded by E17 for the realistic-N number.

**E10 — Plugin namespacing** — confirm the `swarmdaddy:` prefix resolves through the project/plugin sub-agent lookup order (§3.5).

**E11 — Typo fallback** — feed an unknown `subagent_type` and confirm Anthropic's `general-purpose` fallback behaviour.

**E12 — `--max-turns` accounting** — confirm whether the parent `--max-turns` counter only counts top-level Agent tool_use blocks or also includes sub-agent internal turns. Decides whether default `--max-turns` needs raising in fanout mode.

**E13 — Permission A/B (decisive).** Run the same two-unit fan-out under both postures: (a) `--dangerously-skip-permissions`; (b) `--permission-mode default --allowedTools "Agent,Read,Write,Edit,Bash,Grep,Glob"`. Each must prove sub-agent Write, Edit, and Bash succeed end-to-end. Record actual inherited tool inventory from the sub-agent transcript, not assumed. **Outcome decides Decision 1.**

**E14 — Unit-worktree adoption.** Allowed-file write (in `allowed_files`), blocked-file write (outside it — must fail or be detected), marker emission, `commit_stage_artifacts()` against the unit worktree, `merge_unit_execution_worktree()` back to the phase workspace, and resume idempotency (kill between marker and merge — re-run completes cleanly). Validates Decision 13's mapping plus Phase 4 step 6/7. Feeds CB-2. **STATUS 2026-05-04 (late):** soft-check covered by `scripts/experiments/e14_lite.sh`; full real-claude `pump_phases(... mode="fanout")` driver landed at `scripts/experiments/e14_run.py` (replaces the `UnitSessionError` placeholder). Verdict gates on pump status + adopted stages + dispatcher brief shape + post-merge workspace. `REUSE_STREAM=1` replays via `last_run.json` + `replay_data/` snapshot.

**E15 — Status grammar probe.** Two parallel implementations: (a) extended marker tokens emitted by the dispatcher and parsed into ledger; (b) binary marker + structured `status` in result-artifact JSON. Measure code surface touched, parse failure modes on malformed sub-agent output, and observability (when does the controller learn status — at marker time or artifact-read time). **Feeds Decision 15 / CB-1.**

**E16 — Crash/resume.** Kill the dispatcher process at three points: (i) after first marker before second sub-agent spawn, (ii) after second marker before phase finish, (iii) mid-merge. Resume must produce no duplicate BEADS issues, no duplicate worktrees, no duplicate commits, and the same final ledger state as a clean run. Tests the durability claims of `stage_sessions.py` plus the new adoption layer. **STATUS 2026-05-04 (late):** lane (ii) covered by `test_unit_adoption_resume_from_marker_before_merge_is_idempotent`. Lanes (i) and (iii) v0 scaffold landed at `scripts/experiments/e16.py` — drives `pump_phases` with simulated kill points, snapshots ledger + telemetry + commit count, gates on `kill_point_exercised`. v0 caveat: the fake `_claude_runner` short-circuits the adoption layer, so both lanes correctly FAIL the gate until a marker-emitting runner replaces it (or `claude_runner=None` runs against real claude with a SIGTERM wrapper). Real-claude lane is documented as the v1 follow-up.

**E17 — Realistic-N parallelism.** Replace toy `echo` prompts with realistic writer (~2 KB output, file edits, ~30 s) and reviewer (~1 KB output, ~15 s) sub-agents at N ∈ {2, 4, 8, 16}. Measure: actual concurrency (transcript timestamps), stream-buffer pressure, rate-limit hits, total wall-clock, marker ordering. Replaces the toy E9 cap-raising probe for the actual number. **STATUS 2026-05-04 (late):** all four sweeps captured under `/tmp/swarmdaddy-experiments/e17-n{2,4,8,16}/`; `peak_parallel=1` across the board (single-dispatch even at N=16). `done_count` walks tightened in `lib.sh::count_unique_k_markers` to drop input-side echoes — synthetic 1-of-3 case proves the fix has bite (tight=1 vs old walk-everything=3); cached sweep results are unaffected because every dispatched unit happened to complete. `REUSE_STREAM=1` replays via the cached `stream.jsonl` per N.

### Phase 2 — Extend the dispatcher brief (`stage_invocation.py`)

Target `render_orchestrator_brief()` in `swarm-do/py/swarm_do/pipeline/stage_invocation.py`, **not** `context_bundle.py:516`. The dispatcher skeleton from `274ab18` already routes through the orchestrator brief.

Sub-tasks:

1. **Extend `StageInvocation`** with the five new fields (Decision 10) plus `work_unit_id` (Decision 13): `subagent_type: str`, `worktree_path: pathlib.Path`, `bead_id: str | None`, `allowed_files: list[str]`, `acceptance_criteria: str`, `work_unit_id: str | None`. Default `subagent_type` from `agent_role`.
2. **Update `render_orchestrator_brief()`** to emit dispatcher-brief sections in this order: `## Role` (inlined `role-specs/agent-dispatcher.md`), `## Work Units To Dispatch` (for each unit: id, subagent_type, worktree_path, expected_result_path, allowed_files, acceptance_criteria, bead_id, prompt_prefix with `cd <wt> &&`, **and the Bash-cwd discipline string from Decision 14**), `## Marker Contract` (four-status grammar from Decision 3 — variant locked by CB-1 winner), `## Parallelism Rules` (current cap from Decision 7).
3. **Mode-gate** behind `phase_sessions_mode == "fanout"`; legacy `auto` mode renders unchanged.
4. **Replace `Task(...)` with `Agent(...)`** in template prose; keep `Task` as a parser alias for fixtures.

### Phase 3 — Relax artifact contract (`phase_artifact_contract.py`)

Line 79 today:

> "In phase-session mode, `result.completed_work_units` and `handoff.completed_work_units` must stay empty unless you are using a prepared unit id shown in the informational decomposition."

In `fanout` mode, the controller — not the dispatcher Claude — populates `completed_work_units` from adopted `StageMarker` IDs. Two changes:

1. Add a mode-aware variant of the rule. In `fanout` mode the dispatcher MAY leave `completed_work_units` empty; the controller fills it post-finish using the `StageMarkerProcessor.finish()` aggregate.
2. Validation order: when the controller writes the phase result file at finish time, it merges `processor_finish.markers[*].stage_id → completed_work_units`. Schema check passes against the post-merge document.

### Phase 4 — Wire per-unit worktrees + adoption layer

**STATUS 2026-05-04 — wiring landed; adoption layer (step 6) and idempotent-resume (step 7) verified by tests.** Step 1 ships at `phase_pump.py:_prepare_stage_controller` (line 506-514, branches on `phase_sessions_mode == "fanout"`) calling `_materialize_unit_worktrees` (line 545-565), which iterates `unit_ids` and invokes `materialize_unit_execution_worktree(run_id, phase_id, unit_id, data_dir=data_dir)` per unit. Step 6 adoption is wired through `StageMarkerProcessor` + per-unit commit/merge — covered by passing tests `test_unit_marker_commits_unit_worktree_then_merges` and `test_unit_adoption_resume_from_marker_before_merge_is_idempotent` (resolves CB-2 in favour of variant (a) "in-place adoption"). The full `pump_phases(... mode="fanout")` happy-path passes via `test_fanout_launch_contract_uses_bypass_and_agent_prompt` after a 2026-05-04 fixture-leak fix (`make_prepared_run` now pins `XDG_DATA_HOME` to tmp and pre-cleans `/tmp/swarmdaddy-worktrees/<run_id>`). Remaining open: kill-points (i) mid-spawn and (iii) mid-merge are exercised only by primitive-level tests, not end-to-end with real claude — captured as deferred E16 lanes (v0 scaffold landed in `e16.py`; real-claude SIGTERM lane still TBD).

**STATUS 2026-05-04 (very late) — Decision 13 builder helper (writer auto-expand) landed (closes `mstefanko-plugins-grcp`).** Real-world dogfood through `/swarmdaddy:do <plan>` exposed the gap: with `default.yaml` writer at `agents: [agent-writer]` (no explicit `fan_out`) and any phase with N>1 work units, `_work_unit_id_for_invocation` raised `stage writer is ambiguous across N work units` at runtime — exactly what Decision 13 named ("reject ambiguous cases at preflight rather than runtime") but the builder helper had not been wired. Fix: `plan_stage_invocations` now accepts `phase_sessions_mode`; in fanout mode `_auto_expand_writer_per_unit` replicates a writer stage (with no explicit `fan_out`) into N invocations keyed `<id>:fanout-1..N` with `fan_out_index=0..N-1` so `_attach_work_unit_metadata` can map each to a unit. Explicit `fan_out` declarations (compete preset's competitive-variant pattern) are NOT touched — auto-expansion is opt-in through the absence of `fan_out`. `_prepare_stage_controller` threads `phase_sessions_mode` through. Tests: `test_default_preset_auto_expands_writer_per_unit_in_fanout_mode`, `test_explicit_fan_out_preset_is_not_auto_expanded`, `test_auto_mode_unaffected_by_phase_sessions_mode_default`. **Reviewer-per-unit fan-out (Decision 13's "review stages share parent writer's `work_unit_id`") is a separable follow-up and not yet shipped.**

**STATUS 2026-05-04 (late) — experiment-harness cleanup landed.** The four follow-ups flagged after the second sweep are in tree:

- **`done_count` over-count fix (closed `mstefanko-plugins-1o09`).** `scripts/experiments/lib.sh::count_unique_k_markers` scopes to assistant text + tool_result + result.result, mirroring the existing `count_response_text_hits` discipline. `e9.sh`, `e9p.sh`, `e17.sh` switched off the recursive walk-every-string approach. Synthetic 1-of-3 sub-agent test confirms tight=1 vs old=3 (proves the fix has bite); cached real sweeps are unchanged because every dispatched unit completed. **Headline `peak_parallel=1` finding unaffected.**
- **`REUSE_STREAM=1` mode (closed `mstefanko-plugins-tgot`).** `lib.sh::run_claude` short-circuits when env set + cached `stream.jsonl` exists; new `reuse_stream_short_circuit` helper for scripts that bypass `run_claude` (e9p/e17/e14/e16). Verified across all sweeps: replay path emits `[reuse]` log line, no API spend, headline metrics preserved.
- **E14 full real-claude `pump_phases` harness (closed `mstefanko-plugins-d0gt`).** `scripts/experiments/e14_run.py` rewritten as a real `pump_phases(... mode="fanout")` driver against `make_prepared_run` + `bd_epic_id="epic-e14"`. Replaces the `UnitSessionError` placeholder. Verdict gates on pump status, stage adoption, `Agent(subagent_type=)` in dispatcher brief, post-merge workspace. Replays via `last_run.json` + `replay_data/` snapshot.
- **E16 lanes (i)+(iii) v0 scaffold (closed `mstefanko-plugins-b0xo`, P3).** `scripts/experiments/e16.py` drives both lanes through `pump_phases` with simulated kills. Verdict checks no-duplicate-worktrees / no-duplicate-`stage_adopted`-events / terminal-pump-status / `kill_point_exercised`. v0 honestly reports both kill points unfired because the fake `_claude_runner` short-circuits the adoption layer — to land the real test, replace `_claude_runner` with a marker-emitting runner or run `claude_runner=None` against real claude with a SIGTERM wrapper.

**Adoption path is load-bearing — do not skip step 6.** Wire existing helpers; do not re-implement.

1. From `_prepare_stage_controller()` (in `phase_pump.py`), call `materialize_unit_execution_worktree()` per work unit (already shipped in `execution_worktree.py`), keyed by `StageInvocation.work_unit_id` (Decision 13).
2. **Atomic rollback wrapper** (steal from everything-cc): if worktree create succeeds but branch alloc fails, undo worktree before raising. ~30 LoC in reverse-undo order.
3. **Branch-collision pre-flight check** — `git branch --list <name>` before `git worktree add`.
4. *Optional:* implement `overlay_seed_paths()` helper for sharing uncommitted plan docs (`shutil.copy2` + `path-stays-inside-repo` guard); defer if not needed for first dogfood.
5. **Per-unit BEADS** are already created when an epic exists in current `phase_pump.py`; verify path matches the `bead_id` field on `StageInvocation`.
6. **Adoption path (NEW — fills the gap).** `StageMarkerProcessor` currently commits artifacts from the phase workspace, which silently drops a sub-agent's writes inside the per-unit worktree. Wire one of (resolve via CB-2, see §13):

   - **(a) In-place adoption.** Extend `StageMarkerProcessor` to read `worktree_path` from the matching `StageInvocation`, then call `commit_stage_artifacts(worktree=<unit_wt>)` instead of the phase workspace. Merge that branch back via `merge_unit_execution_worktree()` after successful marker.
   - **(b) Separate unit-session adoption layer.** Leave `StageMarkerProcessor` alone for phase-level stages; add a new `UnitSessionAdopter` that runs after the marker, owns the per-unit `commit_stage_artifacts()` + `merge_unit_execution_worktree()` sequence, and updates the ledger.

7. **Idempotent adoption.** If process crashes after marker but before merge, resume must re-attempt merge without duplicate commits. Test (`test_unit_adoption_resume_idempotency`): kill process between marker write and merge; on resume, merge proceeds; no duplicate BEADS state, no duplicate commits.

### Phase 5 — Tool-name migration + launch-contract argv

Tool-name migration spans generated artifacts; launch contract is concrete code.

1. **Role-spec is source of truth.** Update `swarm-do/role-specs/agent-dispatcher.md`: replace `Task` with `Agent` in prose, allowed-tools, and marker-contract section.
2. **Regenerate downstream artifacts** from the updated role spec: `swarm-do/agents/agent-dispatcher.md`, `swarm-do/permissions/dispatcher.json` (consider `Agent(swarmdaddy:agent-writer,swarmdaddy:agent-spec-review,...)` to constrain spawnable types). Document the regeneration command in the plan and CI.
3. **Update `parse_transcript_task_invocations()`** in `orchestrator_stream.py` to match both `Task` and `Agent` tool names (Anthropic SDK recommendation); keep `Task` as parser alias.
4. **Update `_effective_permissions_check()`** in the harness/preflight code: it currently requires `Task` in the dispatcher inventory. Make it accept `Agent` (preferred) and `Task` (legacy alias) under fanout mode; assert that bypass-cascade (Decision 1a) does not require explicit allowlist membership for `Agent`.
5. **Sweep hardcoded `Task` references** in synthetic transcript fixtures, capability probes, dispatcher prompt templates, and tests that assert `Task` is present. Search command: `rg -n '\bTask\b' swarm-do/` filtered to non-history files; categorize each hit as alias-keep vs migrate-to-Agent.
6. **Launch-contract argv (NEW — fills the gap).** Branch `_build_dispatcher_argv()` (or equivalent in `phase_pump.py`) on `phase_sessions_mode == "fanout"`:

   - Posture (a) bypass-cascade: emit `--dangerously-skip-permissions`; **omit** `--allowedTools` for the dispatcher (sub-agent inheritance handles narrowing).
   - Posture (b) allowlist-superset (future): emit `--permission-mode default --allowedTools "Agent,Read,Write,Edit,Bash,Grep,Glob"`.
   - Record the chosen contract in command metadata (`stage_sessions.json` or `phase_session_command.json`) under `launch_contract: {posture, argv, recorded_at}` so post-mortems and resume can verify what was actually launched.

7. **Defensive assertion**: if `phase_sessions_mode == "fanout"` and neither bypass nor an `Agent`-inclusive allowlist is present in the constructed argv, fail-fast with `failure_kind: "dispatcher_missing_agent_tool"`.

### Phase 6 — Failure-class mapping and work-unit retry

Two surfaces to extend, both adopting the mco failure taxonomy from Decision 6:

1. `phase_recovery.py` — the `_failure_kind_for_attempt` path classifies launcher output. Today it classifies at phase granularity. Add a `_failure_kind_for_unit` path that reads the controller's per-unit `MarkerDecision` outcomes (from `command.json.stage_controller`) and maps `STAGE_FAILED` markers to retry classes per the mco vocabulary (`RETRYABLE_*` / `NON_RETRYABLE_*` / `PARTIAL_SUCCESS` / `NORMALIZATION_ERROR`). `RETRYABLE_*` → re-dispatch only the failed unit's sub-agent in a follow-up turn. `NON_RETRYABLE_*` → human_gate as today.
2. `phase_autopilot_policy.py` — currently per-phase. Add per-unit accounting so the autopilot can decide "retry phase with these N units only" instead of "retry the whole phase".
3. `stage_controller.py` — add `PARTIAL_SUCCESS` as a real terminal state for phase results: legitimate "some stages adopted, some blocked", not an error.

This is the largest open piece. Work it after Phases 0–5 are green; partial-phase retry is not strictly required for the first dogfood (a full phase rerun on any failure is acceptable while we shake out bugs).

### Phase 6.5 — Re-review anti-anchoring guards

1. On `STAGE_FAILED` with retry-class transient, controller re-dispatches the failed unit with a **fresh sub-agent** (new `subagent_type` instance — no prior findings carried in prompt). Verbatim from metaswarm anti-anchoring discipline (Decision 12).
2. Cap at 3 retry cycles per unit; on cycle 4, transition unit BEADS to `blocked` + emit `human_gate` event.

### Phase 7 — Tests

New file: `swarm-do/py/swarm_do/pipeline/tests/test_dispatcher_fanout.py`.

Required cases (originals + new):

- `test_dispatcher_prompt_includes_role_and_units` — golden snapshot of the rendered brief for a 2-unit phase.
- `test_dispatcher_synthesized_marker_round_trip` — `fake_claude` script: dispatcher emits one Agent tool_use, frame fixture replays a tool_result, dispatcher emits `STAGE_COMPLETE`, assert `StageMarkerProcessor` adopts the stage and ledger row written.
- `test_dispatcher_failure_marker_records_failed` — same with `is_error: true` tool_result and `STAGE_FAILED` synthesis.
- `test_three_parallel_tasks_produce_three_markers` — fan-out invariant.
- `test_per_unit_worktree_path_in_prompt` — assert prompt prefix contains `cd <expected-worktree>`.
- `test_per_unit_bead_created_before_dispatch` — assert per-unit BEADS bridge set on every `StageInvocation` before `_run_real_claude` starts.
- `test_unknown_subagent_type_falls_back_to_general_purpose` — Phase 1 / E11 caveat.
- `test_existing_test_paths_unchanged` — `phase_sessions_mode != "fanout"` paths use the legacy brief and pass without edits.
- `test_status_grammar_round_trip` — whichever variant wins CB-1: token expansion produces ledger transitions, OR binary marker + structured status routes correctly.
- `test_tool_name_agent_alias` — parser recognizes both `Task` and `Agent` tool_use blocks.
- `test_dispatcher_launch_contract_bypass` — bypass-cascade argv is constructed correctly and recorded in command metadata; sub-agent Write/Edit/Bash succeed under it.
- `test_dispatcher_launch_contract_allowlist` — allowlist-superset argv constructed correctly when posture (b) selected.
- `test_atomic_rollback_on_worktree_failure` — partial setup undone in reverse.
- `test_fresh_reviewer_no_prior_findings` — retry prompt does not leak prior failures.
- `test_partial_success_terminal_state` — phase result with mixed adopted/blocked stages.
- `test_stage_invocation_work_unit_mapping` (Decision 13) — writer→reviewer share `work_unit_id`; merge→`None`; ambiguous mapping rejected at preflight.
- `test_subagent_bash_cwd_persistence` (Decision 14) — synthetic stream where sub-agent issues two Bash calls; assert second call still scoped to unit worktree (prompt requires `cd <wt> && ...` or `git -C <wt>`).
- `test_unit_adoption_commits_from_worktree` — sub-agent write inside `units/<id>/repo` is committed and merged back to phase workspace.
- `test_unit_adoption_resume_idempotency` — kill between marker and merge; resume completes without duplicate commits/BEADS.
- `test_effective_permissions_check_accepts_agent` — preflight no longer requires `Task`; accepts `Agent` under fanout mode.

Add fan-out fixtures to `tests/fixtures/claude_stream/` showing dispatcher emission patterns.

### Phase 8 — Dogfood

In order:

1. Tiny scratch plan (1 phase, 2 work units) → `swarm do --phase-sessions=fanout`. Assert: 2 child beads, 2 worktrees, 2 commits, 2 `stage_adopted` events, run-event timeline shows live ordering. **Permission-posture verification:** assert dispatcher launched with the documented launch contract (Decision 1) AND that all sub-agents inherited tools as expected (compare transcript-reported inventory to expected inheritance).
2. Realistic plan (3 phases, 3 units each) → assert no operator intervention; capture cost; verify `command.json.stage_controller.completed: true` per phase.
3. Re-run the ECC pattern adoption against `fanout` mode using the eval recipe at `swarm-do/docs/eval-batches/2026-04-ecc-pattern-adoption.md` (canonical path). Compare evidence: child beads count, review evidence presence, time-to-first-commit.

---

## 7. Non-Goals (this plan)

- No phase parallelism. Phases stay sequential. Only sub-agents within a phase fan out.
- No partial-phase retry of mixed pass/fail unit batches in v1 (Phase 6 lays the groundwork; v1 retries the whole phase on any failure).
- No alternative launchers (no `claude` subprocess pool from the controller). The dispatcher remains a single `claude -p` session.
- No deprecation of `auto` mode in v1; runs in parallel until `fanout` is dogfooded.
- No new BEADS workflow primitives (e.g., per-unit dependencies). Use existing `phase_beads.create_stage_child` shape.
- No streaming inside the sub-agent's tool calls back to the dispatcher (`claude -p` already gives us this for free with `--verbose`; no work needed).
- No graduated permission trust per sub-agent role in v1. Documented as a future hardening pass under Decision 1 (b).

---

## 8. Caveats Still Open After Experiments

These are documented in the research memo (`research/swarmdaddy-autonomous-fanout-architecture-2026-05-03.md` §5) and only partially resolved:

| ID | Caveat | E1–E4 status | Plan response |
| --- | --- | --- | --- |
| 5a | Task in claude-print | ✅ confirmed works (E1) | Phase 1 verifies plugin-agent resolution |
| 5b | Context pressure in dispatcher | ✅ raised to 8 per Decision 7; close on E17 measurement | §5 decision 7 + E17 (realistic-N) |
| 5c | `stage_controller` wired into `phase_pump`? | ✅ confirmed (audit) | Phase 0 closes test gaps |
| 5d | Off-mode dispatcher git history | ⏳ unread | Phase 0 prereq: `git log -p --follow swarm-do/py/swarm_do/pipeline/cli.py \| grep -B5 _dispatch_phases` to see if a working dispatcher ever shipped |
| 5e | Streaming-marker plan status | ✅ ~80% shipped | §2 itemizes gaps |
| 5f | Sub-agent permission propagation | ✅ CONFIRMED inherit-with-precedence (§3.5); load-bearing | Decision 1 (bypass-cascade default in v1) |
| 5g | Work-unit-granular retry | ⏳ not done | Phase 6 — largest open piece |
| 5h | Per-unit worktree | ⚠️ no Task `cwd` (E2) | §5 decision 5: prompt-prefix `cd` + controller-side worktree creation |
| 5i | `human_gate` failure path | unchanged | preserved as today; dispatcher can't auto-resolve |
| 5j | BEADS race | ✅ closed (E4) | no action |
| 5k | Cost budget | ✅ sub-linear (E3) | accept; budget per dispatcher session ≈ $0.35 + $0.05/extra unit |

### Newly surfaced caveats (not in the original memo)

| ID | Caveat | Resolution path |
| --- | --- | --- |
| 5l | Sub-agent crash semantics in stream | Run a Phase 1 follow-up: prompt a sub-agent to deliberately fail (e.g., bad Bash command). Inspect `tool_result.is_error` and snippet shape. Pin failure mapping in §5 decision 6. |
| 5m | `--max-turns` budget for dispatcher | Each `Agent` use + result = 2 turns. Five sequential delegations = 10 turns minimum. Default `--max-turns` may need raising. Confirm by reading `_run_real_claude` argv and measuring. |
| 5n | Plugin agent resolution in `claude -p` | Phase 1 / E6 experiment. If unresolved, inline role spec as prompt prefix (~2 KB cost per call). |
| 5o | Result-file write race | Sub-agent writes `expected_result_path` *during* its work; dispatcher emits marker *after* the result returns. The streaming `StageMarkerProcessor._pending` already handles "marker arrives before file" — but verify: does the sub-agent's `tool_result` arrive synchronously after the file write, or could the file write hit disk later via some buffering? Treat as unverified until E8 below. |
| 5p | Tool name `Agent` vs `Task` | ✅ closed via Decision 9: `Agent` canonical; `Task` parser alias only |
| 5q | Tool inventory inherit-only-narrow | ✅ CONFIRMED (§3.5); load-bearing — Resolution: Decision 1 |
| 5r | Permission mode inheritance precedence | ✅ CONFIRMED (§3.5) — Resolution: Decision 1 v1 picks bypass-cascade |
| 5s | `--max-turns` semantics for sub-agents | UNCONFIRMED — ship E12 before relying on parent counter only counting Agent tool_use blocks |
| 5t | `parent_tool_use_id` undocumented | OBSERVED-only — keep parser tolerant |
| 5u | Native `isolation: worktree` | CONFIRMED-but-wrong-tool — do not use; use `materialize_unit_execution_worktree()` |

### Recommended next-session experiments (cheap)

The full E5–E17 experiment list now lives in §6 Phase 1. Summary of cheap pre-implementation probes:

- **E5 — sub-agent failure shape.** ~$0.30. Prompt: "Use Agent to run a sub-agent that runs `bash -c 'exit 7'`." Inspect `tool_result.is_error` and content. Resolves 5l.
- **E6 — `subagent_type: swarmdaddy:agent-writer` resolution.** ~$0.30. Resolves 5n.
- **E7 — N parallel agents.** ~$1.00 (toy); see §6 Phase 1 E9/E17 for cap-setting. Resolves 5b.
- **E8 — sub-agent that writes a file then reports success.** ~$0.30. Verify result file is on disk by the time `tool_result` returns. Resolves 5o.

Total cheap pre-impl budget: ~$2; full E13–E17 decisives add ~$5–$8.

---

## 9. Failure Modes And Handling

### Dispatcher emits marker before sub-agent writes result file

`StageMarkerProcessor._pending` retains the marker. Retry on every subsequent `process_text` and once at `finish()`. If still missing, `command.json.stage_controller.completed: false`; phase recovery classifies the attempt. (Already implemented from streaming plan.)

### Sub-agent silently succeeds without writing result file

`tool_result` returns success → dispatcher synthesizes `STAGE_COMPLETE` → marker arrives → file is missing → `pending` → still missing at `finish()` → controller records `failure_kind: "stage_result_missing"` → human_gate (no auto-retry).

This is the strongest argument for **E8** before shipping: confirm the sub-agent's `Write` is durable by the time the dispatcher sees `tool_result`.

### Dispatcher hallucinates a marker for a unit it didn't dispatch

`_validate_marker.unknown_stage` → `MarkerDecision(outcome="rejected_unknown_stage")`, `command.json.stage_controller.rejected_unknown_stage++`. No side effects. (Already in streaming plan.)

### Three parallel sub-agents fail simultaneously

Three `STAGE_FAILED` markers in three quick succession in the dispatcher's stream. Each one is processed in order on the main thread (controller's threading model). Phase result records all three failures. Phase recovery classifies on aggregate.

### Dispatcher hits its own token limit before all units finish

Final `result` frame may show `subtype: "max_tokens"` or similar. Treat as `failure_kind: "dispatcher_token_exhausted"`. `failure_retry_class` = transient if any units haven't been claimed; human_gate if all started. Add to failure taxonomy.

### Plugin agent resolution fails (E6 returns ❌)

Fallback: dispatcher inlines the full role spec from the agent's `*.md` file as the sub-agent prompt prefix. Prompt size grows by ~2 KB per delegation. No correctness loss.

### Cost overrun mid-phase

Today's `--max-failed-attempt-cost-usd` is per attempt of one session. Fan-out runs N sub-agents whose costs aggregate into the parent session's `total_cost_usd` (E3 confirmed: $0.346 in the parent's `result` frame for 2-Task run). So existing budget guard already covers fan-out.

### Race: controller writes phase result while dispatcher still emitting markers

The dispatcher emits its final `STAGE_COMPLETE` markers, the `result` frame closes the stream, *then* `_run_real_claude` returns and the controller calls `processor.finish()` and writes the phase result. No race — the order is enforced by stream closure.

### Dispatcher launches without `Agent` in allowlist

If `phase_sessions_mode == "fanout"` and neither bypass nor an `Agent`-inclusive allowlist is in the constructed argv → fail-fast at preflight with `failure_kind: "dispatcher_missing_agent_tool"` (Decision 9 / Phase 5 step 7).

### `STAGE_NEEDS_CONTEXT` exhausts retry budget

After 3 cycles of `STAGE_NEEDS_CONTEXT` for the same unit (each with augmented context, fresh sub-agent), controller transitions unit BEADS to `blocked` and emits a `human_gate` event. Decision 12 / Phase 6.5.

### `PARTIAL_SUCCESS` phase result

Mixed adopted/blocked stages within one phase produce a `PARTIAL_SUCCESS` terminal state (Decision 6). Preserved as a legitimate outcome, not an error: phase result records both the adopted stage IDs and the blocked stage IDs with their `failure_kind`s.

---

## 10. Done Definition

A `swarm do --phase-sessions=fanout` run against the ECC pattern adoption plan (3 phases, 3 work units per phase) produces:

- 9 child BEADS issues, all closed.
- 9 worktrees with commits, each containing one work unit's diff.
- 9 `stage_adopted` events in the run-event timeline, with timestamps strictly preceding the phase exit timestamps.
- A phase result per phase with `completed_work_units` populated by the controller.
- Review evidence (spec-review, code-review) per work unit if those role types are listed in the prepared plan.
- No operator commands invoked between `swarm do` start and exit.
- Total cost within budget set by `--max-failed-attempt-cost-usd` × phase count.

A second run with one work unit's sub-agent prompt deliberately set to fail (e.g., `Use Bash to run "exit 7"`) produces:

- That unit's BEADS in `blocked` state.
- `STAGE_FAILED` marker + `failure_kind` in `command.json.stage_controller`.
- Other units in the same phase still adopted.
- Phase recovery classifies the attempt and either re-dispatches transient or escalates human_gate per existing rules.

### Additional gates

- Dispatcher launches with documented permission posture (Decision 1) AND the launch contract is recorded in command metadata (`launch_contract: {posture, argv, recorded_at}`) verifiable post-hoc.
- Status protocol winner from CB-1 round-trips through ledger (Decision 15).
- Tool name `Agent` used throughout; `Task` retained only as parser alias (Decision 9); `_effective_permissions_check()` accepts `Agent` under fanout mode.
- Every `StageInvocation` carries a resolved `work_unit_id` (Decision 13) or an explicit `None` for aggregator stages; preflight rejects ambiguous cases.
- Per-unit worktree adoption (CB-2 winner) commits and merges sub-agent writes back to the phase workspace; resume after crash between marker and merge is idempotent.
- Sub-agent prompts contain Bash-cwd discipline (Decision 14) verified by `test_subagent_bash_cwd_persistence`.

---

## 11. Files Touched

In recommended order:

| Phase | File | Change |
| --- | --- | --- |
| 0 | `swarm-do/py/swarm_do/pipeline/tests/test_phase_pump.py` (new) | 9 streaming-plan acceptance cases |
| 0 | `swarm-do/py/swarm_do/pipeline/session_capabilities.py` | verify `--help` probe |
| 0.5 | (no code; smoke test) | dispatcher launch-contract validation |
| 1 | (no code; experiments E6–E12 cheap; E13–E17 decisive) | resolution + concurrency + max-turns smoke tests + research-driven decisives |
| 2 | `swarm-do/py/swarm_do/pipeline/stage_invocation.py` | extend `StageInvocation` with `subagent_type`, `worktree_path`, `bead_id`, `allowed_files`, `acceptance_criteria`, `work_unit_id`; rewrite `render_orchestrator_brief()`; mode-gate; four-status grammar; Bash-cwd discipline string |
| 2 | `swarm-do/role-specs/agent-dispatcher.md` | replace `Task` with `Agent`; add four-status marker contract |
| 3 | `swarm-do/py/swarm_do/pipeline/phase_artifact_contract.py:79` | mode-aware `completed_work_units` rule |
| 4 | `swarm-do/py/swarm_do/pipeline/phase_pump.py` `_prepare_stage_controller()` | wire `materialize_unit_execution_worktree()`; atomic rollback; collision check |
| 4 | `swarm-do/py/swarm_do/pipeline/execution_worktree.py` | (no edit; verify rollback wrapper interface) |
| 4 | `swarm-do/py/swarm_do/pipeline/phase_beads.py` | (verify) idempotent `create_stage_child` |
| 4 | `swarm-do/py/swarm_do/pipeline/stage_marker_processor.py` (CB-2 variant A) **or** new `unit_session_adopter.py` (CB-2 variant B) | per-unit `commit_stage_artifacts()` + `merge_unit_execution_worktree()`; resume idempotency |
| 5 | `swarm-do/role-specs/agent-dispatcher.md` | source-of-truth: `Task` → `Agent`; allowed-tools; marker contract |
| 5 | `swarm-do/agents/agent-dispatcher.md` | regenerated from role spec |
| 5 | `swarm-do/permissions/dispatcher.json` | regenerated; `Agent(<allowed types>)` |
| 5 | `swarm-do/py/swarm_do/pipeline/orchestrator_stream.py` `parse_transcript_task_invocations()` | recognize both `Task` and `Agent` |
| 5 | preflight / harness `_effective_permissions_check()` | accept `Agent` (and `Task` legacy alias) under fanout mode |
| 5 | `swarm-do/py/swarm_do/pipeline/phase_pump.py` (argv builder) | branch on mode; emit bypass or allowlist-superset; record `launch_contract` metadata |
| 5 | synthetic transcript fixtures + capability probes | sweep hardcoded `Task` |
| 5 | wherever writer-settings JSON is composed | defensive `Agent`-in-allowlist assertion |
| 6 | `swarm-do/py/swarm_do/pipeline/phase_recovery.py` | per-unit failure classification + mco taxonomy |
| 6 | `swarm-do/py/swarm_do/pipeline/phase_autopilot_policy.py` | per-unit retry accounting |
| 6 | `swarm-do/py/swarm_do/pipeline/stage_controller.py` | `PARTIAL_SUCCESS` terminal state |
| 6.5 | `swarm-do/py/swarm_do/pipeline/phase_recovery.py` | fresh-reviewer rule on retry; 3-cycle cap |
| 7 | `swarm-do/py/swarm_do/pipeline/tests/test_dispatcher_fanout.py` (new) | acceptance suite (incl. four-status, alias, rollback) |
| 7 | `swarm-do/py/swarm_do/pipeline/tests/fixtures/claude_stream/` | fan-out fixtures |
| - | `swarm-do/py/swarm_do/pipeline/cli.py:1209 _phase_sessions_mode` | add `"fanout"` choice |
| - | `swarm-do/py/swarm_do/pipeline/cli.py:1286 _dispatch_with_phase_sessions` | branch on mode |
| - | `swarm-do/docs/failure-taxonomy.md` | mco taxonomy + `PARTIAL_SUCCESS` + new dispatcher kinds (`sub_agent_error`, `dispatcher_missing_agent_tool`, `dispatcher_token_exhausted`, `stage_result_missing`) |

Re-read on entry to a new session:

- This file (top to bottom).
- `phase-session-live-stage-marker-streaming-plan.md` §Coordination, §Verified Facts.
- `research/swarmdaddy-autonomous-fanout-architecture-2026-05-03.md` §3 The Bones Are Already There.
- `swarm-do/role-specs/agent-dispatcher.md` (full).
- `swarm-do/py/swarm_do/pipeline/stage_controller.py` (verify outcomes match this plan).

---

## 12. Competitive Builds

Two design forks are genuinely 50/50 after research and warrant parallel implementations judged by measurement. The other two candidates raised in review (permission posture, agent resolution) will be settled by E13 and E6/E10/E11 respectively — a competitive build there is wasted slots.

### CB-1 — Marker grammar protocol

Resolves Decision 15.

- **Variant A — Token expansion.** Implement `STAGE_DONE_WITH_CONCERNS` and `STAGE_NEEDS_CONTEXT` as first-class marker tokens. Touch parser, ledger enum, stage-result schema, phase-result mapping, retry policy, JSON schemas.
- **Variant B — Binary + structured.** Keep parser at `STAGE_COMPLETE`/`STAGE_FAILED`. Add `status: done|done_with_concerns|blocked|needs_context` to result-artifact JSON. Controller reads artifact post-marker and routes off `status`.

**Judging criteria:** code surface touched (LOC + files), schema-migration cost, parse-failure modes on malformed dispatcher output, controller-side decision latency (marker-time vs artifact-read-time), forward-compatibility (can A be promoted from B later? trivially yes — that's a tiebreaker for B).

**Prior:** B is favored unless A demonstrates materially better signal-to-noise on real dispatcher transcripts in E15.

### CB-2 — Unit-worktree adoption layer

Resolves Phase 4 step 6.

- **Variant A — Inside `StageMarkerProcessor`.** Extend the existing processor to read `worktree_path` and route `commit_stage_artifacts()` / `merge_unit_execution_worktree()` from there.
- **Variant B — Separate `UnitSessionAdopter`.** New module owns per-unit adoption, runs after the marker, leaves `StageMarkerProcessor` focused on phase-level stages.

**Judging criteria:** test-isolation surface, blast radius if the adopter has a bug (does a unit-adoption bug break phase-level stages?), code locality (one place to edit vs two), conformance to existing pipeline boundaries.

**Prior:** B is favored on blast-radius grounds — a separate adopter contains failures to per-unit stages — but A is simpler if the locality argument holds up under E14.

### Build-and-judge protocol

Run E13–E17 first (cheap signal), then implement both variants behind a `phase_sessions_adoption` / `phase_sessions_status_protocol` config flag, run the same E14/E15 suites against each, and pick. Synthesize via `agent-code-synthesizer` only at function/method level if cherry-picking is genuinely useful — otherwise pick the winner whole.

---

## 13. Recommended Work Order

1. **Phase 0** — close streaming-plan gaps (test_phase_pump.py + capability probe verify + dogfood). 1–2 days.
2. **Phase 0.5** — dispatcher launch-contract validation (blocker; settles Decision 1 in practice).
3. **Experiments E6–E12** (~$3–$5 budget; resolves `subagent_type` resolution + parallelism cap + `--max-turns` semantics).
4. **Experiments E13–E17** (~$5–$8 budget; resolves Decisions 1, 13–15 and feeds CB-1, CB-2).
5. **Phase 5** — Agent tool migration: role spec → regenerate → preflight → launch-contract argv. Land before Phase 2 so the brief generator targets the renamed surface.
6. **Phase 2** — extend `stage_invocation.py` with `work_unit_id` + Bash-cwd discipline + status protocol from CB-1 winner; mode-gated.
7. **Phase 3** — artifact contract relaxation.
8. **Phase 4 with CB-2 competitive build** — wire worktree helper; atomic rollback; both adoption variants behind a flag; pick winner via E14 evidence.
9. **Phase 7** — tests in parallel with 5–8.
10. **Phase 8 stage 1** — tiny dogfood; explicitly assert recorded `launch_contract` metadata.
11. **Phase 6 + 6.5** — failure taxonomy + fresh-reviewer anti-anchoring rule.
12. **Phase 8 stages 2–3** — realistic plan + ECC eval comparison.
13. Deprecate `auto` mode behind a flag; eventual removal.

### Build-order rationale (what blocks what)

- **Phase 0 → Phase 0.5 → E6–E12 → E13–E17.** Streaming-plan tests must land first so any new behaviour can be CI-verified. Phase 0.5 locks Decision 1 in practice (without it, Phases 2/4/5 cannot pick an argv). E6–E12 close cheap unknowns; E13–E17 are the decisives that feed CB-1/CB-2.
- **E13 blocks Phase 5 step 6 (launch-contract argv).** The argv builder cannot land until the bypass-vs-allowlist A/B is decided, otherwise Phase 5 ships speculative posture code and a defensive assertion that may misfire.
- **E15 blocks CB-1 implementation, which blocks Phase 2 step 2.** The marker-contract section of the brief depends on whether we render four tokens or two markers + structured `status` (Decision 15).
- **E14 blocks CB-2 implementation, which blocks Phase 4 step 6.** Both adoption variants must be implementable before measurement decides.
- **Phase 5 lands before Phase 2** so the brief generator targets the renamed (`Agent`) tool everywhere; otherwise Phase 2 emits prose that later sweep-edits would churn.
- **Phase 4 lands before Phase 8** because dogfood is the first thing that exercises the per-unit worktree adoption end-to-end on a real plan.
- **Phase 6 + 6.5 land after first dogfood.** First-ship retry posture is "rerun the whole phase"; per-unit retry + fresh-reviewer rule are required for production but not for the tiny dogfood.

### Competitive builds — block diagram

```
Phase 0 ─► Phase 0.5 ─► E6–E12 ─┬─► E13 ──────────────────► Phase 5 (argv)
                                  ├─► E14 ─► CB-2 build ───► Phase 4 step 6
                                  ├─► E15 ─► CB-1 build ───► Phase 2 step 2
                                  ├─► E16 (resume) ────────► Phase 4 step 7
                                  └─► E17 (realistic-N) ───► Decision 7 cap
```

---

## 14. Cost Budget

Per dispatcher session, derived from E1/E3:

- Base dispatcher overhead: ~$0.30
- Marginal cost per parallel sub-agent: ~$0.05 (sub-linear)
- 3-unit phase: ~$0.45
- 9-unit run (3 phases × 3 units): ~$1.35

These are floor estimates with simple sub-agents. Real writer/reviewer roles consume more tokens. Plan a 5× buffer: budget $7 per ECC-scale run for the first dogfood, scale down once measurements stabilize.

Pre-implementation experiment budget: ~$2 (E5–E8 cheap probes) + ~$5–$8 (E13–E17 decisives) = **~$7–$10 to settle all open decisions before code lands**.

`--max-failed-attempt-cost-usd` should be set per phase, not per run, in fanout mode. Suggested: $5 per phase ceiling for first ship.

---

## 15. Bottom Line

The dispatcher-fan-out design is viable and the foundation is already in tree (commit `274ab18`). The plan extends `stage_invocation.py`, `stage_sessions.py`, `orchestrator_stream.py`, `phase_pump.py`, and `execution_worktree.py` rather than building parallel orchestration modules.

The single most consequential decision shifts from `subagent_type` resolution (tactical, has fallback) to **dispatcher launch posture** (Decision 1). The CONFIRMED inherit-then-narrow tool inventory rule and CONFIRMED parent-precedence permission rule mean graduated trust per sub-agent role is impossible under a bypassed parent. v1 picks bypass-cascade with eyes open; graduated trust is a v2 hardening pass.

Two genuine design forks remain — **marker grammar protocol** (token expansion vs binary + structured artifact, CB-1) and **unit-worktree adoption layer** (in-`StageMarkerProcessor` vs separate `UnitSessionAdopter`, CB-2). Both are resolved by competitive build judged on E14/E15 evidence rather than chosen up front.

Two gaps from the prior draft are now first-class: **launch-contract argv construction** in `phase_pump.py` (Phase 5 step 6) and **per-unit worktree adoption** through `StageMarkerProcessor` (Phase 4 step 6 + CB-2). Without these, the dispatcher renames `Task` to `Agent` but still launches with the wrong permission posture, and writer sub-agents commit into orphaned worktrees that never merge back.

Remaining work is: close streaming-plan gaps (Phase 0), validate launch contract (Phase 0.5), run E6–E12, run E13–E17 to settle Decisions 1/13–15, extend the existing dispatcher skeleton with `work_unit_id` + Bash-cwd discipline, regenerate the Agent permission/role artifacts and update preflight, build both adoption variants behind a flag and pick on evidence, adopt mco's failure taxonomy, ship the fresh-reviewer anti-anchoring guard, and dogfood.

**Do not start coding before E6–E12 are run and Phases 0 + 0.5 are closed.**
