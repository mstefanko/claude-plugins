# Internal Provider Review Plan

Date: 2026-04-25

## Goal

Replace the MCO-centered provider review spike with a swarm-owned read-only
review runner that can fan out across every locally configured review-capable
model. MCO remains useful as a comparison spike, but the long-term runtime
should be `swarm-provider-review`, not a fork or wrapper around the whole MCO
CLI.

The important UX change is that provider review should not require a separate
opt-in pipeline with hardcoded provider names. Operators should set up Claude,
Codex, and later Gemini or ACP agents once; the review stage should discover
the available read-only review pool from that setup and run the eligible
providers automatically.

## Recommendation

Build a small internal provider review runner:

- Keep `bin/swarm-stage-mco` and `pipelines/mco-review-lab.yaml` as the MCO
  comparison spike.
- Add `bin/swarm-provider-review` backed by a Python module such as
  `py/swarm_do/pipeline/provider_review.py`.
- Add a shim registry for `claude`, `codex`, later `gemini`, and later
  `acp:<agent>`.
- Add a provider emission schema that models can emit directly. Keep it smaller
  than `schemas/telemetry/provider_findings.schema.json`; swarm-do fills
  run ids, timestamps, hashes, provenance, status, and consensus fields.
- Normalize every valid provider response into a side-by-side
  provider-findings v2 artifact shape while leaving the MCO v1 schema intact.
- Make stock review-capable pipelines use an automatic provider stage once the
  runner is validated. Selection comes from configured local capabilities, not
  from hardcoded pipeline `providers: [...]` lists.

## Validated Repo Constraints

Validation on 2026-04-25 confirmed these constraints in the current repo:

- `schemas/telemetry/provider_findings.schema.json` is a v1 MCO contract:
  top-level and per-finding `provider` are enum-locked to `mco`, `status` lacks
  `skipped`, and role is locked to `agent-codex-review`.
- `py/swarm_do/pipeline/mco_stage.py` treats `provider_count` as the selected or
  reported provider count for the MCO spike, and existing MCO fixtures assert
  that behavior.
- `py/swarm_do/pipeline/validation.py`, `schemas/pipeline.schema.json`,
  `py/swarm_do/pipeline/editing.py`, `py/swarm_do/pipeline/actions.py`, and
  `py/swarm_do/pipeline/providers.py` all assume provider stages are MCO-only.
- `bin/swarm providers doctor` currently has only the MCO passthrough shape:
  `--mco`, `--mco-timeout-seconds`, and a `required_providers` contract based on
  provider stage types.
- Codex structured-output precedent exists in `bin/codex-review-phase`, but
  there is no equivalent implemented Claude `claude -p --json-schema` or
  `--permission-mode plan` proof. The only Claude read-only signal in the repo
  today is the MCO permissions JSON value `{"permission_mode": "plan"}`.
- A local CLI surface check on 2026-04-25 found the expected Codex flags
  (`codex exec --sandbox`, `--output-schema`, and `--output-last-message`) and
  Claude flags (`claude -p --permission-mode plan`, `--json-schema`,
  `--tools`, and `--disallowedTools`). This confirms command-surface
  plausibility, not read-only safety or auth readiness.
- ADR `0004` is already assigned to plan-prepare. The internal provider review
  ADR must therefore be `docs/adr/0005-internal-provider-review-runner.md`.

## Steady-State Operator UX

The desired behavior:

1. The operator configures model lanes once through `${CLAUDE_PLUGIN_DATA}/backends.toml`,
   preset routing, or a future TUI surface.
2. `bin/swarm providers doctor` reports which review providers are configured,
   installed, schema-capable, authenticated enough to launch, and selected for
   the active preset.
3. A normal `/swarmdaddy:do` or `/swarmdaddy:review` run includes provider
   review evidence when one or more providers are available.
4. Provider review is always read-only. It never owns Beads, routing, memory,
   merges, quality gates, or repo writes.
5. If no providers are available, the provider review stage records a clean
   skipped result and the normal Claude-backed review path continues.

This is a shim-registry model, not arbitrary command scanning. Swarm-do should
probe only known providers with explicit read-only command builders. That keeps
the default automatic while avoiding surprise execution of random local tools.

## Configuration Shape

