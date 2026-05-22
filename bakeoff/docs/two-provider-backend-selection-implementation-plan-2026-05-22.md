# Two-Provider Backend Selection Implementation Plan - 2026-05-22

## Summary

Add Gemini and GitHub Copilot as optional Bakeoff provider backends while
preserving the current exactly-two-provider work-order shape.

This is intentionally smaller than full multi-provider expansion. Bakeoff keeps
its current A/B design: two worker providers run the same work order, the judge
compares A and B with the existing swapped-position flow, and build mode compares
two candidate patches. The new capability is choosing which two providers are in
that pair.

Default generated work orders stay:

- Worker A: `claude` / `sonnet`
- Worker B: `codex` / `gpt-5.5`
- Judge: `claude` / `opus`

That is the canonical default pair. Natural-language drafting may use a
runnable fallback pair when the user did not explicitly choose providers and the
canonical pair is unavailable on the current machine. For example, if Claude and
Gemini are configured but Codex is missing, `/bakeoff:run ...` may draft
Claude + Gemini and call out that fallback in the preview. Existing work-order
files are never rewritten or substituted automatically.

Users may choose a different two-provider pair at work-order creation time, such
as `claude + gemini`, `claude + copilot`, `codex + gemini`, or
`gemini + copilot`.

If the user asks to "use Gemini as well" against the default Claude+Codex pair,
the drafting flow should ask one clarification because that implies three
providers, which remains out of scope for this pass.

## Goals

- Preserve exactly two entries in `providers`.
- Preserve current defaults: Claude + Codex workers, Claude Opus judge.
- Add a draft-time fallback default when the canonical Claude+Codex pair is not
  runnable but another two-provider pair is already available locally.
- Add `gemini` and `copilot` as valid optional backends.
- Let generated work orders select a two-provider pair from
  `claude`, `codex`, `gemini`, and `copilot`.
- Keep provider credentials out of work orders, logs, and Bakeoff-owned config.
- Use locally configured provider CLIs and their existing auth stores.
- Extend `doctor` so it reports optional provider availability and auth state.
- Keep artifacts, reports, manifests, and decision files compatible with the
  existing pairwise model.

## Non-Goals

- No 3+ provider work orders.
- No N-way judge prompts.
- No majority voting, tournament brackets, or multi-provider build selection.
- No global model router or Octopus-style model wizard.
- No API SDK integration and no Bakeoff-managed API keys.
- No automatic install of Gemini or Copilot CLIs.
- No automatic provider substitution for existing work-order paths or replayed
  runs. Fallback applies only while drafting a new natural-language work order
  with implicit provider choice.
- No changes to agent-codex-review-style cross-model review workflows or other
  external multi-agent review patterns. This plan only changes Bakeoff provider
  adapters, doctor readiness, and two-provider pair selection.
- No user-facing judge selection in generated drafts. The judge remains Claude
  by default. Manual work orders may use any catalog backend as the judge once
  that backend adapter exists.

## Research Basis

### External Projects

#### dsifry/metaswarm

Metaswarm uses an optional adapter layer rather than making external providers
part of the core path.

Facts from the external research agent:

- `.metaswarm/external-tools.yaml` is optional. If absent, external tools are not
  used.
- Its template defaults include Codex, Gemini, timeouts, routing hints, and
  budgets.
- The `external-tools` skill supports OpenAI Codex CLI and Google Gemini CLI,
  checks health per task dispatch, uses isolated worktrees, validates results,
  and requires cross-model review.
- Credentials are adapter-specific and minimal: Codex checks CLI login status or
  `OPENAI_API_KEY`/`CODEX_API_KEY`; Gemini checks `GEMINI_API_KEY`,
  `~/.gemini`, or ADC-style credentials.
- Setup and health commands surface optional external tool state rather than
  treating every provider as required.

Primary sources:

- https://github.com/dsifry/metaswarm/blob/main/templates/external-tools.yaml
- https://github.com/dsifry/metaswarm/blob/main/skills/external-tools/SKILL.md
- https://github.com/dsifry/metaswarm/blob/main/skills/external-tools/adapters/codex.sh
- https://github.com/dsifry/metaswarm/blob/main/skills/external-tools/adapters/gemini.sh
- https://github.com/dsifry/metaswarm/blob/main/commands/external-tools-health.md

Pattern to borrow:

- Optional provider adapters.
- Per-dispatch health checks.
- Isolated workspaces for edit-capable providers.
- No-op fallback when optional provider config is absent.

#### nyldn/claude-octopus

