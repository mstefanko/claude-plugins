# SwarmDaddy Durable Run Capabilities Research Plan

Status: research-ready proposal
Date: 2026-04-30
Related plan: `docs/sensitive-path-launcher-hardening-plan.md`
Related investigation: `docs/investigations/2026-04-30-sensitive-path-write-block.md`
Related implementation: `docs/swarmdaddy-durable-run-candidates-1-2-implementation-plan.md`
Related implementation: `docs/swarmdaddy-durable-run-candidates-3-4-implementation-plan.md`
Related implementation: `docs/swarmdaddy-durable-run-candidates-5-6-implementation-plan.md`

## Goal

Research which differentiated capabilities SwarmDaddy should build around its
local, auditable, resumable harness model.

This plan exists so a future session can evaluate the ideas without needing the
original brainstorming context. It is not an implementation plan yet. The output
of the research pass should be a smaller set of implementation-ready plans,
ordered by value, risk, and dependency.

## Positioning Thesis

Do not move swarm-do wholesale to Agent Teams or native Task orchestration right
now. Metaswarm, Harness, wshobson/agents, and claude-team-orchestration lean
toward live agent coordination through Task or Agent Teams. That is useful, but
it changes the product boundary.

SwarmDaddy's durable advantage is different:

> Agent Teams coordinate minds. SwarmDaddy governs runs.

The product boundary to protect is the local durable run: prepared plans,
schemas, launch evidence, artifacts, retries, recovery, cost/spend signals,
worktree state, operator gates, and auditable continuation after failure.

Native Task or Agent Teams may become launcher backends later, but they should
not replace the durable run substrate.

## Evidence From Prior Research

External plugin patterns:

- Metaswarm uses fresh `Task()` subagents and fresh adversarial reviewers. For
  external tools, it creates worktrees and invokes the tool with an explicit
  worktree cwd.
- Superpowers runs headless Claude tests from temporary project directories and
  passes the plugin separately with `--plugin-dir`; it also emphasizes git
  worktree isolation.
- Everything-Claude-Code parses Claude JSONL transcripts for session summaries,
  tool usage, and files modified. It also runs compliance scenarios in `/tmp`
  sandboxes and guards prior-session summaries against stale replay.
- Harness and team-orchestration plugins lean on Agent Teams and Task primitives,
  avoiding some local launcher complexity but taking on experimental/team API
  coupling.

Local SwarmDaddy strengths already present:

- Prepared plan and phase-session artifacts.
- Strict result and handoff contracts.
- Per-attempt launch dirs with stdout/stderr and command metadata.
- Recovery state with attempt history, diff summaries, retry decisions, and
  checkpoint/resume surfaces.
- Worktree and baseline helpers.
- Provider review and telemetry contracts.
- Beads-backed task context and notes.

The research question is not whether SwarmDaddy can imitate these plugins. It is
which capabilities become uniquely strong when built on durable local runs.

## Value Ranking

| Rank | Capability | Value | Effort / Risk | Recommendation |
| ---: | --- | --- | --- | --- |
| 1 | Failure Taxonomy As A Feature | Very high | Low-medium | Research first and implement soon. It improves recovery, TUI, spend gates, and supportability. |
| 2 | Forensic Agent Execution | Very high | Medium | Research with failure taxonomy. It builds directly on existing launch/recovery artifacts. |
| 3 | Policy-Gated Autopilot | Very high | Medium | Research immediately after taxonomy. It prevents waste and unsafe retry loops. |
| 4 | Schema-Validated Handoffs | High | Low-medium | Continue strengthening. Already core; avoid broad schema churn unless clearly needed. |
| 5 | Crash-Resumable Engineering Runs | Very high | Medium-high | Research as an incremental reliability track. High differentiation, but easy to overpromise. |
| 6 | Auditable Worktree Choreography | High | Medium-high | Research after launcher/recovery hardening. Git workflows are valuable but sharp. |
| 7 | Replayable Local Harnesses | High | Medium | Research carefully. Replay harness states and failure classes, not deterministic model outputs. |
| 8 | Local Compliance Mode | Medium-high | Medium | Research later as audit packets and redaction posture, not a compliance product. |
| 9 | Agent CI For Humans | High concept value | High | Treat as packaging of earlier capabilities, not a separate system yet. |
| 10 | Provider Shootouts With Real Evidence | Strategic | High | Defer. Requires stable launcher contracts and fair comparison rules. |

## Research Approach

For each candidate capability, answer:

1. What existing SwarmDaddy primitives already support it?
2. What do similar plugins do here, and where do they stop?
3. What is the smallest useful version?
4. What state/schema/contracts would change?
5. What operator experience would prove value?
6. What tests or fixtures would make it safe?
7. What could go wrong if implemented too early?
8. What should explicitly remain out of scope?

The research should end with:

- a final priority order
- implementation-ready P0/P1/P2 slices
- dependencies between slices
- rejected or deferred ideas with reasons

## Candidate 1 - Failure Taxonomy As A Feature

### Hypothesis

