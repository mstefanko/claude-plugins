# Multi-Agent Orchestrator Architecture Research

Date: 2026-05-14

Scope: investigate why `swarm-do` feels worse than manual delegation for multi-agent research and competitive builds, especially around task sizing, budget discipline, and subagents getting lost.

Primary question: is the failure caused by fixable implementation bugs, or by an architecture that is too complicated for the job?

## Executive Verdict

Yes, there is an architecture issue.

The issue is not that multi-agent research or competitive builds are doomed. The issue is that `swarm-do` tries to be too many systems at once:

- workflow engine
- prompt protocol
- provider router
- Beads state machine
- worktree manager
- stage dispatcher
- budget estimator
- budget checker
- TUI/status layer
- telemetry layer
- role library
- synthesis system

That much machinery makes task boundaries indirect. The system is supposed to make subagent work smaller and safer, but the orchestration surface is so large that it creates new failure modes: prompt drift, synthetic gate reports, advisory budgets, broad file scopes, and multiple places where the real behavior diverges from the intended workflow.

The practical recommendation is to freeze `swarm-do` as a lab and build a thinner tool around the manual delegation workflow that already works:

- direct CLI process launches
- git worktrees
- hard wall-clock and output limits
- allowed write-file gates
- explicit work-order JSON
- one judge/synthesizer pass over artifacts

LangGraph may be useful as a small state machine for research/synthesis/checkpointing. It should not be treated as the main answer for coding subprocesses or budget enforcement. LangGraph helps make orchestration explicit; it does not make vague work small, and it does not enforce subagent tool budgets unless the launched processes are controlled outside the model.

## Important Worktree State At Research Time

The `swarm-do` worktree was dirty before this memo was added:

```text
## main...origin/main
 D ../.claude/scheduled_tasks.lock
 M py/swarm_do/pipeline/stage_invocation.py
 M py/swarm_do/pipeline/tests/test_dispatcher_fanout.py
?? docs/swarmdaddy-rate-limit-stop-resume-plan-2026-05-05.md
```

The modified `stage_invocation.py` and test file appear to be active user work around result binding in fanout prompts. Do not revert them casually in a follow-up session.

## Repository Size And Complexity Signal

This is already a large orchestration framework:

- `py/swarm_do/pipeline/*.py`: 81 Python files, 45,103 lines.
- `skills/swarmdaddy/SKILL.md`: 488 lines.
- `commands/*.md` plus `agents/*.md`: 3,248 lines.
- Skill + command + role prompt surface: 3,736 lines.

This size is not automatically bad, but it is a warning sign for this specific product. The user need is "run a few agents with strict bounds and synthesize the result." The implementation has grown into a full framework, and the framework complexity now competes with the work it is trying to simplify.

## Finding 1: Budget Enforcement Is Mostly Advisory Or Post-Hoc

Evidence:

- `py/swarm_do/pipeline/budget.py:11` defines default ceilings such as `DEFAULT_MAX_WRITER_TOOL_CALLS = 60`, `DEFAULT_MAX_WRITER_OUTPUT_BYTES = 60_000`, and `DEFAULT_MAX_HANDOFFS = 1`.
- `py/swarm_do/pipeline/budget.py:45` estimates unit budgets with a simple heuristic based on file count and acceptance criteria count.
- `py/swarm_do/pipeline/budget.py:89` evaluates budget only after the writer returns.
- `py/swarm_do/pipeline/budget.py:120` warns that self-reported tool calls are advisory when stream telemetry is unavailable.
- `py/swarm_do/pipeline/budget.py:131` can only enforce tool-call ceilings when `measured_calls is not None`.
- `agents/agent-writer.md:100` asks the model to track its own tool calls and hand off around 80% of budget.

Interpretation:

The system has budget concepts, but most of the meaningful enforcement happens too late or depends on telemetry that may not exist. If the subagent gets lost, the parent often cannot preemptively stop it at the exact budget boundary. The prompt asks the worker to self-police, which is exactly the class of control that failed in practice.