Octopus has a broad provider control plane. It is more powerful than Bakeoff
needs, but its provider discovery and override precedence are useful references.

Facts from the external research agent:

- Agents declare `cli`, `model`, phases, tier, permissions, memory, and worktree
  isolation in `agents/config.yaml`.
- Model resolution uses `~/.claude-octopus/config/providers.json` with
  precedence: env override, session override, phase/role routing, capability
  mapping, cost tier, config default, then hardcoded fallback.
- It has a central model catalog with context, capability, provider, tier, and
  status metadata across Codex, Gemini, Claude, Cursor Agent, OpenRouter,
  OpenCode, Perplexity, Copilot, and others.
- Provider detection and doctor logic cover many CLIs, env vars, OAuth/config
  files, local servers, and CLI status probes.
- It isolates external provider env and can load env files for non-interactive
  shells.

Primary sources:

- https://github.com/nyldn/claude-octopus/blob/main/agents/config.yaml
- https://github.com/nyldn/claude-octopus/blob/main/scripts/lib/model-resolver.sh
- https://github.com/nyldn/claude-octopus/blob/main/scripts/lib/models.sh
- https://github.com/nyldn/claude-octopus/blob/main/scripts/lib/providers.sh
- https://github.com/nyldn/claude-octopus/blob/main/scripts/lib/doctor.sh

Pattern to borrow:

- A clear provider catalog.
- Predictable override precedence.
- Optional/session availability reporting.
- Good remediation text in doctor output.

Pattern not to borrow in this pass:

- Full model routing by phase, role, tier, debate participants, and review
  provider sets. That would make Bakeoff much larger than the requested feature.

#### obra/superpowers

Superpowers is harness-oriented rather than provider-oriented.

Facts from the external research agent:

- Plugin manifests expose skills and metadata, not model/provider defaults.
- Bootstrap instructions teach each harness how to load skills, including
  Claude, Copilot, Gemini, Codex, and OpenCode.
- Subagent workflows discuss model choice generically but do not configure
  concrete provider model IDs.
- Credential handling is absent from core; service-specific config belongs in
  separate plugin/harness support.

Primary sources:

- https://github.com/obra/superpowers/blob/main/README.md
- https://github.com/obra/superpowers/blob/main/skills/using-superpowers/SKILL.md
- https://github.com/obra/superpowers/blob/main/skills/subagent-driven-development/SKILL.md
- https://github.com/obra/superpowers/blob/main/CLAUDE.md

Pattern to borrow:

- Keep core workflows provider-neutral where possible.
- Keep credentials and service-specific setup outside core.
- Add harness/provider adapters without turning the whole plugin into a
  credential manager.

### Provider CLI Notes

#### Gemini CLI

Official Gemini CLI docs indicate the CLI supports non-interactive/headless use,
model selection, output format control, auth through local configuration or env,
and approval/sandbox modes for tool use.

Primary sources:

- https://google-gemini.github.io/gemini-cli/docs/cli/headless.html
- https://google-gemini.github.io/gemini-cli/docs/cli/configuration.html
- https://google-gemini.github.io/gemini-cli/docs/cli/authentication.html

Implications for Bakeoff:

- The adapter should pass the work-order prompt on stdin, not as a process
  argument.
- Default model alias can be `pro`.
- Build mode needs a non-interactive approval mode that allows file edits.
  Prefer the least broad mode that works, such as `--approval-mode auto_edit`
  when the installed CLI advertises it. `--approval-mode yolo` or legacy
  `--yolo` is broader and should be used only when needed and recorded in scope
  metadata. If non-interactive edit capability cannot be confirmed via help
  probe, build preflight must fail with remediation pointing to the Gemini
  headless/configuration docs for `--approval-mode` / `--yolo`.

#### GitHub Copilot CLI

GitHub's Copilot CLI docs now describe programmatic use. It can accept prompts
from stdin or `-p`, can select a model, can run without asking the user, and has
tool allow/deny controls.

Primary sources:

- https://docs.github.com/en/copilot/concepts/agents/copilot-cli/about-copilot-cli
- https://docs.github.com/en/copilot/how-tos/use-copilot-agents/use-copilot-cli
- https://docs.github.com/en/copilot/how-tos/copilot-cli/automate-copilot-cli/run-cli-programmatically

Implications for Bakeoff:

- The adapter should pass prompts on stdin and use `--no-ask-user` for
  non-interactive runs.
- Default model can be `auto`.
- Research mode should avoid write tools.
- Build mode can allow write tools in isolated worktrees and let Bakeoff's patch
  capture, protected paths, and verifier gates remain the safety layer.