SwarmDaddy can turn agent failures into operationally useful categories instead
of generic "agent failed" states.

### Why This Fits SwarmDaddy

The durable run already has phases, attempts, launcher results, artifact
validation, retry decisions, and recovery notes. Failure taxonomy is the glue
that makes those surfaces legible.

### Existing Assets

- `phase_recovery.py` already computes failure kinds.
- `phase_sessions.v1.json` already stores attempt history and last failure kind.
- Recovery markdown and run events already preserve evidence.
- The sensitive-path plan adds transcript diagnostics and better launcher
  classification.

### Research Questions

1. What failure kinds exist today, and which are ambiguous or overloaded?
2. Which failure kinds should be retryable, human-gated, or terminal?
3. Which failure kinds need operator-facing messages distinct from internal
   enum names?
4. Should taxonomy live in a central module with documentation and tests?
5. Which failure kinds should be exposed in TUI, Beads notes, and JSON status?

### Smallest Useful Version

Create a documented failure-kind registry with:

- enum/string name
- category
- retry policy
- operator message
- evidence fields required
- examples

### Risks

- Too many categories can make the system noisy.
- Renaming failure kinds can break tests or downstream tooling.
- If taxonomy tries to be perfect before recovery is stable, it becomes a
  documentation exercise instead of a runtime feature.

## Candidate 2 - Forensic Agent Execution

### Hypothesis

SwarmDaddy can make every agent attempt explainable after the fact: what was
asked, what ran, what files changed, what artifacts were expected, what failed,
and why recovery chose its next action.

### Why This Fits SwarmDaddy

Other plugins tend to optimize live collaboration. SwarmDaddy already persists
attempt evidence, which can become a first-class forensic packet.

### Existing Assets

- `phase_launches/<phase_id>/attempt-<n>/command.json`
- `stdout.txt` and `stderr.txt`
- launcher prompts
- recovery stdout/stderr tails
- diff summaries
- attempt history
- planned transcript diagnostics

### Research Questions

1. What evidence is currently captured but hard to find?
2. What should a single attempt evidence index contain?
3. Should recovery write an `attempt-evidence.json` summary alongside markdown?
4. What fields belong in run events versus local evidence files?
5. What redaction rules are needed before surfacing evidence in TUI or Beads?
6. What does a "support bundle" or "audit packet" look like?

### Smallest Useful Version

Add a per-attempt evidence manifest that points to existing files and summarizes:

- launcher
- cwd
- prompt path and SHA
- artifact paths
- return code
- cost/turn metrics when present
- failure kind
- changed files
- transcript diagnostic summary when present

### Risks

- Copying raw transcript or prompt content into too many places can create
  privacy and retention problems.
- Evidence paths can become stale if archive/cleanup behavior moves files.
- This should stay an index and summary, not duplicate the entire run.

## Candidate 3 - Policy-Gated Autopilot

### Hypothesis

SwarmDaddy can make unattended agent execution safer by stopping automatically
when the failure class, cost, retry history, or permission state indicates that
continuing would waste spend or risk damage.

### Why This Fits SwarmDaddy

SwarmDaddy already has phase state, retry policy, spend hints, and human-gated
blocked states. This capability turns those pieces into a coherent safety layer.

### Existing Assets

- Retry decisions and same-failure limits.
- Phase blocked states.
- Cost and turn metrics in Claude stdout.
- Recovery classification.
- Prepared plan and scope boundaries.

### Research Questions

1. Which current failures should never auto-retry?
2. Which failures should retry only with backoff?
3. What default spend fuse should exist per attempt, phase, and run?
4. How should policy decisions be represented in status and TUI?
5. How should operators override a human gate?
6. Which policy should be profile-specific, for example `fast`, `standard`,
   `strict`, or `dogfood`?

### Smallest Useful Version

Add a policy table that maps failure kind and evidence to:

- retry
- retry after backoff
- block with human gate
- terminal fail

### Risks

- Too strict a policy can make autopilot feel brittle.
- Too lenient a policy can burn money quickly.
- Policy must be explainable; hidden gates create frustration.

## Candidate 4 - Schema-Validated Handoffs

### Hypothesis

SwarmDaddy's structured result/handoff contracts can become a stronger
differentiator if they remain strict, versioned, and operator-readable.

### Why This Fits SwarmDaddy

The harness already treats artifacts, not final chat text, as the source of
truth. This is closer to CI/build systems than live agent chats.

### Existing Assets

- Result and handoff schemas.
- Prepared plan schema.
- Artifact validation and adoption logic.
- Contract appended to launcher prompts.

### Research Questions

1. Which schema failures are most common in real runs?
2. Are current schemas too strict, not strict enough, or strict in the wrong
   places?
3. Should result/handoff examples live in `docs/examples/`?
4. Should the artifact contract include fewer words and more machine-checkable
   examples?
5. Is schema evolution documented well enough?

### Smallest Useful Version

Create a schema contract guide that documents:

- required fields
- common validation failures
- retry/recovery behavior for invalid artifacts
- examples of complete, blocked, failed, and needs-input handoffs