This explains the user's observed behavior: "budgets were ignored or not followed" is consistent with the implementation.

## Finding 2: Fanout Adoption Bypasses The Stronger Post-Writer Gate

The strongest deterministic budget and validation gate exists in `post_writer.py`:

- `py/swarm_do/pipeline/post_writer.py:48` calls `writer_budget_status(...)`.
- `py/swarm_do/pipeline/post_writer.py:57` builds a gate from blocked-file violations, out-of-scope files, validation results, and budget status.
- `py/swarm_do/pipeline/post_writer.py:73` includes `budget_status` in the report.
- `py/swarm_do/pipeline/post_writer.py:282` fails the gate if budget status is not ok.

But fanout adoption takes a different path:

- `py/swarm_do/pipeline/unit_session_adopter.py:59` commits stage artifacts.
- `py/swarm_do/pipeline/unit_session_adopter.py:77` writes a post-writer report.
- `py/swarm_do/pipeline/unit_session_adopter.py:83` passes `gate_status="passed"`.
- `py/swarm_do/pipeline/unit_session_adopter.py:87` records that synthetic report.
- `py/swarm_do/pipeline/unit_session_adopter.py:88` records spec review as skipped.
- `py/swarm_do/pipeline/unit_session_adopter.py:97` merges the unit worktree.
- `py/swarm_do/pipeline/unit_session_adopter.py:127` writes a minimal `post_writer_report.v1` payload.
- `py/swarm_do/pipeline/unit_session_adopter.py:137` stores the passed gate with no validation or budget details.

Interpretation:

The fanout path synthesizes a passed post-writer report instead of running the stricter post-writer budget/validation report. This is the most concrete architecture/implementation mismatch found.

The code contains a real gate, but the path that matters for bounded fanout can bypass it.

## Finding 3: Decomposition Is Not Strong Enough To Guarantee Small Work

Evidence:

- `py/swarm_do/pipeline/prepare.py:664` says `prepare_plan_run` is intentionally deterministic and non-model.
- `py/swarm_do/pipeline/prepare.py:824` calls `synthesize_work_units(...)`.
- `py/swarm_do/pipeline/decompose.py:37` defines `decompose_phase(...)`.
- `py/swarm_do/pipeline/decompose.py:55` falls back to deterministic `synthesize_work_units(...)` when the phase is simple or `agent_runner is None`.
- `py/swarm_do/pipeline/decompose.py:104` defines the synthetic work-unit builder.
- `py/swarm_do/pipeline/decompose.py:112` uses `report.file_paths or ["."]`.
- `py/swarm_do/pipeline/decompose.py:158` sets `allowed_files` to the synthesized file list.
- `py/swarm_do/pipeline/plan.py:209` uses `phase.explicit_files` as the file source for inspection.
- `py/swarm_do/pipeline/plan.py:332` only blocks when a phase references files but lacks explicit file targets.

Interpretation:

The decomposition story sounds stronger than it is. In the normal prepare path, there is no guaranteed model-quality decomposition step. The system often performs deterministic bucketing. If the plan lacks explicit file targets, a synthesized unit can receive `allowed_files = ["."]`, which is effectively "the whole repo."

This creates a direct route from a vague plan to a broad worker contract.

## Finding 4: The Default Presets Do Not Enforce Decomposition

Evidence:

- `presets/balanced.toml:25` sets `[decompose] mode = "off"`.
- `presets/competitive.toml:18` sets `[decompose] mode = "off"`.
- `skills/swarmdaddy/SKILL.md:247` says the legacy `/swarmdaddy:do <plan-path>` path honors `[decompose].mode`, with `--decompose=off|inspect|enforce`.
- `skills/swarmdaddy/SKILL.md:250` says `off` continues with the legacy stage graph.
- `skills/swarmdaddy/SKILL.md:251` says `inspect` keeps telemetry but does not gate behavior.
- `skills/swarmdaddy/SKILL.md:252` says `enforce` creates or loads a `work_units.v2` artifact before writer/spec-review issue creation.

