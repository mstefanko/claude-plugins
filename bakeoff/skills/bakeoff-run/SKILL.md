---
name: bakeoff-run
description: "Internal handler loaded by /bakeoff:run to draft, validate, and run Bakeoff work orders."
user-invocable: false
version: "0.0.0"
allowed-tools: "Read,Write,Edit,Glob,Grep,Bash"
author: mstefanko
---

# Bakeoff Run

Own the full `/bakeoff:run` workflow. Do not satisfy the requested research,
review, comparison, analysis, or build inline. The path is preflight, classify
input, draft or validate a work order, get required approval, run
`bakeoff validate`, then run `bakeoff research` or `bakeoff build`.

Only stop before execution for CLI preflight failure, missing path-like input,
unknown or wrong-mode flags, task-fit warning, missing required draft fields,
split or multi-lens clarification or approval, or validation failure needing
repair. In those stops, ask or advise only. Local file and git reads are
allowed only to draft the work order, validate scope, or summarize artifacts.
Do not call provider CLIs directly; only the Bakeoff CLI may launch providers.

## Preflight And Input

Run first:

```bash
BAKEOFF_CLI="$("${CLAUDE_PLUGIN_ROOT}/scripts/bakeoff-ensure-cli" --check --print-path)"
[[ -n "$BAKEOFF_CLI" && -x "$BAKEOFF_CLI" ]]
```

If exit `2`, stop and direct the user to install Go 1.24+ and run
`/bakeoff:setup`, set `BAKEOFF_GO_BINARY`, or use release-binary setup. Any
other non-zero exit is an unexpected CLI resolution failure; surface the output
and direct the user to `/bakeoff:doctor`. Do not draft, validate, or run until
preflight succeeds.
If the command exits zero but the printed value is empty or not executable, stop
as an unexpected CLI resolution failure and direct the user to `/bakeoff:doctor`.

Keep the resolved `BAKEOFF_CLI` value for every CLI invocation in this workflow,
especially generated parallel launch helpers. Never hardcode cache
`dist/bakeoff` paths or re-resolve the child command inside parallel children.

Parse `$ARGUMENTS` before deciding whether the input is a path or request.
Recognize only `--out`, `--run-id`, `--base`, `--diff`, `--changed-files`,
`--quiet`, `--keep-worktrees`, `--no-triage`, and `--no-repo-layout`, with
`--flag value` and `--flag=value` forms where the flag takes a value. Remove
recognized flags from the request before classification. Unknown flags are
errors unless clearly natural-language text. If no path or request remains,
ask for a work-order path or request; do not infer a task from flags alone.

Route flags by final type: `--out`, `--run-id`, `--quiet`, and
`--no-repo-layout` may go to either `research` or `build`; `--base`, `--diff`,
`--changed-files`, and `--no-triage` go only to `research`; `--keep-worktrees`
goes only to `build`. Stop before execution on wrong-mode flags.

If the first remaining argument names an existing file, read it, inspect
`type`, run `bakeoff validate <path>`, then route `build` to `bakeoff build`
and `gather`/`compare`/`analyze` to `bakeoff research`. Existing work-order
paths bypass task-fit, natural-language drafting, split, and multi-lens logic.
Path-like missing input is an error, not a request: path separators, leading
`.`, `~`, `/`, or suffixes `.json`, `.jsonc`, `.work-order.json` are path-like.
Report the path error only and never answer the task inline.

## Drafting Invariants

These invariants apply to every natural-language drafting path: fast path,
careful path, split, and multi-lens.

- **One batched context pass.** If `/bakeoff:run` drafting needs local
  context (file paths, verifier conventions, schema, available
  backends), use ONE `ctx_batch_execute` call covering all questions.
  Sequential `Bash` / `Read` / `Grep` probes during drafting are a
  contract violation. Available backends (`claude`, `codex`, `gemini`,
  `copilot`), the canonical default pair (`claude` + `codex`), and the
  canonical work-order skeletons are embedded in the skill — do **not**
  probe the CLI (`bakeoff providers list`, `bakeoff --help`,
  `bakeoff init`) to discover them. Use `bakeoff doctor --json` only for
  current-machine readiness and fallback-pair selection.