### Risks

- Schema churn can invalidate existing tests and archived runs.
- Overly strict contracts can cause valid work to be discarded because of
  reporting shape.

## Candidate 5 - Crash-Resumable Engineering Runs

### Hypothesis

SwarmDaddy can make long-running engineering work resilient to parent death,
child death, terminal close, machine sleep, compaction, and interrupted model
sessions.

### Why This Fits SwarmDaddy

Durability is the core product distinction. Other plugins may coordinate live
agents well, but a durable run can outlive any single session.

### Existing Assets

- Phase session state.
- Leases and lease expiry.
- Child pid/process group metadata.
- Recovery and attempt history.
- Checkpoints.
- Resume/status commands.

### Research Questions

1. Which crash/resume cases are already covered?
2. Which cases currently duplicate work, lose evidence, or require manual
   adoption?
3. What invariants must never be violated?
4. Should there be a formal resume test matrix?
5. What operator command should repair/reconcile without launching new work?

### Smallest Useful Version

Build a documented crash-resume matrix with fixture tests for:

- parent died after child wrote valid artifacts
- child died with no artifacts
- child died with partial artifacts
- lease expired while child still alive
- nonzero launcher with valid artifacts
- zero-returncode no-artifact attempt

### Risks

- Process liveness checks vary across platforms.
- Recovery can accidentally duplicate active work if lease semantics are wrong.
- Long-running live tests can become expensive or flaky if not fixture-backed.

## Candidate 6 - Auditable Worktree Choreography

### Hypothesis

SwarmDaddy can make multi-unit implementation safer by isolating work in
worktrees, checking scope, preserving diffs, and merging through an auditable
integration path.

### Why This Fits SwarmDaddy

The prepared-plan model already decomposes work. Worktrees make that
decomposition concrete and reviewable.

### Existing Assets

- `worktrees.py`
- `worktree_baseline.py`
- work-unit decomposition artifacts
- integration branch helpers
- diff summaries

### Research Questions

1. Should worktrees be per phase, per work unit, or optional by launcher?
2. How should dirty pre-existing user changes be protected?
3. What scope rules should be enforced before merge?
4. How should merge conflicts become recovery artifacts?
5. What cleanup policy should remove or retain worktrees?
6. How do we avoid accidentally committing worktree directories?

### Smallest Useful Version

Make worktree use explicit and auditable for one path:

- create worktree
- run one unit/phase
- record changed files and branch
- scope-check
- merge or preserve conflict evidence

### Risks

- Git worktree behavior can surprise users with dirty state, ignored paths, and
  branch conflicts.
- Cleanup can be destructive if not designed carefully.
- Merge automation should be conservative.

## Candidate 7 - Replayable Local Harnesses

### Hypothesis

SwarmDaddy can replay harness states and known failure classes to regression
test orchestration behavior, even though model outputs themselves are not
deterministic.

### Why This Fits SwarmDaddy

The durable run already creates structured state files and evidence. Those can
be turned into fixtures.

### Existing Assets

- Phase-session fixtures.
- Claude print fixture tests.
- Prepared-plan artifacts.
- Recovery tests.
- Captured stdout/stderr shapes.

### Research Questions

1. What does "replay" mean without promising deterministic model behavior?
2. Which failure classes need fixtures?
3. Can archived run evidence be sanitized into reusable test fixtures?
4. Should replay be a test helper, CLI command, or selftest mode?
5. What fixture schema should preserve compatibility over time?

### Smallest Useful Version

Create fixture-backed replay tests for recovery classification and artifact
adoption. Do not invoke live models.

### Risks

- Users may interpret replay as deterministic agent replay.
- Fixture drift can make tests brittle if internal state schemas churn.

## Candidate 8 - Local Compliance Mode

### Hypothesis

SwarmDaddy can provide a local audit posture for teams that need traceability,
redaction, and evidence retention without sending harness state to a remote
service.

### Why This Fits SwarmDaddy

Everything important already lives locally. The missing piece is a curated,
redacted audit packet and retention policy.

### Existing Assets

- Local run directories.
- Telemetry retention ADR.
- Evidence files.
- Permission contracts.
- Planned transcript summaries.

### Research Questions

1. What should be included in a local audit packet?
2. What should be excluded or redacted by default?
3. How should retention be configured?
4. Is this a selftest/report command or a run mode?
5. What claims should we avoid making without legal/compliance review?

### Smallest Useful Version

Add a local audit packet generator that summarizes:

- run metadata
- plan hash
- phases and statuses
- artifact paths and hashes
- changed files
- failure taxonomy
- validation commands

### Risks

- "Compliance mode" can imply guarantees the tool does not provide.
- Redaction is hard. Start with conservative summaries and path/hash evidence.

## Candidate 9 - Agent CI For Humans

### Hypothesis

SwarmDaddy can eventually feel like CI for agent work: prepare a plan, run
phases, validate artifacts, stop on policy, and resume from evidence.

### Why This Fits SwarmDaddy

This is the product packaging of the durable run capabilities, not a separate
runtime primitive.

