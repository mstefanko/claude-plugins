# Provider Review MCO Pattern Adoption Plan

Date: 2026-04-26
Owner: provider-review (`py/swarm_do/pipeline/provider_review.py`)
Companion plan: [internal-provider-review-plan.md](internal-provider-review-plan.md)
Reference repo: <https://github.com/mco-org/mco>

## Goal

Bring only the useful, low-burden MCO provider-review patterns into the
swarm-owned provider-review runner. The internal runner remains the base:
read-only by construction, evidence-only in the pipeline, route-aware through
swarm-do backends, and gated by local schema/read-only/auth probes.

This plan intentionally avoids turning `swarm-provider-review` into a general
multi-agent CLI. MCO is broader and has useful runtime polish, but its default
permission posture and standalone orchestration model are not a good fit for
stock swarm-do provider review.

## Decision Summary

| MCO pattern | Decision | Value | Effort | Maintenance risk | Rationale | Source in mco-org/mco |
| --- | --- | --- | --- | --- | --- | --- |
| Process supervision with explicit run handles, raw stdout/stderr capture, and process-group cancellation | Adopt | High | Medium | Low-medium | Real provider CLIs can hang, spawn children, or leave partial output. A small internal runner helper improves safety without adopting MCO's adapter framework. | `runtime/adapters/shim.py` — `ShimAdapterBase.run`/`cancel`, `ShimRunHandle` dataclass, `start_new_session=True`, `os.killpg(..., SIGTERM)` then `SIGKILL` after a grace window |
| Sanitized provider subprocess environment | Adopt with process supervision | Medium | Low | Low | MCO strips session-specific environment such as `CLAUDECODE` before spawning providers. Cheap hardening for nested Claude/Codex launches. | `runtime/adapters/shim.py` — `_ENV_VARS_TO_STRIP = ("CLAUDECODE",)` and `_sanitize_env()` |
| Full normalized findings sidecar while keeping the ledger-facing artifact capped | Adopt | High | Low-medium | Low | Current `MAX_NORMALIZED_FINDINGS = 5` cap (`provider_review.py:54`) protects telemetry/evidence summaries, but losing extra normalized evidence is unnecessary. A local sidecar preserves detail without widening downstream blast radius. | n/a — swarm-do specific addition; modeled after MCO's separation between raw provider artifacts and a single canonical normalized output |
| Progress-aware stall timeout | Defer | Medium | Medium | Medium | Useful once real CLIs run regularly, but it changes timeout semantics. First add a process runner with hard deadlines and cancellation; revisit stall detection with real CLI data. | `runtime/formatters.py` — `provider_progress` event handling; error kinds `stall_timeout`, `hard_deadline_exceeded`, `executor_timeout` |
| SARIF / Markdown-PR renderers | Defer | Medium | Medium | Low-medium | Good output products, but not core to provider evidence. Add later as renderer commands if a real consumer appears. | `runtime/formatters.py` — `format_markdown_pr(...)` and `format_sarif(...)` |
| Per-provider perspectives and divide-by-files/dimensions | Defer | Medium | High | Medium-high | Useful for standalone review sweeps, but they add prompt-routing policy and can blur the provider stage's evidence-only role. | `runtime/contracts.py`, perspective/dimension routing in MCO orchestration |
| Chain, debate, memory, reliability scoring | Reject for provider stage | Low for current goal | High | High | These make provider review authoritative and stateful. They conflict with the plan that downstream review owns synthesis and quality decisions. | `runtime/bridge/` — `confidence.py`, `passive_confirm.py`, `evermemos_client.py`, `forget_cleaner.py` |
| MCO-style generic adapter framework | Reject | Low | High | High | Our known-shim registry and backend resolver are intentionally smaller. A generic adapter layer would duplicate existing swarm routing and broaden the attack/config surface. | `runtime/adapters/` — `ShimAdapterBase` plus per-provider adapters |

## Scope And Compatibility Boundary

- All work is local to `py/swarm_do/pipeline/provider_review.py` plus its tests
  (`tests/test_provider_review.py`), `provider_evidence.py`, and the
  `bin/swarm providers evidence` CLI helper. No new top-level modules.
- The v2 artifact schema (`schemas/telemetry/provider_findings.v2.schema.json`)
  is **not modified** by this plan. New data goes into the manifest
  (`provider-review.manifest.json`, currently unversioned-additive — see
  `provider_review.py:2718`) and the new local sidecar
  (`provider-findings.full.json`).
- The MCO v1 schema (`schemas/telemetry/provider_findings.schema.json`) and
  fixtures stay untouched.
