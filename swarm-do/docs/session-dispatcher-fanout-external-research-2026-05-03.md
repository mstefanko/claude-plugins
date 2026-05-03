# Session Dispatcher Fan-Out External Research

Date: 2026-05-03
Related plan: `docs/phase-session-dispatcher-fanout-plan-2026-05-03.md`

## Executive Findings

1. Claude Code docs now confirm the core Task/Agent assumptions: the Task tool was renamed to `Agent` in Claude Code 2.1.63; current streams expose subagent invocation as `Agent`; messages from inside a subagent can carry `parent_tool_use_id`; the parent receives the subagent final message as the Agent tool result. This matches the local E1-E3 experiments.
2. Permission propagation is not fully per-subagent for plugin agents. Subagents can define `tools`, `model`, `permissionMode`, `maxTurns`, `skills`, and `isolation`, but plugin subagents ignore `permissionMode`, `hooks`, and `mcpServers`. Parent `bypassPermissions`, `acceptEdits`, and `auto` modes take precedence and cannot be overridden per subagent.
3. Claude Code has a native worktree isolation model for subagents: `isolation: worktree`, plus CLI `--worktree`. But native isolation creates Claude-managed temporary worktrees, while SwarmDaddy needs controller-prescribed paths, BEADS ids, expected result paths, and deterministic adoption. Use native worktree isolation only if exact per-unit path control is not required.
4. LangGraph `Send` is the cleanest graph-runtime prior for dynamic fan-out: a conditional edge returns multiple `Send(node, args)` packets, each with custom state, and reducers aggregate results. This is the graph-native equivalent of controller-created stage invocations plus live marker adoption.
5. Pydantic AI is a useful typed-runtime prior. Its marker equivalent is not free-form stream text; it is stable tool-call IDs, typed deferred requests/results, graph task markers, join/reducer outputs, and durable workflow history. Its worktree equivalent is weaker: pluggable file/sandbox backends and per-run toolset/capability isolation, not git worktree lifecycle. SwarmDaddy should borrow the ID/result-ledger discipline while keeping controller-owned worktrees.
6. AutoGen's `GroupChatManager` is the cleanest manager-agent prior: it owns participant selection and publishes a `RequestToSpeak` message to the chosen specialist. The manager is explicit control flow, not a worker.
7. OpenAI Swarm's closest lesson is the minimal `Agent` plus handoff abstraction: a tool/function can return another `Agent`, and the runtime switches execution to it. It is now superseded by OpenAI Agents SDK for production use, but its "handoff as ordinary tool result" shape is directly relevant.
8. metaswarm is the closest prompt/plugin prior. Its marker equivalent is durable BEADS state plus `.beads/context/*` files, not stream markers. Its worktree equivalent is a hub-and-spoke model where the main repo orchestrator creates/assigns worktrees and worker agents own implementation/review/PR lifecycle.
9. Superpowers is the closest methodology prior. It requires isolated worktrees before plan execution, fresh subagents per task, and two-stage review. It explicitly warns against parallel implementation subagents in shared contexts because of conflicts.
10. MCO is a useful external-provider prior, not a direct Claude subagent prior. It dispatches prompts to multiple CLIs in parallel, returns structured output/artifacts, supports JSONL/live streaming, and exposes path constraints and provider permissions.
11. There was working dispatcher-shaped code in this repo. Commit `274ab18` (`putting quality lanes back`, 2026-05-02) added `agent-dispatcher`, `permissions/dispatcher.json`, `stage_invocation.py`, `stage_sessions.py`, `orchestrator_stream.py`, `stage_sessions.schema.json`, phase-pump integration, and tests. Most of that design still exists today. The fan-out work should extend it, not create a parallel dispatcher.

## Claude Code Task/Agent Internals

Sources:
- Claude Code subagents docs: https://code.claude.com/docs/en/sub-agents
- Claude Agent SDK subagents docs: https://code.claude.com/docs/en/agent-sdk/subagents
- Claude Agent SDK permissions docs: https://code.claude.com/docs/en/agent-sdk/permissions
- Claude CLI reference: https://code.claude.com/docs/en/cli-reference
- Claude worktrees docs: https://code.claude.com/docs/en/worktrees
- Claude streaming output docs: https://code.claude.com/docs/en/agent-sdk/streaming-output

Facts:

- Tool naming: Claude Code docs say Task was renamed to `Agent` in v2.1.63. Existing `Task(...)` references in settings and agent definitions still work as aliases. The SDK docs recommend matching both `Task` and `Agent` for compatibility.
- Invocation detection: subagents are invoked via tool-use blocks whose current name is `Agent`. Messages produced inside a subagent context include `parent_tool_use_id`.
- Return shape: the parent receives the subagent's final message verbatim as the Agent tool result. The parent may later summarize it in user-facing text.
- Stream shape: SDK streaming can yield raw stream events, complete `AssistantMessage` objects, and final `ResultMessage`. Without partial messages, callers still receive complete assistant/result messages. The CLI exposes `--output-format stream-json`, `--include-partial-messages`, and `--verbose`.
- Tool access: subagents inherit all parent tools by default unless the subagent file defines `tools` or `disallowedTools`.
- Agent spawning restriction: an agent running as the main thread can be restricted to specific spawnable subagents with `Agent(worker, reviewer)` syntax in its `tools` field. If `Agent` is omitted, it cannot spawn subagents.
- Permissions: subagents inherit the parent permission context. Parent `bypassPermissions`, `acceptEdits`, or `auto` takes precedence and cannot be overridden per subagent.
- Plugin subagent caveat: plugin subagents ignore `permissionMode`, `hooks`, and `mcpServers`. If per-subagent `permissionMode` is required, the agent must be copied into project/user scope or supplied with `--agents`.
- Cwd/worktree: subagents start in the main conversation's current working directory. `cd` commands inside Bash do not persist between tool calls. To isolate edits, set `isolation: worktree` on the subagent or ask Claude to use worktrees.

Implications for SwarmDaddy:

- Use `Agent` in new permission fragments and prompt text. Keep `Task` compatibility only where older fixtures or aliases require it.
- Do not rely on plugin-agent `permissionMode` for writer/reviewer isolation. Use tools allowlists, session settings, project/user-scoped agents, or `--agents` JSON if true per-agent permission mode is required.
- If controller-prescribed worktree paths matter, do not depend solely on native `isolation: worktree`; Claude creates its own temporary worktree. Use controller-created unit worktrees and put the path in the subagent prompt, but remember a one-time `cd` instruction is not persistent across later Bash calls.
- To observe subagent progress, teach `ClaudeStreamParser` to preserve `parent_tool_use_id` and `Agent` tool-use frames. Today it extracts assistant text and final result only, which is enough for dispatcher-synthesized markers but not enough for per-subagent progress telemetry.

## External Orchestration Priors

### AutoGen

Source: https://microsoft.github.io/autogen/0.4.5/user-guide/core-user-guide/design-patterns/group-chat.html

AutoGen's `GroupChatManager` owns the routing loop. It maintains chat history, asks an LLM to select the next participant role, prevents immediate repeat speakers in the example, and publishes `RequestToSpeak` to the selected participant topic.

Equivalent pattern for SwarmDaddy:

- Dispatcher is a manager, not an implementer.
- Participants are typed stage agents.
- The manager emits a bounded transition event after specialist completion.
- The durable controller, not the specialist, owns state transitions.

### LangGraph

Source: https://langchain-ai.github.io/langgraphjs/reference/classes/langgraph.Send.html

LangGraph's `Send` is a dynamic fan-out packet returned from conditional edges. It invokes a target node with custom state, and the docs explicitly show map-reduce style parallel invocation with reducer aggregation.

Equivalent pattern for SwarmDaddy:

- `StageInvocation` is the graph packet.
- `expected_result_path` is the per-packet result sink.
- `StageMarkerProcessor` is the reducer/adopter.
- `stage_sessions.v1.json` is the graph execution ledger.

### Pydantic AI

Sources:
- https://github.com/pydantic/pydantic-ai
- https://pydantic.dev/docs/ai/guides/multi-agent-applications/
- https://pydantic.dev/docs/ai/tools-toolsets/deferred-tools/
- https://pydantic.dev/docs/ai/graph/beta/parallel/
- https://pydantic.dev/docs/ai/integrations/durable_execution/overview/
- https://pydantic.dev/docs/ai/integrations/durable_execution/temporal/
- https://pydantic.dev/docs/ai/tools-toolsets/toolsets/
- https://pydantic.dev/docs/ai/core-concepts/capabilities