### Existing Assets

- CLI commands.
- TUI work.
- Prepared-plan flow.
- Phase sessions.
- Recovery/status surfaces.

### Research Questions

1. What is the minimum operator workflow that feels like "agent CI"?
2. Should this be a CLI wrapper, TUI view, or documentation narrative first?
3. Which status states must be visible at a glance?
4. What should be the equivalent of a CI job summary?
5. What does "rerun failed phase" mean safely?

### Smallest Useful Version

Define an operator-facing run summary:

- current status
- phase table
- last failure
- spend/turns when known
- changed files
- next safe action

### Risks

- Building a separate "CI product" too early can distract from core recovery
  reliability.
- UI polish can hide incomplete semantics.

## Candidate 10 - Provider Shootouts With Real Evidence

### Hypothesis

SwarmDaddy can eventually run the same prepared work through multiple local
agent/provider lanes and compare artifact validity, tests, cost, duration, and
failure classes.

### Why This Fits SwarmDaddy

The artifact contract gives a provider-neutral evaluation surface. The harness
could compare outcomes instead of trusting provider self-reports.

### Existing Assets

- Provider review concepts.
- Launcher abstraction seeds.
- Prepared phase prompts.
- Artifact validation.
- Cost/turn metrics where available.

### Research Questions

1. What is the fair unit of comparison: phase, work unit, or whole run?
2. How do we normalize tool access and permissions across providers?
3. How do we prevent provider abstraction from weakening the Claude lane?
4. What metrics are comparable and which are provider-specific?
5. How should conflicting successful outputs be judged?

### Smallest Useful Version

Do not implement a new provider lane yet. First produce a comparison contract
for one existing launcher result:

- artifact validity
- tests passed
- changed files
- failure kind
- elapsed time
- provider-reported cost when present

### Risks

- Premature abstraction.
- Hard-to-debug differences between provider behavior, prompt wording, and
  harness bugs.
- Increased test matrix and maintenance burden.

## Recommended Research Order

### Research Batch 1 - Foundation Differentiators

Research together:

1. Failure Taxonomy As A Feature
2. Forensic Agent Execution
3. Policy-Gated Autopilot
4. Schema-Validated Handoffs

Why: these share the same runtime surfaces and should produce one coherent
foundation plan.

Expected output:

- failure-kind registry proposal
- attempt evidence manifest proposal
- policy table proposal
- schema/handoff contract cleanup list
- P0 implementation plan

### Research Batch 2 - Durability And Work Isolation

Research after launcher hardening lands:

1. Crash-Resumable Engineering Runs
2. Auditable Worktree Choreography
3. Replayable Local Harnesses

Why: these need stable launcher/recovery evidence before they can be designed
cleanly.

Expected output:

- crash/resume test matrix
- worktree lifecycle proposal
- fixture/replay scope definition
- P1 implementation plan

### Research Batch 3 - Packaging And Strategic Expansion

Research after P0/P1 reliability work is real:

1. Local Compliance Mode
2. Agent CI For Humans
3. Provider Shootouts With Real Evidence

Why: these are valuable but should package a trustworthy engine, not precede it.

Expected output:

- audit packet proposal
- operator run summary proposal
- provider comparison contract
- deferred/dependency list

## Key Assumptions

- SwarmDaddy remains a local durable harness, not a live team-coordination plugin.
- Claude Code fresh sessions remain useful as one launcher backend.
- Phase artifacts remain the source of truth, not final assistant prose.
- Operators value explainability and recovery enough to accept some structured
  ceremony.
- Transcript parsing is diagnostic-only and can degrade without breaking
  recovery.

## Open Questions For The Next Research Session

1. Which current SwarmDaddy docs already describe these capabilities, and which
   are stale or overlapping?
2. Which failure kinds and recovery decisions currently appear in real dogfood
   runs?
3. What is the smallest evidence manifest that would make a failed attempt
   understandable without opening five raw files?
4. What status/TUI shape would make policy gates obvious instead of mysterious?
5. Which worktree operations are safe enough to automate by default?
6. Which claims should stay internal until the engine proves them in repeated
   local runs?

## Definition Of Done For Research

The research pass is complete when it produces:

- a validated priority order
- one implementation-ready P0 plan for taxonomy/evidence/policy
- one implementation-ready P1 plan for durability/worktree/replay
- explicit deferrals for compliance, Agent CI packaging, and provider shootouts
- links to the specific code modules and tests each plan would touch

## Implementation Analysis Output - 2026-04-30

This pass walked the current code paths instead of treating the candidates as
greenfield. Important context: the local tree already contains in-flight
sensitive-path launcher hardening work. In particular,
`phase_failure_classifier.py`, `claude_transcript_diagnostics.py`, and
`execution_workspace.py` already implement pieces that this plan previously
listed as future work. The recommendation shifts from "build basic
classification soon" to "productize the taxonomy, evidence, and policy contract
around the classifier."

### Updated Priority Order