- Posix-only assumptions: `start_new_session=True`, `os.killpg`,
  `os.getpgid`, and `signal.SIGTERM/SIGKILL` are all used by MCO's
  `runtime/adapters/shim.py` and are required for clean process-group
  cancellation. Swarm-do already targets POSIX. Document this constraint
  explicitly under the new helper; the helper degrades to a plain
  `process.terminate()` / `process.kill()` fallback when `os.killpg` is
  unavailable so unit tests on non-POSIX paths still exercise the timeout
  branches.
- No new third-party dependencies. Stay on `subprocess`, `signal`, `os`,
  `pathlib`, `concurrent.futures`. No `psutil`.

## Recommended Implementation

### Phase A — Provider Process Supervision And Environment Sanitization

**Status:** implemented. Replaces the existing `subprocess.run(timeout=...)`
calls inside `_run_codex_review_provider` and `_run_claude_review_provider`
with `_run_provider_process(...)`.

**MCO references:**

- `runtime/adapters/shim.py` — `ShimRunHandle` dataclass; `subprocess.Popen(...,
  start_new_session=True, env=_sanitize_env())`; cancellation path
  `os.killpg(os.getpgid(handle.process.pid), signal.SIGTERM)` followed by
  `SIGKILL` after a 0.2s grace window.
- `runtime/adapters/shim.py` — `_ENV_VARS_TO_STRIP = ("CLAUDECODE",)` and
  `_sanitize_env()` helper.

**Touched files / functions:**

| File | Symbols |
| --- | --- |
| `py/swarm_do/pipeline/provider_review.py` | new `ProviderProcessResult` dataclass; new `_provider_subprocess_env()`; new `_run_provider_process(...)`; refactor `_run_codex_review_provider` (line 2289) and `_run_claude_review_provider` (line 2398) to use the helper; keep existing `runner=subprocess.run` injection point for **probe/version/auth** code paths only |
| `py/swarm_do/pipeline/tests/test_provider_review.py` | migrate Codex/Claude exec path tests at lines 1251, 1287, 1322, 1375, 1417, 1462, 1492, 1510 from `runner=` mocking to a new `popen_factory=` injection point; keep `runner=` mocks for `--help`, `--version`, `auth status`, `login status` |

**Implementation steps (numbered):**

1. Add a new dataclass next to `ProviderRunResult` (`provider_review.py:243`):

   ```python
   @dataclasses.dataclass(frozen=True)
   class ProviderProcessResult:
       command_argv: tuple[str, ...]
       stdout_path: Path
       stderr_path: Path
       returncode: int | None       # None when cancelled/killed
       elapsed_seconds: float
       cancelled: bool = False
       cancel_reason: str | None = None       # "timeout" | "spawn_error" | None
       killed_process_group: bool = False
       stdout_text: str = ""        # bounded read-back of the file (snippet)
       stderr_text: str = ""        # bounded read-back of the file (snippet)
   ```

   `stdout_path`/`stderr_path` always point at the per-provider sidecar so
   downstream code (`_write_provider_sidecars`, `provider_review.py:2604`) can
   continue to read these files instead of buffered text. The text fields hold
   bounded snippets read **after** the process exits or is killed — capped at
   the existing `_text_snippet` limit already used elsewhere
   (`provider_review.py:_text_snippet`).

2. Add `_provider_subprocess_env() -> dict[str, str]` mirroring MCO's
   `_sanitize_env()`. Constants:

   ```python
   _PROVIDER_ENV_STRIP = ("CLAUDECODE",)
   ```

   Document the list at the call site. New entries must go through code review
   and require a docstring justification — keep this small.

