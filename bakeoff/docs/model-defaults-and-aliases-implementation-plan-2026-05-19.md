# Model Defaults And Aliases Implementation Plan

Date: 2026-05-19

## Goal

Make Bakeoff's default model choices easier to keep current without adding a
hidden routing system or weakening work-order replayability.

The intended product behavior is:

- Generated/default work orders use Claude Code's stable tier aliases for
  Claude participants: `sonnet` for workers and `opus` for judges.
- Codex defaults remain the current explicit maintained model id for now:
  `gpt-5.5`.
- User-authored full model ids keep working exactly as they do today.
- Runtime behavior remains work-order-driven: once a work order exists, that
  JSON is the complete source of model configuration.

## Current State

Runtime model selection is already work-order-driven. `model` is a required
participant field and is only validated as a non-empty string. The provider
runner passes it directly to the backend CLI:

- Claude: `claude -p --model <model> --effort <effort>`
- Codex: `codex exec -m <model> -c model_reasoning_effort="<effort>"`

The fragile part is not runtime selection. The fragile part is duplicated
defaults:

- `internal/provider/provider.go` defines `DefaultModelIDs`.
- `internal/workorder/templates/*.work-order.json` embed dated Claude model ids.
- `examples/*.work-order.json` duplicate those ids.
- `skills/bakeoff/SKILL.md` tells Claude to draft defaults in natural-language
  flows using tier prose such as "Claude Sonnet" and "Claude Opus".
- `commands/run.md` does not currently contain model-default references.
- `internal/commands/doctorcmd/doctor.go` displays and probes those defaults.

Local `claude --help` explicitly documents that `--model` accepts aliases such
as `sonnet` or `opus`, or a full model name such as `claude-sonnet-4-6`. This
means Bakeoff can use aliases for fresh generated defaults while preserving
full ids for pinned runs.

## Non-Goals

Do not add any of the following in this change:

- A `~/.bakeoff` or `${CLAUDE_PLUGIN_DATA}` model config file.
- Runtime profile routing such as `cheap`, `balanced`, `premium`, or
  `claude-only`.
- Model catalog validation or live model discovery.
- Automatic migration or mutation of existing work-order files.
- A TUI or setup flow for model selection.
- Any hidden runtime override that changes what an existing work order runs.

These are intentionally out of scope because Bakeoff's strongest UX property is
that the work order is all the run configuration the user needs.

## Explicitly Out Of Scope

Do not clean up every dated model string found by `rg`. This change is about
generated defaults and current user-facing examples, not historical fixtures or
proof that full model ids remain accepted.

Leave these alone unless a later implementation step gives a specific reason:

- `internal/reviewcontext/reviewcontext_test.go`; its dated ids are fixture
  data and help prove full model ids remain valid.
- Existing test work orders whose purpose is not generated defaults.
- Historical implementation plans and research notes under `docs/`, including
  `docs/competitive-builds-implementation-plan-2026-05-18.md`,
  `docs/review-context-and-run-manifest-implementation-plan-2026-05-16.md`,
  `docs/faceted-research-implementation-plan-2026-05-15.md`,
  `docs/operator-ux-dogfood-tightening-implementation-plan-2026-05-15.md`,
  `docs/research-llm-languages-2026-05-16.md`, and
  `docs/review-research-2026-05-19.md`.
- `commands/run.md`; it has no model-default wording today, so there is nothing
  to update there for this change.

## Recommended Design

Add a tiny model defaults catalog and point all default-generation surfaces at
it. Keep runtime pass-through behavior unchanged.

### Default Values

Use these generated defaults:

| Role | Backend | Model | Effort |
| --- | --- | --- | --- |
| Claude worker | `claude` | `sonnet` | `high` |
| Codex worker | `codex` | `gpt-5.5` | `high` |
| Judge | `claude` | `opus` | `xhigh` |
| Claude auth/build probe | `claude` | `sonnet` | probe-specific |
| Codex auth/build probe | `codex` | `gpt-5.5` | probe-specific |

Keep `claude_haiku` in doctor output as an explicit dated id unless/until the
Claude CLI is verified to accept `haiku` as a non-interactive `--model` alias in
the same way it documents `sonnet` and `opus`.

The `gpt-5.5` Codex value is preserved from the current implementation. This
plan does not independently verify that it is the newest or best Codex model id.
If that is in doubt, add a separate provider-compatibility check before changing
the Codex default.

## Implementation Steps

### 1. Add Central Defaults Package

Create:

```text
internal/modeldefaults/models.go
```

Suggested API:

```go
package modeldefaults

const (
	ClaudeSonnet = "sonnet"
	ClaudeOpus   = "opus"

	// Keep explicit until the Claude CLI's haiku alias behavior is verified.
	ClaudeHaiku = "claude-haiku-4-5-20251001"

	CodexDefault = "gpt-5.5"
	CodexGPT5    = "gpt-5"
)

func DoctorModelIDs() map[string]string {
	return map[string]string{
		"claude_sonnet": ClaudeSonnet,
		"claude_opus":   ClaudeOpus,
		"claude_haiku":  ClaudeHaiku,
		"codex":         CodexDefault,
		"codex_gpt5":    CodexGPT5,
	}
}
```