Interpretation:

The safe behavior is not the default. `balanced` is presented as the normal path, but decomposition is off. The user can opt into `--decompose=enforce`, but the default mode makes it easy to launch broad work.

## Finding 5: There Are Two Orchestration Surfaces That Can Drift

Evidence:

- `skills/swarmdaddy/SKILL.md:94` says deterministic helpers own parsing, validation, routing, DAG math, budget estimation, and stage graph rendering, while the skill owns Claude-side actions such as calling `Agent()`.
- `skills/swarmdaddy/SKILL.md:105` says work-unit DAG math, artifact validation, ready-queue batching, resume-point selection, and worktree branch naming are deterministic helper responsibilities.
- `py/swarm_do/pipeline/phase_pump.py:497` prepares the stage controller from Python.
- `py/swarm_do/pipeline/phase_pump.py:541` renders the orchestrator brief from Python.
- `py/swarm_do/pipeline/phase_pump.py:549` checks dispatcher prompt bytes.
- `py/swarm_do/pipeline/stage_invocation.py:534` renders per-stage dispatch prompts that ask the parent Claude to call `Agent(...)`.

Interpretation:

The architecture splits control between Python helpers and a Claude skill that launches child agents. In practice, Python now renders a substantial amount of the dispatcher prompt. The parent Claude still performs `Agent()` calls and marker/report handling. This creates multiple contracts:

- Python stage graph contract
- Claude skill contract
- child agent prompt contract
- stage result JSON contract
- marker contract
- post-writer report contract
- worktree adoption contract

The number of contracts makes it easy for implementation paths to diverge from intended behavior, as seen in fanout adoption.

## Finding 6: Prompt Budget Is Enforced More Strictly Than Worker Budget

Evidence:

- `py/swarm_do/pipeline/phase_pump.py:549` measures dispatcher prompt bytes.
- `py/swarm_do/pipeline/phase_pump.py:551` raises `DispatcherPromptBudgetExceeded` if the prompt is too large.
- `py/swarm_do/pipeline/budget.py:14` defines `DEFAULT_MAX_DISPATCHER_PROMPT_BYTES = 96_000`.

Interpretation:

The parent prompt-size cap is real. The child worker runtime cap is much weaker. This means the system is better at preventing oversized dispatcher prompts than at preventing runaway child work.

That is useful, but it does not solve the user's main pain.

## Finding 7: Existing Plans Already Diagnose The Same Root Cause

Several repo-local plans and postmortems already point to the same failure pattern:

- `../plans/swarm-do-1.12-orchestration-friction-fixes.md`
- `../plans/swarm-do-plan-prepare-and-bounded-work-units.md`
- `docs/fanout-foundations-fix-plan-2026-05-04.md`

Important signals from those documents:

- One historical Phase 5 writer reportedly consumed 125.8k tokens and 99 tool calls in about 15 minutes.
- A 1.12 budget plan noted that Claude `Agent()` child tool calls were opaque to the parent dispatcher, so initial enforcement focused on wall time and output bytes.
- The bounded work-units plan explicitly said the underlying problem was not prompt wording; it was work sizing.
- The fanout foundations plan noted that per-writer token/cost usage is not directly observable from Claude/Codex and must be nullable/unknown.
- The fanout foundations plan also identified result identity, adoption, commit, merge projection, ledger consistency, deterministic caps, and prompt economy as broken or fragile areas.

Interpretation:

The repo already contains the diagnosis: vague multi-objective phases handed to writers become expensive and hard to control. The current implementation has partially addressed this with work units and fanout infrastructure, but the strict guarantees are not consistently wired into the live fanout path.

## Finding 8: Research And Competitive Pipelines Exist, But Not In The Desired Shape

Research:

- `pipelines/research.yaml:6` defines a research fanout.
- `pipelines/research.yaml:7` fans out `agent-research`.
- `pipelines/research.yaml:9` uses count 3.
- `pipelines/research.yaml:14` merges with `agent-research-merge`.