3. Add `_run_provider_process(...)` as the single Popen-based entry point:

   ```python
   def _run_provider_process(
       command: Sequence[str],
       *,
       cwd: Path,
       stdout_path: Path,
       stderr_path: Path,
       timeout_seconds: int,
       popen_factory: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
       grace_seconds: float = 0.5,
       output_snippet_bytes: int = 4096,
   ) -> ProviderProcessResult: ...
   ```

   Behavior, in order:

   - `stdout_path.parent.mkdir(parents=True, exist_ok=True)`.
   - Open `stdout_path` and `stderr_path` for writing (`"w"`,
     `encoding="utf-8"`). Streaming directly to these files mirrors MCO's
     pattern and avoids buffering large CLI output in memory.
   - Spawn with `popen_factory(command, cwd=str(cwd), stdout=stdout_file,
     stderr=stderr_file, text=True, env=_provider_subprocess_env(),
     start_new_session=hasattr(os, "setsid"), close_fds=True)`.
   - Wait with `process.wait(timeout=timeout_seconds)`.
   - On `subprocess.TimeoutExpired`:
     1. If `os.killpg` is available and `start_new_session` succeeded, call
        `os.killpg(os.getpgid(process.pid), signal.SIGTERM)`. Set
        `killed_process_group=True`.
     2. Otherwise fall back to `process.terminate()`.
     3. Wait `grace_seconds` (`process.wait(timeout=grace_seconds)`).
     4. If still running, escalate to `os.killpg(..., signal.SIGKILL)` (or
        `process.kill()` fallback). `process.wait()` to reap.
     5. Set `cancelled=True`, `cancel_reason="timeout"`, `returncode=None`.
   - On `OSError` from `popen_factory`: set `cancelled=True`,
     `cancel_reason="spawn_error"`, `returncode=None`. No file handles to
     close in the failure branch — they are opened inside a `try`/`except` that
     closes them on failure (mirrors MCO).
   - **Always** close the stdout/stderr file handles in a `finally` block.
   - After exit, read back bounded snippets from each file using the existing
     `_text_snippet` helper applied to the trailing `output_snippet_bytes`
     (use `seek(max(0, size - output_snippet_bytes))` then `read()`).
   - Return `ProviderProcessResult` with absolute, resolved paths.

4. Refactor `_run_codex_review_provider` (`provider_review.py:2289`) and
   `_run_claude_review_provider` (`provider_review.py:2398`) to:

   - Build the command exactly as today.
   - Call `_run_provider_process(command, cwd=repo, stdout_path=..., stderr_path=...,
     timeout_seconds=timeout_seconds, popen_factory=popen_factory)`.
   - Translate `ProviderProcessResult` into `ProviderRunResult`. Mapping:
     - `cancelled and cancel_reason == "timeout"` → `error_class="timeout"`,
       `message=f"provider timed out after {timeout_seconds}s"`,
       `schema_mode="native"`, `elapsed_seconds=elapsed`,
       `last_message_text=_read_text_if_exists(last_message_file)` (Codex
       only — Claude has no last-message file).
     - `cancelled and cancel_reason == "spawn_error"` →
       `error_class="spawn_error"`, `message="provider failed to start: ..."`.
     - `returncode != 0` → `error_class="provider_error"`,
       `message=f"provider exited {returncode}"`.
     - `returncode == 0` → existing payload-parse / parser-fallback path.
   - **Remove** the existing `runner(command, text=True, capture_output=True,
     timeout=timeout_seconds)` calls inside these two functions only. Probe
     callers (`auth status`, `login status`, `--help`, `--version`) keep using
     `runner=subprocess.run`.

5. Plumb `popen_factory` from `run_stage` through `_run_selected_real_providers`
   and `_run_real_provider`. Mirror the existing `runner` parameter:

   - `run_stage(args)` reads `popen_factory = getattr(args, "popen_factory",
     subprocess.Popen)`.
   - Tests can pass `popen_factory=...` via `args` or via the test helper
     `_run_realish_stage` (`tests/test_provider_review.py`) which already
     accepts `runner=`.

6. `_write_provider_sidecars` (`provider_review.py:2604`) currently writes
   `stdout_text` and `stderr_text` from the `ProviderRunResult` into the
   sidecar files. After Phase A those files are already populated by
   `_run_provider_process`, so:

   - For real providers, treat the sidecar files as authoritative; do not
     overwrite them. `_write_provider_sidecars` should detect that the files
     exist and skip the write of `stdout_text`/`stderr_text` (or write only if
     the path is missing — fake-provider path).
   - For fake providers, keep current behavior — they synthesize
     `stdout_text` from a JSON payload and never call `_run_provider_process`.

7. Update `meta.json` (sidecar) to record:
   - `cancelled: bool`
   - `cancel_reason: str | null`
   - `killed_process_group: bool`
   - existing `command_argv` (redacted), `returncode`, `elapsed_seconds`,
     `schema_mode`, `error_class`, `message`.

   Field additions are additive; no consumer asserts the absence of fields.

8. Manifest (`provider_review.py:2707`):

   - Add `"environment_sanitization": {"strip": list(_PROVIDER_ENV_STRIP)}`
     under the existing `"retention"` block — purely informational, no schema.
   - No change to `schema_version` (still
     `"provider-review.manifest.v1"` — unversioned-additive policy).

**Acceptance tests (new in `tests/test_provider_review.py`):**