Pydantic AI's multi-agent docs divide orchestration into agent delegation, programmatic handoff, graph-based control flow, and "deep agent" patterns that combine planning, file operations, task delegation, sandboxed code execution, context management, human-in-the-loop approval, and durable execution. The delegation shape is close to Claude's parent/child result flow: the parent agent calls a delegate agent from inside a tool and regains control when the delegate returns. Programmatic handoff keeps routing decisions in application code instead of delegating them to the model.

Relevant patterns:

- Deferred tools end a run with `DeferredToolRequests` containing tool name, args, and `tool_call_id`; once external work finishes, application code resumes the same message history with `DeferredToolResults` keyed by `tool_call_id`.
- Deferred-tool metadata can carry an application task id distinct from the model's tool-call id, which maps well to SwarmDaddy's `stage_id`, BEADS id, and `expected_result_path` split.
- Failed external work can be returned as `ModelRetry` for that tool call, which is the typed analogue of `STAGE_FAILED` plus retry-class mapping.
- Pydantic Graph's beta API supports broadcast fan-out, iterable/async-iterable `map()` fan-out, join nodes, and reducers. It also exposes internal graph markers/tasks such as `EndMarker`, `ErrorMarker`, `GraphTaskRequest`, and `GraphTask`.
- Durable execution integrations with Temporal, DBOS, Prefect, and Restate preserve agent progress across failures/restarts. The Temporal integration explicitly separates deterministic workflow code from I/O-heavy activities and requires stable agent/toolset identity for activity replay.
- Toolsets and capabilities can filter tools, wrap tool execution, observe event streams, and create fresh per-run instances for mutable state isolation.
- Third-party Pydantic AI ecosystem packages include task-management and subagent capabilities; the documented `SubAgentCapability` surface includes `task`, `check_task`, `wait_tasks`, `list_active_tasks`, cancellation, nested subagents, and runtime agent creation.
- File and sandbox support is delegated to toolsets/capabilities such as `pydantic-ai-filesystem-sandbox`, `pydantic-ai-backend`, `pydantic-deep`, and `mcp-run-python`, with backends including in-memory state, local filesystem, Docker sandbox, and MCP code execution.

Marker equivalent: typed tool-call IDs plus `DeferredToolRequests`/`DeferredToolResults`, graph task/end/error markers, join/reducer outputs, durable workflow history, and event-stream hooks. These are stronger than prose markers because identity and result routing are explicit data.

Worktree equivalent: no first-class git worktree lifecycle found in the official Pydantic AI surface. The closest equivalents are per-run toolset/capability isolation, local/Docker/in-memory filesystem backends, sandboxed code execution, and durable workflow/activity boundaries.

Design lesson: keep SwarmDaddy's live `STAGE_COMPLETE`/`STAGE_FAILED` marker protocol for Claude stream adoption, but make every marker reconcile against stable controller-issued ids and structured result files. Do not treat Pydantic AI's sandbox/file abstractions as a replacement for controller-created git worktrees.

### OpenAI Swarm

Source: https://github.com/openai/swarm

OpenAI Swarm was an educational, client-side multi-agent orchestration framework. Its primitives were `Agent`s and handoffs: an agent encapsulates instructions/tools, and a function returning another `Agent` transfers execution. Its `client.run()` loop performs completion, tool execution, agent switching, context updates, and returns when no more function calls remain. The README now says Swarm has been replaced by OpenAI Agents SDK for production.

Equivalent pattern for SwarmDaddy:

- Handoff can be represented as a normal tool result.
- Handoff should be explicit, narrow, and testable.
- Runtime state should stay outside the worker prompt when deterministic control is needed.

## Plugin And Pattern Survey

### metaswarm

Sources:
- https://github.com/dsifry/metaswarm
- https://raw.githubusercontent.com/dsifry/metaswarm/main/skills/orchestrated-execution/SKILL.md
- https://raw.githubusercontent.com/dsifry/metaswarm/main/guides/worktree-development.md
- https://raw.githubusercontent.com/dsifry/metaswarm/main/skills/external-tools/SKILL.md

Relevant patterns:

- BEADS is the source of truth for task state, dependencies, knowledge priming, and recovery.
- The execution loop is IMPLEMENT -> VALIDATE -> ADVERSARIAL REVIEW -> COMMIT.
- The orchestrator validates independently and does not trust subagent self-reports.
- Work units can run in parallel when independent, but commits converge sequentially.
- Recovery persists `.beads/plans/active-plan.md`, `.beads/context/project-context.md`, and `.beads/context/execution-state.md`.
- The hub-and-spoke worktree guide has the main repository as the orchestration hub, creates worktrees for worker agents, and tells agents to `cd` into the worktree before working.
- The external-tools skill creates one isolated worktree per external invocation, captures JSON facts only, and leaves pass/fail judgment to the orchestrator.

