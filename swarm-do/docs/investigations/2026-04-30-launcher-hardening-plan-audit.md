# Audit: Sensitive-Path Launcher Hardening Plan

**Date:** 2026-04-30
**Plan audited:** `swarm-do/docs/sensitive-path-launcher-hardening-plan.md`
**Source investigation:** `swarm-do/docs/investigations/2026-04-30-sensitive-path-write-block.md`
**Method:** analysis-agent pass + senior-developer reflection
**Verdict:** not ready to implement as-written; 2–3 hours of revision away from clean execution

---

## Part 1 — Analysis Agent Findings

### Diagnosis Validation

**Solid.** The investigation's empirical table is the load-bearing artifact, and it directly refutes the three flag-based fixes (`bypassPermissions`, `--dangerously-skip-permissions`, `--add-dir`). Probe C (symlink cwd) succeeded — that's the only positive control, and it's the one the plan bets on. The transcript line-95/96/97 reading explains the empty-result mechanism cleanly: terminal assistant block was a `tool_use` rejected by `tool_use_error`, so the `result` field never captured the prior text.

**One alternative root cause the plan dismisses too fast:** the guard could be inspecting the *resolved canonical path* (i.e. `realpath(cwd)`), not the cwd string. Probe C used a symlink **as the cwd** but Claude Code may be doing `os.path.realpath(os.getcwd())` early, before any tool dispatch — in which case the symlink only worked because of *where the file_path argument resolved*, not because cwd was rewritten. The plan's Open Question #2 acknowledges this but does not block on it. **This is the central technical bet, and it is unverified.** If the guard canonicalizes, Option B fails identically to A — both produce a real path under `~/.claude/` once resolved.

### Structural Fix Risks

1. **Symlink canonicalization defeat** (above). The plan mitigates with prompt rewriting (`file_path` arguments will be the launcher-visible path), but `Write file_path=/tmp/.../launcher-workspaces/.../repo/x` will likely be canonicalized too. The probe in the investigation only tested cwd-spelling — it did *not* test whether passing an absolute symlinked `file_path` to `Write` succeeds. The plan's Phase 2 "live probe" is the place this gets settled, but the plan currently treats the probe as confirmation, not as a go/no-go gate.

2. **Prompt rewriting fragility.** "Replace exact `real_repo_root` spellings" is well-scoped, but:
   - Paths embedded in JSON blobs (e.g. `prepared_plan.v1.json` content quoted into the prompt) may have escaped slashes (`\/`) that won't match.
   - Paths the writer reconstructs at runtime (`pathlib.Path.home() / ".claude" / ...`) cannot be rewritten — only mitigated by prompt-content cues to avoid such reconstruction.
   - The investigation already calls out `context_bundle.py:445`-ish — paths to `previous_handoff_path`, `prior_decisions_path`, etc. The plan inherits this audit responsibility but does not require a `grep` audit checklist.
   - Mitigation present: `assert_prompt_safe` fail-closed assertion. Good.

3. **Rollback switch (`SWARM_CLAUDE_SAFE_CWD=0`)** — claimed safe because the bug repros deterministically without it. That is true *for this exact bug*, but if the fix introduces a regression in the safe-cwd path, the rollback regresses to a known-broken baseline. Acceptable for production debugging only; not a recovery mechanism for users.

### Diagnostics Design Risks

1. **Encoding rule is brittle.** `path.replace("/", "-")` is observed, not specified. The investigation flags the *double-dash for `.`* gotcha (`.claude` → `--claude`), but the plan's Phase 3 step 1 just says `path.replace("/", "-")`. That is wrong by omission — `.` in path components becomes `-` after `/` becomes `-` only because of how `.claude` looks like `/.claude/` → `-.claude-` → ... actually re-reading: the investigation example shows `.claude` produces `--claude` because the segment is `/.claude` (slash-dot-claude) and the slash becomes a dash. So `replace("/", "-")` is sufficient for the literal rule, but the plan should *test against the investigation's exact example string* to verify. The Phase 3 test list does not include the canonical example as a fixture.

2. **Failure mode when encoding changes.** Plan claims `transcript_found=false` and graceful degradation. Acceptable, but the suspicious-launch predicate then falls through to the cheap heuristic — which is fine — *unless* the schema also changed and the cheap heuristic's inputs (`num_turns`, `result`, etc.) shift names. Both layers depend on outer JSON shape. Not fully isolated.