A1. `test_provider_process_writes_sidecars_and_succeeds`: runs an inline shell
script (`/bin/sh -c 'printf hi'`) under `_run_provider_process` with a
non-existent timeout headroom; asserts `returncode==0`, `cancelled is False`,
files exist with expected content, snippets match.

A2. `test_provider_process_cancels_on_timeout_and_kills_process_group`: runs
`/bin/sh -c 'sleep 30'` with `timeout_seconds=1`, `grace_seconds=0.2`; asserts
`cancelled is True`, `cancel_reason=="timeout"`, `returncode is None`,
`killed_process_group is True` (skip if `not hasattr(os, "setsid")`), elapsed
< 5 seconds.

A3. `test_provider_process_cancels_a_child_process`: parent shell command is
`/bin/sh -c 'sleep 30 & wait'`; asserts after timeout the spawned `sleep` is no
longer running (use `os.kill(pid, 0)` against the recorded child pid via a
second polling helper, **or** assert via an absent process group — pid lookup
via `ps -o pgid= -p $$`). Skip on platforms without `os.killpg`.

A4. `test_provider_process_strips_claudecode_env`: sets `CLAUDECODE=1` in
`os.environ`, runs `/bin/sh -c 'printf "%s" "${CLAUDECODE:-MISSING}"'`,
asserts captured stdout is `MISSING`.

A5. `test_provider_process_handles_spawn_error`: passes a non-existent binary;
asserts `cancelled=True`, `cancel_reason=="spawn_error"`, `returncode is None`,
no leaked file handles (open `tempfile.TemporaryDirectory` and verify file
sizes).

A6. Migration of existing tests (lines 1251, 1287, 1322, 1375, 1417, 1462,
1492, 1510): replace `runner=` mocking of `["/bin/codex", "exec", ...]` and
`["/bin/claude", "-p", ...]` with `popen_factory=` mocking. The test helper
should provide a small `FakePopen` that:

- accepts `(cmd, cwd, stdout, stderr, text, env, start_new_session,
  close_fds)` kwargs;
- writes deterministic content to the open `stdout` / `stderr` file objects;
- exposes `wait(timeout=None)` raising `subprocess.TimeoutExpired` on demand;
- exposes `terminate`, `kill`, `pid`.

Codex tests that currently rely on `--output-last-message` writing must keep
that side-effect by writing into `args[args.index("--output-last-message") + 1]`
inside `FakePopen.__init__` or in a helper — same as today.

**Definition of done for Phase A:**

- All tests in `py.swarm_do.pipeline.tests.test_provider_review` pass.
- The discovery suite `python3 -m unittest discover -s py` passes.
- Real Codex / Claude run paths use `subprocess.Popen` with
  `start_new_session=True` and `_provider_subprocess_env()`.
- A timed-out provider in the test fixture leaves no child processes (A3).
- Existing R2/R3/R4 eligibility gates are unchanged. No provider becomes
  eligible without those gates.

**Non-goals for Phase A:**

- No public adapter framework.
- No new timeout DSL.
- No progress/stall timeout semantics.
- No streaming UI / `provider_progress` events.
- No change to schemas, manifests beyond additive metadata, or v2 artifact.

### Phase B — Full Normalized Findings Sidecar

**Status:** ready to implement after Phase A. Not blocked by R2/R3 local proof
runs.

**Touched files / functions:**

| File | Symbols |
| --- | --- |
| `py/swarm_do/pipeline/provider_review.py` | new `_full_normalized_findings_artifact(...)`; refactor `normalize_provider_review_results` (line 1807) to compute the full row set first and the capped subset second; new constant `FULL_FINDINGS_SCHEMA_VERSION = "provider-findings.full.v1"`; manifest write update in `write_manifest` (line 2707); new return type so `run_stage` can write the full sidecar |
| `py/swarm_do/pipeline/provider_evidence.py` | extend `provider_evidence_summary` (line 33) to read truncation counts from a sibling `provider-review.manifest.json` when present; existing artifact-only behavior remains the fallback |
| `py/swarm_do/pipeline/tests/test_provider_review.py` | new tests for full sidecar emission, manifest count fields, and zero-truncation case |
| `py/swarm_do/pipeline/tests/test_provider_evidence.py` | new test that the summary reports `showing 5 of N` from manifest counts |

**Implementation steps:**