- **No `Write` before approval.** Drafting must show the compact
  preview and wait for the preview's exact approval. Single-work-order
  previews accept `yes`, `approve`, or `run it`; multi-file split or
  multi-lens previews accept only displayed choices such as `write and
  run`, `sequential`, or `parallel`. Only then issue the file-mutating tool call.

Proposal is not approval. Repo exploration may support a read-only preview, but
it does not authorize writing or running. `bakeoff draft-build` is
pre-approval safe because it writes only validated JSON to stdout.

Classify missing required fields as explicit, repo-discoverable, or user-owned
before proposing values or asking the user. Do not silently fill defaults for
build acceptance criteria, build gate verifier command and pass condition,
metric verifier protected paths, or edit scope when no file/package/route/diff
or local-change scope is named. Repo-discoverable fields may be proposed after
one narrowly targeted, read-only batched context pass over relevant tests,
Make targets, command code, benchmarks, fixtures, and existing work orders.
User-owned fields include product intent, observable acceptance criteria,
refactor invariants, ambiguous base refs, and secret/auth material.

Synthesis-friendly defaults are limited to provider pair, judge, budgets,
`scope_policy.enforcement`, `build.base_ref` when omitted, and the skeleton
field shapes. Refactors and extracts must name concrete behavioral invariants;
do not treat "no behavior change", "existing tests pass", scope restatements,
style preferences, or verifier restatements as acceptance criteria. Do not
invent verifier placeholders such as "the conventional test command", "the auth
tests", "the build", or `go test ./internal/<pkg>/...` from a package name.

Available provider backends are `claude`, `codex`, `gemini`, and `copilot`.
Generated drafts must contain exactly two providers. The canonical provider
pair is `claude/sonnet` plus `codex/gpt-5.5`; the generated judge remains
`claude/opus`. Manual work orders may use any catalog backend as judge as long
as validation accepts the backend/model pair. If the user names an unknown
backend, ask one clarification question. Do not run `bakeoff providers list`,
`bakeoff --help`, `bakeoff init`, or scratch init commands for drafting
discovery.

Provider-pair extraction rules:

- If the user explicitly names exactly two known providers, use those providers.
- If the user asks to replace one provider with another, keep exactly two
  providers and show the resulting pair in the preview.
- If wording such as "add Gemini", "include Gemini too", or "use Gemini as
  well" applies to a just-completed run or an explicit source run id, do not
  ask which provider to replace. Route to escalation preview instead.
- If the same wording would add a third provider to a brand-new work order with
  no source run context, ask one clarification: `Bakeoff normal work orders use
  exactly two providers. Should Gemini replace Claude or Codex for this work
  order, or do you want to escalate an existing run?`
- If the user names fewer than two or more than two providers and the intended
  pair cannot be inferred without adding a third provider, ask one
  clarification.

Implicit provider selection rules:

- Run `bakeoff doctor --json --quiet --skip-auth-probe` once after CLI
  preflight when drafting from natural language and the user did not explicitly
  choose providers.
- If `selected_default_pair` is present, draft that pair. If it is not the
  canonical pair, call out the fallback in the preview.
- If `fallback_requires_user_choice` is true, ask which fallback peer to use
  and do not draft until the user chooses.
- If `runnable_default_pair_available` is false, stop and summarize the missing
  provider readiness from doctor.
- Existing work-order paths, reruns, and replayed artifacts never substitute
  providers.

Post-run escalation is separate from work-order drafting. Use
`bakeoff escalate SOURCE_RUN_ID --provider BACKEND[:MODEL] --mode MODE
--dry-run` after reading structured source artifacts and only when the source
run is `gather`, `compare`, `analyze`, or `gather` with
`facet.id: "code-review"`. Do not offer build escalation. Recommend one mode
first, then list alternatives:

- `independent` (fresh third answer): use when the source run is unresolved,
  decision-incomplete, or the user wants independent evidence. Cost: one
  provider call plus one escalation judge.
- `witness` (audit the current result): use when the user wants a broad sanity
  check of the report, decision, judge passes, or triage. Cost: one provider
  call.
- `dispute` (focus only on contested points): use when artifacts expose ties,
  conflicts, unknowns, judge caveats, kept-from-nonwinner material, or triage
  gaps. Cost: one provider call.

Always require explicit mode approval before running a non-dry-run escalation.
For code-review escalation, leave triage enabled unless the user supplied
`--no-triage`.