## Current Bakeoff Surfaces To Update

### Work-Order Schema and Validation

Current state:

- `Participant` carries `id`, `backend`, `model`, `effort`, and `scope`.
  See `internal/workorder/workorder.go`.
- Valid backends are hard-coded as `claude` and `codex`.
- `validateProviders` requires exactly two providers.
- `validateProviders` requires provider IDs to be unique and providers to differ
  on at least one of backend, model, or scope.
- `validateJudge` prevents the judge backend+model from matching a worker
  backend+model.

Required updates:

- Keep the exactly-two-provider requirement.
- Replace the local backend enum with a provider catalog lookup.
- Allow `gemini` and `copilot` for worker participants.
- Keep existing ID uniqueness and differing-triple validation.
- Continue validating model as a non-empty string rather than restricting to
  known model IDs, so users can pin provider-specific model versions.
- Validate `judge.backend` through the same provider catalog and allow manual
  work orders to use `gemini` or `copilot` as judge once their adapters exist.
  Generated drafts still default to `claude` / `opus`.

Important files:

- `internal/workorder/workorder.go`
- `internal/workorder/workorder_test.go`
- `docs/work-orders.md`

### Provider Launch and Capability Detection

Current state:

- `provider.BuildParticipantArgv` switches on `participant.Backend`.
- Claude launch shape is `claude -p --model <model> --effort <effort>`.
- Codex launch shape is `codex exec -m <model> -c model_reasoning_effort=...`.
- Version and help probes support only `claude`, `codex`, and `git`.
- Capability parsing is backend-specific and currently only understands
  Claude/Codex scope controls.

Required updates:

- Introduce a provider catalog in `internal/provider`, for example:

```go
type BackendSpec struct {
    Name         string
    Executable   string
    DefaultModel string
    Optional     bool
    PromptFlavor string
    SupportsBuild bool
}
```

- Add helper functions:
  - `KnownBackends() []BackendSpec`
  - `ValidBackend(name string) bool`
  - `DefaultModel(name string) string`
  - `VersionArgv(tool string) ([]string, error)`
  - `ScopeHelpArgv(backend string) ([]string, error)`
  - `BuildParticipantArgv(...)`

- Keep argv construction adapter-local.
- Keep prompts on stdin. Do not put user work-order text in process arguments.

Initial launch shapes:

| Backend | Executable | Default model | Research argv sketch | Build additions |
| --- | --- | --- | --- | --- |
| `claude` | `claude` | `sonnet` | existing `claude -p --model <model> --effort <effort>` | existing scope/tool flags |
| `codex` | `codex` | `gpt-5.5` | existing `codex exec -m <model> ...` | existing workspace-write sandbox |
| `gemini` | `gemini` | `pro` | `gemini --model <model>` with prompt on stdin | `--approval-mode auto_edit` when available; fail build preflight with remediation if non-interactive edit mode cannot be confirmed |
| `copilot` | `copilot` | `auto` | `copilot --model <model> --no-ask-user` with prompt on stdin | allow write/edit tool if help advertises it |

Important files:

- `internal/provider/provider.go`
- `internal/provider/provider_test.go`
- `internal/commands/shared.go`
- `internal/scope/scope.go`
- `internal/commands/buildcmd/scope.go`

### Scope Enforcement

Current state:

- Research mode:
  - Claude codebase/web scopes use `--disallowedTools` or `--allowedTools`.
  - Codex codebase/web scopes use `--sandbox read-only`; codebase scope also
    uses `--disable web_search`.
  - Web scope can use an isolated temp CWD.
- Build mode:
  - Claude codebase scope blocks web tools when possible.
  - Codex build requires `--sandbox workspace-write`.

Required updates:

- Add scope capability parsing for Gemini/Copilot based on their installed
  `--help` output.
- Mark unavailable controls as partial/advisory in `scope_enforcement` rather
  than pretending all providers have equivalent controls.
- For build mode, continue to rely on isolated worktrees, patch capture,
  protected path checks, and verifier gates as the hard safety layer.
- Do not fail optional providers at doctor time just because they lack perfect
  scope controls; fail only when the requested run cannot be made
  non-interactive or cannot edit when build mode requires editing.

Conservative v1 behavior:

- Research `codebase`: use CWD plus prompt instruction; deny/write-block tools
  when a provider exposes reliable controls.
- Research `web`: use isolated CWD; allow web/search controls only when a
  provider exposes reliable controls.