Use the existing backend resolver for Claude and Codex wherever possible:

- Claude provider route defaults to the resolved `agent-review` route.
- Codex provider route defaults to the resolved `agent-codex-review` route.
- Preset routing can override those role routes exactly as it does today.
- Later providers that do not map to existing roles can live under an explicit
  `[review_providers]` table in `backends.toml`.

Suggested optional config extension:

```toml
[review_providers]
selection = "auto"       # auto | explicit | off
min_success = 1
max_parallel = 4
include = []             # empty means all eligible known shims
exclude = []

[review_providers.claude]
enabled = true

[review_providers.codex]
enabled = true

[review_providers.gemini]
enabled = false
model = "gemini-review-model"
effort = "high"
```

Configuration precedence:

1. Provider model routing is route-first. Claude and Codex use the existing
   backend resolver path:
   preset routing overrides `${CLAUDE_PLUGIN_DATA}/backends.toml`, which
   overrides role defaults. Auth remains in the provider's native CLI
   configuration or environment. Provider review must not add a second
   model/auth table for Claude or Codex.
2. Providers without an existing role route, such as initial Gemini or ACP
   shims, put shim-local model/effort selection under
   `[review_providers.<provider>]`. Credentials never live there; auth remains
   native CLI or environment configuration.
3. `[review_providers]` controls provider-review policy: selection mode,
   include/exclude, max parallelism, minimum success, and provider-specific
   enablement.
4. Presets may add a `[review_providers]` table only for run-shaping policy
   such as `selection`, `include`, `exclude`, `max_parallel`, and `min_success`.
   Presets should not carry credentials or duplicate provider model/auth.
5. Stage YAML should not carry provider model/auth. Stock pipelines may use only
   `selection: auto` or `selection: off` and must not carry a `providers` list.
   User or experiment pipelines may carry `providers` only with
   `selection: explicit`. Validation must reject `providers` in stock pipelines
   and reject `providers` under `selection: auto` or `selection: off`.

Pipelines should not need provider names for the common case:

```yaml
- id: provider-review
  depends_on: [writer]
  provider:
    type: swarm-review
    command: review
    selection: auto
    output: findings
    memory: false
    timeout_seconds: 1800
  failure_tolerance:
    mode: best-effort
```

User-forked pipelines may still pin providers for experiments, but stock
pipelines should prefer `selection: auto`.

Auto-selection DSL semantics:

- `provider.type = "swarm-review"` supports `selection = "auto" | "explicit" |
  "off"`.
- With `selection: auto`, `providers` must be absent; the resolver selects
  eligible shims from config and local readiness.
- With `selection: explicit`, `providers` is required and is interpreted as a
  stable provider allowlist, still subject to read-only/schema eligibility.
- With `selection: off`, the stage writes a skipped artifact and launches no
  providers. This is the config-level kill switch for stock pipelines.
- Dry-run and budget preview must estimate provider stages before launching any
  provider. `selection: off` contributes `0`; `selection: explicit` contributes
  the explicit provider count capped by `max_parallel`; `selection: auto`
  contributes `min(max_parallel, eligible_shims)` when doctor cache data is
  available and otherwise `min(max_parallel, known_shim_count)` as an upper
  bound with an estimate warning. The run artifact records the actual
  configured, selected, launched, and schema-valid counts.
- `failure_tolerance.quorum.min_success` is evaluated against schema-valid
  provider outputs. If fewer providers are selected than `min_success`, the
  stage is `partial` or `skipped` and downstream review continues only when the
  tolerance mode allows it.

## Provider Discovery

Add a `ReviewProviderResolver` beside `BackendResolver`.

For each known shim, discovery should produce:

- `provider_id`: `claude`, `codex`, `gemini`, or `acp:<name>`.
- resolved route: backend, model, effort, and setting source when applicable.
- executable path or ACP endpoint config.
- CLI version.
- schema mode: native schema, parser fallback, or unavailable.
- read-only mode: confirmed command flags or unavailable.
- status: eligible, skipped, warning, or error.
- reason: missing binary, unsupported flag, disabled by config, auth failure,
  route mismatch, timeout, or ready.

Selection algorithm:

1. Start with known shim order: `claude`, `codex`, `gemini`, then sorted ACP
   agents.