For build fast-path drafts, run `bakeoff draft-build` with the extracted id,
goal, acceptance criteria, edit scope, gate verifier, optional base/protected
paths, and exactly two `--provider` flags when the user explicitly chose a pair
or doctor selected a fallback pair. Pass those flags in the same order you will
show in the preview; `draft-build` preserves the two-provider order. With zero
`--provider` flags the command stays deterministic and emits the canonical
Claude+Codex pair. Use stdout as the preview source; the command owns the
canonical build shape, provider/judge defaults, budgets, `build.verify[].argv`,
and self-validation. Metric verifier drafts, generated fixtures, and protected
benchmark harnesses still use careful manual drafting.

For gather/code-review, compare, and analyze drafts, copy field names from
`examples/*.work-order.json`. Avoid schema drift: use `providers[].backend`
and `scope: "codebase"`, not `kind`, `role`, or `"local"`; use
`judge: {backend, model, effort}`; use nested `build.verify[]` with
`argv: [...]`; put criteria in `background`; use integer `schema_version: 1`.
Non-build and manual build drafts should internally validate before preview
when practical, but the enforced safety gate is the on-disk
`bakeoff validate` after approval.

## Task Fit And Type Routing

For natural-language input, run task fit before type inference or JSON
drafting. If weak fit, stop with "This may not need Bakeoff because <reason>"
and ask for `draft anyway` or narrowing; do not answer directly. `draft
anyway` clears only the task-fit or duplicate-work warning for the current turn
and does not waive required fields. Combine the warning with missing-field
choices when both apply: `inspect <run-id>`, `draft anyway`, or
`provide fields`.

Weak-fit cases include formatter-only work, build requests lacking verifier or
acceptance criteria, vague goals without target/scope/evidence, unbounded
reviews, RCA/analyze without symptom/log/repro/trace/files/incident/command,
sequential plans, and deterministic evidence extraction plus thin
interpretation. For deterministic one-pass evidence, show the repair-menu shape
from `references/run-appendix.md` at most once, with one or two rewrites that
preserve intent and do not invent requirements. Do not warn solely because a
task is small; if independent readers may disagree on behavior impact,
compatibility, maintainability, or risk, draft normally.

After task fit passes or is confirmed, check explicit multi-lens review before
generic clean split. Do not propose a split or multi-lens run in the same
response as a task-fit warning.

Classify types conservatively: code-editing candidates or competing patches are
`build`; review/audit/check PR/diff/local changes is `gather` with
`facet.id: "code-review"`; compare options is `compare`; RCA, design analysis,
or synthesis is `analyze`; fact-finding is `gather`. "Build a report/matrix"
is research unless the user asks providers to edit code. If build mode would
launch editing providers without clear implementation authorization, ask once.

## Single Work-Order Drafting

Use the build-only fast path when exactly one build work order is clear and the
user supplied goal, observable acceptance criteria, at least one concrete gate
verifier command, explicit edit boundary, any non-`HEAD` base, no metric
protected-path discovery, no split/multi-lens/sequential plan, no mode flag
conflict, no web/secrets/auth material, and no missing facts. Run preflight,
parse flags, run `bakeoff draft-build`, show a compact preview, wait for
single-work-order approval (`yes`, `y`, `approve`, `run it`, or `write and
run`), then write, validate, and run `bakeoff build`.

Do not fast-path when acceptance criteria, gate verifier, scope, type, metric
direction/protected paths, generated fixture/golden constraints, review scope,
analyze evidence, path-like input, flags, base ref, web scope, or secret/auth
handling are unclear. Fall through to careful drafting: explore once for
repo-discoverable fields, ask one targeted question for user-owned fields, and
stop when a missing value cannot be determined safely.

Manual drafts must be clean JSON, not TODO templates. Include explicit
`schema_version`, `id`, `type`, `goal`, `background`, `providers`, `judge`,
`budgets`, and `scope_policy.enforcement: "best_effort"`. Defaults: research
providers come from the provider-pair rules above with catalog default models
and high effort; build providers use `scope: "codebase"`; judge is Claude
`opus` xhigh; research budget is 900 seconds/60000 bytes; build budget is 1200
seconds/80000 bytes. Build drafts require `build.base_ref`, non-empty
`build.verify`, at least one `kind: "gate"` verifier, and codebase-scoped
providers. Do not include `build.patch_max_bytes`. For metric verifiers,
protect benchmark harnesses, fixtures, goldens, and expected-output files.

