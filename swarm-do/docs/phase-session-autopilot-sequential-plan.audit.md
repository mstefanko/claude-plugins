# Audit: phase-session-autopilot-sequential-plan.md

Audit target: `/Users/mstefanko/.claude/plugins/marketplaces/mstefanko-plugins/swarm-do/docs/phase-session-autopilot-sequential-plan.md`
Foundation reference: `/Users/mstefanko/.claude/plugins/marketplaces/mstefanko-plugins/swarm-do/docs/phase-session-foundation-plan.md`
Repo: `/Users/mstefanko/.claude/plugins/marketplaces/mstefanko-plugins`
Code path under audit: `swarm-do/py/swarm_do/pipeline/...` (note: foundation plan paths are written `py/swarm_do/...`; the actual prefix is `swarm-do/py/swarm_do/...`).

---

## Summary

- **BLOCKING — naming pick required.** Phase 2 says rename `decisions.md` to `dependency-decisions.md` *or* keep it and add `shared-decisions.md`. The plan literally lists both as alternatives ("Keep `decisions.md` as dependency-local decisions or replace it with clearer names"). The writer cannot proceed without a single chosen scheme; downstream tests, fixture goldens, and prompt rendering all hard-code these paths.
- **BLOCKING — promotion mechanism for `shared-decisions.md` is undefined.** The plan adds the file but does not say what writes it, what schema/format it uses, or which CLI/run event records the promotion. There is no controller process today that could "promote" anything; `context_bundle.py` only reads handoffs.
- **BLOCKING — Phase 1 owner is split between two systems with no contract.** "Deterministic and plan-review checks" mixes a Python lint pass in `prepare.py` with the `agent-plan-review` LLM role; the plan does not say which findings each side emits, nor where the `phase_order_dependency_missing` code lives in code (`PLAN_REVIEW_SEVERITIES` is in `prepare.py:78`, but no code enum lists finding `code` values).
- **BLOCKING — Phase 3 Step 5 contradicts Step 1 on shell quoting.** Step 1 contract uses `"$(cat <dispatcher.prompt.md>)"` (a shell command substitution), Step 6 says "no shell interpolation of prompt text." The writer must be told whether the adapter spawns `claude -p` via `subprocess.run([...])` with the prompt as an argv element, or via a shell. These are different code paths.
- **BLOCKING — run-events enum delta missing.** Foundation Phase 2 froze a closed `event_type` enum at `swarm-do/py/swarm_do/schemas/telemetry/run_events.schema.json`. The new plan adds events ("emit run events for every stop reason," "prepare gate emits findings"), but lists zero new enum values. Validation will fail (`schema_ok=false`) the first time the writer emits a new event.
- **GAP — `--init` ordering across phases.** Phase 4 introduces `--init`, but Phase 3 Step 8 documents it. Either Phase 3 must list "uses `--init` from Phase 4" as a dependency, or `--init` must be moved into Phase 3. As-is, a writer doing Phase 3 first will either (a) re-implement `--init` ad hoc or (b) ship docs referencing a flag that does not exist. (The flag *does* already exist at `swarm-do/py/swarm_do/pipeline/cli.py:1802`, which contradicts the plan's framing of `--init` as new work — see Verified Claims.)
- **GAP — Phase 3 Step 7 / Validation Commands are inconsistent.** Step 7 says "Add integration tests" but the Validation Commands at the bottom of the plan do not list a `test_phase_pump_claude_print` module. Either the foundation's Phase 3b name should be reused (`swarm-do/py/swarm_do/pipeline/tests/test_phase_pump.py` already exists, lines 49+ already cover `claude-print` ineligibility), or a new module is needed and must be named.
- **AMBIGUITY — Phase 5 schema strategy is unchosen.** "Add dependency metadata to a new prepared artifact schema version *or* a backward compatible optional field." Migration path for the existing accepted run `data/runs/01KQAC90FK5FNF4JWXMXHHR2AQ/prepared_plan.v1.json` (foundation plan calls this out) depends on the choice.

---

## Per-Phase Findings

### Phase 1 — Prepare-Gate Build-Order Review

**BLOCKING — split ownership.** Plan says "Add deterministic and plan-review checks" but does not partition them. Recommendation: state explicitly which of the seven listed heuristics are deterministic (e.g., "validation command references a file path created in a later phase" — string scan, deterministic) versus LLM-judged (e.g., "broad 'wire up everything' language" — judgment). Today `prepare.py` already calls `validate_plan_review_finding(...)` (`swarm-do/py/swarm_do/pipeline/prepare.py:394`) which expects the LLM-style structured payload `{severity, phase_id, location, reason, citation}` — the writer needs to be told whether `code` is being added to that schema or whether the deterministic side emits a parallel lint-finding shape.

**BLOCKING — `code` field is new.** The plan's example finding has a `code` field (`"code": "phase_order_dependency_missing"`). `validate_plan_review_finding()` (`prepare.py:394-423`) does not accept `code` today; required fields are `{severity, phase_id, location, reason, citation}`. The writer must either (a) extend `validate_plan_review_finding` to allow an optional `code` (specify), (b) place this finding into `lint_findings` (see `prepare.py:692`), which has no `code` schema either, or (c) introduce a new finding category. Pick one and name the storage location.

**GAP — `severity: "advisory"` semantics.** Plan says "Advisory findings are shown in acceptance summaries and block `--prepare --continue`, but not manual acceptance." `PLAN_REVIEW_SEVERITIES = {"blocking", "safe_fix", "advisory"}` (`prepare.py:78`) already exists, but it is unclear how today's `--prepare --continue` blocks on advisory findings. The writer needs the existing predicate (e.g., `_safe_fix_count`, `_severity_counts` at `prepare.py:367-377`) augmented and tested. Specify which function gates `--prepare --continue`.

**GAP — `agent-plan-review` instruction file location.** The role-spec lives at `swarm-do/role-specs/agent-plan-review.md` and the agent doc at `swarm-do/agents/agent-plan-review.md` (and `swarm-do/roles/agent-plan-review/shared.md`). "Instructions explicitly include build-order review" — which of these three files is the writer expected to edit? They have different scopes (role-spec is the front-matter-bearing canonical file; the others may be derived). Pick one and say which.

**SCOPE-CREEP-RISK — seven heuristics.** The plan lists seven distinct build-order patterns. A writer may reasonably try to encode all seven deterministically in `prepare.py`. Recommend explicitly bounding deterministic work to the two or three that are reliably string-detectable (e.g., "phase N validation command references phase N+M file path") and leaving the rest as `agent-plan-review` instructions.

**Acceptance is testable.** The two acceptance bullets ("reversed plan fails," "correct plan passes") are good — but recommend adding a fixture path so the writer knows where to place the bad/good plan markdown.

---

### Phase 2 — Dependency-Scoped Handoffs

**ASSUMPTION (VERIFIED) — `_prior_handoffs` exists.** Confirmed at `swarm-do/py/swarm_do/pipeline/context_bundle.py:213`. Signature: `_prior_handoffs(base, run_id, prepared, phase_index) -> list[dict]`. It currently iterates `prepared["phase_map"]` for `idx < phase_index` (matches the plan's "all earlier phases" claim).

**ASSUMPTION (REFUTED) — "decisions.md aggregates from all earlier handoffs."** The plan implies `decisions.md` today aggregates broadly. Verified: `_decisions_markdown` (`context_bundle.py:259-265`) flattens `item["decisions"]` from each prior handoff into a single bulleted list with no per-source attribution. So the plan's framing is correct that scoping today is "all earlier" — but the writer should know the file has no structure beyond a flat list, which affects how `dependency-decisions.md` vs `shared-decisions.md` will be split.

**BLOCKING — naming choice.** Plan text:

> Keep `decisions.md` as dependency-local decisions or replace it with clearer names: `dependency-decisions.md`, `shared-decisions.md`.

This is two paths: (A) keep `decisions.md` (now scoped) + add `shared-decisions.md`, or (B) rename to `dependency-decisions.md` + add `shared-decisions.md`. Existing tests at `swarm-do/py/swarm_do/pipeline/tests/test_context_bundle.py` will hard-code the path. Pick one. Recommendation: (A) — minimizes churn, keeps backward compatibility for any caller reading `context/<phase>/decisions.md`.

**BLOCKING — `shared-decisions.md` source-of-truth.** Plan says "controller-promoted" but defines no:
1. Promotion CLI command (no entry in foundation Phase 2 CLI Surface).
2. Schema for what counts as a "shared" decision.
3. Storage location (per-run? per-repo?).
4. Run event for the promotion.

A writer reading this will invent something. Specify or defer to a follow-up phase.

**GAP — handoff struct field assumed.** `_prior_handoffs` returns dicts; the plan's new logic must read `depends_on_phase_ids` from phase-session state. Confirm whether the writer must:
- Load `phase_sessions.v1.json` inside `_prior_handoffs` (currently only reads handoff files from `data/runs/<run-id>/phase_handoffs/<phase-id>/`), or
- Have `render_context_bundle` resolve dependencies first and pass `dependency_phase_ids` into `_prior_handoffs` as a new parameter (cleaner — recommended).

**Acceptance is weak.** "Handoff rendering uses explicit dependencies" — not testable. Recommend: "Given a 3-phase plan with `phase_3.depends_on_phase_ids = ['1']`, the rendered `previous-handoff.md` for phase 3 contains content from phase 1 only and not phase 2."

---

### Phase 3 — claude-print launcher (8 sub-steps)

**Step 1 — Define The Launcher Contract**

**BLOCKING — shell vs argv contradiction.** Step 1 example:

```bash
claude -p \
  --name "swarmdaddy-<run-id>-<phase-id>" \
  --output-format json \
  ...
  "$(cat <dispatcher.prompt.md>)"
```

Step 6 says: "no shell interpolation of prompt text." `"$(cat …)"` *is* shell interpolation. The writer must be told: the adapter calls `subprocess.run([claude_path, "-p", "--name", session, ..., prompt_text], ...)` with the prompt loaded into Python (via `Path.read_text`), not via shell. Update Step 1 to show the argv form and remove `$(...)`.

**GAP — `--name` flag.** Step 1 uses `--name`; Step 5 uses "session name `swarmdaddy-<run-id>-<phase-id>`" but does not say which flag carries it. Verify that `claude -p` accepts `--name` (the existing `_claude_print_capability` at `session_capabilities.py:102-138` does not probe for it). If `--name` is not a real flag, the writer will spin or invent. Run `claude -p --help` and document.

**GAP — `--permission-mode <mode>` value.** Plan says `<mode>` but does not say which (`acceptEdits`? `default`? `bypassPermissions`?). Pick one for the v1 launcher and justify.

**Step 2 — Capture Real Fixtures**

**BLOCKING — no documented capture procedure.** Foundation Phase 0 created `swarm-do/py/swarm_do/pipeline/tests/fixtures/claude_print/README.md` but `_claude_print_capability` blocks until that directory has `*.json` files (`session_capabilities.py:112-117`). The new plan says "tiny accepted prepared run for fixture capture," but the capability blocks `claude-print` runs in the pump (`phase_pump.py` lines reporting `phase_pump_launcher_ineligible`). So you cannot capture a fixture *through* the pump until the fixture exists. Bootstrapping problem.

Recommendation: write a one-off harness script (`swarm-do/bin/capture-claude-print-fixture` or similar) that calls `claude -p` directly outside the pump and writes the JSON into the fixtures dir. Specify this in the plan. Without it, the writer will either disable the capability check temporarily (regression risk) or invent the script ad hoc.

**GAP — fixture redaction policy.** Real Claude output may contain prompt content. Specify whether fixtures store raw transcripts or scrubbed payloads, and which fields are redacted.

**Step 3 — Implement Parser Tests**

**BLOCKING — pick the parser.** Plan says: "extend `session_capabilities.parse_claude_print_json()` OR add a dedicated parser." The function exists (`session_capabilities.py:74-83`) and currently just validates that the outer text is a JSON object. The new behavior wants to (a) detect status, (b) locate the result/handoff JSON files. Recommendation: keep `parse_claude_print_json` minimal (it is exported in `__all__` and may have callers), and add a new function `extract_claude_print_artifacts(payload) -> {status, result_path, handoff_path, errors}` in the same module.

**Step 4 — Strengthen Capability Probe**

**ASSUMPTION (VERIFIED).** `_claude_print_capability` exists at `session_capabilities.py:102-138`. Currently probes `shutil.which("claude")`, fixture dir presence, and (when `live=True`) `claude --version`. The plan adds a `--live` probe — `--live` already exists end-to-end: `cli.py` exposes it on `sessions doctor` (foundation Phase 0), `doctor_report(live=...)` accepts it (`session_capabilities.py:1`), and the test suite has `test_session_capabilities.py`. Writer should not invent `--live`.

**GAP — what new probe behavior.** Plan does not say what additional probe data to collect beyond what exists. Today's probe records `{claude_path, version_exit_code, version_stdout, version_stderr, fixture_dir, fixture_count, spend_required}`. If "strengthen" means probe `claude -p --output-format json` round-trip, say so.

**Step 5 — Implement The Adapter**

**ASSUMPTION (VERIFIED) — `ENABLED_LAUNCHERS` exists.** `swarm-do/py/swarm_do/pipeline/phase_pump.py:31`: `ENABLED_LAUNCHERS = {"manual", "fake-test"}`. Adding `"claude-print"` to that set is the right hook.

**BLOCKING — eleven-step adapter list under-specified.** The 11 numbered steps describe the loop but not:
- How the result and handoff JSON files are *produced* by the child Claude. The dispatcher prompt must instruct Claude to write them at known paths. The plan does not say whether (a) Claude writes them via Write tool to paths embedded in the prompt, or (b) Claude prints them inline as JSON and the adapter writes them. Big difference: (a) requires Write permission and the dispatcher must inject the paths; (b) does not require Write but enlarges the JSON payload.
- Step 7 says "locate the result JSON file" — at what path? `phase_result_path(run_id, phase_id, attempt)` already exists in `phase_sessions.py`. Specify that it is the contract.

**GAP — error-path stop reasons.** Step 11 lists six stop reasons. Foundation enum (above) does not include "parse_failure" or "result_validation_failure" as separate run events. Either reuse `phase_session_failed` with a `reason` field or extend the enum.

**Step 6 — Process and Timeout Controls**

**ASSUMPTION (VERIFIED).** `lease_policy.refresh_interval_seconds = 300` (`phase_sessions.py:56`). The plan's "running TTL refresh interval" maps to that. The writer should call `phase_sessions.refresh_phase()` (foundation lists it) on that interval.

**BLOCKING — `subprocess timeout slightly below running lease TTL`.** Define the relationship. `running_ttl_seconds = 14400` (4h). "Slightly below" is not a number. Recommend: `subprocess timeout = running_ttl_seconds - refresh_interval_seconds * 2` (i.e., 13800s) or pull from a new `lease_policy.subprocess_timeout_seconds`. Pick one and put it in `DEFAULT_LEASE_POLICY` in `phase_sessions.py:53-57`.

**Step 7 — Integration Tests**

**GAP — module name.** Foundation Phase 3b mentioned `test_phase_pump_claude_print.py` (per the audit prompt). Today there is only `test_phase_pump.py` which already covers `claude-print` *ineligibility* (`test_phase_pump.py:49-64`). Pick: extend `test_phase_pump.py` (recommended) or add a dedicated module. If dedicated, add it to the Validation Commands list.

**Step 8 — Document Operator Flow**

**GAP — `--init` cross-phase reference.** As stated in Summary. Either move `--init` into Phase 3, or have Phase 3 declare a dependency on Phase 4. Note that `--init` *already exists* at `cli.py:1802` (`p.add_argument("--init", action="store_true", ...)`), so the plan is overstating "new work" — verify and remove that misclassification from Phase 4.

**Phase 3 Acceptance**

The four acceptance bullets are testable. Good. Recommend adding: "When the captured fixture is replayed via an injected runner, the pump produces a `phase_result.v1` and `phase_handoff.v1` that pass schema validation."

---

### Phase 4 — Sequential Autopilot UX

**ASSUMPTION (REFUTED) — `--init` is new.** Already exists at `cli.py:1802`. The phase needs to be reframed as "document and wire `--init` consistently," not "add."

**ASSUMPTION (PARTIAL) — `phase_status()` returns `failed` ambiguously.** The plan says: "Improve `phase_status()` so `failed` is reported as a blocking terminal state, not an ambiguous `waiting` state." Verified `phase_status` is exported from `phase_sessions.py` and used at `phase_pump.py:75-86`, returning at least `not_initialized` with a `recommended_command`. The full state set was not enumerated in this audit — the writer must read `phase_sessions.py` to know which states currently exist. Recommendation: have the plan list the *current* return values and the *target* return values side-by-side. Otherwise the writer cannot know what "improve" means.

**GAP — "next actionable command for every state" structure.** The plan lists 8 states. It does not say whether the mapping lives:
- As a `dict[str, str]` in `phase_sessions.py`,
- As a method `phase_status_recommended_command(state)`,
- As CLI-side formatting in `cli.py`.

Today `phase_status` already returns `recommended_command` for `not_initialized` (`phase_pump.py:80`). Generalize that field. Pick a home and specify.

**BLOCKING — run-events for stop reasons.** "Emit run events for every stop reason" — Phase 3 already emits `phase_pump_stopped` with `details.status` for each reason. Is the plan asking for *new* event types or for the existing event to gain coverage? If new types, list the enum additions. If existing, say "ensure every code path that returns from `pump_phases` emits `phase_pump_stopped` first" and add a test.

**Acceptance is weak.**

> A user can start an accepted run once and watch it advance phase by phase.

Not testable. Recommendation: "Given a 3-phase fixture with `--launcher fake-test --max-phases all --init`, `pump_phases` returns `status='complete'` with three entries in `completed_phases` and emits exactly three `phase_session_completed` events."

---

### Phase 5 — Explicit Phase Dependency Metadata

**BLOCKING — schema strategy.** Plan: "Add … to a new prepared artifact schema version OR a backward compatible optional field." The schema is at `swarm-do/py/swarm_do/schemas/prepared_plan.schema.json` and uses `"schema_version": {"type": "integer", "enum": [1]}` with `"additionalProperties": false` on `phase_map` items. So adding `depends_on_phase_ids` requires either:
- Adding the field to `phase_map.items.properties` (still `enum: [1]`) — but `additionalProperties: false` means *unknown* fields fail; *new declared* fields are fine. So this is a non-breaking option as long as existing artifacts (which lack the field) still validate (they will, since the field is not added to `required`).
- Bumping `schema_version` to `2` and rejecting v1 reads at the prepare layer.

Recommendation: option 1 (add as optional field, no version bump). The migration story for `data/runs/01KQAC90FK5FNF4JWXMXHHR2AQ/prepared_plan.v1.json` (foundation plan) becomes: existing artifacts have no field; resolver applies the previous-phase-only fallback that already exists in `_prior_handoffs`. State this explicitly.

**AMBIGUITY — "dependencies on later phases unless explicitly supported by a reordered plan."** Two readings:
1. Reordering is allowed: the prepared artifact may list phases out of execution order, and `depends_on_phase_ids` defines true order.
2. Reordering is *not* allowed in v1: the array order *is* the execution order, and dependencies must point earlier in the array.

Foundation plan's "Phase Identity And Dependency Model" pins option 2: `phase_map[i] depends on phase_map[i-1]`. The new plan should say "v1 preserves array-order execution; reordering is deferred." Without this clarification a writer will introduce out-of-order execution as a bonus feature.

**GAP — validation function location.** Plan lists 5 validation rules (unknown ids, self-deps, cycles, forward deps, dupes). Where does the validator live? Recommend: `swarm-do/py/swarm_do/pipeline/prepare.py` next to existing `validate_plan_review_finding`, exposed as `validate_phase_dependencies(phase_map) -> list[finding]`, called during prepare. Specify.

**GAP — fail mode.** Are dependency errors `blocking` findings (block acceptance) or schema errors (fail load)? Pick one. Recommendation: blocking findings, so the operator sees them in the standard prepare-gate flow.

**Acceptance.** "Dependency metadata is visible in the prepared artifact" is weak — recommend: "Re-running prepare on a v1 artifact emits `depends_on_phase_ids = [phase_map[i-1].phase_id]` for every phase except `phase_map[0]`, which has `[]`."

---

## Cross-Cutting Findings

**BLOCKING — run-events enum delta.** Foundation Phase 2 froze the enum at `swarm-do/py/swarm_do/schemas/telemetry/run_events.schema.json`. Verified the current enum (per `run_events_schema_full` indexed output) includes:

```
phase_session_initialized, phase_session_claimed, phase_session_started,
phase_session_refreshed, phase_session_completed, phase_session_failed,
phase_session_blocked, phase_session_needs_input, phase_session_lease_expired,
phase_result_recorded, phase_handoff_recorded, phase_context_rendered,
phase_pump_started, phase_pump_stopped, phase_pump_launcher_ineligible,
prepare_started, prepare_safe_fixes_accepted, ..., prepare_accepted, ...
```

The new plan adds at minimum:
- A prepare-gate `phase_order_dependency_missing` finding event (Phase 1) — likely re-uses `prepare_review_findings` but should be confirmed.
- Adapter events: "adapter start, parse result, validation failure, process failure" (Phase 3 Step 6) — none of these enum values exist.
- New stop-reason events (Phase 4) — see above.

Action for writer: list the exact enum additions needed, OR explicitly fold each new signal into `phase_pump_stopped` / `phase_session_failed` with a `details.reason` discriminator and add no new enum values. Pick one.

**GAP — foreground-only vs daemon.** Foundation Phase 6 (daemon) had explicit promotion criteria. The new plan's "no babysitting" framing implies unattended operation. The plan does not say:
1. Does autopilot survive parent-process death? (Today: foreground pump dies with the shell.)
2. Does Phase 3 require the daemon (Foundation Phase 6) to ship first?

Recommendation: state explicitly that v1 autopilot is foreground (operator keeps a terminal/tmux/screen open), and that "no babysitting" means "no per-phase prompts" — not "no shell." If true unattended is the goal, Phase 6 daemon must be a dependency, and the plan's scope grows substantially.

**GAP — Validation Commands list.** The five modules listed are `test_session_capabilities`, `test_context_bundle`, `test_phase_sessions`, `test_phase_pump`, `test_prepare_artifact`. Verified all five exist in `swarm-do/py/swarm_do/pipeline/tests/`. But:
- No mention of `test_resume.py` despite Phase 2 changing handoff scoping (resume reads phase-session state — see foundation Phase 2 DoD).
- No mention of `test_plan_lint.py` despite Phase 1 adding lint rules.
- No mention of `test_plan_prepare_write.py` despite Phase 5 changing the prepared schema and prepare-time defaulting.

Add these three modules to the validation list.

**ASSUMPTION (VERIFIED) — test invocation form.** Per project memory: `cd swarm-do && PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.<module>`. The plan writes `PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.<module>` with no cwd. The writer must `cd swarm-do/` first. Recommend prefacing the Validation Commands block with `cd swarm-do/`.

**GAP — backfill story.** Foundation plan called out an existing accepted run (`data/runs/01KQAC90FK5FNF4JWXMXHHR2AQ/prepared_plan.v1.json`). New plan changes prepared-artifact schema (Phase 5) and handoff scoping (Phase 2). State explicitly whether existing accepted runs:
- Continue to work (preferred — implies optional field + previous-phase fallback in `_prior_handoffs`),
- Are auto-migrated on next access,
- Must be re-prepared.

**SCOPE-CREEP-RISK — "Future — Parallel Phase Execution" section.** Section exists (per indexed output). Make sure the writer does not start sketching parallel scaffolding while implementing Phase 5 dependency metadata. Recommend explicit "v1 single-active-phase invariant must hold; this section is non-binding."

---

## Verified Claims

- `_prior_handoffs` exists at `swarm-do/py/swarm_do/pipeline/context_bundle.py:213`. Iterates `phase_map[idx < phase_index]` (matches plan's "all earlier phases" framing).
- `_decisions_markdown` flattens `item["decisions"]` from each prior handoff into a single bulleted list — `swarm-do/py/swarm_do/pipeline/context_bundle.py:259-265`.
- `_previous_handoff_markdown` at `context_bundle.py:245-256` emits a per-phase section using `summary` and `next_phase_context`.
- `decisions_path = context_dir / "decisions.md"` at `context_bundle.py:61` (the file the new plan proposes renaming).
- `ENABLED_LAUNCHERS = {"manual", "fake-test"}` at `swarm-do/py/swarm_do/pipeline/phase_pump.py:31` (Phase 3 Step 5 hook).
- `parse_claude_print_json` exists at `swarm-do/py/swarm_do/pipeline/session_capabilities.py:74-83`. Currently a thin JSON-object validator, exported in `__all__`.
- `_claude_print_capability` exists at `session_capabilities.py:102-138`. Hard-blocks on `claude_print_fixtures_missing` when `swarm-do/py/swarm_do/pipeline/tests/fixtures/claude_print/*.json` is empty.
- `--live` flag is already wired through `doctor_report(live=...)` at `session_capabilities.py:1` and consumed in `cli.py` (foundation Phase 0).
- `--init` flag already exists at `swarm-do/py/swarm_do/pipeline/cli.py:1802`. Phase 4's framing of `--init` as new is incorrect.
- `pump_phases` already supports `init_if_missing=True` and `max_phases=None` semantics at `swarm-do/py/swarm_do/pipeline/phase_pump.py:44-90`.
- `lease_policy` defaults at `swarm-do/py/swarm_do/pipeline/phase_sessions.py:53-57`: `claim_ttl_seconds=900, running_ttl_seconds=14400, refresh_interval_seconds=300`. Matches foundation plan.
- `PLAN_REVIEW_SEVERITIES = frozenset({"blocking", "safe_fix", "advisory"})` at `swarm-do/py/swarm_do/pipeline/prepare.py:78`. `validate_plan_review_finding` requires `{severity, phase_id, location, reason, citation}` (no `code`) at `prepare.py:394-423`.
- `prepared_plan.schema.json` `phase_map.items` uses `additionalProperties: false` and currently lists `phase_id, title, complexity, kind, content_sha, plan_context_sha, cache_key` as required — `swarm-do/py/swarm_do/schemas/prepared_plan.schema.json` (verified via batch read).
- Run events schema enum at `swarm-do/py/swarm_do/schemas/telemetry/run_events.schema.json` is closed (`enum: [...]`) and includes the foundation phase-session deltas. No autopilot-plan-specific events present.
- `agent-plan-review` role lives at `swarm-do/role-specs/agent-plan-review.md` (canonical) with mirrored content at `swarm-do/agents/agent-plan-review.md` and `swarm-do/roles/agent-plan-review/shared.md`.
- `claude-print` already test-covered for ineligibility-without-claim at `swarm-do/py/swarm_do/pipeline/tests/test_phase_pump.py:49-64` — Phase 3 Step 7 should *extend* this file, not create a new module unless renamed.
- Validation Commands cwd: per project memory, `cd swarm-do && PYTHONPATH=py python3 -m unittest ...`. Plan omits the `cd`.

---

## Status: COMPLETE