Return a fresh map so callers cannot mutate package-level defaults.

### 2. Replace Provider Defaults Map

Update `internal/provider/provider.go`:

- Remove `DefaultModelIDs`, or keep it only as a deprecated compatibility
  wrapper if another package needs a transitional path.
- Do not add model alias resolution here.
- Do not validate model names here.

The provider runner should keep passing `participant.Model` through unchanged.

### 3. Update Doctor

Update `internal/commands/doctorcmd/doctor.go`:

- Build the JSON `defaults` object from `modeldefaults.DoctorModelIDs()`.
- Print defaults using the same existing key order.
- Use `modeldefaults.ClaudeSonnet` for Claude auth probes.
- Use `modeldefaults.CodexDefault` for Codex auth probes.
- Use the same constants in build preflight probes.

Expected `doctor --skip-auth-probe --json` defaults after the change:

```json
{
  "claude_haiku": "claude-haiku-4-5-20251001",
  "claude_opus": "opus",
  "claude_sonnet": "sonnet",
  "codex": "gpt-5.5",
  "codex_gpt5": "gpt-5"
}
```

### 4. Update Init Templates

Update every embedded work-order template under:

```text
internal/workorder/templates/
```

Replace:

```text
claude-sonnet-4-6 -> sonnet
claude-opus-4-7   -> opus
```

Leave:

```text
gpt-5.5
```

Templates affected:

- `gather.work-order.json`
- `compare.work-order.json`
- `analyze.work-order.json`
- `review.work-order.json`
- `build.work-order.json`

### 5. Update Public Examples

Apply the same Claude-only replacements in:

```text
examples/*.work-order.json
```

This keeps copied examples aligned with `bakeoff init`.

### 6. Update Natural-Language Drafting Instructions

Update:

```text
skills/bakeoff/SKILL.md
```

Replace the current default-provider section:

```text
Default providers:

- research: Claude Sonnet high and Codex GPT-5.5 high, with scope selected by
  task shape;
- build: both providers use `scope: "codebase"`;
- judge: Claude Opus xhigh.
```

With:

```text
Default providers:

- research: Claude `sonnet` high and Codex `gpt-5.5` high, with scope selected
  by task shape;
- build: both providers use `scope: "codebase"`;
- judge: Claude `opus` xhigh.

Use Claude aliases for generated defaults. Use full provider model ids only
when the user asks to pin a specific version.
```

This is documentation-only guidance for work-order drafting. Do not mention or
implement hidden model preferences.

Do not edit `commands/run.md` for this change. It has no model-default wording
today.

### 7. Update Work-Order Documentation

Update `docs/work-orders.md` near the participant field description.

Add a concise section:

```md
## Model Names

Bakeoff passes `model` through to the selected backend CLI. Claude defaults use
tier aliases such as `sonnet` and `opus`, which follow Claude Code's current
alias behavior. Use a full provider model id when a run should be pinned to a
specific version.

Claude alias resolution may depend on operator/provider configuration such as
`ANTHROPIC_DEFAULT_SONNET_MODEL` or `ANTHROPIC_DEFAULT_OPUS_MODEL`. Use full ids
when exact replay matters.

The requested model strings are recorded in `meta.json` under `resolved_models`.
Bakeoff does not currently record the provider-resolved dated id behind a
Claude alias.
```

Do not claim Bakeoff resolves aliases itself.

Also update the minimal build JSON example in `docs/work-orders.md` so its
Claude provider uses `sonnet` and its judge uses `opus`. Keep the Codex example
as `gpt-5.5`.

### 8. Optional README Note

If the README has room near work-order examples or budgets, add one sentence:

```md
Generated work orders use Claude model aliases (`sonnet`, `opus`) so defaults
stay current; use full model ids in the work order to pin exact versions.
```

Keep this brief. Do not introduce a new configuration concept.

## Tests

### Unit Tests

Update `internal/workorder/workorder_test.go`:

Do not update unrelated work-order samples solely because they contain dated
Claude ids. Those samples help prove full provider ids remain valid. Instead,
add a focused template parsing test, for example
`TestInitTemplatesUseModelDefaults`, that:

1. Calls `InitTemplate` for each init kind.
2. Strips JSONC comments with `StripJSONCComments`.
3. Decodes the template.
4. Asserts:
   - Claude provider model equals `modeldefaults.ClaudeSonnet`.
   - Codex provider model equals `modeldefaults.CodexDefault`.
   - Judge model equals `modeldefaults.ClaudeOpus`.

Use the `review` init kind's effective type as-is; it should still contain a
`gather` work order with the `code-review` facet.

Add a matching focused examples test, for example
`TestPublicExamplesUseModelDefaults`, that:

1. Reads each `examples/*.work-order.json` file.
2. Decodes it with the same JSON path used for normal work orders.
3. Asserts Claude provider models use `modeldefaults.ClaudeSonnet`, Codex
   provider models use `modeldefaults.CodexDefault`, and judge models use
   `modeldefaults.ClaudeOpus`.