3. **Suspicious-launch predicate calibration.** The conjunctive base (claude-print + rc=0 + no artifacts + parseable JSON) is tight. The disjunctive escalators (`num_turns >= 3`, `total_cost_usd >= 0.10`, no changed files) are loose — `num_turns >= 3` will fire on essentially every claude-print failure. That's probably fine because the conjunctive base already filters most benign cases, but the cost ceiling is per-attempt transcript parse, not zero. Consider raising `num_turns >= 5` to match the cheap fallback for consistency.

4. **Failure-kind separability.** `sensitive_path_tool_denied`, `writer_tool_denied_no_artifacts`, `writer_silent_with_turns` are *not* cleanly separable as defined:
   - `sensitive_path_tool_denied` requires transcript classification of `sensitive_path_blocked`.
   - `writer_tool_denied_no_artifacts` requires transcript classification of `tool_disabled` (or generic tool error).
   - `writer_silent_with_turns` is the no-transcript fallback.
   But the actual failure ("Write exists but is not enabled") matches *both* `tool_disabled` (literal wording) and `sensitive_path_blocked` (semantic cause). The plan should pick one — recommend collapsing to `writer_tool_denied_no_artifacts` with a `tool_error_kind` sub-field, rather than three top-level kinds.

### Phase Ordering

**Mostly correct, two issues:**

1. **Phase 0 → Phase 1 → Phase 2 is wrong order for de-risking.** Phase 2's live probe is the experiment that decides whether the entire plan works. It currently sits *after* the workspace module is built and wired. **The de-risking probe should run before Phase 1.** A 10-minute manual probe (write a file with absolute symlinked `file_path` from a symlinked cwd, confirm Claude actually writes it) settles the central technical bet before 6 phases of code are written.

2. **Phase 4 and Phase 5 can merge.** Phase 4 is "classifier refactor + new failure kinds." Phase 5 is "write diagnostics to disk + recovery markdown." The diagnostics writer is consumed only by the classifier. Splitting them creates two PRs that have to land together to be useful. Merge into one phase with two test files.

3. **Phase 6 (context guard wording) is independent of the rest.** Could land before, after, or in parallel with the workspace fix. Not a blocker either direction.

### Acceptance Criteria

Mostly testable. Two are subjective:

- *"Claude can use Write/Edit against launcher-visible paths"* — only verifiable via live probe, which is a one-off run, not a regression test. Plan should specify exactly which file to write and where to assert it lands.
- *"no `outer_artifacts_missing` hides a tool rejection"* — this is a non-property (absence of a misclassification). Cannot be tested directly without a regression fixture for the original Phase 2 scenario.

The Phase 2 live probe is hand-wavy: "Ask Claude to write a temporary file through the launcher-visible path." Should specify the exact prompt, the exact assertion path, the exact teardown.

### Gaps & Edge Cases

1. **`~/.local/share/swarmdaddy` under `~/.claude` via symlink.** Not addressed. If a user has `~/.local` symlinked under `~/.claude` (unlikely but possible in dotfiles setups), `data_dir` itself is sensitive. **Mitigation:** in `execution_workspace.py`, `realpath` the chosen launcher-workspace path and assert it does *not* resolve under sensitive prefixes. The plan asserts the prompt is safe but does not assert the *workspace dir* is safe.

2. **Concurrent runs hitting the same `<repo-id>/repo` symlink.** The plan validates existing symlinks before reuse but does not lock. Two concurrent pumps for the same repo will race on creation. `os.symlink` is atomic, and the plan validates target equality before reuse, so the worst case is a transient `FileExistsError` on simultaneous creation. **Mitigation:** catch `FileExistsError` and re-validate. Not in plan.

3. **Existing run state migration.** Run `01KQF2CF61YV7SYVREEWRE4GFB` (and any others) is on disk with `outer_artifacts_missing` classification. Plan does not address this. **Recommendation:** explicit non-goal — old runs stay misclassified; the new classifier only applies to new attempts. Add to "Out of Scope" / Non-Goals.