2. Drop providers disabled by config or excluded by the active preset.
3. Drop providers without required read-only support.
4. Prefer native schema providers. Parser fallback is not eligible for stock
   automatic selection in v1; allow it only for doctor diagnostics or explicit
   experiment-mode runs, with a confidence cap and warning.
5. Cap selected providers at `max_parallel`.
6. Record both `configured_providers` and `selected_providers` in the artifact
   so skipped providers are observable.

## Shim Contracts

Codex v1 command:

```bash
codex exec --json \
  --sandbox read-only \
  -C <repo> \
  --output-schema <emission-schema-file> \
  --output-last-message <last-message-file> \
  <prompt>
```

Do not use `codex exec review` for v1 because the local reviewed CLI surface
does not expose `--output-schema` there.

Claude v1 command:

```bash
claude -p \
  --permission-mode plan \
  --output-format json \
  --json-schema '<minified-emission-schema>' \
  <prompt>
```

Claude should be native-schema first. Parser fallback exists only to survive CLI
flag drift. It should cap confidence, and it should not be enabled for stock
automatic provider review until native schema output is stable. In the first
implementation, parser fallback is a doctor diagnostic or an explicit
experiment-mode option.

Claude read-only eligibility is a validation gate, not an assumption. Before the
Claude shim is marked eligible, doctor must prove the installed CLI supports the
chosen structured-output flags and a read-only tool posture. Phase 0 must prove
whether `--permission-mode plan` is sufficient by itself; if not, the shim must
add explicit tool restrictions with
`--tools`/`--disallowedTools` and tests that demonstrate repo writes are denied.
Until that proof exists, Claude can report `schema-capable` but not
`read-only-confirmed`.

This proof is a Phase 0 prerequisite for Claude shim implementation, not
parallel research or broad external investigation. Validate the installed
Claude CLI locally with a focused write-denial fixture: a provider prompt must
fail to create, edit, or delete files in a temporary repo while using the exact
planned read-only flags. Shim command builders must not mark Claude eligible
until a doctor probe validates the CLI flags and this fixture is green. Codex
has existing `--output-schema` precedent, but still needs a Phase 0 CLI-drift
test for the exact `codex exec --json --sandbox read-only --output-schema`
surface before the Codex shim is eligible.

ACP v1-later contract:

- initialize
- session/new
- session/prompt
- collect session/update until completion
- validate final text locally against the emission schema

ACP is only a transport shim. Consensus, dedupe, schema enforcement, and
artifact ownership stay in swarm-do.

## Emission Schema

Add a small model-facing schema, for example:

`schemas/provider_review/review_emission.v1.schema.json`

It should contain only fields the model is allowed to claim:

- `findings[]`
- `severity`
- `category`
- `summary`
- `file_path`
- `line_start`
- `line_end`
- `confidence`
- `evidence`
- `recommendation`

It should not contain:

- `run_id`
- `timestamp`
- `finding_id`
- `provider_count`
- `detected_by`
- `consensus_score`
- `stable_finding_hash_v1`
- `schema_ok`
- artifact paths
- provider error rows

Those fields are swarm-owned and are added only after local validation.

## Normalization And Consensus

Normalization should reuse the existing hash and path logic:

- Normalize paths with `swarm_do.telemetry.extractors.paths.normalize_path`.
- Compute `stable_finding_hash_v1` with the existing pinned implementation.
- Use the same severity/category normalization already used by the MCO spike
  unless a cleaner shared helper is split out.

Dedupe rules:

- Group findings by non-null `stable_finding_hash_v1`.
- Merge `detected_by` from provider ids that reported the same hash.
- Add a secondary consensus cluster key for anchored findings so equivalent
  reports are not missed merely because summaries differ. The candidate key
  should use normalized file path, normalized line range, normalized category,
  and, when available, evidence snippet similarity. Keep
  `stable_finding_hash_v1` as the telemetry-stable row hash; use the secondary
  key only for provider-review consensus grouping.
- Preserve per-provider raw findings under the raw artifact directory, not in
  the normalized finding row.
- If a finding cannot produce a stable hash, keep it as unverified evidence and
  do not merge it with unrelated unanchored findings.

Consensus rules for provider-findings v2:

- `provider_count` means schema-valid provider outputs, not merely selected
  providers.