- Research `mixed`: no extra restrictions beyond prompt and runner budget.
- Build: require provider-specific non-interactive edit capability in doctor
  build preflight.

### Prompt Fixtures

Current state:

- `prompt.workerFixtureBackend` returns `codex` only for Codex; all other
  backends fall back to Claude-flavored fixtures.
- Fixtures exist for `worker-*-claude.txt` and `worker-*-codex.txt`.
- The Codex build fixture includes a Codex workspace-write sandbox instruction.

Required updates:

- Make fallback explicit through a provider prompt flavor instead of relying on
  `if backend == codex else claude`.
- Recommended minimal design:
  - `claude` uses existing Claude fixtures.
  - `codex` uses existing Codex fixtures.
  - `gemini` and `copilot` use a `generic-terminal-agent` flavor, initially
    copied from the Claude fixture with provider-neutral wording.
- Define the generic flavor by a scrub checklist before adding fixtures:
  - No provider names in behavioral instructions: Claude Code, Claude, Codex,
    Gemini, Copilot, OpenAI, Anthropic, or Google unless the work-order content
    itself mentions them.
  - No provider-specific CLI flags or tool controls, such as `--allowedTools`,
    `--disallowedTools`, `--sandbox`, `--disable`, `--approval-mode`, `--yolo`,
    or `--no-ask-user`.
  - No provider-specific sandbox claims, such as "Codex workspace-write
    sandboxing" or assumptions that a provider can hard-disable web search.
  - No model names or family names in fixture text.
  - Agent instruction/config file warnings should be generalized. Keep
    `CLAUDE.md` and `AGENTS.md`, but add relevant generic/provider-local config
    paths such as `GEMINI.md`, `.claude/*`, `.codex/*`, `.gemini/*`, and
    `.github/copilot-instructions.md`.
  - Scope enforcement must be described as the harness/provider metadata says,
    not as a fixture-level guarantee.
- Add tests proving Gemini/Copilot prompts are selected deliberately and do not
  mention Claude/Codex-only sandbox assumptions.

Important files:

- `internal/prompt/prompt.go`
- `internal/prompt/fixtures/*`
- `internal/prompt/prompt_test.go`
- `internal/prompt/fixtures/manifest.json`

### Pairwise Judge and Decision Logic

Current state:

- Research mode uses `wo.Providers[0]` and `wo.Providers[1]` as A/B.
- Compare/analyze/build modes run swapped judge passes.
- Gather/review uses one structured-union pass with A/B mapping.
- Build judge only runs when exactly two eligible patches need comparison.

Required updates:

- No conceptual change for this pass.
- Keep all pairwise logic.
- Preserve exactly two providers so existing A/B code remains valid.
- Add tests proving a non-default pair flows through the same A/B code paths.

Important files:

- `internal/commands/researchcmd/run.go`
- `internal/commands/buildcmd/judge.go`
- `internal/decision/decision.go`
- `internal/report/report.go`

### Doctor

Current state:

- Doctor loops over `claude`, `codex`, and `git`.
- Scope capability probes are hard-coded for `claude` and `codex`.
- Auth probes run only Claude and Codex.
- Build preflight runs only Claude and Codex.
- Defaults and bias messages name Claude/Codex directly.

Required updates:

- Split provider readiness into canonical defaults, optional providers, and
  runnable pair selection.
- Canonical default backends:
  - `claude`
  - `codex`
- Required tool for most workflows:
  - `git`
- Optional provider backends:
  - `gemini`
  - `copilot`
- Missing optional providers should not fail `bakeoff doctor`.
- Missing Codex should fail canonical default readiness but should not
  automatically fail overall readiness if Claude plus one optional provider is
  installed and usable. Doctor should report the selected fallback pair and warn
  that the canonical default pair is degraded.
- Missing Claude should continue to fail the MVP because the generated judge
  remains Claude and the fallback policy anchors on Claude plus one peer.
- If optional providers are installed, doctor should report:
  - executable path
  - version
  - default model
  - auth probe status, unless `--skip-auth-probe`
  - scope capabilities
  - build preflight status when `--build`
- JSON output should expose optional provider data in stable fields rather than
  only in warning strings.
- Existing work-order validation remains separate from doctor readiness. Doctor
  reports what can be drafted by default; running an explicit work-order file
  still succeeds or fails based on the backends named in that file.

Potential JSON shape:

```json
{
  "canonical_default_pair": ["claude", "codex"],
  "selected_default_pair": ["claude", "gemini"],
  "fallback_candidates": [["claude", "gemini"]],
  "fallback_requires_user_choice": false,
  "canonical_default_available": false,
  "runnable_default_pair_available": true,
  "providers": {
    "claude": {
      "canonical_default": true,
      "required_for_selected_default": true,
      "available": true,
      "path": "/path/to/claude",
      "version": "...",
      "default_model": "sonnet",
      "auth_probe": {"status": "ok"},
      "scope_capabilities": {}
    },
    "gemini": {
      "canonical_default": false,
      "required_for_selected_default": true,
      "available": true,
      "path": "/path/to/gemini",
      "version": "...",
      "default_model": "pro"
    }
  }
}
```

When Codex is missing and both Gemini and Copilot are available, doctor should
still report `runnable_default_pair_available: true`, but there is no single
selected pair until the user chooses:

```json
{
  "canonical_default_pair": ["claude", "codex"],
  "selected_default_pair": null,
  "fallback_candidates": [["claude", "gemini"], ["claude", "copilot"]],
  "fallback_requires_user_choice": true,
  "canonical_default_available": false,
  "runnable_default_pair_available": true
}
```

Keep existing top-level `tools`, `defaults`, `scope_capabilities`, and
`auth_probes` long enough to avoid unnecessary parity fixture churn, but prefer
the new `providers` map for new behavior.

Important files:

- `internal/commands/doctorcmd/doctor.go`
- `internal/commands/doctorcmd/doctor_test.go`
- `tests/parity/fixtures/doctor_*`

### Default Pair Resolution

Default pair resolution is a drafting concern, not a schema concern.

Rules:

1. If the user explicitly names providers, use those providers or ask a
   clarification if the request implies more or fewer than two.
2. If the user does not name providers and Claude+Codex are available, draft
   Claude+Codex.
3. If the user does not name providers, Claude is available, Codex is missing,
   and exactly one optional backend is available, draft Claude plus that backend.
4. If the user does not name providers, Claude is available, Codex is missing,
   and both Gemini and Copilot are available, ask which second provider to use.
5. If the user does not name providers and no runnable two-provider pair exists,
   surface the missing-provider issue and direct the user to doctor/setup.
6. Never auto-substitute providers for an existing work-order path, rerun, or
   replayed artifact.

Expose the same result as structured data for scripting: `fallback_candidates`
lists valid fallback pairs, and `fallback_requires_user_choice` is true when more
than one fallback pair is runnable and no implicit selection should be made.

Availability levels:

- `installed`: executable found and version probe works.
- `auth_ready`: provider can complete the lightweight auth probe.
- `build_ready`: provider can complete the live edit probe in a temporary
  workspace.

For natural-language draft selection, prefer `auth_ready` when the normal doctor
or quickstart data is available. If the user skipped auth probes, `installed`
can select the draft fallback, but the preview should say the fallback provider
has not been auth-probed. Build drafts should prefer `build_ready` when known;
otherwise the preview should warn that doctor `--build` may be needed before
running.

Preview wording example:

```text
Codex is not available on this machine. Gemini is available, so this draft uses
Claude + Gemini.

Providers: claude/sonnet + gemini/pro
Judge: claude/opus
```

### Artifacts, Manifests, and Reports

Current state:

- Provider IDs, backend, model, scope, and effort are already recorded
  generically in meta/manifests.
- `provider_cli_versions` is fixed to Claude/Codex/Git.
- Stderr classification has Codex-specific transport-noise handling.

Required updates:

- Record CLI versions for every backend present in the work order, plus `git`.
- Keep provider status tables generic.
- Keep Codex-specific stderr normalization as a backend-specific classifier, and
  add no Gemini/Copilot special cases unless tests show noisy-but-successful
  stderr patterns.

Important files:

- `internal/artifact/artifact.go`
- `internal/manifest/manifest.go`
- `internal/report/report.go`

### Secret Handling

Current state:

- `runnerenv.SafeEnv` removes `ANTHROPIC_`, `OPENAI_`, and generic secret-like
  env vars.
- This means provider CLIs mostly rely on local auth stores rather than inherited
  API key env vars.

Required updates:

- Keep default behavior: do not leak env keys to provider child processes.
- Add explicit prefix scrub coverage for:
  - `GEMINI_`
  - `GOOGLE_`
  - `GITHUB_`
  - `COPILOT_`
- Continue scrubbing generic markers like `TOKEN`, `SECRET`, `API_KEY`, and
  `PASSWORD`.
- If a future CI workflow needs env-key forwarding, make that an explicit
  opt-in allowlist, not part of this provider-selection MVP.

