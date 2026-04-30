# Investigation: writers can't Write/Edit inside `~/.claude/`

**Status:** open — Round 1 fix shipped; Round 2 leak vector identified; fix path for Round 2 NOT yet decided.
**Date:** 2026-04-30
**Triggering run:** `01KQF2CF61YV7SYVREEWRE4GFB`, Phase 2 ("Hook Runtime Profiles").
**Failed-phase artifacts:** `~/.local/share/swarmdaddy/runs/01KQF2CF61YV7SYVREEWRE4GFB/`
**Writer session transcripts:**
- Round 1 (original failure): `~/.claude/projects/-Users-mstefanko--claude-plugins-marketplaces-mstefanko-plugins-swarm-do/6c8d27b0-a6e4-4a68-adf6-2a1299d50c75.jsonl`
- Round 2 (post-fix re-attempt): `~/.claude/projects/-Users-mstefanko--claude-plugins-marketplaces-mstefanko-plugins-swarm-do/f8826cd4-a2a5-410b-9d13-61d298a90fa0.jsonl`

---

## TL;DR for the next session

> **2026-04-30 — Round 2 update.** Round 1 fix shipped via commits `3faaf44 Sensitive path` and `79b08e1 Fixing gaps`: a "safe-symlink" execution workspace under `~/.local/share/swarmdaddy/launcher-workspaces/<hash>/repo` that the launcher uses as cwd, plus a full jsonl-parsing failure-kind heuristic in `phase_recovery.py`. **The heuristic is working perfectly** — Phase 2's re-attempt produced `last_failure_kind=writer_tool_denied_no_artifacts` with the exact `<tool_use_error>` string in `last_error`. **The structural fix is incomplete:** Phase 2 still hit the same Write rejection because `pwd` (the very first Bash call in every writer session) returns the canonical real path on macOS, leaking `<sensitive-home>/...` to the model, which then uses that prefix for absolute Write calls. See "Round 2" section at the bottom for the new evidence, three follow-up fix options (R2-1/R2-2/R2-3), and reproducer probes.

- **Root cause confirmed:** Claude Code blocks `Write`/`Edit` (and "sensitive" Bash writes) for any path/cwd inside `~/.claude/`. The block is independent of `--permission-mode`, `--allowedTools`, `--add-dir`, and `--dangerously-skip-permissions`. Empirically refuted three flag-based fixes; only changing the writer's `cwd` (via a symlink outside `~/.claude/`) worked.
- **Why we hit this in production:** the swarmdaddy plugin source tree lives at `~/.claude/plugins/marketplaces/mstefanko-plugins/swarm-do/`, so every writer subprocess is launched with cwd inside the deny zone. The phase_pump launcher hardcodes `--permission-mode dontAsk` (`phase_pump.py:447-451`), and the project already hit the same issue for state writes — `paths.py:14-21` documents the workaround for the *state dir*, but never extended it to *source-tree writes*.
- **Why Phase 1 succeeded but Phase 2 didn't:** identical denial; Phase 1 (61 turns) improvised a `cat > FILE << 'EOF'` Bash heredoc fallback after Write was rejected. Phase 2 (14 turns) gave up after the rejection and ended the turn with empty `result` text, which `_launcher_failure_kind` (`phase_recovery.py:738-761`) classifies as `outer_artifacts_missing` → `deterministic_contract_failure` → blocked.
- **What to research next session:**
  1. Pick between Options A/B/C below for the structural fix (cwd-relocation strategy).
  2. Decide cheap vs full defense-in-depth heuristic in `phase_recovery.py`.
  3. Verify the picked path with a probe and a Phase 2 re-run.

---

## How we got here (Phase 2 failure walkthrough)