| Priority | Capability | Updated Recommendation |
| ---: | --- | --- |
| P0 | Failure Taxonomy As A Feature | Build now as a central registry and policy contract around the existing classifier. |
| P0 | Forensic Agent Execution | Build now as an attempt evidence manifest that indexes existing launch/recovery files without duplicating raw prompts or transcripts. |
| P0 | Policy-Gated Autopilot | Build now as a behavior-preserving table-driven policy layer; defer aggressive spend fuses until evidence manifests are stable. |
| P0 | Schema-Validated Handoffs | Build now as examples, documentation, and targeted validation fixtures; avoid schema churn unless real failures justify it. |
| P1 | Crash-Resumable Engineering Runs | Build the fixture matrix and fix the expired-lease/live-child duplicate-work risk now; defer broad platform/process promises. |
| P1 | Replayable Local Harnesses | Build as fixture-backed orchestration tests now. Do not market or expose it as deterministic model replay. |
| P1 | Agent CI For Humans | Build only as a thin run-summary packaging layer after evidence manifests exist. |
| Defer | Auditable Worktree Choreography | Design next, implement later. The current helper is useful but too sharp to automate broadly. |
| Defer | Local Compliance Mode | Defer until attempt manifests and redaction posture exist. Package as audit packets, not compliance claims. |
| Defer | Provider Shootouts With Real Evidence | Defer. First stabilize one launcher result/evidence contract. |

### Feature Implementation Analysis

#### Candidate 1 - Failure Taxonomy As A Feature

Current fit:

- Runtime classification now lives mostly in
  `py/swarm_do/pipeline/phase_failure_classifier.py`.
- Recovery still has legacy fallback classification in
  `phase_recovery._launcher_failure_kind()` and policy decisions in
  `_retry_stop_decision()`.
- State stores `last_failure_kind`, `last_launcher_error`,
  `retry_policy_decision`, and `attempt_history` in
  `phase_sessions.v1.json`.
- The schema deliberately leaves `failure_kind` as a string, so adding a
  registry can be backward-compatible if strings remain stable.

Architecture:

- Add `py/swarm_do/pipeline/failure_taxonomy.py` with definitions for known
  failure kinds: category, default policy action, operator message, required
  evidence keys, and examples.
- Keep `phase_failure_classifier.py` responsible only for deriving the most
  specific kind from launcher/artifact evidence.
- Make `phase_recovery.py` consume the registry for retry/human-gate decisions
  instead of growing more ad hoc conditionals.
- Preserve old strings such as `outer_artifacts_missing`; document
  `writer_tool_denied_no_artifacts` and `writer_silent_with_turns` as more
  specific successors for one historical class.

Updated recommendation: build now. The classifier boundary already exists; the
remaining work is consolidation, documentation, and tests.

#### Candidate 2 - Forensic Agent Execution

Current fit:

- `phase_pump.py` writes `phase_launches/<phase_id>/attempt-<n>/command.json`,
  `dispatcher.launcher.prompt.md`, `stdout.txt`, and `stderr.txt`.
- `phase_recovery.py` writes stdout/stderr tails, diff summaries, recovery
  markdown, transcript diagnostics, and attempt history.
- `phase_attempts.py` summarizes attempt rows and cost from existing state and
  launch files.
- There is no single manifest that says "this is the evidence packet for
  attempt N."

Architecture:

- Add an attempt evidence writer that creates
  `phase_recovery/<phase_id>/attempt-<n>.evidence.json`.
- The manifest should index existing files by path, kind, sha256, byte size,
  and redaction class.
- It should summarize launcher, cwd/workspace metadata, return code, metrics,
  failure kind, retry decision, changed files, artifact validation results, and
  transcript diagnostic summary.
- Store `attempt_evidence_path` in `attempt_history` and surface it in
  `phases status --attempts`.
- Do not copy raw transcript content, full prompts, or stdout/stderr bodies into
  state or run events.

Updated recommendation: build now. The evidence is already captured, but the
operator has to know where to look.

#### Candidate 3 - Policy-Gated Autopilot

Current fit:

- Retry behavior is spread across `_retry_stop_decision()`,
  `_needs_recovery_retry()`, `_fallback_retry_after_seconds()`, same-failure
  counting, and the `retry_policy` object in `phase_sessions.v1.json`.
- `pump_phases()` can pass `--max-budget-usd` to Claude, but there is no
  run-level spend fuse that stops future attempts based on accumulated evidence.
- Recovery already records blocked states, blocked reasons, retry decisions,
  and Beads notes.

Architecture:

- Introduce a small policy evaluator, either inside `failure_taxonomy.py` or as
  `phase_autopilot_policy.py`.
- First slice should preserve current behavior while making every decision
  explainable as data: `retry`, `retry_after_backoff`, `human_gate`, or
  `terminal`.
- The evaluator should take failure kind, attempt evidence, attempt number,
  same-failure count, retry policy config, and known cost metrics.
- Record the resulting policy explanation in attempt history and run events.
- Defer default spend fuses until attempt evidence manifests provide a stable
  cost source.