1. Inside `normalize_provider_review_results` (`provider_review.py:1807`), split
   the current pipeline:

   - Build the full normalized list `findings_full = sorted(findings,
     key=_normalized_finding_sort_key)` **without** the cap.
   - Compute `displayed_count = min(len(findings_full), MAX_NORMALIZED_FINDINGS)`,
     `truncated_count = max(0, len(findings_full) - displayed_count)`.
   - Set `findings = findings_full[:MAX_NORMALIZED_FINDINGS]` for the v2
     artifact (preserves current schema and ledger behavior).
   - Return both lists. Two clean options:

     (a) Change the function signature to return
     `tuple[dict[str, Any], list[dict[str, Any]]]` — `(artifact, findings_full)`.
     Smaller diff; one return-site update in `run_stage`.

     (b) Add the full list to a new key the v2 schema does **not** validate.
     Rejected because v2 has `additionalProperties: false`.

     **Choose (a).** All call sites:
     `provider_review.py:run_stage` (line 2825) and unit tests calling
     `normalize_provider_review_results` directly. Identify them with `grep -n
     "normalize_provider_review_results" py/`.

2. Add `_write_full_findings_sidecar(...)`:

   ```python
   FULL_FINDINGS_SCHEMA_VERSION = "provider-findings.full.v1"

   def _write_full_findings_sidecar(
       *,
       output_dir: Path,
       artifact: Mapping[str, Any],
       findings_full: Sequence[Mapping[str, Any]],
       displayed_count: int,
       truncated_count: int,
   ) -> Path:
       sidecar = {
           "schema_version": FULL_FINDINGS_SCHEMA_VERSION,
           "provider": "swarm-review",
           "run_id": artifact["run_id"],
           "issue_id": artifact["issue_id"],
           "stage_id": artifact["stage_id"],
           "configured_providers": artifact["configured_providers"],
           "selected_providers": artifact["selected_providers"],
           "schema_valid_providers": artifact["schema_valid_providers"],
           "provider_count": artifact["provider_count"],
           "min_success": artifact["min_success"],
           "selection_result": artifact["selection_result"],
           "source_artifact_path": artifact["source_artifact_path"],
           "manifest_path": artifact["manifest_path"],
           "display_cap": MAX_NORMALIZED_FINDINGS,
           "displayed_count": displayed_count,
           "truncated_count": truncated_count,
           "findings": list(findings_full),
       }
       path = output_dir / "provider-findings.full.json"
       _write_json(path, sidecar)
       return path
   ```

   No JSON Schema file is required for v1 — this is a local sidecar, never
   validated by `validate_value`. Note in code comment that this artifact is
   **not** consumed by telemetry.

3. Update `run_stage` (`provider_review.py:2742`):

   - After `normalize_provider_review_results`, call
     `_write_full_findings_sidecar` and capture the returned path.
   - **Skip the sidecar** when `selection.selected_providers` is empty (we
     already short-circuit with `skipped_result` and never call
     `normalize_provider_review_results` in that branch — Phase B preserves
     this).

4. Update `write_manifest` (`provider_review.py:2707`) to accept and record:

   ```python
   "full_findings": {
       "path": str(output_dir / "provider-findings.full.json"),
       "schema_version": FULL_FINDINGS_SCHEMA_VERSION,
       "display_cap": MAX_NORMALIZED_FINDINGS,
       "displayed_count": displayed_count,
       "truncated_count": truncated_count,
       "total_findings": displayed_count + truncated_count,
   }
   ```

   Default this block to `null` when the stage is skipped (no providers ran).
   No `schema_version` bump on the manifest itself — additive.

5. Update `provider_evidence.py:provider_evidence_summary`:

   - Look for a manifest at `Path(artifact_path).parent /
     "provider-review.manifest.json"` when `artifact_path` is provided. If the
     manifest exists and `full_findings` is a mapping with a `total_findings`
     and `displayed_count`, replace the existing line:

     ```
     - findings: 5 shown of {len(findings)}
     ```

     with:

     ```
     - findings: {displayed_count} shown of {total_findings} normalized ({truncated_count} truncated)
     ```

   - Fallback: keep the current `len(findings)` count when manifest is missing
     or malformed. Failure to read the manifest must never raise — log to
     stderr and use the artifact-only count.

6. Permission profile (`permissions/provider-review.json`): no change. Reading
   the local sidecar uses the existing `Read` permission.

**Acceptance tests:**

B1. `test_normalized_artifact_keeps_top_five_and_writes_full_sidecar`: provider
emits 12 valid findings; assert v2 artifact has 5 (the existing
`MAX_NORMALIZED_FINDINGS`); assert `provider-findings.full.json` exists with 12
findings, sorted by `_normalized_finding_sort_key`, and includes the swarm-owned
identity fields listed above; assert manifest `full_findings.total_findings ==
12`, `displayed_count == 5`, `truncated_count == 7`.

