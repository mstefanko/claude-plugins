# Go-Side Draft Command Implementation Plan

Date: 2026-05-20

## Goal

Move build work-order JSON assembly out of prompt text and into the Go CLI.

The current plugin contract embeds a canonical build skeleton, drift warnings,
backend defaults, budgets, and validation guidance in both `commands/run.md`
and `skills/bakeoff/SKILL.md`. That text works, but it is prompt-maintenance
debt: every schema/default change has to be duplicated into the plugin
contract, and the model can still mis-copy field names when drafting by hand.

Add a small, non-mutating Go command that turns already-extracted build draft
inputs into validated work-order JSON:

```bash
bakeoff draft-build \
  --id lscmd-finished-at-ordering \
  --goal "Order ls output by finished_at descending" \
  --acceptance "Rows are sorted by finished_at descending." \
  --scope "internal/commands/lscmd" \
  --gate "tests=go test ./internal/commands/lscmd -run TestLsOrder -count=1"
```

The model remains responsible for classification and extraction from natural
language. Go owns canonical JSON shape, default providers, judge, budgets,
`build.verify[].argv`, and self-validation before output.

## Recommended Architecture

Ship one root-level leaf command first:

```text
bakeoff draft-build [flags]
```

Defer a broader `draft` namespace or `skeleton` command until there is a second
real command ready to ship. A namespace would force the first PR to define
parent-command behavior without adding value to the build-fast-path problem.

Why `draft-build` first:

- It addresses the load-bearing bloat directly: the embedded build skeleton and
  schema-drift reminders can shrink or disappear from plugin instructions.
- It is safer than natural-language drafting in Go. The CLI accepts typed
  fields; it does not infer missing acceptance criteria, verifier commands, or
  edit boundaries.
- It is non-mutating, so the plugin can run it before approval without
  violating the no-write-before-approval invariant.
- It reuses existing validation and defaults rather than creating a parallel
  schema implementation.

Keep `bakeoff init` unchanged. `init` writes a TODO template for humans.
`draft-build` prints approval-ready JSON for the plugin and scripts.

The product value is reliability more than net line-count reduction. A realistic
implementation may add 300-500 lines of Go, tests, and docs while trimming only
80-120 prompt lines. The win is converting build fast-path schema assembly from
an advisory prompt behavior into a Go-validated path.

## Product Contract

### Command

```text
bakeoff draft-build [flags]
```

The command writes one JSON work order to stdout and writes nothing to disk.
It exits with code `2` for usage/validation errors through the normal CLI error
path.

### Required Flags

| Flag | Repeatable | Meaning |
| --- | --- | --- |
| `--id <slug>` | no | Work-order id and suggested filename stem. |
| `--goal <text>` | no | One-sentence implementation goal. |
| `--acceptance <text>` | yes | Observable acceptance criterion. At least one required. |
| `--scope <text>` | yes | Edit boundary, such as file, package, route, or narrow prose scope. At least one required. |
| `--gate <id>=<command>` | yes | Gate verifier command. At least one required. |

`--gate` creates:

```json
{
  "id": "<id>",
  "kind": "gate",
  "argv": ["sh", "-c", "<command>"],
  "wall_clock_seconds": 300,
  "max_output_bytes": 60000
}
```

Use `sh -c` deliberately. The model usually receives verifier commands as
single shell command lines from the user; converting them to exact argv is a
different parsing problem and is not needed for this first command.

### Optional Flags

| Flag | Default | Meaning |
| --- | --- | --- |
| `--base-ref <ref>` | `HEAD` | Build base ref. |
| `--background <text>` | none | Additional context paragraph. Repeatable. |
| `--protected-path <path>` | none | Repository-relative protected path. Repeatable. |
| `--comparison-goal <text>` | standard minimal-change preference | Build comparison goal. |
| `--budget-wall-seconds <n>` | `1200` | Work-order wall budget. |
| `--budget-max-output-bytes <n>` | `80000` | Work-order output budget. |
| `--gate-wall-seconds <n>` | `300` | Default wall budget for each gate. |
| `--gate-max-output-bytes <n>` | `60000` | Default output budget for each gate. |

Do not add provider/model override flags in the first pass. The point is to
centralize the plugin defaults that are currently embedded in prose.

### Output Shape

The generated JSON should be equivalent to:

```json
{
  "schema_version": 1,
  "id": "<id>",
  "type": "build",
  "goal": "<goal>",
  "background": [
    "Acceptance criteria:\n- <acceptance 1>\n- <acceptance 2>",
    "Edit boundary:\n- <scope 1>\n- <scope 2>",
    "<background, repeated as supplied>",
    "Bakeoff will capture candidate patches from isolated worktrees and will not apply them to this checkout."
  ],
  "providers": [
    { "id": "claude", "backend": "claude", "model": "sonnet", "scope": "codebase", "effort": "high" },
    { "id": "codex", "backend": "codex", "model": "gpt-5.5", "scope": "codebase", "effort": "high" }
  ],
  "scope_policy": { "enforcement": "best_effort" },
  "judge": { "backend": "claude", "model": "opus", "effort": "xhigh" },
  "build": {
    "base_ref": "HEAD",
    "comparison_goal": "Prefer the patch that satisfies the acceptance criteria with the smallest maintainable change.",
    "verify": [
      {
        "id": "tests",
        "kind": "gate",
        "argv": ["sh", "-c", "go test ./..."],
        "wall_clock_seconds": 300,
        "max_output_bytes": 60000
      }
    ]
  },
  "budgets": {
    "wall_clock_seconds": 1200,
    "max_output_bytes": 80000,
    "heartbeat_seconds": 60,
    "output_cap_grace_seconds": 10,
    "max_output_overrun_bytes": 80000
  }
}
```

Omit `build.patch_max_bytes` from generated output so the existing validator
continues to own that default. Omit `build.protected_paths` when no
`--protected-path` values are supplied.

## Implementation Details

### 1. Add a Draft-Build Command Package

Create:

```text
internal/commands/draftbuildcmd/draft_build.go
```

Suggested command structure:

```go
type DraftBuildOptions struct {
	ID                   string
	Goal                 string
	Acceptance           []string
	Scopes               []string
	Background           []string
	Gates                []string
	ProtectedPaths       []string
	BaseRef              string
	ComparisonGoal       string
	BudgetWallSeconds    int
	BudgetMaxOutputBytes int
	GateWallSeconds      int
	GateMaxOutputBytes   int
}

func NewCmdDraftBuild(f commands.Factory, runF func(context.Context, *DraftBuildOptions) error) *cobra.Command
```

Initial root help line:

```text
draft-build         print a validated build work order
```

No parent command is added in this first pass, so there is no
parent-with-no-subcommand behavior to define.

### 2. Add a Work-Order Draft Builder

Create:

```text
internal/workorder/draft.go
```

Suggested API:

```go
type BuildDraftOptions struct {
	ID                   string
	Goal                 string
	Acceptance           []string
	Scopes               []string
	Background           []string
	Gates                []GateDraft
	ProtectedPaths       []string
	BaseRef              string
	ComparisonGoal       string
	BudgetWallSeconds    int
	BudgetMaxOutputBytes int
	GateWallSeconds      int
	GateMaxOutputBytes   int
}

type GateDraft struct {
	ID      string
	Command string
}

func DraftBuild(opts BuildDraftOptions) (any, error)
```

`DraftBuild` should:

1. Apply defaults.
   - Use `internal/modeldefaults` constants for provider and judge model names,
     rather than re-hardcoding `sonnet`, `opus`, or `gpt-5.5`.
   - Keep budget and verifier defaults local to the draft builder only if they
     are not already centralized elsewhere.
2. Validate required draft inputs before assembling JSON:
   - non-empty `ID`;
   - non-empty `Goal`;
   - at least one non-empty `Acceptance`;
   - at least one non-empty `Scopes`;
   - at least one `GateDraft`;
   - every gate has non-empty `ID` and command text.
   - no required value is a known placeholder (see "Placeholder rejection"
     below).
3. Assemble canonical `type: "build"` JSON.
4. Marshal the assembled typed value with `workorder.JSONText`.
5. Decode that JSON back to an object and call existing `Validate(data)` on it.
6. Return the original assembled typed value, not a normalized object that adds
   default-only fields like `build.patch_max_bytes`.

Keep this builder in `internal/workorder` so tests can assert the data contract
without going through Cobra, and so future draft commands reuse one package.

Use small draft-specific serializable structs, not `map[string]any`, for the
stdout document. This gives deterministic, human-friendly JSON field order and
avoids `encoding/json` map-key sorting. Do not marshal `workorder.WorkOrder`
directly: its `Background` field is normalized to a string and `BuildSpec`
would emit `patch_max_bytes`.

Suggested private structs:

```go
type buildDraftDocument struct {
	SchemaVersion int                  `json:"schema_version"`
	ID            string               `json:"id"`
	Type          string               `json:"type"`
	Goal          string               `json:"goal"`
	Background    []string             `json:"background"`
	Providers     []Participant        `json:"providers"`
	ScopePolicy   ScopePolicy          `json:"scope_policy"`
	Judge         Participant          `json:"judge"`
	Build         buildDraftSpec       `json:"build"`
	Budgets       Budgets              `json:"budgets"`
}

type buildDraftSpec struct {
	BaseRef        string              `json:"base_ref"`
	ComparisonGoal string              `json:"comparison_goal,omitempty"`
	ProtectedPaths []string            `json:"protected_paths,omitempty"`
	Verify         []VerifierSpec      `json:"verify"`
}
```

If exported tests need to inspect fields, export only the top-level return type
or test through JSON encoding; do not export extra schema types unless there is
a caller outside tests.

### 3. Parse Command Flags

In `draftbuildcmd`, use Cobra/pflag:

- `StringVar` for scalar flags.
- `StringArrayVar` for repeatable flags where commas should be preserved:
  `--acceptance`, `--scope`, `--background`, `--protected-path`, `--gate`.
- `IntVar` for budgets.

Use `StringArrayVar`, not `StringSliceVar`, because acceptance criteria and
commands can contain commas.

Parse `--gate` with the first `=` as the separator:

```text
tests=go test ./...
```

Trim both sides around the first `=`. Reject missing `=`, empty id, placeholder
id, empty command after trimming, or placeholder command. Do not split the
command into argv words; preserve the trimmed command after the first `=` as the
shell command.

Field mapping is intentionally mechanical:

| `draftbuildcmd.DraftBuildOptions` | `workorder.BuildDraftOptions` |
| --- | --- |
| `ID` | `ID` |
| `Goal` | `Goal` |
| `Acceptance` | `Acceptance` |
| `Scopes` | `Scopes` |
| `Background` | `Background` |
| parsed `Gates []string` | `Gates []workorder.GateDraft` |
| `ProtectedPaths` | `ProtectedPaths` |
| `BaseRef` | `BaseRef` |
| `ComparisonGoal` | `ComparisonGoal` |
| `BudgetWallSeconds` | `BudgetWallSeconds` |
| `BudgetMaxOutputBytes` | `BudgetMaxOutputBytes` |
| `GateWallSeconds` | `GateWallSeconds` |
| `GateMaxOutputBytes` | `GateMaxOutputBytes` |

Do not derive fields from each other in the command package. For example,
`--scope` is copied into the background edit-boundary section; it is not used to
guess protected paths.

### 3a. Placeholder Rejection

Reject known placeholders for required fields after `strings.TrimSpace`.

Use this initial exact/prefix set:

- empty string;
- case-insensitive exact `TODO`, `TBD`, `FIXME`;
- case-insensitive prefixes `TODO:`, `TODO -`, `TODO_`, `TODO-`, `TBD:`,
  `FIXME:`;
- exact template prefixes currently present in init templates:
  `ONE SENTENCE:` and `MULTI-LINE:`;
- full angle-bracket placeholders such as `<goal>`, `<scope>`, and
  `<verifier-command>`.

Apply placeholder rejection to:

- `--id`;
- `--goal`;
- each `--acceptance`;
- each `--scope`;
- each `--gate` id;
- each `--gate` command.

Do not perform semantic acceptance-criteria linting in v1. For example,
rejecting "no behavior change" or "tests pass" remains prompt guidance and
review/approval behavior, not a Go-side rule in this command.

### 4. Validate Protected Paths Through Existing Build Validation

Do not duplicate protected-path rules in the command package. Pass
`--protected-path` values into `build.protected_paths` and let
`workorder.Validate` enforce:

- repository-relative path;
- slash-separated;
- no absolute paths;
- no `..`;
- no glob syntax;
- no duplicates.

The command should return the validator's message verbatim through
`commands.WrapValidation`.

### 5. Register the Command

Update:

```text
internal/cli/root.go
```

Changes:

- import `internal/commands/draftbuildcmd`;
- add `draftbuildcmd.NewCmdDraftBuild(f, nil)` to `root.AddCommand`;
- update `rootHelp` command lists to include `draft-build`;
- update the byte-exact parity fixture
  `tests/parity/fixtures/root_help/normalized.json` in the same change;
- optionally update the orientation block's "Get started" section with
  `bakeoff draft-build ...` only if the help does not become noisy.

### 6. Update Plugin Instructions

Update:

```text
commands/run.md
skills/bakeoff/SKILL.md
```

Command front matter:

- Add `Bash(${CLAUDE_PLUGIN_ROOT}/bin/bakeoff draft-build:*)`.
- Add `Bash(bakeoff draft-build:*)`.

Contract changes:

- In build fast-path action, replace hand-built JSON with:

  ```text
  Run `bakeoff draft-build` with the extracted id, goal, acceptance criteria,
  scope, gate verifier, and optional base/protected paths. Use the emitted JSON
  as the preview source.
  ```

- Keep the R1 missing-field checklist. `draft-build` must not infer missing
  acceptance criteria, verifier, or scope; it should fail if the model tries.
- Keep R2 no-write-before-approval. Explicitly classify `bakeoff draft-build`
  as a read-only/pre-approval-safe command because it writes only stdout.
- Remove or greatly shrink the embedded build skeleton from `Canonical
  Skeletons`.
- Keep a short drift warning for non-build/manual drafts only.
- Reframe pre-preview validate:
  - build fast path: `draft-build` self-validates before stdout;
  - other draft modes: keep existing advisory pre-preview validate language.

Expected trim: roughly 80-120 lines across the two prompt-bearing files after
keeping R1/R1.6, R2, and non-build drafting guidance. Treat larger savings as a
bonus, not the justification for the change.

### 7. Update Documentation

Update:

```text
docs/work-orders.md
docs/cli-reference.md
README.md
```

Minimum docs:

- explain `bakeoff draft-build` as non-mutating stdout JSON generation;
- list required flags;
- show one simple example;
- explain that `init` is a human TODO template while `draft-build` is validated
  approval-ready JSON;
- note that `draft-build` supports gate verifiers first; metric verifier
  drafting remains manual for now.

### 8. Tests

Add unit tests for the builder:

```text
internal/workorder/draft_test.go
```

Cases:

- minimal build draft emits valid `type: "build"` JSON;
- defaults match current plugin defaults (`sonnet`, `gpt-5.5`, `opus`,
  `1200`, `80000`, gate `300`, gate `60000`);
- multiple `--acceptance`, `--scope`, and `--background` values preserve order;
- `--gate tests=go test ./...` becomes `argv: ["sh", "-c", "go test ./..."]`;
- missing acceptance/scope/gate returns validation error;
- protected path validation is enforced through `Validate`;
- output omits `build.patch_max_bytes` when the user did not ask for it.

Add command option tests:

```text
internal/commands/command_options_test.go
```

Cases:

- `draft-build` parses scalar and repeatable flags into `DraftBuildOptions`;
- comma-containing acceptance criteria and commands are not split;
- invalid `--gate` syntax fails.

Add command behavior tests:

```text
internal/commands/draftbuildcmd/draft_build_test.go
```

Cases:

- `runDraftBuild` prints decodable JSON;
- printed JSON validates through `workorder.Validate`;
- command writes only stdout and no file;
- invalid input surfaces a validation error.

Update CLI tests:

```text
internal/cli/root_test.go
tests/parity/fixtures/root_help/normalized.json
```

Regenerate `tests/parity/fixtures/root_help/normalized.json`; it is byte-exact
and will fail when root help gains `draft-build`. Add a command-output parity
fixture if the parity suite expects every root command to be represented:

```text
tests/parity/fixtures/draft_build/normalized.json
```

### 9. Manual Verification

Run:

```bash
go test ./...
```

Then manually smoke:

```bash
bakeoff draft-build \
  --id lscmd-finished-at-ordering \
  --goal "Order ls output by finished_at descending" \
  --acceptance "Rows are sorted by finished_at descending." \
  --scope "internal/commands/lscmd" \
  --gate "tests=go test ./internal/commands/lscmd -run TestLsOrder -count=1" \
  >/tmp/lscmd-finished-at-ordering.work-order.json

bakeoff validate /tmp/lscmd-finished-at-ordering.work-order.json
```

If using the plugin, run one fresh `/bakeoff:run` positive build-drafting
trial after the plugin instructions are updated and confirm:

- no hand-authored build skeleton appears in the transcript;
- `bakeoff draft-build` runs before preview;
- preview uses the emitted JSON;
- no file is written before approval;
- post-approval `bakeoff validate` still runs.

## Rollout Plan

Ship in two commits or PRs if possible:

1. Go CLI support and CLI docs.
2. Plugin prompt slimming that switches build fast-path drafting to
   `bakeoff draft-build`.

This keeps the CLI independently testable before prompt behavior depends on it.
If the plugin change behaves poorly, revert only the prompt update; the Go
command remains a harmless additive CLI surface.

## Prompt Text Expected To Shrink

Likely removable or compressible sections after `draft-build` lands:

- the full embedded build skeleton in `commands/run.md`;
- the full embedded build skeleton in `skills/bakeoff/SKILL.md`;
- most build-specific schema drift examples (`providers[].kind`,
  top-level `gates[]`, `verify[].command`, `schema_version: "1.0"`);