Updated recommendation: build now, behavior-preserving first. Explainability
matters more than adding new stop conditions immediately.

#### Candidate 4 - Schema-Validated Handoffs

Current fit:

- `schemas/phase_result.schema.json` and
  `schemas/phase_handoff.schema.json` are strict and use
  `additionalProperties: false`.
- `phase_sessions.validate_phase_artifacts()` checks identity, prepared-plan
  sha, phase content sha, handoff/result status agreement, attempt agreement,
  and prepared work-unit subset rules.
- `_append_claude_print_contract()` embeds templates and type rules directly in
  the launcher prompt.
- Common validation failures are represented as
  `PhaseArtifactContractError.kind`, but those kinds are not documented as a
  contract.

Architecture:

- Add a schema contract guide and complete examples for `complete`, `failed`,
  `blocked`, and `needs_input`.
- Add fixture tests that validate examples and assert representative failure
  kinds for common malformed artifacts.
- Keep schemas stable. Prefer clearer examples and prompt wording before
  changing required fields.
- Link artifact validation failure kinds into the failure taxonomy registry.

Updated recommendation: build now as documentation and fixtures. Runtime schema
churn remains out of scope.

#### Candidate 5 - Crash-Resumable Engineering Runs

Current fit:

- `phase_sessions.py` has locked state, leases, lease expiry, child pid/process
  group metadata, retry state, cancellation, cleanup, and archive helpers.
- `phase_recovery.py` can adopt valid artifacts before deciding whether an
  active phase is stale, retryable, blocked, or still active.
- `phase_pump.py` records child process metadata and refreshes leases while the
  child runs.

Architecture:

- Treat this as a recovery-invariant test matrix first, not as a new daemon.
- Fixture tests should cover parent death after valid artifacts, child death
  with no artifacts, child death with partial artifacts, nonzero launcher with
  valid artifacts, zero-returncode/no-artifact attempts, and expired lease while
  the child is still alive.
- The current `_active_phase_decision()` checks lease expiry before same-host
  child liveness. That can mark an expired lease retryable even when the child
  is still alive, risking duplicate active work.

Updated recommendation: build the test matrix and live-child guard now. Defer
broad claims about terminal close, machine sleep, and cross-host process
liveness until the matrix is green.

#### Candidate 6 - Auditable Worktree Choreography

Current fit:

- `worktrees.py` can create integration/unit branch names, add unit worktrees,
  merge unit branches, and emit a merge-conflict event shape.
- `worktree_baseline.py` snapshots dirty state and computes baseline-relative
  changed files.
- The current worktree path is inside the repo at `.swarm-do/worktrees`, and
  `merge_unit_branch()` checks out the integration branch in the main repo.

Architecture:

- Later implementation should use data-dir-owned or sibling worktree roots, not
  a path that easily appears as source-tree dirt.
- Merge automation should avoid checking out the user's main working tree; use a
  dedicated integration worktree.
- Scope checks should compare changed files against phase/work-unit allowed
  files before any merge.
- Merge conflicts should become evidence manifests, not ad hoc terminal output.

Updated recommendation: defer implementation. The value is high, but the
current helper is too sharp for unattended use.

#### Candidate 7 - Replayable Local Harnesses

Current fit:

- Tests already use synthetic prepared runs, fake launchers, captured Claude
  stdout shapes, transcript fixtures, and phase-session fixtures.
- `phase_failure_classifier.py`, `phase_recovery.py`, and
  `phase_attempts.py` are good replay surfaces because they operate on stored
  files/state rather than live model calls.

Architecture:

- Define replay as fixture replay of harness state and failure classes.
- Add sanitized fixture directories that look like minimal run directories and
  load them through the same recovery/status/evidence readers.
- Do not replay live model outputs or promise deterministic model behavior.
- Use replay fixtures to protect failure taxonomy, evidence manifests,
  crash-resume cases, and schema validation.

Updated recommendation: build now as internal test infrastructure. A user-facing
replay command can wait.

#### Candidate 8 - Local Compliance Mode

Current fit:

- Run evidence is local, archiveable, and already avoids mutating frozen
  telemetry rows.
- The telemetry retention ADR and permission contracts provide useful posture.
- There is no curated redacted audit packet yet.

Architecture:

- Start from the attempt evidence manifest once it exists.
- Generate an audit packet containing metadata, hashes, phase statuses, failure
  taxonomy, validation commands, and changed-file lists.
- Exclude or redact prompt bodies, raw transcripts, full stdout/stderr, and
  sensitive path content by default.
- Present this as "local audit packet" rather than "compliance mode."

Updated recommendation: defer until evidence manifests and redaction classes
exist.

#### Candidate 9 - Agent CI For Humans

Current fit:

- `phases status --cost --attempts --events` already provides most raw pieces.
- The TUI has a phase-session runs table with status, attempts, cost, and last
  failure.
- Resume surfaces already produce `next_command` and phase failure summaries.

Architecture:

- Package existing status/evidence into a concise run summary: current status,
  phase table, last failure, failed/total cost, changed files, evidence path,
  and next safe action.