B2. `test_normalized_artifact_writes_full_sidecar_with_zero_truncation`: 3
findings → full sidecar has 3 rows, `truncated_count == 0`.

B3. `test_skipped_stage_does_not_write_full_sidecar`: selection off → no
`provider-findings.full.json` exists; manifest `full_findings is None`.

B4. `test_provider_evidence_summary_reports_truncation_from_manifest`:
artifact has 5 findings, manifest reports 12 normalized; summary string
contains `"5 shown of 12 normalized (7 truncated)"`. No raw provider text in
the summary (existing assertion preserved).

B5. `test_provider_evidence_summary_falls_back_when_manifest_missing`: delete
manifest before summarizing; summary still uses the artifact-only count and
emits no error.

**Definition of done for Phase B:**

- v2 artifact remains schema-valid against
  `schemas/telemetry/provider_findings.v2.schema.json` (no schema change).
- Telemetry extractor `swarm_do/telemetry/extractors/provider_review.py` still
  emits at most 5 findings.jsonl rows per stage (it consumes the v2 artifact
  alone).
- A run with >5 valid findings produces a discoverable `provider-findings.full.json`
  in the stage output dir.
- Manifest carries the full-sidecar pointer and counts.
- `bin/swarm providers evidence` reports `N shown of M normalized` when the
  manifest is present.

**Non-goals for Phase B:**

- Do not promote the full sidecar into telemetry (keep it as run-local
  artifact under the existing retention policy at `provider_review.py:2733`).
- Do not remove the main artifact cap.
- Do not change consensus policy or confidence promotion.
- Do not add a JSON schema file for the full sidecar — it stays a local
  debug aid until a downstream consumer needs the contract.

### Phase C — Decision Gate For Deferred Runtime Polish

**Status:** decision-only. No code changes until inputs from Phase R2/R3 local
proof runs land.

Phase C is a recorded decision protocol, not a queued implementation. Add no
code from the deferred items unless the trigger criteria below are met. The
internal-provider-review-plan.md already lists R2/R3 as the prerequisite local
proof runs for real Codex/Claude eligibility — Phase C reuses that evidence.

**Trigger A — Progress-aware stall timeout** (MCO `runtime/formatters.py`
`provider_progress` event handling, `error_kind in {"stall_timeout",
"hard_deadline_exceeded", "executor_timeout"}`).

Adopt only if **two or more** of the following hold after R2/R3:

- A real provider regularly hangs while producing no output (>30s gap with
  process alive in two or more captured runs).
- Hard deadline cancellation discards substantial successful work
  (`elapsed_seconds > timeout_seconds * 0.8` and parsed payload exists).
- Stdout/stderr growth is monotonic and large enough to be a useful liveness
  signal (median >1KiB/min during normal runs, captured in sidecars).

If adopted, narrow DSL:

- `timeout_seconds` remains the hard cap.
- Add `stall_timeout_seconds` as an optional attribute on the swarm-review
  stage YAML, defaulting to **null** (off).
- Add a new `cancel_reason="stall_timeout"` to `ProviderProcessResult`.
- Include the new reason in the v2 artifact via the existing
  `provider_errors[*].provider_error_class` enum (already a free string in
  v2). Document the value list in code constants.

**Trigger B — SARIF / Markdown-PR renderers** (MCO `runtime/formatters.py`
`format_markdown_pr` and `format_sarif`).

Adopt only when there is a **named consumer** asking for the format:

- Specific PR-bot or CI integration.
- Specific operator workflow that cannot be served by
  `bin/swarm providers evidence`.

If adopted, ship as renderers over the existing artifact, **not** as new
provider-runner output modes:

- `bin/swarm providers evidence --format markdown-pr <provider-findings.json>`
- `bin/swarm providers evidence --format sarif <provider-findings.json>`

The renderer reads the v2 artifact plus the optional full sidecar and emits
SARIF / Markdown without launching providers.

**Trigger C — Per-provider perspectives, divide-by-files, chain, debate,
memory, reliability scoring.**

Reject by default. Reopen only via a new ADR that explains why downstream
review synthesis is no longer the right owner. None of these belong in the
provider-review evidence stage.

## Evidence Preservation And Memory Strategy

The user's question: should captured provider evidence flow into the
`claude-mem` memory store, into the swarm-do telemetry ledger, or stay
run-local?

Current paths and where each kind of evidence belongs:

| Evidence | Volume | Sensitivity | Destination | Why |
| --- | --- | --- | --- | --- |
| Raw provider stdout/stderr/last-message | High (KB–MB) | High — model output, may include prompt-injection vectors, snippets, tool logs, local paths | Stay local under `runs/<run_id>/stages/<stage_id>/providers/<id>/`; retention as documented in `provider_review.py:2733` | Replaying raw model output through claude-mem would re-inject text that has not been validated as safe. The internal plan already classifies these as "local-run-artifact-sensitive". |
| Capped normalized findings (5 rows) | Small | Low after redaction (`_redact_secret_like_evidence`) | v2 artifact → `findings.jsonl` ledger via `swarm_do/telemetry/extractors/provider_review.py:62` | Existing path; unchanged by this plan. |
| Full normalized findings sidecar (Phase B) | Medium (10s–100s of rows) | Same as capped rows after redaction, but more of them | Local run artifact only | Useful for audit/debug, but the ledger and prompts already get the priority subset. Promoting all of it would duplicate `findings.jsonl` work without changing decisions. |
| Calibration outputs (`bin/swarm providers calibrate-consensus`) | Small | Low (statistical only) | Operator workspace only; never committed | Already implemented; calibration is intentionally a local research tool. |
| Selection / status / counts / consensus policy version | Tiny | None | v2 artifact (already there) | No change. |

**claude-mem (cross-session memory) recommendation: do not write provider
review evidence to claude-mem.** Provider review is evidence-only,
single-pass, and the model output has not been adjudicated. The downstream
review stage is the authoritative consumer and is also the place where
quality gates live. Any cross-session memorization should happen there, not
upstream.

The narrow exception worth recording: the **consensus calibration report**
(`provider-review.consensus-calibration.v1`) summarizes false-merge / false-
split rates across captured Claude/Codex samples. If we want longitudinal
visibility into whether secondary clustering is becoming safe to promote, the
right path is:

1. Keep the calibration report as a local artifact (already the case).
2. When R9 calibration is rerun on captured samples, append a single summary
   row to a new `${CLAUDE_PLUGIN_DATA}/telemetry/provider_review_calibration.jsonl`
   ledger. Bounded fields: `timestamp`, `policy_version`, `sample_count`,
   `false_merge_count`, `false_split_count`, `mean_confidence_after_caps`. No
   raw findings, no model output.
3. **Defer** this addition until the user actually runs calibration twice in
   a row and wants to compare. Premature ledgering of an experimental signal
   is not paid for by current usage.

Net effect: this plan ships Phase A and Phase B. Telemetry stays as today.
No claude-mem writes from provider review. Calibration ledgering is a
documented future option, not an in-scope deliverable.

## Execution Order

1. Phase A.1: implement `_run_provider_process`, `ProviderProcessResult`,
   `_provider_subprocess_env`. Land the helper with its own tests (A1, A4, A5)
   before refactoring the existing provider entrypoints.
2. Phase A.2: refactor `_run_codex_review_provider` and
   `_run_claude_review_provider` to call the helper. Migrate test fixtures
   from `runner=` to `popen_factory=` for these paths only. Land tests A2, A3,
   A6.
3. Phase A.3: update `_write_provider_sidecars` to honor pre-populated sidecar
   files; update `meta.json` schema additively; record env-strip list in the
   manifest.
4. Phase A green: focused suites
   `py.swarm_do.pipeline.tests.test_provider_review`,
   `py.swarm_do.pipeline.tests.test_provider_evidence`,
   `py.swarm_do.pipeline.tests.test_providers`. Then `discover -s py`.
5. Phase B.1: split `normalize_provider_review_results` into full + capped;
   add `_write_full_findings_sidecar` and the manifest update. Land tests B1,
   B2, B3.
6. Phase B.2: extend `provider_evidence_summary` to consult the manifest.
   Land tests B4, B5.
7. Phase B green: rerun the same focused suites; rerun
   `py.swarm_do.pipeline.tests.test_provider_evidence`.
8. After R2/R3 local proof runs land (separate gate documented in
   internal-provider-review-plan.md), revisit Phase C using the criteria
   above. Phase C produces no code without an explicit decision pass.

## Validation Commands

Focused suites first:

```bash
PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_provider_review
PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_provider_evidence
PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_providers
```

Full discovery before merge:

```bash
PYTHONPATH=py python3 -m unittest discover -s py
```

Before enabling real provider review in stock runs (unchanged from the
internal plan):

```bash
SWARM_RUN_CODEX_R2_FIXTURE=1 PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_provider_review.ProviderReviewTests.test_local_codex_r2_fixtures_pass_when_explicitly_enabled
SWARM_RUN_CLAUDE_R3_FIXTURE=1 PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_provider_review.ProviderReviewTests.test_local_claude_r3_fixture_passes_when_explicitly_enabled
```