For code-review requests, gather read-only git context when useful
(`git status --short`, `git diff --stat`, `git rev-parse --show-toplevel`,
branch/base refs). Use `git diff` only for bounded context the user asked to
review. Recommend `bakeoff research <path> --base <ref> --diff` when generated
review context is useful. Let the CLI auto-triage reviews unless
`--no-triage` is supplied.

Before writing, show a compact preview with id/type, planned file path,
providers, judge, budget, scope policy, goal, short background summary, and
command. Include full JSON only if at most 120 lines and 10 KB; otherwise say
`show` can print it. Ask: "Write, validate, and run this work order? Reply
`yes` to continue, reply `show` to print the full JSON, or tell me what to
change." If the user edits, asks, or replies ambiguously, revise or clarify and
show an updated preview before writing.

After approval, write only `./<id>.work-order.json`. If the filename or
`runs/<id>` exists, append the smallest numeric suffix (`-2`, `-3`, ...);
never use date suffixes or overwrite unless explicitly asked. Run
`bakeoff validate <path>` before execution. Surface errors verbatim, repair,
show the updated preview, and revalidate only after fresh approval.

## Clean Splits

Suggest 2-3 separate work orders only when each part has its own goal and
evidence surface or verifier, no part depends on another result, shared context
fits in 1-2 repeatable sentences, and every part maps to `gather`, `compare`,
`analyze`, review-as-`gather`, or `build`. Do not split existing files,
sequential plans, more than three parts, under-scoped parts, or work needing
shared state, merge agents, or cross-run synthesis. Use the split proposal and
preview templates in `references/run-appendix.md`.

If the user accepts with `split`, draft each work order separately and show a
compact preview for all parts before writing. Full JSON follows the same
120-line/10 KB limit; otherwise support `show` and `show part-N`. One approval
covers only the displayed set. If any part changes, re-show all parts.

For non-parallel split previews, require exact `write and run`; `yes`,
`approve`, and `run it` are not enough. Parallel fanout is eligible only for
generic splits of 2-3 non-build `gather`/`compare`/`analyze` work orders where
every file validates and every part has an explicit collision-free run id.
Offer local `sequential`, `parallel`, and `show` choices only in that displayed
preview. `write and run` remains sequential; outside that preview, `parallel`
is normal user text. Never offer parallel for build parts or more than three
parts.

Derive one base slug. Append `.part-N` to work-order ids, filenames, and
supplied `--run-id`; if no `--run-id` was supplied, use the stem as the run id.
Resolve collisions after `.part-N`, for example `base.part-1-2`. After
approval, write all files, validate all files, and only then run the approved
sequence or fanout. If any validation fails, run nothing, surface the error,
repair, show the final set, and ask for fresh approval. Validation warnings are
advisory when validation exits successfully.

Sequential splits continue after exits `0`, `3`, or `4`; exit `3` is completed
with unresolved disagreement, and exit `4` is decision-incomplete with durable
artifacts. Stop on exit `1`, `2`, `130`, interruption, or command failure;
summarize completed and failed parts, then ask before remaining parts. Split
runs may continue after exit `4`; sequential multi-lens stops on exit `4`.

Parallel research children launch quiet JSON `"$BAKEOFF_CLI" research` commands
concurrently with one subshell per child under `/bin/sh` or Bash, no `xargs
-P`, no `eval`, no `set -e`, explicit run ids, separate stdout/stderr/exit/pid
files, bounded lifecycle progress only, and no claims about
provider/judge/triage phases. Any emitted fanout helper must start with
`#!/bin/sh` or `#!/usr/bin/env bash`; never emit or run it under `zsh`. Wait
for all children to settle. The helper must assign `BAKEOFF_CLI` to the
absolute path captured by `bakeoff-ensure-cli --check --print-path` before
starting children. Classify exits `0`, `3`, and `4` as completed,
with caveats; classify `1`, `2`, `130`, launch failure, orphaned
pid-without-exit, or missing artifacts as failed. Never summarize parallel runs
with `latest`.

Summarize generic split runs independently. Do not produce an overall winner,
merged patch, merged answer, persisted split summary, or cross-run synthesis
unless the user asks separately.

## Multi-Lens Review