- `agreement_ratio = len(detected_by) / provider_count` when `provider_count > 0`.
- `max_confidence` is the maximum validated provider confidence after local caps.
- `consensus_score = agreement_ratio * max_confidence`.
- `consensus_level`:
  - `confirmed` when at least two providers agree and the score is high enough.
  - `needs-verification` when one provider or a low score reports useful evidence.
  - `unverified` for malformed, fallback-capped, or weakly anchored findings.

Confidence caps:

- Native schema output can use the provider's emitted confidence up to `1.0`.
- Parser fallback should cap at `0.65`.
- Findings without a file and line anchor should cap at `0.50`.
- Provider outputs that validate only after repair should cap at `0.50` and
  record the repair reason.
- Secondary consensus clusters must not raise stock/default confidence until
  empirical Claude/Codex samples show acceptable false-merge and false-split
  behavior. Before that calibration, only exact stable-hash agreement can drive
  `confirmed` confidence in stock pipelines; anchored clusters remain
  `needs-verification` evidence.

## Pre-Implementation Validation Gates

Complete these before implementation begins:

- **Claude read-only flags:** validate locally with a write-denial fixture, not
  broad research. The fixture must prove the selected Claude read-only flags
  deny create, edit, and delete attempts in a temporary repo before Claude can
  become eligible.
- **Non-spend auth probing:** run a small prototype investigation for Claude and
  Codex. The result should identify the lowest-cost installed/authenticated/
  launchable probe shape for doctor, or document that no true non-spend probe
  exists and the fallback must be explicit and bounded.
- **Consensus clustering:** run empirical clustering research before any
  secondary cluster contributes stock/default confidence. Use real or captured
  Claude/Codex native-schema outputs to estimate false merge and false split
  rates, then set the initial confidence policy.

## Artifact Contract

Keep writing one provider artifact under the run stage directory:

```text
${CLAUDE_PLUGIN_DATA}/runs/<run_id>/stages/<stage_id>/provider-findings.json
```

Expected raw sidecars:

```text
provider-review.manifest.json
providers/<provider_id>/stdout.jsonl
providers/<provider_id>/stderr.txt
providers/<provider_id>/last-message.json
providers/<provider_id>/meta.json
```

The manifest should record the normalized prompt hash, schema version, command
argv without secrets, CLI versions, timeout settings, selection policy, and raw
sidecar paths. Raw sidecars may contain model output and local paths; retention
and redaction policy must be documented before provider review is enabled by
default.

Minimum retention/redaction policy before the runner merge:

- Raw sidecars are local run artifacts, not telemetry ledgers, and are retained
  or purged with the run artifact directory unless a later ADR defines a
  shorter raw-provider window.
- The manifest records command argv only after secret redaction. It must not
  record environment variables, credential file contents, API keys, OAuth
  tokens, or provider config files.
- The manifest records a prompt hash and prompt path, not an inline copy of the
  prompt. The prompt file may still exist elsewhere in the run artifact tree.
- Raw stdout/stderr/last-message files are classified as sensitive because they
  may contain code snippets, local paths, tool logs, and model reasoning. They
  stay out of `${CLAUDE_PLUGIN_DATA}/telemetry/` until a separate promotion
  decision says otherwise.
- Doctor output and normalized `provider-findings.json` should avoid storing
  raw provider text except for bounded evidence snippets already allowed by the
  v2 schema.

Schema strategy is side-by-side, not in-place mutation:

- Keep `schemas/telemetry/provider_findings.schema.json` as the
  `provider-findings.v1-draft` MCO spike contract. Existing MCO fixtures and
  `py/swarm_do/pipeline/tests/test_mco_stage.py` remain v1 tests.
- Add `schemas/telemetry/provider_findings.v2.schema.json` for
  `provider-findings.v2-draft` normalized swarm-review artifacts.
- Add `schemas/provider_review/review_emission.v1.schema.json` for direct
  model emission before swarm-owned normalization.
- In v2, top-level `provider` becomes `swarm-review`, `status` includes
  `skipped`, provider errors identify the shim and failure class, and
  `configured_providers`, `selected_providers`, `launched_providers`, and
  `provider_count` are distinct.