## Rejected Or Deferred MCO Features (Reference Only)

### Per-Provider Perspectives

Worth revisiting later, but not in v1. Perspectives change the review prompt
per provider, which makes provider outputs less directly comparable. Useful
for broad sweeps, but the current stage is meant to collect independent
evidence for downstream review.

### Divide By Files Or Dimensions

Useful for large repositories, but it adds scoping logic, target balancing,
and new failure modes when a provider reports outside its assigned slice.
Defer until the baseline internal runner is proven with real providers.

### Chain And Debate

Do not bring these into the provider stage. They are synthesis workflows, and
swarm-do already has downstream review stages that own synthesis and quality
judgment. MCO references: `runtime/bridge/passive_confirm.py`,
`runtime/bridge/confidence.py`.

### Memory And Reliability Scoring

Do not bring MCO memory into provider review. It creates persistent state,
provider weighting, and lifecycle policy that conflict with the current
artifact-local, evidence-only design. MCO references:
`runtime/bridge/evermemos_client.py`, `runtime/bridge/forget_cleaner.py`.
If swarm-do later wants provider reliability, design it as a separate
telemetry analysis feature outside the provider-review stage.

## Success Criteria

- A timed-out provider in the test fixture leaves no child processes
  detectable via `os.kill(pid, 0)` against any spawned descendant (Phase A
  test A3).
- Real-provider sidecars remain local-run sensitive artifacts and are not
  promoted to telemetry; manifest `retention.class ==
  "local-run-artifact-sensitive"` is preserved (`provider_review.py:2733`).
- The canonical v2 artifact remains bounded to `MAX_NORMALIZED_FINDINGS == 5`
  and schema-valid against
  `schemas/telemetry/provider_findings.v2.schema.json`.
- Full normalized findings are available locally as
  `provider-findings.full.json` for audit/debugging when more than five
  findings exist.
- `bin/swarm providers evidence` reports `N shown of M normalized` when the
  manifest is present, falls back gracefully when it is not.
- Claude/Codex eligibility still requires read-only/schema/auth proof gates
  (R2/R3/R4 unchanged).
- No MCO dependency is introduced for stock swarm-do provider review.
- No claude-mem writes are introduced from the provider-review stage.

## Risks And Mitigations

- **Test churn from runner→popen_factory migration.** Mitigation: keep the
  existing `runner=subprocess.run` injection point for probe / version /
  auth callers; introduce `popen_factory=subprocess.Popen` only for the two
  provider exec paths. The migration touches a known set of test cases
  (lines 1251, 1287, 1322, 1375, 1417, 1462, 1492, 1510 in the current
  test file) and adds a small `FakePopen` helper.
- **Cross-platform `os.killpg`.** Mitigation: gate process-group calls on
  `hasattr(os, "setsid")` / `hasattr(os, "killpg")`; fall back to
  `process.terminate()`/`kill()`. Document that the strong cancellation
  guarantee depends on POSIX, matching MCO. Tests that assert
  `killed_process_group=True` skip on non-POSIX platforms.
- **Sidecar file size growth.** Streaming straight to disk avoids in-memory
  buffering. Snippet read-back is bounded to ~4 KiB. The full sidecar
  (Phase B) carries normalized findings only — no raw stdout — so its size
  is bounded by provider count × finding count.
- **Manifest field drift.** Manifest is unversioned-additive; new fields
  must be optional in any future reader. Document this constraint in the
  comment block above `write_manifest`.
- **Confusing two artifact paths.** The v2 artifact and the full sidecar
  share schema-valid identity fields. The full sidecar carries
  `schema_version: provider-findings.full.v1`, which downstream telemetry
  ignores. Add a one-line comment near `_write_full_findings_sidecar`
  pointing to this plan as the authority on the split.
- **Phase C creep.** Each Phase C trigger requires fresh evidence from real
  Codex/Claude runs. Reject any Phase C work that does not cite captured
  R2/R3 data.

## Closed Questions

- Keep the existing `runner=` injection for probe helpers (auth status, login
  status, version). Probe paths are short, time-bounded, and produce small
  output, so `subprocess.run` remains the right low-burden interface until a
  probe needs process-group cancellation.
- Do not add `bin/swarm providers evidence --include-truncated` in this plan.
  The full sidecar is a local audit/debug artifact; exposing additional
  findings through the CLI waits for a named downstream consumer.