Use this specialized path only for review-shaped natural-language requests
that explicitly ask for separate lenses or review passes, such as
`multi-lens`, `review swarm`, `with separate lenses`, or `security and tests as
separate lenses`. Plain "review this for security and tests" is one normal
review. If "swarm" is ambiguous, ask whether separate lens runs are wanted.

Run task fit first. If the review target is unbounded by branch, PR, diff, file
set, or local changes, stop with the task-fit warning and do not ask for
lenses. If lenses are missing, ask which 2-3 to run. For more than three, warn
and ask the user to narrow or say `run all lenses`; hard-stop at three unless
the user explicitly approves all lenses. Do not offer parallel for `run all
lenses` in this implementation. Lens presets and the summary template live in
`references/run-appendix.md`; map SQL injection to `security`, accessibility
to `ux`, and allow narrow custom kebab slugs while asking one clarification
for vague lenses like `quality` or `everything`.

For each lens, draft a normal review work order: `type: "gather"`,
`facet.id: "code-review"`, shared providers/judge/budgets/scope/base/diff, and
lens-specific `goal`, `background`, `facet.focus`, `facet.include`, and
`facet.exclude`. Keep code-review triage enabled unless `--no-triage` is set,
and pass `--no-triage` to every lens when set.

Use one base slug from the request or supplied `--run-id`. Append the lens slug
as the final component for ids, filenames, and run ids: `<base>.<lens>`.
Resolve collisions after the lens slug (`security-2`) and never use `.part-N`
for multi-lens. Preview selected lenses, files, run ids, commands, review
settings, verification/triage state, and the cost note from the appendix. Do
not print full JSON by default; use `show` or `show <lens>` with the 120-line
/ 10 KB limit.

Parallel multi-lens is eligible only for explicit 2-3 lens review previews
where every draft is `type: "gather"` with `facet.id: "code-review"`, every
file validates before launch, every run id is explicit and collision-free, and
every final lens label matches `^[a-z0-9][a-z0-9-]{0,31}$`. Normalize known
presets to labels like `security`, `performance`, `ux`, and `tests`. For
custom lenses, use unique lowercase kebab labels only when normalization is
unambiguous; if the label would need spaces, punctuation, uppercase, dots,
underscores, slashes, or more than 32 characters, do not offer parallel until
the lens is renamed or run sequentially.

For eligible previews, offer local `write and run`/`sequential`, `parallel`,
`show`, and `show <lens>` choices using the appendix wording. `write and run`
and `sequential` both mean the existing one-after-another execution. Accept
`parallel` only after an eligible displayed preview offered it. If `parallel`
is sent after an ineligible preview, say parallel is not available for that
preview and re-show valid choices; outside such a preview, treat `parallel` as
ordinary user text.

After approval, write every lens file and validate all final paths before any
run. On validation failure, launch nothing, repair, re-preview, and require
fresh approval. Validation warnings are advisory when validation exits
successfully. Sequential approval runs `"$BAKEOFF_CLI" research <lens-work-order>
--run-id <base>.<lens>` plus routed research flags one at a time. Parallel
approval launches all lens children concurrently as `"$BAKEOFF_CLI" research
<lens-work-order> --run-id <base>.<lens> [--out <dir>] [research flags] --json
--quiet`, forwarding only `--out`, `--base`, `--diff`, `--changed-files`,
`--no-triage`, and `--no-repo-layout`. Use separate stdout, stderr, exit, and
pid files per child, and report only launched/running/completed lifecycle
state. Shared `--out` writes must stay run-id-keyed: each child writes only
under `<out>/<run-id>/`, auto-triage writes under that child directory,
`latest` is nondeterministic, and the parent writes only the
`<out>/<base>.multi-lens-summary.md` convenience file.

Continue after exit `0`. Treat exit `3` as completed but unusual and untriaged
unless triage artifacts exist. Stop on validation failure, exit `1`, `2`, `4`,
`130`, interruption, or command failure. On a stop, show completed lenses, the
stopped lens and artifacts, remaining lenses, whether a partial summary file
was written, and ask for `continue lenses` before running remaining lenses.
This stricter stop/continue behavior applies to sequential multi-lens only.
Parallel multi-lens waits for every launched child to settle; exit `4` is
completed with a decision-incomplete caveat because all children are already
running. Mark the summary partial if any lens failed, was interrupted, never
launched, is orphaned, lacks required artifacts, or has failed/missing/stale
triage. Do not ask `continue lenses` after parallel launch unless a lens truly
never launched.