Important files:

- `internal/runnerenv/runnerenv.go`
- `internal/runnerenv/runnerenv_test.go`

## User-Facing Drafting Behavior

### Natural Language

Default:

- If the user does not specify providers and Claude + Codex are available, draft
  Claude + Codex.
- If the user does not specify providers, Codex is unavailable, Claude is
  available, and exactly one optional backend is available, draft Claude plus the
  available optional backend and call out the fallback in the preview.
- If the user does not specify providers, Codex is unavailable, Claude is
  available, and both Gemini and Copilot are available, ask which second provider
  to use.
- If the user explicitly asks for Codex, never silently replace Codex.
- If the user supplies a work-order path, never rewrite or substitute the
  provider pair.
- Common spelling normalization, such as interpreting "Gemeni" as Gemini, should
  live in the `/bakeoff:run` language-extraction instructions. Do not add
  separate fuzzy provider matching to the Go CLI in this MVP.

Supported examples:

- "use Claude and Gemini"
- "use Claude + Gemini"
- "replace Codex with Gemini"
- "use Copilot instead of Claude"
- "use Codex and Copilot"
- "use Gemeni and Claude" may normalize the common misspelling to Gemini in the
  LLM drafting layer.

Ambiguous examples:

- "use Gemini as well"
- "add Gemini"
- "include Gemini too"

For ambiguous add/as-well wording, ask one clarification:

> Bakeoff supports exactly two providers for now. Should Gemini replace Claude or
> Codex for this work order?

For implicit fallback wording, do not ask when there is only one runnable
fallback pair. State the fallback:

> Codex is not available on this machine. I found Gemini, so I will draft this
> work order as Claude + Gemini.

Generated preview should show the provider pair explicitly:

```text
Providers: claude/sonnet + gemini/pro
Judge: claude/opus
```

### Manual Work Orders

Manual work orders continue to use:

```json
"providers": [
  {"id": "claude", "backend": "claude", "model": "sonnet", "scope": "codebase", "effort": "high"},
  {"id": "gemini", "backend": "gemini", "model": "pro", "scope": "codebase", "effort": "high"}
]
```

No new top-level provider config is needed.

### `bakeoff draft-build`

Add repeatable provider flags:

```text
bakeoff draft-build ... --provider claude --provider gemini
bakeoff draft-build ... --provider claude:sonnet --provider gemini:pro
```

Rules:

- Exactly zero or two `--provider` flags.
- Zero means canonical default Claude + Codex for this CLI command. Do not use
  environment-dependent fallback in `draft-build` unless a later flag explicitly
  requests it; command stdout should be deterministic for scripts.
- Two means use exactly those providers.
- `backend:model` pins a model.
- `backend` alone uses the provider catalog default model.
- Duplicate provider IDs should be disambiguated only if useful later; for this
  MVP, duplicate backend entries can be rejected unless the model differs and the
  user supplied explicit IDs in a manual work order.

Potential future flag, not required for MVP:

```text
--judge claude:opus
```

## Implementation Work Breakdown

### Phase 1: Provider Catalog, No Behavior Change

1. Add provider catalog types and helpers under `internal/provider`.
2. Move Claude/Codex defaults into the catalog or have `modeldefaults` read from
   the catalog.
3. Refactor existing backend checks to use catalog helpers.
4. Keep generated defaults and behavior identical.
5. Run focused tests:
   - `go test ./internal/provider ./internal/workorder ./internal/commands/doctorcmd`

Acceptance criteria:

- Existing Claude/Codex work orders validate unchanged.
- Existing provider argv tests pass.
- Doctor output is unchanged or intentionally compatible.
- Provider catalog can answer canonical default pair separately from known
  optional backends.

### Phase 2: Add Gemini and Copilot Adapters

1. Add `gemini` and `copilot` backend specs.
2. Add argv builders.
3. Add version/help probes.
4. Add capability parsers from representative help text fixtures.
5. Add fake provider binaries for parity/integration tests.
6. Add auth probe participants for optional installed providers.

Acceptance criteria:

- `provider.BuildParticipantArgv` has unit coverage for Gemini and Copilot.
- Unknown backend validation still fails clearly.
- Doctor reports optional providers without failing when they are missing.
- Doctor can compute whether the canonical pair is available and whether a
  fallback pair is available.

### Phase 3: Work-Order Validation and Default Pair Resolution