- In v2 only, `provider_count` means schema-valid provider outputs. The v1 MCO
  meaning is left unchanged to avoid silent fixture churn.
- Fixture migration is additive: keep `mco_review_*` fixtures under the v1 test
  path, add new `provider_review_*` fixtures for v2, and add one compatibility
  test proving v1 MCO artifacts still validate after v2 lands.

## Pipeline Integration

Replace the MCO lab path in these steps:

1. Keep `mco-review-lab` unchanged for comparison.
2. Add a new internal stage type value, `provider.type = "swarm-review"`, and
   allow `selection: auto` with no hardcoded `providers` list.
3. Update pipeline validation, JSON schema, graph rendering, budget preview,
   stage editing helpers, and TUI mutation helpers that currently assume
   `provider.type = "mco"`.
4. Update the `/swarmdaddy:do` orchestration skill and any executor helpers so
   `provider.type = "swarm-review"` dispatches `bin/swarm-provider-review`,
   while `provider.type = "mco"` continues to dispatch `bin/swarm-stage-mco`
   only for the lab path.
5. After runner validation, add the automatic provider stage to stock
   review-capable pipelines instead of requiring an opt-in `mco-review-lab`
   preset.

Candidate placements:

- Implementation pipelines: after `writer`, parallel with `spec-review`, before
  final `agent-review`.
- Output-only review pipeline: as the read-only evidence collector before the
  final review synthesis.
- Hybrid review: replace the special `agent-codex-review` lane with the
  provider-review stage only after the consumer inventory and Codex parity
  criteria below are complete.

Failure behavior:

- Best-effort by default.
- A provider-stage error never accepts or rejects a phase by itself.
- Downstream Claude review receives a short evidence summary plus the artifact
  path.
- Doctor can fail preflight only when the active pipeline requires provider
  review and no eligible provider is available after configuration says it
  should be on.

MCO retirement criteria:

- The internal runner has parity fixtures for the successful MCO cases and at
  least one partial-failure case.
- Stock pipelines use `swarm-review` and no stock preset requires MCO.
- `README.md`, `tui/README.md`, and command help describe MCO as an experiment
  or omit it from normal requirements.
- ADR 0005 is accepted as the preferred provider-review direction and then
  supersedes ADR 0003 so it no longer says provider stages are MCO-only.
- `mco-review-lab` remains available only as an explicitly experimental
  comparison preset, or is removed after the comparison data is no longer
  useful.

Codex lane retirement criteria:

- Before replacing `agent-codex-review`, inventory all consumers of that role,
  including `bin/swarm-run`, `bin/swarm-gpt-review`, `pipelines/hybrid-review.yaml`,
  `data/pipelines/*`, role specs, telemetry extractors, schemas, generated docs,
  fixtures, presets, and TUI/catalog module entries.
- Keep the existing lane until `swarm-review` preserves its blocking-issues
  contract, timeout/discard behavior, telemetry extraction, and hybrid-review
  operator UX.

## Doctor And TUI

Extend `swarm providers doctor`:

```bash
bin/swarm providers doctor --review --json
```

This is a new flag on the existing `providers doctor` subcommand, not a new
subcommand. Existing MCO flags stay:

- `--mco` continues to run the MCO passthrough doctor for the lab path.
- `--mco-timeout-seconds` continues to apply only to the MCO passthrough.
- `--review` runs internal review-provider shim probes for the active preset or
  requested preset. If the active pipeline contains a required `swarm-review`
  stage, doctor may run review checks automatically; otherwise no-flag behavior
  remains backward compatible.

Report:

- active preset and pipeline
- resolved review provider config
- eligible providers
- skipped providers with reasons
- exact CLI versions
- exact schema/read-only flags detected
- selected provider count
- whether the active pipeline would run, skip, or fail provider review

JSON return contract migration:

- Preserve current top-level `ok`, `active_preset`, `pipeline_name`,
  `required_backends`, `required_providers`, and `checks` for compatibility.
- Add `review_required`, `review_policy`, `configured_review_providers`,
  `eligible_review_providers`, `selected_review_providers`,
  `skipped_review_providers`, `review_schema_flags`, `review_read_only_flags`,
  and `review_selection_result` when `--review` is used or a `swarm-review`
  stage is required.