- Keep it as a CLI/TUI presentation layer over phase status and attempt
  evidence.
- Do not create a separate CI runtime or state model.

Updated recommendation: build soon after attempt evidence manifests.

#### Candidate 10 - Provider Shootouts With Real Evidence

Current fit:

- The result/handoff artifact contract is provider-neutral in principle.
- Provider review concepts and telemetry exist, but phase execution is still
  centered on `claude-print`.
- Cost/usage fields are provider-specific and only partially normalized.

Architecture:

- First define one comparison row over an existing attempt: artifact validity,
  tests/validation status, changed files, failure kind, duration, and
  provider-reported cost when available.
- Do not add new launcher backends or fairness rules until the single-lane
  evidence contract is stable.

Updated recommendation: defer. Premature provider abstraction would distract
from the durable-run substrate and multiply the test matrix too soon.

## Build-Now Implementation Plans

### Plan A - Failure Taxonomy Registry

Assumptions:

- Failure-kind strings remain backward-compatible; old run history is not
  migrated.
- The registry documents current behavior first and should not silently change
  retry policy.
- Artifact validation error kinds belong in the same operator-facing taxonomy
  even though they are not launcher failures.

Implementation:

1. Add `py/swarm_do/pipeline/failure_taxonomy.py` with a frozen definition type
   containing `name`, `category`, `default_action`, `blocked_reason`,
   `retry_policy_decision`, `operator_message`, `evidence_keys`, and examples.
2. Register current known launcher, artifact, process, workspace, and
   child-reported failure kinds.
3. Replace `_DETERMINISTIC_ARTIFACT_ERROR_KINDS` and the static branches in
   `_retry_stop_decision()` with registry lookups while preserving current
   outputs.
4. Add tests asserting every known current failure kind has a registry entry and
   existing retry/block decisions are unchanged.
5. Add a generated or hand-maintained markdown table listing names, categories,
   retry behavior, and operator messages.

Open questions:

- Should unknown failure kinds default to retry or human gate? Current behavior
  mostly retries unless a specific deterministic rule matches.
- Should child-reported `failure_kind` values be required to use the registry,
  or remain free-form child evidence?

Concerns to validate:

- Dashboards and queries that look for `outer_artifacts_missing` should also
  include `writer_tool_denied_no_artifacts` and `writer_silent_with_turns`.

### Plan B - Attempt Evidence Manifest

Assumptions:

- The manifest is an index and summary, not a copy of all evidence.
- Prompt files, stdout/stderr files, and transcripts may contain sensitive
  content, so manifests store paths, hashes, byte counts, and short diagnostic
  summaries only.
- Manifest schema version starts at 1 and evolves independently from
  `phase_sessions.v1.json`.

Implementation:

1. Add `schemas/phase_attempt_evidence.schema.json`.
2. Add `py/swarm_do/pipeline/phase_attempt_evidence.py` with helpers to
   hash/index known files and build a manifest from phase state, command
   metadata, classification, diff evidence, and artifact validation.
3. Call the writer from `_build_attempt_evidence()` after stdout/stderr tails,
   diff summary, transcript diagnostics, and recovery markdown are available.
4. Add `attempt_evidence_path` to `schemas/phase_sessions.schema.json` attempt
   history and surface it in `phase_attempts.py`.
5. Extend `phases status --attempts` to print the evidence path for failed or
   blocked attempts.
6. Test missing files, partial artifacts, transcript diagnostics present/absent,
   and redaction behavior.

Open questions:

- Should the manifest live under `phase_recovery/<phase_id>/` or inside the
  launch attempt directory? Recommendation: recovery directory, because it can
  index both launch and recovery files.
- Should manifests include hashes for invalid result/handoff artifacts?
  Recommendation: yes, when files exist.

Concerns to validate:

- Avoid creating a second source of truth. Manifest status fields should be
  summaries of existing state, not independently mutable state.

### Plan C - Table-Driven Autopilot Policy

Assumptions:

- First slice preserves existing behavior.
- Policy decisions must be explainable in status output and run events.
- Cost gates are useful, but should not be defaulted until cost evidence is
  consistently available.

Implementation:

1. Add a policy evaluator that consumes taxonomy entries plus runtime evidence:
   return code, artifact error kinds, changed files, partial artifacts, elapsed
   time, same-failure count, attempt count, retry policy config, and known cost
   metrics.
2. Replace `_retry_stop_decision()`, same-failure handling, and
   `_needs_recovery_retry()` decision glue with calls that return a structured
   policy result.
3. Record `policy_action`, `policy_reason`, and `policy_inputs` in attempt
   history or the evidence manifest; keep `retry_policy_decision` for backward
   compatibility.
4. Add tests proving existing cases still return the same phase status, blocked
   reason, retry decision, and next retry time.
5. Add optional config keys for per-attempt/per-run cost gates only after the
   evidence manifest can supply reliable cost totals.

Open questions:

- Should same-failure limit be represented as a policy override or as a taxonomy
  rule? Recommendation: policy override, because it depends on phase history.