After lens runs, read artifacts through `ctx_execute_file`, `ctx_execute`, or
an equivalent context sandbox that returns compact digests, counts, paths, and
hashes rather than raw large artifacts. Inspect captured child JSON,
`report.md`, `decision.json`, `manifest.json`, `triage/final.json`,
`triage/triage.md`, and `triage/source_finding_filter.json` when present, plus
child logs when a child failed or JSON is missing. Always attempt to write
`<out>/<base>.multi-lens-summary.md`, with numeric collision suffixes, after
all sequentially completed or parallel-launched children settle. Include every
requested lens, run id, report path when present, triage path/state, result
class and exit code, triage counts when available (`real_issue`,
`needs_repro`, evidence gaps, false positives, deferred, documented, and
ignored items), most actionable findings by lens, overlap, clean lenses,
caveats, explicit `bakeoff show <run-id>` commands, the summary path, and a
note that `latest` may point to any one child and is not the group. If triage
is disabled, missing, stale, dry-run, failed, or only recommended, state that
findings are raw or unverified. Always include `## Optional Synthesis`: when
synthesis was not requested, write `Not requested.` plus the separate
`type: "analyze"` synthesis-pass option when usable artifacts exist; if no lens
has usable artifacts, say synthesis is unavailable until a lens completes.

Do not synthesize automatically. Ask whether the user wants a synthesis pass
deduping verified lens results into one prioritized fix plan. If accepted,
draft a separate normal `type: "analyze"` work order over completed reports and
triage files; it must prefer verified `real_issue` and `needs_repro` items, not
invent findings, and preserve source lens and run id.

## Execution And Summary

Default interactive runs keep CLI heartbeats. Use `--json --quiet` only when
the user asks for quiet or machine-readable output, except for parallel
research children.

On exit `0`, `3`, or `4`, read artifacts and summarize. Exit `3` means a
completed run with unresolved disagreement, not launcher failure. Exit `4`
means the decision is incomplete because the judge failed or did not converge,
with durable provider artifacts.

For research runs only, if exit `4` is paired with structured artifacts showing
all providers `ok` or `ok_after_format_retry` and the judge failed or did not
converge, recommend `bakeoff rerun <run-id> --judge-only` first. Mention a full
`bakeoff rerun <run-id>` only secondarily. Do not recommend judge-only rerun
for build runs.

Final responses must include run id, command or exit-code meaning, decision
kind, report path, relevant triage path/state for code-review research,
`bakeoff show <run-id>`, and for build runs the selected patch artifact only
when `decision.json.canonical_winner` is non-null:
`<out>/<run-id>/providers/<winner>/build/diff.patch`. Include diagnostics for
build runs when present. Stop after the Bakeoff handoff.

At most one artifact-aware continuation recommendation is allowed. Read stable
structured artifacts before recommending: parseable `decision.json`, mode,
decision kind, provider statuses, work-order type/facet, canonical winner,
current triage state, and structured verifier/diagnostic status. `report.md`
may explain but must not override missing or contradictory structured signals.
Preserve exact artifact paths, including custom `--out`; do not assume
`runs/<run-id>` unless surfaced. Cross-session continuation needs explicit
paths or `/bakeoff:inspect`/`/bakeoff:history`.

Allowed recommendation shapes are stop, inspect, judge-only rerun for research,
escalation preview for non-build research/review, draft an implementation plan
(`type: "analyze"`), gather/research, compare, review (`gather` plus
`code-review`), or draft a build work order for approval.
Prefer planning between research and build unless the implementation is tiny,
concrete, and verifier-ready. Review-to-build advice requires actionable
current triage plus supplied or repo-discovered acceptance criteria and
verifier. For build runs, prefer inspecting or reviewing the selected patch
when a canonical winner exists; if none exists, say there is no selected patch.

Do not apply patches, create issues, create branches, commit, push, open PRs,
synthesize a third patch, chain into another build, or edit source files from
provider output unless the user makes a separate explicit request.

## Permission Reminder

`Write` and `Edit` are only for work-order files and plugin-created multi-lens
summary files. They are never permission to apply, rewrite, combine, or publish
provider patches. Bakeoff build mode owns isolated worktrees; the plugin does
not create branches, manage worktrees, or retain implementation sandboxes.