- Text output should keep the existing `SKIPPED provider:mco` behavior for the
  default no-MCO case, and add separate `provider-review:<id>` rows for internal
  review shims.
- Test migration must cover the current MCO contract, a review-only contract, and
  a combined `--review --mco` report.

TUI follow-up:

- Rename MCO-specific provider editing helpers to generic provider-review
  helpers.
- Show configured versus selected providers.
- Keep MCO-specific controls only in the experiment/comparison path.

## Implementation Work Breakdown

0. **Phase 0 gates before coding**
   - Reserve `docs/adr/0005-internal-provider-review-runner.md` with
     `Status: Proposed` and `Intended to supersede: ADR 0003` before
     implementation docs begin. Do not mark ADR 0003 fully superseded until the
     internal runner passes its Phase 0 gates and becomes the preferred
     provider-review path.
   - Prove Claude eligibility with a doctor flag probe for structured output and
     read-only mode plus a local write-denial fixture, not broad research. The
     fixture must demonstrate that create, edit, and delete attempts are denied.
     Block Claude shim eligibility until this is green.
   - Prototype non-spend auth probing for Claude and Codex. Doctor must be able
     to distinguish installed, authenticated, and launchable states without a
     full review run, or record that the provider only supports an explicit,
     bounded spend probe.
   - Empirically validate secondary consensus clustering before it affects
     stock/default confidence. Until that data exists, only exact hash matches
     may produce stock `confirmed` confidence; secondary clusters stay
     `needs-verification`.
   - Add a Codex CLI-drift test for the exact
     `codex exec --json --sandbox read-only --output-schema` command builder.
   - Land the fake-shim fixture harness used by runner, doctor, DSL validation,
     and downstream evidence tests. The minimum end-to-end fake-shim scenarios
     are no eligible providers, selection off, partial provider failure,
     malformed output, timeout, no findings, and duplicate findings across two
     providers.
   - Lock the side-by-side schema decision: v1 MCO remains unchanged, v2
     provider-review lives beside it.
   - Define raw sidecar retention, redaction, and manifest policy before the
     runner merge, not merely before stock default enablement.
   - Inventory `agent-codex-review` consumers before any retirement work.

1. **Plan and ADR refresh**
   - Add this plan.
   - Add ADR 0005 stating that internal provider review is intended to supersede
     MCO as the preferred path, while MCO remains a comparison spike.
   - Add explicit MCO retirement criteria and mark ADR 0003 superseded by
     ADR 0005 when `swarm-review` becomes the preferred stage.

2. **Emission schema**
   - Create `schemas/provider_review/`.
   - Add `schemas/provider_review/review_emission.v1.schema.json`.
   - Add `schemas/telemetry/provider_findings.v2.schema.json`.
   - Add schema tests for minimal valid finding, no-findings result, and invalid
     model-owned swarm fields.
   - Add compatibility tests proving existing MCO v1 fixtures still validate.

3. **Provider resolver**
   - Add `ReviewProviderResolver`.
   - Reuse `BackendResolver` for Claude and Codex route selection.
   - Add config parsing for optional `[review_providers]` in
     `${CLAUDE_PLUGIN_DATA}/backends.toml` and preset-scoped policy overrides.
   - Add unit tests for auto, explicit include/exclude, disabled providers, and
     deterministic ordering.

4. **Shim command builders**
   - Start only after the Phase 0 eligibility and CLI-drift gates are green.
   - Add Claude and Codex shim classes.
   - Capture version, command, schema mode, read-only mode, and meta.
   - Add tests that assert exact command argv and fail closed on missing flags.
   - Add a Claude read-only proof test before marking the Claude shim eligible;
     if `--permission-mode plan` is insufficient, add explicit tool restrictions
     and test that write attempts are rejected.

5. **Runner**
   - Add `bin/swarm-provider-review`.
   - Run selected providers in parallel with per-provider timeout.
   - Store raw sidecars and a manifest under the Phase 0 retention/redaction
     policy.
   - Validate native schema output before normalization.
   - Parser fallback is allowed only behind explicit experiment-mode selection,
     doctor diagnostics, and confidence caps. It is not eligible for stock
     automatic provider review in v1.