1. End-to-end run dispatched. Phase 0 and Phase 1 completed normally.
2. Phase 2 writer launched at 2026-04-30T13:12:18Z via `claude -p --permission-mode dontAsk --output-format json --allowedTools "Bash(bd:*) Bash(git:*) Bash(mkdir:*) Bash(pytest:*) Bash(python3:*) Bash(rg:*) Bash(sed:*) Edit Read Write"` (full argv: `~/.local/share/swarmdaddy/runs/01KQF2CF61YV7SYVREEWRE4GFB/phase_launches/2/attempt-1/command.json`).
3. Writer ran 14 turns / 7986 output tokens / $0.73, ended with `stop_reason: end_turn`, `result: ""`, zero permission_denials. Wrote NO files (`phase_recovery/2/attempt-1.diff-summary.md` shows only Phase 1's artifacts in the baseline diff).
4. Recovery layer: `result == ""` → `extract_claude_print_artifacts` raises *"missing artifact object"* → `_launcher_failure_kind` returns `outer_artifacts_missing` (`phase_recovery.py:756`) → `_retry_stop_decision` maps that + returncode 0 to `BLOCKED_RETRY_POLICY_HUMAN_GATE / deterministic_contract_failure` (`phase_recovery.py:599`). Phase 2 status pinned at `blocked`.
5. Reading the writer transcript turn-by-turn (lines 95–97 of `6c8d27b0-...jsonl`) reveals the smoking gun:
   - Turn 95 (assistant TEXT): `"I have enough context. Let me implement Phase 2…"`
   - Turn 96 (assistant tool_use): `Write file_path=.../swarm-do/hooks/run-with-profile.sh content="#!/usr/bin/env bash …"`
   - Turn 97 (tool_result, is_error=True): `<tool_use_error>Error: No such tool available: Write. Write exists but is not enabled in this context. Use one of the available tools instead.</tool_use_error>`
   - No further assistant text. Session ended. `result` field captures only the last assistant TEXT block, but turn 95's text wasn't the *terminal* assistant message — turn 96's tool_use was — so the `result` field rendered empty.
6. Phase 1's transcript shows the SAME error at one Write attempt (`grep -c '"name":"Write"'` = 1, `grep -c 'is not enabled'` = 1 in `2cc87dd4-...jsonl`), but the Phase 1 model recovered into `cat > FILE << 'PYEOF'` Bash heredocs to write `selftest.py`, `test_selftest.py`, the result.json, the handoff.json, etc. Phase 2 didn't recover.

---

## Original three claims (verbatim, from the senior-dev review of the proposed fix)

> **Claim 1 — bypassPermissions is the right mode: VALID.** The agent ran claude --help and confirmed the choices include bypassPermissions; dontAsk is real too (I was wrong to suspect it was project-invented). Pre-merge sanity probe:
> ```
> cd <sensitive-source>/swarm-do && \
>   echo 'Write ./tmp-perm-probe.txt with content "ok".' | \
>   claude -p --permission-mode bypassPermissions --output-format json --allowedTools Write \
>   2>&1 | tail -20 && ls -la tmp-perm-probe.txt
> ```
> acceptEdits is a worse fit — it auto-accepts the prompt but still runs through the engine that has the ~/.claude/ deny.
>
> **Claim 2 — minimal security delta: VALID.** The Bash heredoc backdoor in Phase 1 already proves the writer has effective arbitrary-write capability under dontAsk. Switching to bypassPermissions just makes it more efficient (one Write call vs. cat-heredoc dance). One side-note from the agent worth booking separately: if you want real least-privilege, tighten the Bash allowlist to forbid >/tee/cat > redirection — but that's orthogonal to this fix.
>
> **Claim 3 — defense-in-depth jsonl parsing: NOT worth doing as I described it. Build a cheap variant instead.**

### Empirical re-verification of Claim 1

The probe in Claim 1 looked sound. Running it (`/tmp/swarm-perm-probe.sh`):

| Probe | Mode/flags | Result |
|---|---|---|
| original | `--permission-mode bypassPermissions --allowedTools Write` | **denied** — `subtype=success is_error=false turns=3 denials=1`; result text: *"The available tools here don't include Write/Edit, and Bash was blocked as a sensitive-file write. I can't create `tmp-perm-probe.txt` in this context — please grant write permission or run the comman[d]…"*; file NOT created. |
| A | `--dangerously-skip-permissions` (no `--permission-mode`) | **denied** — same shape; *"The Write tool isn't enabled in this context, and Bash was denied because the path was flagged as sensitive."* |
| B | `--permission-mode bypassPermissions --add-dir <project>` | **denied** — same shape; *"The Write tool isn't available in this context, and the Bash write was denied as a sensitive-file edit."* |
| C | `--permission-mode bypassPermissions` + cwd via symlink at `/tmp/swarm-do-symlink` → real plugin path | **succeeded** — `turns=5 denials=1`; result text: *"Wrote `tmp-perm-probe.txt` with content "ok"."*; file `-rw-r--r-- 2 bytes` materialised at the resolved plugin path via the symlink. |

**Claim 1 verdict revised: WRONG.** `bypassPermissions` does not bypass the sensitive-path guard. Nor does `--dangerously-skip-permissions`. Nor does `--add-dir`. The guard appears to be a hardcoded Claude Code rule that fires when *the working directory string* contains `/.claude/` (or matches some equivalent prefix); it is not gated by any permission-mode flag we tested.

The analysis agent ran `claude --help`, observed that `bypassPermissions` exists as a value, and inferred semantics from the long-form description of `--dangerously-skip-permissions` ("Bypass all permission checks"). That inference was reasonable but incorrect — "permission checks" and "sensitive-path checks" are separate layers in this CLI version.

### Claim 2 verdict — still valid, but moot

If we ever land a fix that lets the writer use `Write`/`Edit` cleanly, Claim 2's analysis stands: the writer already had effective arbitrary-write power via Bash heredoc under `dontAsk` (P1 had only `rm -rf /tmp/...` denied, while `cat > FILE << 'EOF'` worked freely). Switching modes — or relocating cwd — doesn't materially widen the security boundary.

The agent's side-note about tightening Bash allowlist (forbid `>`/`tee`/`cat >`) is independently worth tracking, but orthogonal to this bug.

### Claim 3 verdict — still useful, but reweighted

The original recommendation was "build the cheap heuristic, defer the full jsonl parser." That recommendation was made under the assumption that the underlying permission bug was a one-shot fix. With the probes above showing that the underlying rule is hardcoded and Claude-Code-version-dependent, the **probability of recurrence** for silent-writer failures with similar tool-rejection patterns is meaningfully higher than first estimated — pushing the marginal value of full jsonl parsing up. See "Defense in depth — re-evaluation" section below.

---

## Why this kept hiding

1. The codebase already documents the `dontAsk` `~/.claude/` auto-deny (`paths.py:14-21`), but framed it as a *state-dir* problem. Source-tree writes were never on anyone's radar because Phase 1 happened to recover via Bash heredoc. The latent bug was masked by model improvisation luck.
2. `_launcher_failure_kind` (`phase_recovery.py:738-761`) classifies *any* `result==""` end_turn as `outer_artifacts_missing`. That tag has well-defined recovery semantics ("contract shape problem; block, don't retry") which were correct for the symptom but wrong for the cause. There's no signal in the recovery output that the failure was actually a tool denial.
3. The launcher captures `--output-format json` only — terminal result, not a stream-json transcript. So unless someone reads the per-session jsonl by hand, tool-rejection errors are invisible to the recovery layer.
4. `permission_denials` in the result.json captures Claude's *permission-mode* denials, not its *sensitive-path* denials. Phase 1 had two `permission_denials` entries (both `rm -rf /tmp/...`), but the Write rejection appears nowhere in that list — it's a `tool_use_error` inside the conversation, not a permissions-system denial.

---

## Possible solutions

### Structural fix (the writer needs to be able to Write/Edit)

Three options, ranked by invasiveness. None of these are decided; the next session should pick.

#### Option A — Set subprocess `cwd` to a symlink outside `~/.claude/`

**Sketch:**
1. At launcher start, ensure a stable symlink exists, e.g. `<data_dir>/repo-cwd` → `REPO_ROOT` (data_dir is `~/.local/share/swarmdaddy/`, already outside `~/.claude/`).
2. In `phase_pump.py`'s subprocess invocation (around `phase_pump.py:447`), pass `cwd=<symlink>` to the `subprocess.Popen` / `subprocess.run` call.
3. Keep `--permission-mode dontAsk` (or switch to `bypassPermissions` — both worked in probe C, since the deciding factor is cwd).

**Risk:** the launcher prompt embeds *absolute* `<sensitive-home>/.../...` paths for context files, prepared plan, work units, the launcher result/handoff target paths, and so on (`context_bundle.py:445`-ish, `phase_pump.py` various). If the writer infers absolute paths from the prompt and uses them in its Write calls, the path string will still contain `/.claude/` and the sensitive-path guard will fire. Unverified — depends on Claude path-check semantics (cwd substring vs file_path substring vs canonicalised path).

**Probe to settle the risk:**
```bash
# Inside symlinked cwd, give the model an absolute ~/.claude/ path to write
ln -sfn <sensitive-source>/swarm-do /tmp/swarm-do-symlink
cd /tmp/swarm-do-symlink
echo 'Write <sensitive-source>/swarm-do/probe-abs.txt content "ok"' \
  | /Applications/cmux.app/Contents/Resources/bin/claude -p --permission-mode bypassPermissions \
    --output-format json --allowedTools Write > /tmp/probeAbs.json
# If the file lands → Option A works as-is.
# If denied → the guard inspects the file_path argument, not just cwd → Option B required.
```

**Probability of success:** moderate. Worth probing before committing.

#### Option B — Cwd relocation **plus** rewrite all REPO_ROOT-derived paths in launcher prompts

Same cwd change as Option A, *and* rewrite every `REPO_ROOT` interpolation in launcher-bound prompts to use the symlink path so the writer never sees a `/.claude/` substring. Concretely:

- `phase_pump.py` — anywhere it formats a path into `dispatcher.launcher.prompt.md`.
- `context_bundle.py` — `previous_handoff_path`, `prior_decisions_path`, `shared_decisions_path`, `prepared_artifact_path`, etc. (state dir is already outside, but also any "Source Artifacts" entries that reference the source tree).
- `_append_claude_print_contract` — result_path / handoff_path lines.
- The Phase Text body itself (rendered from `prepared_plan.v1.json`) — any path columns that show files relative to repo root will need rewriting only if they're absolute; relative is fine.

**Implementation sketch:**
- Introduce `safe_repo_root() -> Path` helper that returns either `REPO_ROOT` (when outside `~/.claude/`) or the launcher-cwd symlink path. Use throughout prompt-assembly code.
- The symlink target is a function of REPO_ROOT, so `safe_repo_root()` and REPO_ROOT only differ in spelling.
- Audit pass: `grep -rn 'REPO_ROOT\|repo_root' py/swarm_do/pipeline/ -l` and visit each callsite to decide which need the safe variant.

**Risk:** miss a callsite. Mitigation: a runtime assertion in the launcher that the assembled prompt does NOT contain the substring `/.claude/` (sanity check before subprocess spawn). If the assertion fires, fail the launch and surface the missed interpolation.

**Probability of success:** high. This is the right scope for a real fix.

**Definition-of-done:**
- `dispatcher.launcher.prompt.md` for any new run contains zero `/.claude/` substrings (covered by an automated check in tests).
- `subprocess` cwd is the symlink for every claude-print launch.
- Phase 2 of run `01KQF2CF61YV7SYVREEWRE4GFB` (or a fresh test run) completes with non-empty result and a written `tmp-perm-probe.txt`-equivalent.
- Tests `swarm_do.pipeline.tests.test_phase_pump`, `test_context_bundle`, and the launcher argv assertion tests still pass with the new shape (some may need updating).

#### Option C — Move the swarm-do source tree out of `~/.claude/`

Long-term posture fix. The plugin marketplace would link/symlink to a canonical source location at e.g. `~/projects/swarm-do/` (or wherever). That eliminates the entire deny-zone class of bugs without touching the launcher.

**Risk:** breaks plugin marketplace conventions; needs a separate decision about how the marketplace and the source tree relate. Out of scope for a same-day fix; could be the right answer in 30 days.

**Probability of success:** very high (it's just a directory move) but high operational and review cost.

### Defense in depth — re-evaluation

The original analysis recommended *cheap heuristic only, defer full parser*. With probe results in hand, I want to re-weigh.

#### Cheap variant (already-recommended)

Inputs already available to `phase_recovery.py`: `result` text, `num_turns`, diff-summary's "Changed Files Since Baseline" list, returncode.

Add a new failure_kind ahead of the existing `outer_artifacts_missing` check, roughly:

```python
# Pseudo-code, inside _launcher_failure_kind:
if (returncode == 0
        and not stdout_result_text
        and num_turns >= SILENT_WITH_TURNS_THRESHOLD  # e.g. 5
        and not diff_changed_files):
    return "writer_silent_with_turns"
```

`writer_silent_with_turns` is then mapped to `BLOCKED_RETRY_POLICY_HUMAN_GATE` like the other deterministic contract failures, with a more diagnostic `last_error` ("writer ran N turns, used $X, wrote zero files, ended turn with empty result — likely a tool denial or prompt confusion").

**Cost:** ~20-30 LOC + a couple of unit tests; no new file dependencies.
**Coupling:** zero new coupling — uses inputs we already produce.
**What it catches:** the entire class of silent-writer failures (this bug, prompt confusion, future tool-disable bugs, mid-run quota cutoffs, hook rejection storms). Diagnostic message is generic.
**What it misses:** specific cause attribution — operator still has to read the jsonl to learn *which* tool was rejected.

#### Full variant (jsonl parsing)

Read `~/.claude/projects/<encoded-cwd>/<session_id>.jsonl` after a writer ends, scan for `tool_use_error` patterns, attach the offending tool name(s) and rejection text to `last_error`, and emit distinct failure_kinds like `tool_disabled_at_runtime` or `sensitive_path_blocked`.

**Implementation sketch:**
- `session_id` is in the launcher's stdout JSON (`launcher_result["stdout"]` already parsed via `parse_claude_print_json`). Extract it.
- Encode the cwd → projects dir name (replace `/` with `-`, handle leading `/`). The encoding rule is observable: `cwd=<sensitive-source>/swarm-do` → `-Users-mstefanko--claude-plugins-marketplaces-mstefanko-plugins-swarm-do`. Note the *double* dash for `.` — needs care.
- Open `~/.claude/projects/<encoded>/<session_id>.jsonl`, stream-parse lines, extract any `tool_use_error` strings from `tool_result` content.
- Attach to recovery markers and a new `failure_kind`.

**Cost:** ~80-150 LOC + unit tests with fixture jsonls + a path-encoding helper that's already implicitly known to Claude Code itself.
**Coupling:** new dependency on Claude Code's transcript schema and project-dir encoding scheme. If Anthropic renames `tool_use_error` → `toolUseError`, or restructures `content`, the parser silently degrades back to "unable to attribute" — failing back to `outer_artifacts_missing` for any case the cheap heuristic also doesn't catch.
**What it catches that cheap doesn't:**
- Specific tool name and rejection string in `last_error` — operator can act without spelunking.
- *Non-terminal* tool rejections (model recovers but with degraded output) — cheap heuristic only fires when result is empty, but the full parser can flag "writer ran 14 turns, hit 3 tool_use_errors, recovered partially, 1 file written" cases. (Unclear whether we care about those — Phase 1 was technically that case and we counted it as a success.)
- Hook-injected rejections, MCP-tool denials, model self-blocking patterns.
**What both miss:**
- Failures where the model produces text but lies about completion (no contract artifacts). That's still `outer_artifacts_missing` and still correctly handled.

**Re-weighing the YAGNI argument:**

Original case for deferring: "this is a one-shot bug; once fixed it won't recur."

After probes: the *underlying mechanism* (sensitive-path guard hardcoded in CLI) is OUTSIDE our control and has zero documented contract. Anthropic could:
- Tighten the rule (more denied paths) → another silent-failure class.
- Loosen the rule (Option A/B fix becomes unnecessary) → no harm done.
- Change the error message format → no impact on cheap heuristic, breaks full parser if it pattern-matches.
- Change the jsonl schema → breaks full parser, no impact on cheap heuristic.

So the recurrence probability for silent-writer-due-to-tool-rejection is non-zero post-fix. The cheap heuristic catches that class without taking on schema risk. The full parser adds *attribution speed* — the diagnostic delta is "operator reads jsonl by hand once" vs "operator reads `last_error` field." That's real value, but bounded.

#### Recommendation for the new session

- **Build cheap heuristic now** — low cost, no coupling, catches the class. ~30 LOC.
- **Pick ONE escalation criterion for the full parser** before deciding to build it. Suggestions:
  - "If we hit 2+ misclassified silent failures in 30 days, build the full parser."
  - "If we ever ship Option A and need to debug whether the sensitive-path guard's behavior changed, build the full parser."
  - "If we add a new launcher backend (codex, GPT-5) where the failure modes are even more obscure, build the parser then."
- The full parser also has an *adjacent* use case worth noting: cost/usage attribution, hook telemetry, debugging prompt-engineering changes. If those independently justify reading jsonls, the parser amortises. Worth checking with whoever owns observability.

---

## Open questions for the new session

1. **Does the sensitive-path guard inspect `cwd`, the `file_path` argument, the resolved canonical path, or all three?** Probe sketch above. Determines whether Option A is viable or Option B is required.
2. **Does Claude Code expose any escape hatch we haven't tested?** Things to look for in `claude --help`: `--no-sensitive-path-check`, `--unsafe-paths`, an env var like `CLAUDE_ALLOW_SENSITIVE_PATHS`, settings.json fields like `permissions.bypassSensitivePathCheck`. Likely none, but worth a careful read.
3. **What is the canonical `~/.claude/projects/<encoded>/` directory name encoding rule?** If the full parser is on the table, we need to derive this deterministically from `cwd`, not infer per-run.
4. **Is `--cwd` a valid flag on `claude -p`?** If so, set it explicitly rather than relying on inherited cwd from the parent process. (Subprocess `cwd=` arg may or may not propagate to where Claude reads it.)
5. **Owner decision: A vs B vs C.** A is fastest if probe in §"Probe to settle the risk" passes. B is the right scope. C is a longer-horizon decision.
6. **Tighten Bash allowlist?** Side-note from original analysis: forbid `>`/`tee`/`cat >`-style redirection in writer Bash. Independent of the structural fix; track separately.

---

## Reproducer & verification commands

### Reproduce the failure (no real model spend)

The blocked Phase 2 state already exists. To re-examine:

```bash
RUN=~/.local/share/swarmdaddy/runs/01KQF2CF61YV7SYVREEWRE4GFB
cat $RUN/phase_recovery/2/attempt-1.recovery.md     # failure_kind, partial_artifacts
cat $RUN/phase_launches/2/attempt-1/stdout.txt      # full launcher result JSON
cat $RUN/phase_launches/2/attempt-1/dispatcher.launcher.prompt.md  # what was sent to writer
# Writer transcript (the smoking-gun source):
ls ~/.claude/projects/-Users-mstefanko--claude-plugins-marketplaces-mstefanko-plugins-swarm-do/6c8d27b0*.jsonl
```

### Confirm sensitive-path block independently of swarmdaddy

`/tmp/swarm-perm-probe.sh` (created during this investigation) contains the original `bypassPermissions` probe. `/tmp/swarm-perm-probe2.sh` adds A/B/C variants (`--dangerously-skip-permissions`, `--add-dir`, cwd-via-symlink). Re-run any of them via:

```bash
bash /tmp/swarm-perm-probe2.sh
```

The expected output for the as-of-2026-04-30 CLI version is the table in the "Empirical re-verification of Claim 1" section above.

### Re-run Phase 2 after a fix

```bash
cd <sensitive-source>/swarm-do

# 1. Tests still green (some assert on argv shape)
PYTHONPATH=py python3 -m unittest swarm_do.pipeline.tests.test_phase_pump

# 2. Clear Phase 2 block on the existing run
bin/swarm phases recover 01KQF2CF61YV7SYVREEWRE4GFB

# 3. Re-dispatch one phase via fresh claude-print session
bin/swarm phases pump 01KQF2CF61YV7SYVREEWRE4GFB --launcher=claude-print --max-phases 1

# 4. Watch the result
bin/swarm phases status 01KQF2CF61YV7SYVREEWRE4GFB
```

If `phases recover` reports a `deterministic_contract_failure` it can't unblock, manual fallback: edit `~/.local/share/swarmdaddy/runs/01KQF2CF61YV7SYVREEWRE4GFB/phase_sessions.v1.json`, set Phase 2's `status` back to `ready`, clear `attempt`, `attempt_history`, `last_failure_kind`, `last_error`, `retry_policy_decision`, `started_at`, `session_name`, `prompt_sha`, `result_path`, `handoff_path`, then run step 3.

---

## Files / line numbers referenced

- Launcher argv: `swarm-do/py/swarm_do/pipeline/phase_pump.py:434-465`
- `--permission-mode dontAsk` literal: `phase_pump.py:447-449`
- Pre-existing `dontAsk` workaround for state dir: `swarm-do/py/swarm_do/pipeline/paths.py:14-23`
- Failure classifier: `swarm-do/py/swarm_do/pipeline/phase_recovery.py:738-761` (`_launcher_failure_kind`)
- Retry/block decision: `phase_recovery.py:592-602` (`_retry_stop_decision`)
- Artifact extraction (raises *"missing artifact object"*): `swarm-do/py/swarm_do/pipeline/session_capabilities.py:89-110` (`extract_claude_print_artifacts`) and `:222-242` (`_find_artifact_object`)
- Allowed-tools helper: `phase_pump.py` near `_allowed_tools_arg` (used at lines 435 + 451)
- Captured fixture launcher (mirror of phase_pump argv shape): `swarm-do/py/swarm_do/pipeline/capture_claude_print_fixture.py:55-70`
- Tests that assert on argv shape (will need updating if argv changes): `swarm-do/py/swarm_do/pipeline/tests/test_phase_pump.py:181-185`, `test_provider_review.py:565-595, 676, 1908`

---

# Round 2 — 2026-04-30 (post-fix)

## What shipped between Round 1 and Round 2

Two commits landed: `3faaf44 Sensitive path` and `79b08e1 Fixing gaps`. Inspection of `phase_launches/2/attempt-1/command.json` after the re-pump shows the new shape:

- **Execution workspace abstraction.** The launcher creates (or reuses) `~/.local/share/swarmdaddy/launcher-workspaces/<hash>/repo` as a symlink to the real plugin path, then uses it as the writer subprocess `cwd`. Recorded in `command.json` as `launcher_cwd`, `launcher_repo_root`, `real_repo_root`, `safe_cwd_enabled: true`, `execution_workspace_mode: "safe-symlink"`.
- **Prompt rewriting.** Launcher prompts are rewritten to use the safe symlink path; the assembled prompt is asserted to contain no `/.claude/` substrings (`assert_prompt_safe`). On the Round 2 re-attempt the assembled prompt indeed contained zero `/.claude/` substrings — the rewrite layer is correct.
- **Full jsonl-parsing heuristic in `phase_recovery.py`.** Not the cheap version we recommended in Round 1's Claim 3 — the *full* version that reads the writer's `~/.claude/projects/<encoded>/<session_id>.jsonl`, scans for `tool_use_error` results, and emits `failure_kind=writer_tool_denied_no_artifacts` with `last_error` carrying the literal rejection string. **In production it worked exactly as advertised.**
- **`--permission-mode` is unchanged** — still `dontAsk`. The argv shape and the rest of the launcher invariants are otherwise the same as before.

## Round 2 re-pump evidence

After resetting Phase 2 (`/tmp/reset-phase2.py`) and refreshing `git_base_sha` (`/tmp/refresh-git-base.py`), `phases pump` dispatched a fresh attempt. Result:

| Field | Value |
|---|---|
| `status` | `blocked` |
| `last_failure_kind` | `writer_tool_denied_no_artifacts` |
| `last_error` | `Write tool_disabled: <tool_use_error>Error: No such tool available: Write. Write exists but is not enabled in this context. Use one of the available tools instead.</tool_use_error>` |
| `retry_policy_decision` | `deterministic_contract_failure` |
| `started_at` / `completed_at` | 2026-04-30T18:09:07Z → 18:10:32Z (~85s) |
| Writer session id | `f8826cd4-a2a5-410b-9d13-61d298a90fa0` |
| `prompt_rewrite_count` | `0` (prompt was already clean — nothing to rewrite) |
| `/.claude/` substrings in launcher prompt | **0** |
| Write tool call's `file_path` arg | `<sensitive-source>/swarm-do/hooks/run-with-profile.sh` |

The model used the canonical real path in its Write call, even though that string never appeared in the prompt it received.

## Root cause for Round 2 — `pwd` leaks the canonical path

The first Bash call in the new Phase 2 transcript:
```
B: pwd && ls -la
R: <sensitive-source>/swarm-do | total 96 ...
```

Once the model has the canonical root, every absolute path it constructs starts with `<sensitive-home>/...`. Write calls trip the sensitive-path guard regardless of the carefully-arranged safe cwd.

**Mechanism:** Python's `subprocess.Popen(cwd=<symlink>)` calls `chdir()`. On macOS, `chdir()` resolves the symlink before exporting `$PWD` into the child env. The shell's `pwd` builtin reads `$PWD` and prints whatever's there — canonical, not symlink. The launcher's safe-symlink workspace correctly sets *cwd*, but unintentionally sets `$PWD` to the canonical path.

**Other leak channels observed in the Round 2 transcript:**
1. `Read` on a directory path returns an `EISDIR` error message that includes the canonical path string.
2. `README.md` contains documentation references to `~/.claude/plugins/cache/.../swarmdaddy/` paths in prose (around README line 700). The model Read README during context-gathering and saw canonical paths in the body.
3. Anything else that resolves symlinks: `pwd -P`, `realpath`, `readlink -f`, `git rev-parse --show-toplevel`, Python `Path.resolve()`, etc. Any one of these called by the model leaks the real path.

The "safe-symlink" workspace fixes the *prompt* surface; it does not seal the *runtime environment*. Multiple independent canonical-path-leak channels exist.

## Round 2 fix options

Numbered for cross-reference. Pick one or combine.

### R2-1 — Plug the `pwd` leak (cheapest, partial)

**Sketch:**
- In `phase_pump.py`'s subprocess invocation, pass `env={**os.environ, "PWD": str(safe_symlink_path)}`.
- With `$PWD` already set in the env, the shell's `pwd` builtin will print `$PWD` (the symlink path) rather than recomputing.
- Add a one-line instruction to the writer prompt scaffolding: *"All file-path arguments must be relative to your current working directory. Do not invoke `pwd -P`, `realpath`, `readlink -f`, `git rev-parse --show-toplevel`, or any command that resolves symlinks; do not concatenate against absolute prefixes you discover at runtime."*

**Cost:** ~10 LOC + a sentence in prompt. Plus a probe to verify the `PWD` env trick works on this shell version (see "Reproducer probes" below).
**Catches:** the `pwd` leak, the most direct vector. Trains the model toward relative paths.
**Misses:** Read-on-directory error leaks, README leaks, anything else that internally resolves symlinks.
**Risk:** the model may ignore the prompt instruction; or hit a different vector (e.g. `git ls-files` resolves to canonical for some operations); or the shell builtin honoring `$PWD` may depend on shell version.

### R2-2 — Path-redaction interposer (most defensive, most invasive)

**Sketch:**
- Add a hook (or launcher-level interposer on stdout) that intercepts Bash and Read tool *results* before they reach the model.
- Rewrite any occurrence of the canonical real path → safe symlink path in the result content.
- Possible mechanisms: PostToolUse hook in writer-settings.json (verify Claude Code's hook contract supports rewriting tool_result payloads); or stream-edit the JSON tool-result frames in the launcher subprocess plumbing.

**Cost:** unclear — depends on whether Claude Code's PostToolUse hook can mutate tool_result content. If hooks can't, this requires custom launcher plumbing that intercepts the streaming JSON frames.
**Catches:** all known leak vectors *that flow through tool results*.
**Misses:** anything where the canonical path arrives via channels the interposer can't intercept (system info, model "knowledge" from training, hook-injected text).
**Risk:** brittle, ties launcher to Claude Code hook contract; could rewrite legitimate occurrences in unexpected ways (e.g. test output that intentionally references canonical paths); ongoing maintenance as Claude Code internals evolve.

### R2-3 — Move the source tree out of `~/.claude/` (structural)

Same as Option C from Round 1. Maintain swarm-do source at e.g. `~/projects/swarm-do/`; have the plugin marketplace symlink/copy from there. With no canonical `/.claude/` path *to* leak, the entire class of bugs disappears.

**Cost:** one-time relocation; plugin marketplace conventions need confirming with the marketplace owner.
**Catches:** all leak vectors permanently. No ongoing maintenance.
**Misses:** nothing.
**Risk:** plugin marketplace expectations around source location; needs an explicit decision about whether the marketplace copy is the source-of-truth or a downstream artifact.

## Recommended path

**R2-1 first as a 30-minute experiment.** It's low-cost, the failure mechanism is direct, and closing the `pwd` channel may be sufficient on its own (the model may stop concatenating against an absolute prefix once it doesn't trivially have one). **Then re-run Phase 2.** If the next failure still references `~/.claude/...`, the writer transcript will show *which* leak vector survived (Read/README/something else). That result determines whether to escalate to R2-2 or R2-3.

R2-3 is the right long-term answer; defer to it only if R2-1 isn't enough or if there's appetite to relocate the source tree. R2-2 is mostly a stopgap for environments where R2-3 is genuinely off the table.

## Re-evaluation: cheap vs full Round 1 Claim 3 heuristic

The shipped fix used the **full jsonl-parsing heuristic**, not the cheap one Round 1 had recommended. In production it worked exactly as designed — `last_error` carries the literal tool error string, attribution is unambiguous, operator can act without spelunking. The coupling concern (Claude Code transcript schema being internal-and-unstable) didn't bite this time, but remains a forward risk: if Anthropic renames `tool_use_error` or restructures `tool_result.content`, the heuristic silently degrades back to `outer_artifacts_missing`.

**Add a regression test now** with a frozen Phase-2 jsonl fixture so any future Claude Code schema change is caught at CI time rather than on a live run. The fixture is the existing transcript at `~/.claude/projects/-Users-mstefanko--claude-plugins-marketplaces-mstefanko-plugins-swarm-do/f8826cd4-a2a5-410b-9d13-61d298a90fa0.jsonl` — copy a redacted version into `py/swarm_do/pipeline/tests/fixtures/claude_print/` and assert the heuristic emits `writer_tool_denied_no_artifacts` plus the expected `last_error`.

## Open questions for the next session

1. **Does setting `$PWD` in subprocess env make `pwd` return the logical path?** Shell-version dependent. Verify with the probe below before assuming R2-1 works.
2. **Audit the writer's possible canonical-path-leak commands.** Decide which to forbid in the prompt scaffolding: `pwd` (verified leak), `pwd -P` (always canonical), `realpath`, `readlink -f`, `git rev-parse --show-toplevel`, `git ls-files` paths, `find`, `mdfind`, `python3 -c 'import os; print(os.getcwd())'` (uses canonical), Python `Path(__file__).resolve()`. Test which actually leak in the safe-symlink workspace.
3. **Where exactly does the new heuristic in `phase_recovery.py` parse jsonl from?** The Round 2 evidence shows the `~/.claude/projects/<encoded>/<session_id>.jsonl` directory uses the *canonical* cwd (note the `-Users-mstefanko--claude-plugins-...` encoding — that's the canonical path, not the launcher-workspaces symlink). So the heuristic must be encoding the real path, not the safe path. Confirm this is correct and document it.
4. **Should `assert_prompt_safe` extend to runtime tool_result content?** A streaming guard that watches for `/.claude/` substrings in tool results during the run could fail-fast on the first leak rather than waiting for the writer to give up — diagnostic, not corrective.
5. **R2-3 plugin layout decision.** Does the marketplace expect source under `plugins/marketplaces/<vendor>/`, or is symlink-from-elsewhere acceptable? Read marketplace docs and/or ask the marketplace owner before committing to this option.
6. **Documentation hygiene:** scrub `README.md` (and other in-repo docs the writer might Read) of any `~/.claude/...` path references that aren't strictly necessary. Reduce the leak surface even if R2-1/2/3 are deferred.

## Reproducer probes (Round 2)

Run these from a shell, no swarmdaddy state involved.

### Probe P0 — confirm the `pwd` leak

```bash
# The exact mechanism from production
mkdir -p /tmp/leak-test
ln -sfn <sensitive-source>/swarm-do /tmp/leak-test/repo

cd /tmp/leak-test/repo
echo "PWD=$PWD"
pwd          # expect canonical <sensitive-home>/... ← the leak
pwd -P       # expect canonical <sensitive-home>/...
pwd -L       # may print symlink /tmp/leak-test/repo if shell honors -L

rm -rf /tmp/leak-test
```

### Probe P1 — does setting `$PWD` in env let `pwd` return the symlink?

```bash
ln -sfn <sensitive-source>/swarm-do /tmp/leak-test
cd /tmp/leak-test
PWD=/tmp/leak-test bash -c 'echo "shell:$0  PWD=$PWD  pwd=$(pwd)  pwd -P=$(pwd -P)  pwd -L=$(pwd -L)"'
PWD=/tmp/leak-test zsh  -c 'echo "shell:$0  PWD=$PWD  pwd=$(pwd)  pwd -P=$(pwd -P)  pwd -L=$(pwd -L)"'
rm -f /tmp/leak-test
```

If `pwd` reports `/tmp/leak-test` in either shell → R2-1 viable. If both shells report canonical → R2-1 needs additional shell coercion (e.g. `setopt CHASE_LINKS` semantics, or a `cd -L` wrapper).

### Probe P2 — full end-to-end with `claude -p`

```bash
mkdir -p /tmp/leak-test
ln -sfn <sensitive-source>/swarm-do /tmp/leak-test/repo

cd /
PWD=/tmp/leak-test/repo /Applications/cmux.app/Contents/Resources/bin/claude \
  -p --permission-mode dontAsk --output-format json \
  --allowedTools "Bash(pwd:*) Write" \
  <<< 'Run "pwd" then write ./probe.txt with content "ok". Stop after.'

ls -la /tmp/leak-test/repo/probe.txt   # if landed → R2-1 plus prompt-only fix is sufficient
rm -f /tmp/leak-test/repo/probe.txt
rm -rf /tmp/leak-test
```

If `probe.txt` lands → R2-1 alone solves it. If denied → check the model's Bash output: did `pwd` report symlink (R2-1 worked but model still hit a leak) or canonical (R2-1's `PWD` env trick failed)? Either result narrows the next step.

## Helper artifacts created during the investigation

These exist on disk and are useful for the next session:

- `/tmp/reset-phase2.py` — resets Phase 2 of run `01KQF2CF61YV7SYVREEWRE4GFB` to dispatchable state. Backs up `phase_sessions.v1.json` to `phase_sessions.v1.json.bak-before-phase2-reset` first.
- `/tmp/refresh-git-base.py` — updates all `git_base_sha` occurrences in the prepared plan to current HEAD. Backs up to `prepared_plan.v1.json.bak-before-git-base-refresh`. Use after committing fixes between attempts so the prepared plan's drift check passes.
- `/tmp/swarm-perm-probe.sh`, `/tmp/swarm-perm-probe2.sh` — Round 1 sensitive-path probes (bypassPermissions / --dangerously-skip-permissions / --add-dir / cwd-via-symlink). Use these to re-confirm the underlying CLI behavior hasn't changed before assuming Round 1 conclusions still hold.

## Files / line numbers (Round 2 additions)

- Execution workspace abstraction (Round 1 fix shipped here): `swarm-do/py/swarm_do/pipeline/phase_pump.py:430-445` (`workspace.rewrite_prompt`, `workspace.assert_prompt_safe`, `ExecutionWorkspaceError`).
- Subprocess invocation that needs the `PWD` env (R2-1 site): the `Popen`/`run` call in `phase_pump.py` after the argv assembly — find the spawn site near line 470+.
- New failure_kind classifier (Round 1 fix shipped here): `swarm-do/py/swarm_do/pipeline/phase_recovery.py` — search for `writer_tool_denied_no_artifacts` to find both the emitter and the `_retry_stop_decision` mapping.
- README leak surface: `swarm-do/README.md` ~line 700 (refers to `~/.claude/plugins/cache/.../swarmdaddy/`).