Keep this test limited to current public examples. Do not make it scan
historical docs, old fixtures, or unrelated test data.

Update `internal/commands/doctorcmd/doctor_test.go`:

- Add a new JSON-focused test, for example
  `TestRunDoctorJSONReportsModelDefaults`.
- Use `newDoctorFakeFactory(t, true)`.
- Run `runDoctor(context.Background(), f, &DoctorOptions{SkipAuthProbe: true,
  Quiet: true, JSON: true})`.
- Decode with the existing `decodeDoctorReport(t, out)` helper.
- Assert `report["defaults"]` contains:
  - `claude_sonnet == "sonnet"`;
  - `claude_opus == "opus"`;
  - `claude_haiku == "claude-haiku-4-5-20251001"`;
  - `codex == "gpt-5.5"`;
  - `codex_gpt5 == "gpt-5"`.

Suggested shape:

```go
func TestRunDoctorJSONReportsModelDefaults(t *testing.T) {
	f, out := newDoctorFakeFactory(t, true)

	err := runDoctor(context.Background(), f, &DoctorOptions{
		SkipAuthProbe: true,
		Quiet:         true,
		JSON:          true,
	})
	if err != nil {
		t.Fatal(err)
	}

	report := decodeDoctorReport(t, out)
	defaults := report["defaults"].(map[string]any)
	if defaults["claude_sonnet"] != "sonnet" {
		t.Fatalf("defaults = %#v", defaults)
	}
}
```

Expand the sample assertions rather than keeping only the single example check.
`SkipAuthProbe` avoids live model spend while still exercising doctor JSON and
scope capability setup through fakes.

If doctor fake providers need to assert received argv later, assert model
arguments are aliases for Claude and explicit ids for Codex.

### Parity Fixtures

Expect parity fixture updates for init and doctor outputs, especially:

- `tests/parity/fixtures/init_gather/normalized.json`
- `tests/parity/fixtures/init_compare/normalized.json`
- `tests/parity/fixtures/init_analyze/normalized.json`
- `tests/parity/fixtures/init_review/normalized.json`
- `tests/parity/fixtures/init_build/normalized.json`
- `tests/parity/fixtures/doctor_human/normalized.json`
- `tests/parity/fixtures/doctor_skip_auth_json/normalized.json`
- `tests/parity/fixtures/doctor_build_json/normalized.json`

The current parity script has no `--update` mode. Use it to identify the exact
diffs, then update only the expected `normalized.json` files that correspond to
the intended default changes:

```sh
python3 scripts/parity-go.py --list
python3 scripts/parity-go.py init_gather init_compare init_analyze init_review init_build doctor_human doctor_skip_auth_json doctor_build_json
```

Do not introduce an update mode in this implementation unless the fixture edits
become too error-prone. That would be useful tooling, but it is not required for
the model-default change.

## Validation

Run:

```sh
go test ./...
```

Then run the parity workflow:

```sh
python3 scripts/parity-go.py init_gather init_compare init_analyze init_review init_build doctor_human doctor_skip_auth_json doctor_build_json
python3 scripts/parity-go.py
```

Finally spot-check:

```sh
bin/bakeoff init gather --force
bin/bakeoff doctor --skip-auth-probe --json
```

Inspect the generated gather work order and doctor JSON to confirm:

- Claude worker model is `sonnet`.
- Judge model is `opus`.
- Codex worker model remains `gpt-5.5`.

## Rollout Notes

This is a defaults change, not a schema change.

Existing work orders continue to run unchanged because Bakeoff still accepts
arbitrary non-empty model strings. Users who want exact repeatability can keep
using full provider model ids in work orders. Users who prefer fresh Claude
tiers can use `sonnet` and `opus`.

There is a real reproducibility tradeoff: `model: "sonnet"` and `model: "opus"`
track Claude's current alias behavior, and may also be affected by operator
environment defaults such as `ANTHROPIC_DEFAULT_SONNET_MODEL`,
`ANTHROPIC_DEFAULT_OPUS_MODEL`, or `ANTHROPIC_DEFAULT_HAIKU_MODEL`. The
work-order and run metadata will show the requested alias, not the dated model
id that Claude ultimately selected. That is acceptable for generated defaults,
but users need full ids when exact replay matters.

The release note should say:

```text
Generated work orders now use Claude model aliases (`sonnet`, `opus`) instead
of dated Claude model ids. Full model ids are still supported when you want to
pin a run to a specific provider version.
```

## Maintenance Guardrails

- Keep all generated defaults in `internal/modeldefaults`.
- Keep templates and examples covered by tests so they cannot drift silently.
- Keep runtime pass-through behavior unchanged.
- Do not add a second runtime config surface unless there is repeated user
  evidence that editing work orders is not enough.
- If Codex gains a stable documented alias or profile that tracks the latest
  recommended model, evaluate switching `CodexDefault` separately.
- Re-check the explicit Codex default during normal release maintenance; this
  plan preserves `gpt-5.5` but does not validate it against a live model
  catalog.