- part of R4 pre-preview validate wording for build fast path, because the
  draft command validates before stdout;
- repeated provider/judge/budget default prose in build drafting paths.

Do not remove:

- R1 missing-field guidance/checklist;
- R1.6 refactor edge-case guidance;
- R2 no-write-before-approval;
- available backend list, unless `draft-build` fully replaces every build path
  that would otherwise need it;
- non-build drafting guidance for gather/compare/analyze/review.

## Open Questions

1. Should this ship as `draft-build` or a `draft build` namespace?

   Recommendation: ship `draft-build` first. There is no second draft command
   ready to justify a parent namespace, and this CLI has byte-exact help
   fixtures that make every new root command explicit. Promote to a `draft`
   namespace later only when a second leaf is real.

2. Should `bakeoff skeleton-build` or `bakeoff skeleton build` exist as an
   alias?

   Recommendation: no in the first pass. Add it later only if humans ask for a
   stdout-only template command. The plugin needs `draft-build`, not another
   template surface.

3. Should `--gate` preserve shell commands as `["sh", "-c", "..."]`?

   Recommendation: yes for v1. It preserves the exact verifier string the user
   supplied and matches the current embedded skeleton. Exact argv support can be
   added later with a separate flag such as `--gate-argv-json`.

4. Should `draft-build` support metric verifiers?

   Recommendation: defer. Metric verifier drafting has more required semantics:
   metric name, direction, min delta, min runs, protected paths, and expected
   JSON output. Build-fast-path prompts already fall back when metric harness
   discovery is needed. Gate-only support captures the common case and removes
   the largest prompt skeleton.

5. Should the command write files with `--out`?

   Recommendation: no. Pre-approval safety is the central plugin benefit. Keep
   stdout-only in v1. The plugin can write after approval using the existing
   flow.

6. Should provider/model override flags be added?

   Recommendation: no in v1. Default provider/judge assembly is the bloat being
   centralized. Overrides expand the surface and should wait until there is a
   concrete user request.

7. Should output include `build.patch_max_bytes`?

   Recommendation: no. The current plugin explicitly omits it and lets Go
   validation apply the default. Emitting fewer default-only fields keeps draft
   JSON smaller and avoids locking optional defaults into generated files.

8. Should `background` be a string or array?

   Recommendation: array. It lets the command preserve acceptance criteria,
   scope, extra context, and the isolated-worktree boilerplate as distinct
   chunks without inventing a new schema field.

9. Should `draft-build` reject placeholder-looking values such as `TODO`?

   Recommendation: reject exact placeholder values for required inputs
   (`TODO`, `TODO: ...`, empty bullet strings) where it is trivial and
   unambiguous. Do not attempt semantic linting for synthesized or weak
   acceptance criteria in the first pass; that belongs in prompt guidance and
   user approval.

## Concerns And Mitigations

### Concern: this adds CLI surface area for a plugin-only workflow

Mitigation: keep the surface intentionally narrow and useful for scripts too.
It prints validated JSON from typed fields. It does not know about plugin
approval, natural-language prompts, or provider execution.

### Concern: models may blindly call `draft-build` with synthesized fields

Mitigation: keep R1/R1.6 in the prompt. Also make the command require
acceptance, scope, and at least one gate. The CLI cannot detect semantic
synthesis, but it can refuse empty placeholders and malformed verifier input.

### Concern: `sh -c` hides argv structure

Mitigation: this matches the current plugin skeleton and keeps exact user
verifier commands intact. Add exact argv support only when needed; do not make
the first command solve shell parsing.

### Concern: generated JSON could drift from validation defaults

Mitigation: build the object in one helper and call `workorder.Validate` before
printing. Add tests that decode the printed JSON and validate it. Keep provider
and model defaults sourced from `internal/modeldefaults` where practical.

### Concern: prompt slimming could remove useful non-build guidance

Mitigation: make the plugin update surgical. Only build fast-path JSON assembly
should move to Go in the first pass. Gather, compare, analyze, review, split,
and multi-lens drafting still need existing guidance.

## Done Criteria

- `bakeoff draft-build` prints validated build work-order JSON to stdout.
- The command writes no files.
- The emitted JSON passes `bakeoff validate`.
- Unit tests cover defaults, repeated flags, gate parsing, and invalid input.
- Root help and CLI docs mention `draft-build`.
- Plugin instructions use `bakeoff draft-build` for build fast-path previews.
- Prompt-bearing files shrink by removing or compressing the duplicated build
  skeleton and build schema-drift prose.
- A fresh plugin dogfood trial shows no pre-approval file write and no
  hand-authored build schema.