1. Allow `gemini` and `copilot` in `Participant.Backend`.
2. Keep exactly two providers.
3. Add a default-pair resolver used by the `/bakeoff:run` natural-language
   drafting path:
   - explicit provider request wins
   - canonical Claude+Codex when available
   - Claude plus the only available optional provider when Codex is missing
   - clarification when both optional providers are available and Codex is
     missing
   - no substitution for existing work-order paths
4. Update `DraftBuildOptions` with optional provider pair.
5. Update `bakeoff draft-build` flags.
6. Update `/bakeoff:run` skill drafting instructions:
   - known backends list
   - canonical default provider pair
   - draft-time fallback provider pair
   - provider-pair extraction
   - clarification behavior for "as well" / add-third-provider wording
   - clarification behavior when multiple fallback pairs are available
7. Update examples only where useful; keep default examples Claude + Codex.

Acceptance criteria:

- A manual `claude + gemini` research work order validates.
- A manual work order with `judge.backend: "gemini"` or
  `judge.backend: "copilot"` validates when that backend is in the catalog.
- A manual three-provider work order fails with a clear error.
- `draft-build` emits default Claude + Codex without provider flags.
- `draft-build --provider claude --provider gemini` emits a valid two-provider
  build work order.
- Natural-language drafting uses Claude+Gemini when Codex is missing and Gemini
  is the only available optional backend.
- Natural-language drafting asks a clarification when Codex is missing and both
  Gemini and Copilot are available.
- Existing work-order path execution never substitutes providers.

### Phase 4: Scope and Build Preflight

1. Add Gemini/Copilot scope metadata.
2. For research, mark unsupported tool restrictions as partial/advisory.
3. For build, require non-interactive edit capability through help-probed flags
   or live build preflight.
4. Update doctor `--build` to probe optional providers when installed.
5. For Gemini specifically, prefer `--approval-mode auto_edit` when advertised.
   If no non-interactive edit mode can be confirmed from help output, fail build
   preflight with remediation that points to Gemini CLI's headless/configuration
   docs for `--approval-mode` and `--yolo`.

Acceptance criteria:

- Missing optional provider does not fail normal doctor.
- Installed-but-noninteractive optional provider is reported as unavailable for
  build, with remediation.
- Build mode with fake Gemini/Copilot provider can create a patch in an isolated
  worktree and pass through existing capture/verifier logic.

### Phase 5: Artifacts, Reports, and Docs

1. Record provider CLI versions dynamically for present backends.
2. Keep provider status report generic.
3. Update README quickstart and provider sections.
4. Update `docs/work-orders.md`.
5. Update `docs/cli-reference.md` (present in this repo).
6. Update parity fixtures after intentional output changes.

Acceptance criteria:

- `meta.json` records selected backends and models.
- `manifest.json` provider summaries include Gemini/Copilot fields when used.
- Reports still render provider IDs without hard-coded Claude/Codex assumptions.
- Docs explain exactly-two-provider selection and optional provider doctor state.

## Test Plan

Unit tests:

- Work-order validation:
  - accepts `claude + gemini`
  - accepts `codex + copilot`
  - accepts manual `judge.backend` values for any catalog backend with an
    adapter, including Gemini/Copilot
  - rejects one provider
  - rejects three providers
  - rejects unknown backend
- Provider argv:
  - Claude/Codex unchanged
  - Gemini uses stdin-safe argv and model
  - Copilot uses stdin-safe argv, model, and non-interactive flag
- Scope capabilities:
  - Gemini representative help
  - Copilot representative help
  - unavailable optional provider
- Prompt fixtures:
  - Gemini/Copilot generic flavor contains no Claude/Codex-only sandbox wording
  - generic flavor scrub test fails on provider-specific names, CLI flags,
    sandbox claims, and model names in fixture text
- Runner env:
  - scrubs `GEMINI_`, `GOOGLE_`, `GITHUB_`, and `COPILOT_` secrets
- Doctor:
  - optional providers missing does not fail
  - missing Codex with Claude+Gemini available reports canonical default
    degraded but runnable fallback available
  - missing Codex with Claude+Gemini+Copilot available reports that a fallback
    choice is needed via `fallback_requires_user_choice: true`
  - missing Claude fails MVP readiness even if optional providers are available
  - optional providers installed but auth-failing yields warnings/status
  - missing Codex fails canonical default readiness but does not fail overall
    readiness when an unambiguous runnable fallback pair exists
  - missing Claude, missing `git` for workflows that require git, or no runnable
    second provider still fails readiness
  - existing work-order path with missing named backend still fails rather than
    substituting a fallback

Integration tests with fakes:

- Research run with `claude + gemini`.
- Research run with `copilot + codex`.
- Build run with fake Gemini provider producing a patch.
- Build run with fake Copilot provider producing a patch.
- Doctor JSON with optional provider availability matrix.
- Doctor JSON with canonical and selected default pair fields.
- Doctor JSON with `fallback_candidates` and
  `fallback_requires_user_choice: true` when multiple fallback pairs exist.
- Natural-language draft preview with Codex-missing fallback wording.

Parity fixtures:

- `doctor_human`
- `doctor_build_json`
- `doctor_missing_tools_json`
- `doctor_skip_auth_json`
- Any root help or draft-build output fixture affected by new flags.

Focused commands:

```text
go test ./internal/provider ./internal/workorder ./internal/scope ./internal/runnerenv
go test ./internal/commands/doctorcmd ./internal/commands/draftbuildcmd
go test ./internal/commands/researchcmd ./internal/commands/buildcmd
```

Full validation before merge:

```text
go test ./...
scripts/parity-go.py
```

## Risks and Mitigations

### Provider CLI flag drift

Gemini and Copilot CLI flags may change.

Mitigation:

- Probe `--help` where possible.
- Keep provider-specific flag selection isolated in adapters.
- Fail doctor/build preflight with clear remediation when expected flags are
  absent.

### Non-interactive edit behavior differs by provider

Build mode depends on a provider being able to edit files without prompting.

Mitigation:

- Add doctor `--build` live probes for installed optional providers.
- Use isolated worktrees for every build provider.
- Let patch capture, protected paths, and verifier gates enforce safety.

### Scope controls are not equivalent

Claude, Codex, Gemini, and Copilot expose different tool/sandbox controls.

Mitigation:

- Record `scope_enforcement` per provider.
- Treat unsupported restrictions as partial/advisory.
- Keep prompt-level scope instructions for all providers.
- Do not claim hard enforcement unless a provider exposes a verified mechanism.

### Credential leakage

Additional provider CLIs may use env vars or local auth stores.

Mitigation:

- Continue using `runnerenv.SafeEnv`.
- Add explicit scrub prefixes for Gemini/Google/GitHub/Copilot.
- Do not write keys to work orders, artifacts, or plugin config.
- Prefer local CLI auth stores.

### Output schema compliance

New providers may be worse at emitting strict `<final_json>`.

Mitigation:

- Reuse existing format retry and salvage behavior.
- Keep provider prompts schema-heavy and provider-neutral.
- Add fake and live smoke tests before declaring build support ready.

## Resolved Decisions

- Generated judge remains `claude` / `opus`.
- Manual work orders may set `judge.backend` to `gemini` or `copilot` once that
  backend is in the provider catalog and has an adapter. Judges are participants
  and should use the same launch, capability, auth, format-retry, and artifact
  paths as workers.

## Open Questions

- Should `doctor --build` probe all installed optional providers by default, or
  only when a flag such as `--provider gemini` is supplied?
- Should natural-language draft fallback require `auth_ready`, or is `installed`
  enough when the user has skipped auth probes?
- Should `bakeoff draft-build` stay deterministic with zero `--provider` flags,
  or should it also support machine-dependent fallback through an explicit flag
  such as `--provider auto`?
- Should duplicate backend pairs with different models be allowed manually, for
  example `gemini/pro + gemini/flash`, or should v1 require different backends?
- Should provider IDs be generated from backend names only, or should
  model-specific IDs be allowed in `draft-build` when the same backend is used
  twice later?

Recommended answers for MVP:

- `doctor --build` probes installed optional providers by default, but missing
  optional providers do not fail.
- Natural-language fallback should prefer `auth_ready` when known. If auth was
  skipped, `installed` can be used for the draft preview with an explicit
  warning that auth has not been probed.
- `bakeoff draft-build` should stay deterministic by default. If fallback is
  added there later, gate it behind an explicit `--provider auto` or
  `--fallback-provider` flag.
- Require different backends for generated drafts; leave same-backend different
  model pairs to manual work orders or a later explicit feature.
- Use backend names as provider IDs in generated work orders.

## Final Recommendation

Implement provider selection as a two-provider pair feature first.

This gives users most of the requested value while preserving Bakeoff's strongest
property: small, auditable A/B runs. Add draft-time fallback for users who have
Claude plus Gemini or Copilot but not Codex, but keep the canonical default pair
as Claude+Codex and keep existing work-order execution explicit. The larger 3+
provider design should remain separate until there is evidence that pair
selection is insufficient.