- Should `launcher_workspace_error` and `launcher_prompt_sensitive_path` be
  terminal or human-gated? Current behavior human-gates; preserve that first.

Concerns to validate:

- Too much policy indirection can make recovery hard to debug. Tests should
  assert both final status and explanation fields.

### Plan D - Schema Contract Guide And Fixtures

Assumptions:

- Existing schemas remain the contract.
- The main gap is operator/model readability, not missing required fields.
- Examples should be validated by tests so docs cannot drift.

Implementation:

1. Add a guide under `docs/` that explains required fields, identity checks,
   status meanings, retry behavior, and common validation failures.
2. Add complete result/handoff example pairs under `docs/examples/` for
   `complete`, `failed` retryable, `blocked`, and `needs_input`.
3. Add tests that load every example pair through `validate_phase_artifacts()`
   or a fixture equivalent.
4. Add negative fixtures for common failures: result identity mismatch,
   prepared sha mismatch, attempt mismatch, handoff status mismatch,
   object-vs-string array mistakes, and unprepared completed work-unit ids.
5. Update the launcher artifact contract only if examples reveal confusing or
   redundant wording.

Open questions:

- Should examples use real-looking ULIDs and hashes or obvious placeholder
  values? Recommendation: use real valid synthetic values so examples can be
  machine-validated.

Concerns to validate:

- Do not loosen schemas to accommodate model mistakes before confirming those
  mistakes are common and semantically harmless.

### Plan E - Crash-Resume Matrix And Live-Child Guard

Assumptions:

- Recovery should prefer preserving potentially active work over starting a
  duplicate attempt.
- Fixture tests are enough for the first slice; no live model calls are needed.
- Same-host child liveness is more trustworthy than cross-host liveness.

Implementation:

1. Add phase recovery tests for:
   - parent died after child wrote valid artifacts;
   - child died with no artifacts;
   - child died with partial invalid artifacts;
   - nonzero launcher with valid artifacts;
   - zero-returncode no-artifact launch;
   - lease expired while same-host child pid/process group is still alive.
2. Change `_active_phase_decision()` so an expired lease with a proven live
   same-host child is preserved instead of immediately becoming
   `lease_expired_no_artifacts`.
3. Add an explicit action/status detail such as
   `expired_lease_child_alive_preserved` so operators can tell why recovery did
   not reclaim the phase.
4. Keep cross-host or unknown-liveness expired leases on the current
   conservative recovery path.
5. Verify `phases recover --dry-run` reports the same decision without mutating
   state.

Open questions:

- If a child is alive but the process group no longer matches, should recovery
  treat it as dead or human-gate? Current code treats group mismatch as dead;
  keep that unless a real counterexample appears.

Concerns to validate:

- `os.kill(pid, 0)` can return true for reused pids. Process group matching
  reduces that risk but does not eliminate it on every platform.

### Plan F - Replay Harness Fixtures

Assumptions:

- Replay means deterministic harness-state replay, not model-output replay.
- Fixture schemas can be internal at first.
- The same fixtures should support taxonomy, evidence manifest, and
  crash-resume tests.

Implementation:

1. Add minimal sanitized run directories under
   `py/swarm_do/pipeline/tests/fixtures/replay_runs/`.
2. Add a helper that copies a fixture run into a temp data dir and runs
   `reconcile_phase_sessions()`, `summarize_phase_attempts()`, and evidence
   manifest validation against it.
3. Cover at least one fixture per P0 failure class:
   `writer_tool_denied_no_artifacts`, `writer_silent_with_turns`,
   `partial_artifacts_invalid`, deterministic schema failure, expired lease,
   and adopted valid artifacts.
4. Keep a README in the fixture directory stating redaction rules and explicitly
   saying raw live transcripts should not be checked in.

Open questions:

- Should there be a `bin/swarm phases replay` command later? Recommendation:
  not until the internal fixture format survives a few changes.

Concerns to validate:

- Fixture drift can become maintenance drag. Keep fixtures minimal and validate
  through public-ish module APIs rather than asserting every private field.

### Plan G - Operator Run Summary

Assumptions:

- This is presentation over existing state, not a new state store.
- It depends on the evidence manifest for a clean "inspect this packet" link.
- TUI and CLI should share the same summarizer.

Implementation:

1. Add a summary helper that composes `phase_status()` and
   `summarize_phase_attempts()` into one run summary object.
2. Include status, phase table, active/blocked phase, last failure, failed and
   total cost, changed files, evidence path, and next safe command.
3. Add `bin/swarm phases summary <run_id>` or make `phases status --summary`
   call the helper.
4. Update the TUI phase-session detail panel to display the shared summary
   rather than rebuilding a separate partial view.
5. Add tests for blocked, retry-waiting, complete, and active runs.

Open questions:

- Should summary be the default `phases status` output once stable, or an
  explicit flag? Recommendation: explicit first, default later if it proves
  better.

Concerns to validate:

- The summary must not hide raw evidence paths. A polished view that makes
  debugging harder would undercut the durable-run advantage.
