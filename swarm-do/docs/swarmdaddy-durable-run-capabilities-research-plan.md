# SwarmDaddy Durable Run Capabilities Research Plan

Status: research-ready proposal
Date: 2026-04-30
Related plan: `docs/sensitive-path-launcher-hardening-plan.md`
Related investigation: `docs/investigations/2026-04-30-sensitive-path-write-block.md`

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