6. **Normalizer**
   - Normalize provider findings into side-by-side provider-findings v2 draft.
   - Reuse `stable_finding_hash_v1`.
   - Group exact duplicate hashes first, then apply the anchored secondary
     consensus key for same-location/same-category reports with divergent
     summaries. Merge `detected_by`, compute provider count, consensus score,
     and consensus level.
   - Add fixtures for all-success, partial failure, malformed output, no
     findings, no eligible providers, and duplicate consensus.
   - Keep MCO v1 fixtures and tests intact; add v2 fixtures instead of rewriting
     v1 expected payloads.

7. **Doctor**
   - Extend provider doctor with the `--review` flag and review-provider checks.
   - Keep current MCO passthrough for the lab path.
   - Preserve current MCO JSON/text contract and add tests for review-only and
     combined `--review --mco` output.

8. **Pipeline DSL**
   - Add `provider.type = "swarm-review"`.
   - Add `selection = "auto"` and optional `providers` only for
     `selection: explicit` in user or experiment pipelines.
   - Update JSON schema, manual validation, graph rendering, stage-agent count,
     budget preview, quorum semantics, and pipeline tests for auto-selection.
   - Update `py/swarm_do/pipeline/editing.py`,
     `py/swarm_do/pipeline/actions.py`, and
     `py/swarm_do/pipeline/providers.py` MCO-only guards.
   - Add stock-pipeline validation rejecting hardcoded `providers` lists for
     `swarm-review`.

9. **Orchestrator dispatch**
   - Update `skills/swarmdaddy/SKILL.md` so MCO and internal provider stages use
     different helpers.
   - Dispatch `bin/swarm-provider-review` with stage id, run id, issue id, repo,
     prompt file, output directory, timeout, and selection policy.
   - Pass the normalized summary and artifact path to downstream review exactly
     like the MCO evidence path, without allowing provider output to mutate
     Beads outside the provider-stage issue.
   - Audit `.claude-plugin/plugin.json` and marketplace packaging assumptions for
     the new binary. The current manifest does not enumerate `bin/` helpers, so
     record whether this is a no-op or add the required manifest metadata if the
     packaging surface changes.

10. **Stock pipeline wiring**
   - Add provider-review to stock review-capable pipelines after runner tests
     pass.
   - Remove the need for a separate opt-in MCO review preset for normal use.
   - Keep `mco-review-lab` marked experiment for comparison only.
   - Do not retire `agent-codex-review` until the consumer inventory and parity
     criteria above are satisfied.

11. **Docs and UI**
    - Update README provider requirements and CLI reference.
    - Update telemetry README for provider-findings v2 draft.
    - Update TUI state labels from MCO-specific to provider-review-specific.

## Test Matrix

- `python -m unittest py.swarm_do.pipeline.tests.test_provider_review`
- `python -m unittest py.swarm_do.pipeline.tests.test_providers`
- `python -m unittest py.swarm_do.pipeline.tests.test_pipeline_validation`
- `python -m unittest py.swarm_do.pipeline.tests.test_pipeline_actions`
- `python -m unittest py.swarm_do.telemetry.tests.test_extractors_hashing`
- schema tests for `schemas/provider_review/review_emission.v1.schema.json`
- schema tests for side-by-side provider-findings v1/v2 compatibility
- fixture tests for Codex native schema output
- fixture tests for Claude native schema output
- fixture tests for parser fallback confidence caps
- fixture tests for duplicate consensus across Claude and Codex
- fake-shim end-to-end tests for no eligible providers, selection off, partial
  provider failure, malformed output, timeout, and duplicate anchored findings
- CLI drift tests for current `codex exec` and `claude -p` flags
- write-denial tests proving eligible provider shims cannot modify repo files
- doctor contract tests for current MCO-only, review-only, and combined
  `--review --mco` output

## Risks

- **CLI drift:** mitigate through doctor checks, version capture, exact argv
  tests, and parser fallback with lower confidence.
- **Too much schema trust:** avoid by making the model emission schema small and
  adding swarm-owned fields only after local validation.
- **Auto-selection surprise cost:** doctor and dry-run must show selected
  providers before run start, with config-level include/exclude and max-parallel
  controls.
- **Read-only drift:** never treat a provider as eligible because it is merely
  installed. Eligibility requires current CLI flags, schema support, and a
  verified read-only posture.