4. **Bash heredoc as canonical write path.** If symlink canonicalization defeats Option B for `Write`/`Edit`, the writer falls back to Bash heredocs (which Phase 1 used successfully). Plan does not test that this fallback still works under the new safe cwd. **Risk:** the plan's "follow-up" to tighten Bash allowlist would *kill* the only working write mechanism. Ordering matters: Bash hardening must come *after* Write/Edit are confirmed working under safe cwd.

5. **`prepared_plan.v1.json` is read by the writer.** If that file contains absolute repo paths, the writer reads them directly (not via the launcher prompt), and prompt rewriting does not protect those reads. Need to verify whether the writer dereferences absolute paths at runtime. Not in plan.

6. **`_run_real_claude` callable shape change.** Phase 2 step 10 acknowledges test-double impact. `test_phase_pump.py:181-185` and `test_provider_review.py:565-595, 676, 1908` (per investigation) all assert on argv shape. This is a non-trivial test refactor; plan understates it.

### Work Breakdown (Recommended Revision)

**Ready as-written:**
- Phase 0 (fixtures) — augment with the canonical investigation example string as a fixture for the encoder.
- Phase 6 (context guard wording) — independent, can land any time.

**Needs clarification before implementation:**
- Phase 1 (workspace module) — pin `repo-id` hash function (recommend `hashlib.sha256(realpath(repo_root).encode()).hexdigest()[:16]`); add realpath-based safety check on the workspace dir itself.
- Phase 2 (wiring) — split into 2a (subprocess `cwd` only, no prompt rewriting) and 2b (prompt rewriting). 2a alone settles the canonicalization question. Also pin: exact live-probe prompt text, exact assertion file path, exact teardown command.
- Phase 3 (parser) — add the canonical example as a fixture; add a test that the `.` → `--` collision in real-world paths roundtrips.
- Phase 4+5 (merge) — one phase, classifier + diagnostics writer.

**Should be downscoped:**
- New failure kinds: collapse three to one (`writer_tool_denied_no_artifacts` with sub-field) plus `writer_silent_with_turns` fallback. Two kinds, not four.

### Highest-Leverage De-Risking Step

**Run this before any code is written:**

```bash
# Probe: does Claude write an absolute /.claude/ path when invoked from a symlinked cwd?
SAFE=/tmp/swarm-do-symlink
REAL=<sensitive-source>/swarm-do
ln -sfn "$REAL" "$SAFE"
cd "$SAFE"
echo "Write $REAL/probe-abs.txt with content \"ok\"." | \
  claude -p --permission-mode bypassPermissions \
    --output-format json --allowedTools Write
ls -la "$REAL/probe-abs.txt"
rm -f "$REAL/probe-abs.txt"
```

**Decision tree:**
- File materialized → Option A is sufficient. The plan's prompt-rewriting work (most of Phase 1, all of `assert_prompt_safe`, all `rewrite_prompt` plumbing) is unnecessary. Cut Phase 1 by ~40%, drop Phase 6's overlap with rewriting.
- File denied → Option B as planned. Proceed.
- File denied even with launcher-visible `file_path` (i.e. when the prompt asks for `$SAFE/probe-abs.txt`) → **Option B fails too.** Need Option C (move source tree out of `~/.claude/`) or accept Bash heredoc as the canonical write path.

Without running this probe, all 7 phases of work are speculative. **This is the single most important thing to do.**

### Code-Review Verdict

**Not approved as-written.** Specific blockers:
1. The central technical bet (symlink defeats sensitive-path guard for `file_path` arguments, not just cwd) is *unverified*. The investigation tested cwd-via-symlink but not absolute-`file_path`-via-symlinked-tree. The plan inherits this gap.
2. Three new failure kinds with overlapping definitions.
3. Phase ordering risks 6 phases of work before the load-bearing experiment.
4. Workspace dir safety check is missing (workspace itself could be sensitive via user dotfile shenanigans).
5. Migration story for existing misclassified runs is silent.

**Approved with these revisions:**
- Run the de-risking probe first; record the result in the plan and gate the structural choice on it.
- Merge Phases 4+5; split Phase 2 into 2a/2b for incremental de-risk.
- Collapse failure kinds to two.
- Add realpath safety check on workspace dir.
- Add explicit non-goal: existing runs are not migrated.
- Pin: `repo-id` hash function, exact probe prompt/assertion, exact transcript-encoding canonical example fixture.

