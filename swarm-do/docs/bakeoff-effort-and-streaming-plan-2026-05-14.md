# Bakeoff — Effort Tuning + Streaming Heartbeats Implementation Plan

**Date:** 2026-05-14
**Target:** `~/.claude/plugins/marketplaces/mstefanko-plugins/bakeoff/`
**Builds on:** `bakeoff-tiny-cli-harness-implementation-plan-2026-05-14.md`

## Scope

Three independent changes, ordered by ROI. Each is shippable on its own.

1. **Per-mode effort defaults** (small code + template change) — stop paying high-effort tokens on retrieval and judging.
2. **I/O heartbeats** (Phase A, small runner + CLI change) — make observable subprocess progress visible; surface quiet periods before timeout.
3. **Adaptive budget extension** (Phase B, deferred) — extend deadlines only if Phase A telemetry proves timeouts mostly happen while output is still arriving.

## Non-goals

- No token streaming to stdout. We emit per-tick status lines, nothing finer.
- No provider output-format changes in Phase A. The current runner extracts `<final_json>` from plain stdout; heartbeats must not change that contract.
- No structured stream-JSON parsing in Phase A. We rely on stdout/stderr byte counts and output age. Stream-JSON is a later adapter project only if byte telemetry proves insufficient.
- No new dependencies. Stdlib `asyncio` and `time` only.
- No work-order schema changes beyond a single optional `budgets.heartbeat_seconds` field (default 60).

## Reconcile: 420 vs 900

The current code and templates default to **900 seconds** (`runner.py:41`, all three `examples/*.work-order.json`). If 420 is the desired target, this plan adopts it; if 900 is correct, leave defaults alone. Either way, the change is one constant + three example files. **Open decision — confirm before merge.**

---

## Part 1 — Per-mode effort defaults

### Evidence