Competitive builds:

- `pipelines/compete.yaml:16` defines writer fanout.
- `pipelines/compete.yaml:20` uses count 2.
- `pipelines/compete.yaml:23` routes one writer through Claude Opus.
- `pipelines/compete.yaml:26` routes one writer through Codex GPT-5.4.
- `pipelines/compete.yaml:31` merges with `agent-writer-judge`.
- `presets/competitive.toml:2` describes the preset as an opt-in lab and not a production default.

Interpretation:

The plugin already contains something conceptually close to "competitive builds," but it is not the requested workflow:

- not Claude Sonnet plus GPT-5.5
- not a thin wrapper
- not decomposition-enforced by default
- not hard-budgeted at the process level
- not a production-default path

## Community Research Summary

The community signal is consistent: multi-agent workflows can help, but the winning pattern is disciplined delegation, not autonomous swarm behavior.

Useful external threads/signals:

- Reddit: [Subagents are slow, consume vast tokens while hiding how lost they are at their jobs](https://www.reddit.com/r/ClaudeCode/comments/1mdgjqz/subagents_are_slow_consume_vast_tokens_while/) - reports that converting working slash-command workflows into subagents made simple tasks slower and token-heavy.
- Reddit: [Wonderful world of Claude Code subagents running for ~2.5hrs non-stop](https://www.reddit.com/r/ClaudeAI/comments/1m8u4cx) - reports runaway subagent behavior and heavy token use.
- Reddit: [I reverse-engineered why Claude Code burns through your usage so fast](https://www.reddit.com/r/ClaudeAI/comments/1sbqalg/i_reverseengineered_why_claude_code_burns_through/) - reports cache/usage issues and emphasizes the cost impact of context rebuilds.
- Reddit: [Claude Code is wasting tokens on purpose apparently](https://www.reddit.com/r/ClaudeCode/comments/1so5aiw/claude_code_is_wasting_tokens_on_purpose/) - argues that broad grep/glob-style exploration and poor context compression waste tokens.
- Reddit: [I tracked exactly where Claude Code spends its tokens](https://www.reddit.com/r/ClaudeAI/comments/1s27dex/i_tracked_exactly_where_claude_code_spends_its/) - reports that agents waste tokens navigating code with broad searches instead of symbol-aware/context-aware tools.
- Reddit: [I asked Claude to investigate its own token burn](https://www.reddit.com/r/ClaudeAI/comments/1t4gchn/i_asked_claude_to_investigate_its_own_token_burn/) - highlights orientation-loop cost and the value of a compact structured context brief.
- Reddit: [multiple agents/worktrees](https://www.reddit.com/r/codex/comments/1s09f60/multiple_agentsworktrees/) - practical advice centers on worktrees and truly independent subtasks.
- Reddit: [How are you actually running Codex at scale?](https://www.reddit.com/r/codex/comments/1sc7g2x/how_are_you_actually_running_codex_at_scale/) - reports that worktrees are promising but operationally painful; one user recommends forcing tasks over about 500 LOC to be split.
- Reddit: [Are agents actually useful for complex tasks?](https://np.reddit.com/r/ClaudeAI/comments/1rozbqb/are_agents_actually_useful_for_complex_tasks/) - concern that once an agent makes a bad assumption, it can spend many tokens pursuing the wrong path.

Community synthesis:

- Multi-agent coding works best when tasks are independent.
- Worktrees are the common practical isolation mechanism.
- Overlapping edits create coordination and review bottlenecks.
- Review bandwidth becomes the real limiting factor.
- Vague prompts burn tokens through orientation loops.
- Agents need exact files/functions, repo maps, or compact context briefs.
- Structured final outputs help, but only after the task itself is bounded.
- LangGraph is commonly viewed as useful for explicit state/control, while role-chat frameworks tend to grow token history and coordination overhead.

## What Is Actually Working Better Than Manual?

Better than manual:

- parallel research briefs with fixed questions and structured outputs
- competitive prototypes when the surface area is tiny
- independent worktree tasks with non-overlapping files
- testable changes where the judge can inspect diffs and test output
- short implementation contracts that name allowed files and validation commands
- human-approved decomposition before dispatch

Not better than manual:

- broad ambiguous coding tasks
- "figure out the architecture and implement it" tasks
- tasks where workers share or overlap files
- tasks where the judge must infer correctness from long chat transcripts
- parent-agent orchestrators that delegate to child agents while lacking process-level control over those children

## LangGraph Assessment

LangGraph could help if used narrowly:

- model the run state
- checkpoint research/build attempts
- fan out provider calls
- collect structured outputs
- route to a judge/synthesizer
- resume failed runs

LangGraph will not solve the core pain by itself:

- it will not make work small
- it will not enforce child CLI token/tool budgets unless wrapped around subprocess controls
- it will not prevent broad codebase spelunking
- it will not remove review burden
- it will not make overlapping edits safe

Recommended use:

Use LangGraph only as the state-machine layer if it makes the new wrapper easier to reason about. Keep the worker execution layer as direct subprocesses with hard external limits.

## Recommended Replacement Shape: Manual Delegation Compiler

Build a thinner tool whose job is to compile a human-approved work order into bounded agent runs.

Core principle:

The orchestrator should not be an autonomous manager. It should be a strict dispatcher.

Minimum work-order schema:

```yaml
id: short-task-id
mode: research-bakeoff | build-bakeoff
goal: one-sentence outcome
background: compact context brief
allowed_read_files:
  - path/or/glob
allowed_write_files:
  - path/or/glob
blocked_files:
  - path/or/glob
acceptance_criteria:
  - concrete check
validation_commands:
  - command to run
budgets:
  wall_clock_seconds: 900
  max_output_bytes: 60000
  max_changed_files: 5
providers:
  - name: claude
    model: claude-sonnet
  - name: codex
    model: gpt-5.5
judge:
  provider: codex-or-claude
  model: strong-model
  decision: pick-winner | synthesize
```

Important behaviors:

- No autonomous decomposition by default.
- First run can generate a proposed work order, but dispatch requires human approval.
- Launch Claude and Codex as direct CLI subprocesses, not as child `Agent()` calls from a parent Claude session.
- Use separate git worktrees for build-bakeoff.
- Kill the whole process group on timeout.
- Capture stdout/stderr with output byte caps.
- After each worker, inspect `git diff --name-only`.
- Reject output that touches files outside `allowed_write_files`.
- Run validation commands outside the model.
- Feed the judge only the work order, changed file list, diffs, test results, and worker final JSON.
- Avoid handing the judge full transcripts unless debugging a failure.

## Two Target Modes

### Mode 1: `research-bakeoff`

Purpose: replace manual parallel research with Claude + GPT and a synthesizer.

Flow:

1. Human writes or approves research work order.
2. Tool launches Claude Sonnet and GPT-5.5 in parallel.
3. Each worker must return JSON:
   - claims
   - evidence
   - source links
   - conflicts
   - unknowns
   - recommended next checks
4. Synthesizer receives only structured outputs and source lists.
5. Final memo includes consensus, disagreements, confidence, and next actions.

This is the safest first build because it is output-only and does not require merging code.

### Mode 2: `build-bakeoff`

Purpose: replace manual competitive implementation.

Flow:

1. Human approves small implementation work order.
2. Tool creates two worktrees.
3. Tool launches Claude and GPT in parallel with identical contracts.
4. Tool enforces wall-clock and output caps externally.
5. Tool runs validation commands in each worktree.
6. Tool collects:
   - changed files
   - diff stat
   - full diff or clipped diff
   - test output
   - worker final JSON
7. Judge picks winner or writes a synthesis plan.
8. Human approves adoption/merge.

This mode should initially avoid automatic synthesis commits. Let the judge recommend the best diff or best pieces, then let a follow-up implementation session apply the synthesis.

## What To Salvage From `swarm-do`

Salvage:

- role prompt language where it has proven useful
- research/research-merge concepts
- writer judge concept
- worktree helper ideas
- allowed/blocked file vocabulary
- result JSON discipline
- evidence normalization ideas
- validation command reporting
- failure taxonomy language

Do not carry over initially:

- Beads-first orchestration
- parent Claude `Agent()` fanout as the execution substrate
- phase pump complexity
- TUI/status surfaces
- retry cycles with fresh reviewers
- multi-phase DAG execution
- large prompt-rendering contract stack
- automatic adoption/merge
- synthetic passed reports

## Suggested MVP Architecture

Keep the first version small enough to audit in one sitting.

Suggested modules:

```text
swarm_thin/
  cli.py                  # parse command and work order
  work_order.py           # schema load/validate
  providers.py            # build claude/codex command lines
  subprocess_runner.py    # timeout, process group kill, output cap
  worktrees.py            # create/list/cleanup worktrees
  diff_gate.py            # allowed write files, changed files, diff stat
  validate.py             # run validation commands
  judge.py                # judge prompt from artifacts only
  report.py               # markdown/json run report
```

Avoid a database at first. Write one run directory:

```text
runs/<run-id>/
  work-order.yaml
  claude/
    stdout.txt
    stderr.txt
    final.json
    diff.patch
    validation.txt
  codex/
    stdout.txt
    stderr.txt
    final.json
    diff.patch
    validation.txt
  judge/
    prompt.txt
    result.md
  report.md
```

## Hard Gates The New Tool Should Enforce

Required gates:

- work order must include allowed write files for build mode
- no `allowed_write_files: ["."]` in build mode unless explicitly forced
- timeout kills subprocess group
- max output bytes truncates/cancels worker stream
- changed files outside allowed write files fail the worker
- validation command failure is visible to the judge
- judge cannot see full transcripts by default
- adoption/merge always requires human approval in v1

Optional later gates:

- max changed files
- max diff size
- max test runtime
- deny broad `rg`/`find` patterns through a wrapper shell
- require first worker action to read a repo map/context brief
- require a "stop and ask" status for missing file targets

## First Follow-Up Tasks For A New Session

1. Decide whether the new tool lives inside `swarm-do` as `swarm_thin` or in a new plugin/repo.
2. Write the work-order schema and one example research-bakeoff order.
3. Implement direct subprocess launching for Claude and Codex with wall-clock timeout and output cap.
4. Implement research-bakeoff first; avoid code mutation until the output-only loop feels good.
5. Add build-bakeoff with worktrees and allowed write-file gate.
6. Add judge prompts that consume only artifacts.
7. Add a migration note that `swarm-do` remains the experimental/full-framework path.

## If Continuing To Fix `swarm-do` Instead

The most valuable fixes would be:

1. Wire fanout adoption through the real `post_writer.py` budget/validation report instead of `_write_post_writer_report(... gate_status="passed")`.
2. Make `--decompose=enforce` the default for any mutating fanout.
3. Block `allowed_files = ["."]` for writer units unless explicitly forced.
4. Treat missing explicit file targets as blocking for mutating work, even when no files are referenced.
5. Replace child `Agent()` budget self-reporting with parent-owned subprocess execution where possible.
6. Make competitive preset explicitly unsupported for broad phases unless work units are accepted.
7. Add a hard "no automatic merge on synthetic report" rule.

These would reduce the current pain, but they do not remove the larger architectural weight.

## Bottom Line

The user's manual workflow is strong because the human is doing the most important parts:

- choosing small tasks
- limiting scope
- deciding when two agents should compete
- reading artifacts
- judging whether synthesis is worth it

The replacement tool should preserve that. It should automate the mechanical parts, not replace the judgment parts.

Build the next version as a thin, strict dispatcher. Let it feel boring. Boring is exactly what makes multi-agent runs trustworthy.