---

## Part 2 — Senior-Developer Reflection

Verified the agent's load-bearing claim against the investigation file. **The central finding holds:** the investigation describes the absolute-`file_path`-via-symlink probe (investigation lines 105–114) but never actually runs it. The empirical table at line 62 only records Probe C with a *relative* `file_path` (`tmp-perm-probe.txt`) inside the symlinked cwd. So the plan is committing 7 phases of code on a probe that was sketched but not executed.

### Ratified

1. **Run the absolute-`file_path` probe before any code.** Single highest-leverage action. The investigation literally has the script ready at lines 105–114; nobody ran it. If `Write file_path=/Users/.../.claude/...` succeeds from a symlinked cwd, the entire prompt-rewriting layer (`rewrite_prompt`, `assert_prompt_safe`, `rewrite_count`, the safety assertions) is dead weight. If it fails, Option B is correct. Either way, the answer changes the design surface materially.

2. **Split Phase 2 into 2a (cwd only) / 2b (prompt rewriting).** Falls out of #1 — 2a is the probe-as-code, 2b is conditional.

3. **Collapse the three new failure kinds.** They all map to the same `BLOCKED_RETRY_POLICY_HUMAN_GATE / deterministic_contract_failure` retry policy per the plan's own classification table. Carrying three labels with overlapping semantics (`tool_disabled` vs `sensitive_path_blocked` — the actual error message *"Write exists but is not enabled"* matches both) is taxonomy debt for no operational benefit. `writer_tool_denied_no_artifacts` with a `tool_error_kind` sub-field, plus `writer_silent_with_turns` as the no-transcript fallback. Two kinds.

4. **Realpath the workspace dir itself.** Cheap, defensive, prevents a footgun.

5. **Migration story for old runs is silent.** Easy fix: explicit non-goal in the doc.

### Pushback

- **`num_turns >= 3` vs `>= 5`** — agent flags this as inconsistency. It's actually intentional asymmetry: the suspicious-launch predicate (with transcript parsing as the consequence) deserves a *lower* bar than the cheap-heuristic fallback (which classifies without evidence). Cost of a transcript parse is a few ms of disk I/O; cost of a wrong classification is a misleading retry decision. The asymmetry is correct.

- **Phase 4+5 merge** — agent recommends merging. Disagree. Phase 4 is logic-only and unit-testable in isolation; Phase 5 is filesystem effects and operator-facing artifacts. If Phase 5 ships broken, you can revert it without touching the classifier. Two reviewable PRs > one large one.

- **`prepared_plan.v1.json` runtime-deref concern** — agent flags this as a gap. Looking at the launcher contract (the plan keeps the artifact contract appended last in `phase_pump.py`), the writer is given paths through the prompt; it doesn't independently re-derive from JSON unless the prompt instructs it. Worth a quick `grep` to confirm, but probably a non-issue.

### Additions the agent missed

- **Telemetry continuity.** When the safe-cwd path lands, downstream tooling that grep'd `outer_artifacts_missing` (dashboards, beads notes, Slack alerts) will silently lose visibility into a class it used to catch. The plan should add an explicit deprecation note: "queries on `outer_artifacts_missing` should add `OR failure_kind IN (writer_tool_denied_no_artifacts, writer_silent_with_turns)` for at least one release."

- **Test for the rollback path.** Plan adds `SWARM_CLAUDE_SAFE_CWD=0` but doesn't list a test asserting the fallback actually works. Easy to break by accident.

- **Bash-heredoc allowlist follow-up should be explicitly gated** on safe-cwd being verified working. The plan's Follow-Up Work bullet mentions tightening Bash allowlist; without ordering, that work could land first and remove the only escape hatch we have if Option B fails.

### Verdict

The plan as-written is **not ready to implement**, but is **2–3 hours of revision away from being ready**: run the probe, record the result, decide A vs B based on data not inference, collapse the failure kinds, add the workspace-dir realpath check, and pin the migration non-goal. Then it's a clean execution.

The pattern here — a careful investigation that stops one probe short of the load-bearing experiment, and a plan that inherits the gap — is a classic "execution-ready on the surface, uninstrumented at the core" failure mode. The plan looks complete (phase structure, fixtures, rollback, acceptance criteria), but its central technical claim is unverified.