- **Consensus false negatives:** exact stable hashes may miss equivalent
  reports with different wording. Use anchored secondary grouping cautiously and
  keep unanchored findings unmerged.
- **Raw artifact exposure:** raw provider output may include prompts, paths,
  snippets, and tool logs. Define retention, redaction, and manifest policy as a
  merge gate before the runner stores raw sidecars, and revisit before stock
  default enablement.
- **ACP scope creep:** keep ACP behind the shim interface. Do not move consensus,
  schema policy, memory, or orchestration into ACP.
- **Provider evidence overreach:** provider findings remain evidence for the
  downstream review stage, not quality gates.

## Research And Validation Decisions

This queue separates discovery work from implementation gates. Anything marked
as a gate must be proven before a provider is eligible or before the runner
stores raw sidecars; it is not optional future research.

| Topic | Decision | Timing |
| --- | --- | --- |
| Claude read-only flags | Validate locally with the write-denial fixture, not broad research. The installed CLI exposes `--permission-mode plan`, `--json-schema`, `--tools`, and `--disallowedTools`; eligibility still requires proving prompts cannot create, edit, or delete repo files. | Pre-implementation Phase 0 gate before Claude can be marked `read-only-confirmed` or eligible. |
| Non-spend auth probing for Claude/Codex | Yes, this needs small prototype research. Doctor should distinguish installed, authenticated, and launchable without running a full review. Prefer native no-op/status probes; if a probe may spend tokens, make it explicit and bounded. | Pre-implementation Phase 0 gate before finalizing real doctor/provider probes; fake shims can land first. |
| Consensus clustering quality | Yes, this needs empirical research before secondary clusters affect stock/default confidence. v1 can still implement exact-hash grouping and a conservative anchored key, but real Claude/Codex outputs must be sampled for false merge and false split rates before promotion. | Pre-implementation Phase 0 gate before promoting secondary-cluster `confirmed` confidence in stock/default behavior. |
| Parser-fallback default policy | No more research is needed for v1 policy. Parser fallback is off for stock automatic provider review and allowed only for doctor diagnostics or explicit experiment-mode runs, with confidence caps. | Resolved for v1; revisit only after real native-schema and fallback data is collected. |
| Provider artifact retention/redaction | A concrete policy decision is required before the runner writes raw sidecars, but this should be handled as a Phase 0 design gate rather than open-ended research. Use the minimum policy in the artifact contract above. | Phase 0 gate before runner merge. |
| End-to-end fake-shim tests | Not research. These are mandatory implementation fixtures for no eligible providers, selection off, partial failure, malformed output, timeout, no findings, and duplicate findings. | Phase 0 harness plus runner/normalizer tests. |

Remaining research after the v1 runner is usable:

- Re-measure the secondary consensus key as provider behavior changes.
- Revisit parser fallback only if native schema support proves too brittle.
- Tune non-spend auth probes as provider CLIs add or remove status surfaces; the
  initial probe shape is still a pre-implementation gate.

## Resolved Decisions

- Provider-findings v2 lives beside the current v1 MCO schema. Do not mutate
  `schemas/telemetry/provider_findings.schema.json` in place.
- v2 `provider_count` means schema-valid provider outputs. The v1 MCO meaning
  remains unchanged.
- The internal provider review ADR is ADR 0005 because ADR 0004 is already
  assigned to plan-prepare.
- ADR 0005 starts as intended supersession. ADR 0003 is not marked fully
  superseded until the internal runner passes Phase 0 and becomes the preferred
  provider-review path.
- `swarm providers doctor --review` is a new flag on the existing doctor
  subcommand; `--mco` and `--mco-timeout-seconds` remain for the lab path.
- Fake-shim integration fixtures, Claude read-only proof, Codex CLI-drift proof,
  and raw sidecar policy are Phase 0 merge gates, not future research.
- Parser fallback is not enabled for stock automatic provider review in v1. It
  is limited to doctor diagnostics or explicit experiment-mode runs until real
  data justifies promotion.

## Open Decisions

- Whether the first stock default should run a single eligible provider or skip
  until at least two providers are available. Single-provider output is still
  useful, but it should be labeled `needs-verification`.
- Whether output-only `/swarmdaddy:review` should always run provider review or
  only when the target is a diff/branch rather than a broad question.