| Source | Finding |
|--------|---------|
| OpenAI GPT-5 Prompting Guide ([cookbook](https://cookbook.openai.com/examples/gpt-5/gpt-5_prompting_guide)) | `minimal/low` for extraction, classification, formatting; `medium` is the recommended default; `high` for diagnosis, multi-option comparison, planning, code reasoning. |
| Anthropic Extended Thinking docs ([docs.claude.com](https://docs.claude.com/en/docs/build-with-claude/extended-thinking)) | Extended thinking lifts AIME 2025 from 16% → 60%+ (~4x). Diminishing returns above 16–32k thinking tokens. |
| Sahoo et al., "Do LLMs Overthink Basic Math Reasoning?" arXiv 2507.04023 (Jul 2025) | Zero accuracy gain from low → medium → high on listing/extraction tasks. Reasoning models can emit ~18x more tokens with no/lower accuracy. Non-monotonic accuracy-vs-verbosity curve. |
| "Illusion of Diminishing Returns" arXiv 2509.09677 (Sep 2025) | Thinking mitigates self-conditioning errors in long-horizon chains even when single-step accuracy looks saturated. Supports `high` for multi-step reasoning. |
| Aragão et al., LLM-as-judge study, Frontiers 2025 ([fdata.2025.1611389](https://www.frontiersin.org/journals/big-data/articles/10.3389/fdata.2025.1611389/full)) | GPT-5-low achieved 100% structured-output reliability vs. 99.8% at high. Judges show sublinear or flat accuracy gains past medium effort with large cost increases. |

### Recommended defaults

| Mode | Worker effort | Judge effort | Why |
|------|---------------|--------------|-----|
| `gather` | `low` | `low` | Enumeration is extraction-class; arXiv 2507.04023 shows no lift from raising effort. Judge only dedupes and flags conflicts. |
| `compare` | `high` | `medium` | Defending a position with rebuttals is OpenAI's canonical "high" use case. Judge applies a fixed rubric; Frontiers 2025 shows judges plateau or regress past medium. |
| `analyze` | `high` | `medium` | Atomic spine = long-horizon reasoning (arXiv 2509.09677). Judge does mechanical rubric scoring + overlay annotation — not novel reasoning. |

**Worker/judge asymmetry is evidence-backed.** Frontiers 2025 specifically shows judge reliability is *higher* at low effort and cost-adjusted accuracy peaks below high.

### Implementation

1. **`src/bakeoff/work_order.py`** — replace the `"effort": "high"` hardcodes in the init template with per-mode lookups:
   ```python
   MODE_EFFORT_DEFAULTS = {
       "gather":  {"worker": "low",  "judge": "low"},
       "compare": {"worker": "high", "judge": "medium"},
       "analyze": {"worker": "high", "judge": "medium"},
   }
   ```
   Wire these into the init template builder (~line 355).
2. **`examples/*.work-order.json`** — regenerate the three example files to match.
3. **Validator default stays `"high"`** for safety: any explicit work order without `effort` set still gets the conservative value. Only `init` templates change.
4. **`README.md`** — short table of the recommended defaults with one-line justifications and links to the two most-cited sources.

### Phase 1 acceptance

- `bakeoff init gather` writes `effort: "low"` on both workers and the judge.
- `bakeoff init compare` writes `effort: "high"` on workers, `"medium"` on judge.
- `bakeoff init analyze` writes `effort: "high"` on workers, `"medium"` on judge.
- An existing work order with `effort` omitted still validates to `"high"` (regression test).
- Doctor's `effort: "low"` auth probe is unchanged.

---

## Part 2 — I/O heartbeats (Phase A)

### Goal

Print a status line per provider every `heartbeat_seconds` (default 60). Surface quiet periods (no stdout or stderr for >120s) before the wall-clock timeout fires. No new tooling, no output-format changes — use signals already available in `runner.py`.

### Signals available now

`runner.py` already reads stdout and stderr independently (`read_stdout`, `read_stderr`). Track both streams, because provider CLIs do not use them consistently: Codex's human progress can appear on stderr, while final answer text may appear on stdout; Claude's plain `-p` output is stdout-centric.

- `stdout_bytes`, `stderr_bytes` — cumulative captured output by stream.
- `last_stdout_at`, `last_stderr_at` — `time.monotonic()` of the last non-empty chunk by stream.
- `last_output_at` — max of the two stream timestamps.

Derived: `last_output_age = now - last_output_at`. A non-zero byte delta means the subprocess emitted observable output; it does **not** prove the model is reasoning productively. A large `last_output_age` is a quiet/stall warning, not a semantic diagnosis.

### Implementation

1. **`runner.py`** — extend `run_provider` with one new parameter:
   ```python
   on_tick: Callable[[dict], None] | None = None
   ```
   The callback receives a dict:
   ```python
   {
       "elapsed": float,
       "stdout_bytes": int,
       "stderr_bytes": int,
       "total_bytes": int,
       "stdout_delta_bytes": int,
       "stderr_delta_bytes": int,
       "total_delta_bytes": int,
       "last_stdout_age": float | None,
       "last_stderr_age": float | None,
       "last_output_age": float,
       "phase": "running" | "quiet",
   }
   ```
2. Spawn a heartbeat task alongside `feed_prompt`, `read_stdout`, `read_stderr`:
   ```python
   async def heartbeat() -> None:
       prev_stdout = 0
       prev_stderr = 0
       while process.returncode is None:
           await asyncio.sleep(heartbeat_seconds)
           if process.returncode is not None:
               return
           now = time.monotonic()
           stdout_total = stdout_total_bytes
           stderr_total = stderr_total_bytes
           last_output_at = max(t for t in (last_stdout_at, last_stderr_at) if t is not None) if (
               last_stdout_at or last_stderr_at
           ) else None
           age = now - last_output_at if last_output_at else now - started
           tick = {
               "elapsed": now - started,
               "stdout_bytes": stdout_total,
               "stderr_bytes": stderr_total,
               "total_bytes": stdout_total + stderr_total,
               "stdout_delta_bytes": stdout_total - prev_stdout,
               "stderr_delta_bytes": stderr_total - prev_stderr,
               "total_delta_bytes": (stdout_total - prev_stdout) + (stderr_total - prev_stderr),
               "last_stdout_age": now - last_stdout_at if last_stdout_at else None,
               "last_stderr_age": now - last_stderr_at if last_stderr_at else None,
               "last_output_age": age,
               "phase": "quiet" if age > 120 else "running",
           }
           _safe_on_tick(tick)
           prev_stdout = stdout_total
           prev_stderr = stderr_total
   ```
3. Add `last_stdout_at: float | None = None`, `last_stderr_at: float | None = None`, `stdout_total_bytes`, and `stderr_total_bytes`. Update the matching timestamp and counter inside each reader when a non-empty chunk arrives.
4. **`cli.py`** — supply a callback that prints:
   ```
   [claude]  running   120s elapsed   18.1 KB stdout   0.3 KB stderr   (+4.2 KB in 60s)
   [codex]   quiet     180s elapsed   22.4 KB stdout   8.1 KB stderr   no output for 122s
   ```
5. **Work-order schema** — `budgets.heartbeat_seconds` is an optional positive integer; default 60. Validator rejects zero/negative. No bump of `schema_version` (additive, optional).
6. **Persist aggregate telemetry** — add a small `io` block to each final result/status:
   ```json
   {
     "io": {
       "stdout_bytes": 18123,
       "stderr_bytes": 281,
       "last_stdout_age": 0.4,
       "last_stderr_age": 88.2,
       "last_output_age": 0.4,
       "heartbeat_count": 5,
       "quiet_tick_count": 1
     }
   }
   ```
   This is what makes the Phase B decision evidence-based instead of anecdotal. It is an additive field inside existing artifacts, not a new artifact layout.

### Operational rules

- Heartbeats are best-effort: a callback exception is caught and logged, never raised into `run_provider`.
- The heartbeat task is cancelled in the same `_settle_tasks` path as the other readers.
- No heartbeat fires after `process.returncode` is set. The final status line comes from the existing `_status` return — heartbeats are strictly intermediate.
- The status language is intentionally conservative: `running` means "recent observable output," and `quiet` means "no observable output recently." Do not call it "thinking", "healthy", or "stalled" unless the final timeout path actually fires.

### Phase A acceptance

- A 200s fake-provider script that writes "tick" to stdout every 30s produces ≥3 heartbeat lines marked `running`.
- A 200s fake-provider script that writes progress only to stderr every 30s also produces ≥3 heartbeat lines marked `running`.
- A 200s fake-provider script that writes once then sleeps produces ≥1 heartbeat line marked `quiet` before the timeout fires.
- `providers/<id>/status.json` records the final `io` block, including `heartbeat_count` and `quiet_tick_count`.
- A `heartbeat_seconds: 0` work order is rejected by the validator with a field-named error.
- Heartbeats stop emitting within `heartbeat_seconds + 100ms` of the process exiting.
- No regression in any existing `tests/test_runner.py` case.

---

## Part 3 — Adaptive budget extension (Phase B, deferred)

**Status:** deliberately not built. Ship Phase A first, collect a week of `io.last_output_age`, `heartbeat_count`, `quiet_tick_count`, and timeout outcomes, then decide whether extension is justified.

### The two viable signals

| Signal | Reliability | Effort | Failure mode |
|--------|-------------|--------|--------------|
| **Byte-rate** — extend when fresh stdout/stderr bytes arrived since the previous extension decision and `last_output_age <= 60s` | Cheap, works today, no provider contract change | Small runner change | Can reward noisy/junk output. Needs hard cap, fresh-progress guard, and telemetry. |
| **Structured JSONL events** — provider-specific adapters for `claude -p --output-format stream-json --verbose` and `codex exec --json` | Higher semantic signal | Larger adapter project | Changes the output contract, requires per-provider event parsing and fallback, and can break when CLI event shapes drift. |

### Candidate Phase B (byte-rate + guard)

Only build this if Phase A shows a real pattern: providers time out near the original wall limit while output is still arriving, and manual inspection suggests those runs often would have completed with a small grace window.

Replace `runner.py:113`:
```python
await asyncio.wait_for(process.wait(), timeout=wall_seconds)
```
with a sliding-deadline loop:
```python
deadline = started + wall_seconds
hard_cap = started + 2 * wall_seconds  # never extend past this
extensions_applied = 0
last_extension_total_bytes = 0
while True:
    try:
        await asyncio.wait_for(process.wait(), timeout=max(0.1, deadline - time.monotonic()))
        break
    except asyncio.TimeoutError:
        now = time.monotonic()
        if now >= hard_cap:
            raise  # original timeout path

        total = stdout_total_bytes + stderr_total_bytes
        last_output_at = max(t for t in (last_stdout_at, last_stderr_at) if t is not None) if (
            last_stdout_at or last_stderr_at
        ) else None
        fresh_progress = total > last_extension_total_bytes
        recent_output = (now - last_output_at) <= 60 if last_output_at else False

        if fresh_progress and recent_output:
            deadline = min(now + heartbeat_seconds, hard_cap)
            last_extension_total_bytes = total
            extensions_applied += 1
            on_tick({..., "phase": "extended"})
        else:
            raise  # quiet or no fresh progress — let timeout fire
```

### Hard rules for Phase B

- **Absolute cap:** `hard_cap = 2 × wall_clock_seconds`. Non-negotiable.
- **Fresh-progress gate:** never extend twice from the same output bytes. `total_bytes` must increase since the previous extension decision.
- **Quiet gate:** never extend when `last_output_age > 60s`.
- **Use stdout + stderr.** Provider progress can appear on either stream.
- **One extension per deadline decision.** No compounding within a tick.
- **Record the behavior:** final status includes `extensions_applied`, original wall budget, and hard-cap seconds.
- **Tests must include a malicious-provider fixture** that emits one byte every 59s — it should hit `hard_cap` and time out, not run forever.

### Phase B acceptance (when built)

- Adversarial test: provider that writes 1 byte every 59s terminates at `2 × wall_clock_seconds`, not later.
- Healthy test: provider that writes 1 KB every 10s for `1.5 × wall_clock_seconds` completes successfully and `meta.json` records `extensions_applied > 0`.
- Stall test: provider that writes 10 KB then sleeps times out at the original `wall_clock_seconds`, not at `hard_cap`.
- Duplicate-decision test: provider emits once shortly before the original deadline, then goes quiet. It gets at most one heartbeat-sized extension, not repeated extensions from the same bytes.

### Structured JSONL option (Phase B+, optional)

If byte-rate proves too gameable in practice, build structured parsing as a provider-adapter project, not as a quick heartbeat tweak:

- `providers.py` would need explicit structured modes: Claude via `--output-format stream-json --verbose` (plus partial-message flags if needed), Codex via `--json`.
- `runner.py` would need per-backend adapters that both preserve raw JSONL artifacts and reconstruct the existing plain-text `<final_json>` contract for validators.
- Event shapes differ: Claude stream frames expose assistant messages and `tool_use` blocks; Codex JSONL exposes its own event vocabulary. Do not assume a shared `tool_use` / `message_delta` schema.
- Unknown or malformed event shapes fail closed: preserve raw output, do not extend based on unparsed structure, and fall back to the plain-output contract where possible.

Do not build this speculatively. It is justified only if Phase A/byte-rate data shows meaningful false positives or false negatives that raw I/O telemetry cannot handle.

---

## Risks

- **Effort defaults drift across providers.** Anthropic and OpenAI may interpret `low/medium/high` differently. Mitigation: document the per-mode rationale, not specific token counts; let users override per-task. Defaults are a starting point, not a contract.
- **Heartbeat noise on fast runs.** A 30-second task with 60-second heartbeats produces zero ticks — fine. A 120-second task produces one — also fine. Don't lower the default below 60 without telemetry.
- **Observable output is not semantic progress.** Byte-rate can mean useful answer text, verbose CLI logs, or junk. Phase A labels should stay neutral; Phase B must require fresh output, recent output, and a hard cap.
- **Extension creep in Phase B.** The `2 × wall_clock_seconds` cap is the most important rule in this document. Any future change that loosens it requires a separate ADR.

## Rollout

1. **Part 1** ships standalone. One PR. Existing work orders unaffected.
2. **Part 2** ships standalone. One PR. Heartbeats are off if `cli.py` passes `on_tick=None`; default `cli.py` wires the printer. Status artifacts persist aggregate `io` telemetry.
3. **Dogfood for one week** and inspect timed-out runs: Were they quiet, or still emitting output near the deadline? Did output appear on stdout, stderr, or both?
4. **Part 3** is deferred until that telemetry exists. Cut a new plan doc with the observed timeout distribution and a default-on vs opt-in recommendation.

## Open decisions

- 420 vs 900 default `wall_clock_seconds` — confirm before merging Part 1.
- Whether `gather` judge truly belongs at `low` or `medium`. Frontiers 2025 supports `low`; if dedupe quality degrades in dogfood, bump to `medium`. Worth an A/B in the first week.
- Whether to add a configurable quiet threshold or keep `quiet` fixed at 120s. Default fixed unless dogfood says otherwise.
- If Phase B is built, whether adaptive extension is default-on under hard caps or opt-in via a new work-order field. Decide in the Phase B plan, not here.

## Success criteria

- A user running `bakeoff research gather.work-order.json` on a 5-minute task sees at least 4 heartbeat lines and knows whether each worker is emitting observable output, without ever opening a log file.
- A timed-out run's status artifacts show whether the provider had recent stdout/stderr output near the deadline.
- Token spend on `gather` mode drops by the ratio of `low`-vs-`high` reasoning tokens for both workers and the judge (vendor-dependent; Anthropic typically 5–10x, OpenAI 3–8x).
- No change to provider output format, artifact layout, work-order schema version, or judge prompts.