Marker equivalent: BEADS status plus `.beads/context/execution-state.md`, not stream markers.

Worktree equivalent: controller-created worktrees per work unit or external tool invocation, plus later merge/cleanup.

Design lesson: keep markers as the live adoption protocol, but keep BEADS/result JSON as the durable source of truth. Never make the worker's final prose the authoritative completion signal.

### Superpowers

Sources:
- https://github.com/obra/superpowers
- https://raw.githubusercontent.com/obra/superpowers/main/skills/using-git-worktrees/SKILL.md
- https://github.com/obra/superpowers/blob/main/skills/subagent-driven-development/SKILL.md

Relevant patterns:

- Worktree setup is a required pre-execution skill: choose `.worktrees/` if present, verify it is ignored, create a branch/worktree, run setup, and verify the baseline test suite.
- Subagent-driven development dispatches a fresh subagent per task, then runs spec-compliance review and code-quality review.
- It emphasizes curated context: the controller gives the subagent exactly the plan/file context it needs instead of making it read the full plan.
- It warns against dispatching multiple implementation subagents in parallel when conflicts are likely.

Marker equivalent: task status and review outcomes in the controlling conversation, not a machine-readable stream protocol.

Worktree equivalent: an isolated branch/worktree before execution, with baseline verification and cleanup.

Design lesson: SwarmDaddy should parallelize only independent units with disjoint write scopes or unit worktrees. The dispatcher prompt should include file scope and acceptance criteria directly.

### MCO

Source: https://github.com/mco-org/mco/blob/main/README.md

Relevant patterns:

- MCO dispatches Claude, Codex, Gemini, OpenCode, and Qwen in parallel and aggregates structured output.
- It supports review coordination modes: parallel, chain, debate, divide by files, and divide by dimensions.
- It supports machine JSON, SARIF, PR Markdown, artifact modes, JSONL/live streaming, path constraints, provider permissions, and max provider parallelism.

Marker equivalent: structured output/artifacts and optional stream events.

Worktree equivalent: MCO primarily accepts a repo path and path constraints; it is not primarily a worktree lifecycle manager.

Design lesson: expose dispatcher fan-out state as structured artifacts and JSONL-compatible events. Keep provider/path constraints explicit.

### everything-claude-code

Source: https://github.com/affaan-m/everything-claude-code

The README describes a large Claude Code plugin/config collection with many agents, skills, hooks, and command shims. Its catalog explicitly calls out parallelization with git worktrees and subagent orchestration patterns such as the context problem and iterative retrieval.

Marker equivalent: no concrete machine-readable marker protocol found in the public README surface.

Worktree equivalent: git worktrees are documented as a parallelization topic, but this research pass did not find a specific controller-owned worktree lifecycle comparable to SwarmDaddy's `execution_worktree.py`.

Design lesson: useful as a role/skill catalog prior, not as the dispatcher runtime source of truth.

## Local Repo Archaeology

Commands checked:

- `git log --all --stat -- role-specs/agent-dispatcher.md py/swarm_do/pipeline/phase_pump.py`
- `git log --all --oneline -- py/swarm_do/pipeline/stage_invocation.py py/swarm_do/pipeline/stage_sessions.py py/swarm_do/pipeline/orchestrator_stream.py permissions/dispatcher.json agents/agent-dispatcher.md role-specs/agent-dispatcher.md schemas/stage_sessions.schema.json`
- `git show --stat --oneline 274ab18cb19bc737059d3fc981b5ef7606a6107d`

Findings:

- The exact user-supplied path `swarm-do/role-specs/agent-dispatcher.md` is parent-relative from the git root. From this workspace directory, the correct path is `role-specs/agent-dispatcher.md`; the git root is `/Users/mstefanko/.claude/plugins/marketplaces/mstefanko-plugins`.
- Commit `274ab18` (`putting quality lanes back`, 2026-05-02) introduced the dispatcher design:
  - `agents/agent-dispatcher.md`
  - `role-specs/agent-dispatcher.md`
  - `permissions/dispatcher.json`
  - `py/swarm_do/pipeline/stage_invocation.py`
  - `py/swarm_do/pipeline/stage_sessions.py`
  - `py/swarm_do/pipeline/orchestrator_stream.py`
  - `schemas/stage_sessions.schema.json`
  - phase-pump integration and tests
- Those files are not dead history; they still exist in the current tree.
- Current `stage_invocation.py` already expands preset graph stages, fan-out stages, provider stages, merge stages, lenses, upstream ids, and expected stage result paths.
- Current `render_orchestrator_brief()` still renders `Task(subagent_type="general-purpose", prompt=...)` and `STAGE_COMPLETE` marker text.
- Current `stage_sessions.py` persists a durable per-stage ledger with `pending`, `in_progress`, `adopted`, `failed`, `blocked`, and `skipped`.
- Current `orchestrator_stream.py` parses bounded `STAGE_COMPLETE` and `STAGE_FAILED` lines.
- Current `phase_pump.py` already prepares the stage controller, initializes stage sessions, creates stage BEADS children when an epic exists, writes coordinator settings, runs `claude -p --output-format stream-json --verbose`, processes markers live, and writes controller-owned phase result/handoff if stages complete.
- Current tests already cover much of the streaming foundation: `test_phase_pump_streaming.py`, `test_stage_quality.py`, `test_claude_stream.py`, launcher/recovery/core split tests, and execution-worktree unit worktree tests.

Gaps in current code versus the fan-out plan:

- `StageInvocation` has no `subagent_type`, `worktree_path`, `bead_id`, `allowed_files`, or `acceptance_criteria` field yet.
- `render_orchestrator_brief()` hardcodes `general-purpose` and does not render controller-prescribed per-unit worktree prompts.
- `_prepare_stage_controller()` creates stage BEADS children but does not call `materialize_unit_execution_worktree()` for each work unit.
- `execution_worktree.py` already has `materialize_unit_execution_worktree()` and `merge_unit_execution_worktree()`, with tests, but phase dispatcher preparation is not wired to them.
- `permissions/dispatcher.json` still allows `Task`, not `Agent`. Docs say aliases work, but new code should use `Agent` and optionally `Agent(<allowed types>)`.
- `ClaudeStreamParser` ignores `tool_use` blocks and does not retain `parent_tool_use_id`. This is fine for dispatcher-emitted marker text, but insufficient if the UI or controller wants subagent progress events.
- `parse_transcript_task_invocations()` only recognizes tool-use name `Task`; it should recognize `Agent` too.

## Recommended Plan Amendments

1. Rename the new mode to `fanout`, but implement it by extending current dispatcher files rather than creating new orchestration modules.
2. Update the role and permission fragments to use `Agent` terminology, while preserving `Task` fixture compatibility where needed.
3. Add a `subagent_type` field to `StageInvocation`, defaulting from `agent_role`. For plugin-scoped names, verify exact resolution once with `claude -p`; docs support plugin subagents generally, but the exact scoped name should still be measured in this plugin context.
4. Add controller-owned unit worktree materialization before prompt render. The repo already has `materialize_unit_execution_worktree()`; wire it instead of inventing another worktree allocator.
5. Render per-unit prompts with explicit `worktree_path`, `project_root`, `expected_result_path`, `allowed_files`, `bead_id`, and acceptance criteria.
6. Keep marker adoption as the live signal, but treat stage result JSON plus `stage_sessions.v1.json` plus BEADS as the durable source of truth.
7. If subagent internal progress matters, extend `ClaudeStreamParser` to emit assistant/tool frames with `parent_tool_use_id` and count `Agent` tool-use starts. If only completion matters, current assistant-text marker parsing is enough.
8. Do not rely on plugin subagent `permissionMode`; use session settings/tool allowlists or project/user/CLI-defined agents if permission mode must differ by role.
9. Consider adding `--include-partial-messages` only if token/tool-call streaming is needed. `--verbose` plus `stream-json` already supports the current marker-adoption path per local experiments and current tests.
10. Borrow Pydantic AI's deferred-result discipline: every dispatcher marker should reconcile by stable `stage_id` against the controller ledger, the expected result path, and, when available, the originating `Agent` tool-use id.
11. Use metaswarm's guardrail as a design invariant: the dispatcher never trusts worker prose. It checks result files, commits, BEADS state, and review verdict artifacts.
