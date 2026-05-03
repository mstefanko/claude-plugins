# Session Dispatcher Fan-Out — Merged External Research

Date: 2026-05-03
Scope: Synthesizes the codex memo (`swarm-do/docs/session-dispatcher-fanout-external-research-2026-05-03.md`) and the opus three-part memo (`research/external-priors-{dispatcher-fanout,claude-code-plugins,claude-code-task-internals}-2026-05-03.md`).
Related plan: `swarm-do/docs/phase-session-dispatcher-fanout-plan-2026-05-03.md`.

> **Reading guide.** This memo replaces the four sources for design-review purposes. Sections marked **CONFIRMED** are anchored to anthropic-official docs; **OBSERVED** are stream captures from local experiments; **UNCONFIRMED** require an explicit test before the design depends on them.

---

## 1. Executive Findings

1. **Tool rename is real and load-bearing.** Claude Code v2.1.63 renamed `Task` → `Agent`. Existing `Task(...)` references still work as aliases. New permission fragments and prompt text should use `Agent`; keep `Task` only where fixtures demand it. **CONFIRMED** (subagents docs §"Restrict which subagents can be spawned").
2. **Subagent permission inheritance is one-way narrowing.** Subagents inherit the parent's permission context. Parent `bypassPermissions`, `acceptEdits`, and `auto` modes take precedence and **cannot** be overridden per subagent. Plugin subagents additionally ignore `permissionMode`, `hooks`, and `mcpServers`. **CONFIRMED.**
3. **Tool inventory is inherit-then-narrow, never broaden.** Frontmatter `tools` (allowlist) and `disallowedTools` (denylist) only filter the parent's pool. A writer subagent that lists `Write` in its frontmatter still cannot Write if the dispatcher wasn't launched with Write in its inventory. **CONFIRMED — this is the highest-risk constraint for the fanout design (see §6 risk #1).**
4. **Sub-agent output contract is "final message only."** Intermediate tool calls/results stay inside the subagent; only the final assistant message becomes the parent's `tool_result`. `--verbose` + `--output-format stream-json` exposes internal frames tagged with `parent_tool_use_id`, but that envelope field is undocumented and should be treated as best-effort observability. **CONFIRMED for the contract, OBSERVED for the envelope.**
5. **Native `isolation: worktree` exists but is the wrong tool for SwarmDaddy.** Claude creates its own temporary worktree; SwarmDaddy needs controller-prescribed paths tied to BEADS ids and expected result paths. Use controller-created worktrees and inject the path via prompt; don't expect a `cwd` parameter (it doesn't exist on Agent's input schema).
6. **LangGraph `Send` is the cleanest published prior for the dispatcher's fan-out shape.** Each `Send(node, arg, *, timeout)` packet carries a per-task payload (analogous to `StageInvocation`), runs in parallel within one super-step, and reduces results back into parent state. `Command(goto=[Send(...), ...])` returned by a supervisor node is structurally identical to "dispatcher schedules N specialist Tasks."
7. **The four-status vocabulary `DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT` is the de-facto Claude Code subagent return convention.** Used verbatim by both metaswarm and superpowers. SwarmDaddy's binary `STAGE_COMPLETE` / `STAGE_FAILED` should consider expanding to this richer space (especially `DONE_WITH_CONCERNS` to surface follow-ups without forcing retries, and `NEEDS_CONTEXT` to re-spawn rather than retry).
8. **Pydantic AI's deferred-tool-result discipline maps onto SwarmDaddy's marker reconciliation.** Stable tool-call IDs + `DeferredToolRequests`/`DeferredToolResults` keyed by `tool_call_id` are the typed analogue of `STAGE_COMPLETE` reconciling against controller-issued `stage_id`, BEADS id, and `expected_result_path`. Borrow the ID/result-ledger discipline; keep controller-owned worktrees (Pydantic AI has no git worktree primitive).
9. **everything-claude-code is the closest worktree-fanout prior in code.** A working tmux+worktree orchestrator with `git worktree add` per worker, atomic rollback on setup failure, and an `overlaySeedPaths` pattern for sharing uncommitted plan files into worktrees. The tmux-as-orchestrator approach is wrong for us, but the seed-paths and rollback patterns are directly stealable (~30 LoC each).
10. **Working dispatcher-shaped code already exists in this repo.** Commit `274ab18` ("putting quality lanes back", 2026-05-02) introduced `agent-dispatcher`, `permissions/dispatcher.json`, `stage_invocation.py`, `stage_sessions.py`, `orchestrator_stream.py`, `stage_sessions.schema.json`, plus phase-pump integration and tests. **The fanout work should extend this, not create a parallel dispatcher.**

---

## 2. Claude Code Task/Agent Internals (CONFIRMED unless noted)

Authoritative sources (fetched 2026-05-03):

- [Subagents docs](https://docs.claude.com/en/docs/claude-code/sub-agents)
- [Agent SDK subagents](https://docs.claude.com/en/api/agent-sdk/subagents)
- [Permissions](https://docs.claude.com/en/docs/claude-code/permissions)
- [Settings](https://docs.claude.com/en/docs/claude-code/settings)
- [CLI reference](https://docs.claude.com/en/docs/claude-code/cli-reference)
- [Plugins reference](https://docs.claude.com/en/docs/claude-code/plugins-reference)
- [Headless](https://docs.claude.com/en/docs/claude-code/headless)
- [Worktrees](https://code.claude.com/docs/en/worktrees)

### 2.1 Invocation and stream shape

- Tool name in stream: `Agent`. Input schema: `{description, subagent_type, prompt}`. **No `cwd`, no `settings`, no `permission_mode`.** OBSERVED in E1 capture; CONFIRMED by SDK docs.
- The SDK recommends matching both `Task` and `Agent` for stream-parser compatibility.
- Messages produced inside a subagent context include `parent_tool_use_id`. **OBSERVED; not in official docs — keep parser tolerant of absence/rename.**
- The parent receives the subagent's final message verbatim as the Agent tool_result.
- CLI streaming flags: `--output-format stream-json`, `--include-partial-messages` (requires `--print --output-format stream-json`), `--include-hook-events` (requires stream-json), `--verbose`.

### 2.2 `subagent_type` resolution

Lookup order: **Managed > Project > User**, with built-ins always available.

- Built-in: `Explore`, `Plan`, `general-purpose` (always available — guaranteed fallback).
- Project: `.claude/agents/`, discovered by walking up from cwd. **`--add-dir` directories are NOT scanned** — dispatcher must run with the swarm-do repo root (or ancestor) as cwd.
- User: `~/.claude/agents/`.
- CLI-defined: `--agents '<json>'`. Same fields as frontmatter plus a `prompt`.
- Plugin: namespaced as `<plugin>:<agent>` in `/agents` UI. CONFIRMED for UI; **whether the Agent tool's `subagent_type` parameter accepts `swarmdaddy:agent-writer` vs bare `agent-writer` is not explicitly stated — TEST before depending on it.**

**Failure mode unknown.** If `subagent_type` doesn't resolve, behavior is undocumented. Could be tool_error to dispatcher, or silent fallback to `general-purpose`. **TEST:** spawn `subagent_type: "definitely-not-real"` and capture.

### 2.3 Permission propagation (CONFIRMED, partial)

> "Subagents inherit the permission context from the main conversation and can override the mode, except when the parent mode takes precedence." (sub-agents §Permission modes)

Override-blocking rules (verbatim from docs):

> "If the parent uses `bypassPermissions` or `acceptEdits`, this takes precedence and cannot be overridden. If the parent uses [auto mode], the subagent inherits auto mode and any `permissionMode` in its frontmatter is ignored."

- **`--dangerously-skip-permissions` ⇒ subagent runs in `bypassPermissions`.** Sub-agent Bash is not gated, full stop.
- **`--permission-mode acceptEdits` ⇒ subagent inherits acceptEdits**, frontmatter `permissionMode` ignored.
- **`--settings <path>`**: not a separately-propagated boundary. There is one process and one settings stack for the conversation; subagents share the parent's resolved settings stack plus their frontmatter overlays.
- **Plugin subagent caveat:** plugin subagents ignore `permissionMode`, `hooks`, and `mcpServers`. To get per-agent permission mode, copy into project/user scope or supply via `--agents`.

### 2.4 Tool inventory resolution

Algorithm (CONFIRMED):

```
inventory = inherit_all_tools_from_parent()  # including MCP tools
inventory -= frontmatter.disallowedTools     # applied first
if frontmatter.tools:
    inventory = intersection(inventory, frontmatter.tools)  # narrow further
```

A subagent **cannot** add a tool the parent doesn't have. Load-bearing for our design — see §6 risk #1.

### 2.5 Cwd/worktree model

- Subagents start in the main conversation's cwd. `cd` inside Bash does not persist between tool calls.
- Native option: `isolation: worktree` on subagent frontmatter, or CLI `--worktree`. Creates a Claude-managed temporary worktree — wrong abstraction for controller-prescribed paths.
- Right shape for SwarmDaddy: controller creates the worktree (already have `materialize_unit_execution_worktree()` in `execution_worktree.py`); the path is rendered into the prompt. A one-time `cd` instruction is not persistent across later Bash calls — pass the path explicitly in every relevant prompt section.

### 2.6 Cost & turn accounting (PARTIAL)

- `--max-turns` is documented as "limit agentic turns (print mode only)" but doesn't say whether subagent turns count.
- Frontmatter `maxTurns` is per-subagent and independent of the parent cap. **CONFIRMED.**
- Conceptual model: parent's turn counter advances by **one per Agent tool call**, not by subagent internal turns (since intermediates stay scoped). **UNCONFIRMED — TEST:** dispatcher with `--max-turns=5` spawning a subagent that internally takes 20 turns; verify the parent counter only counts Agent tool_use blocks.
- `--max-budget-usd` exists. Use this for budget enforcement; treat `--max-turns` as "max dispatcher decisions."
- OBSERVED: subagent costs aggregate into parent's `result.total_cost_usd`.

### 2.7 Concurrency cap (UNCONFIRMED)

Docs explicitly endorse parallelism ("Multiple subagents can run concurrently") but don't document a hard cap. OBSERVED: 2-in-flight worked. **Plan as-if** there's a soft cap around 5–10. **TEST:** dispatcher emits N parallel Agent tool_use blocks for N ∈ {2, 4, 8, 16}; measure actual concurrency and harness behavior. Cap fanout in dispatcher's role prompt to N=8 until measured.

---

## 3. External Priors — Orchestration Frameworks

### 3.1 LangGraph (`Send`, `Command`) — closest fan-out shape

Sources: [graph-api](https://docs.langchain.com/oss/python/langgraph/graph-api), [use-graph-api](https://docs.langchain.com/oss/python/langgraph/use-graph-api), [types.py](https://github.com/langchain-ai/langgraph/blob/main/libs/langgraph/langgraph/types.py).

**`Send(node, arg, *, timeout)`** is a packet a conditional edge emits to dispatch a single targeted invocation. Properties relevant to SwarmDaddy:

1. **Dynamic** — the set of targets isn't known at compile time.
2. **Per-invocation payload** — `arg` is whatever shape the receiver expects, *not* the parent graph's state. Concurrent fan-out updates compose without clobbering, provided the parent's reducer is a real semilattice (list-concat, dict-merge).
3. **Parallel within a super-step** — multiple `Send`s from the same conditional edge run concurrently.
4. **Per-task `timeout`** — exactly the per-Task budget SwarmDaddy needs.

**`Command(update=..., goto=..., graph=...)`** is what a node returns to atomically mutate state and pick the next node. `goto` accepts a node name, list of nodes, OR a `Send` / list of `Send`s. The supervisor pattern returns `Command(goto=[Send("writer", ...), Send("spec-review", ...)])` — structurally identical to "dispatcher schedules N specialist Tasks."

**Retry / error handling** lives on `add_node`: `retry_policy=RetryPolicy(max_attempts, retry_on=...)` plus a 1.2-alpha per-node `error_handler` that runs after retries are exhausted and can return a `Command` to compensate or route to a recovery node.

**Mapping for SwarmDaddy:**

| LangGraph | SwarmDaddy equivalent |
| --- | --- |
| `Send` packet | `StageInvocation` |
| `Send.arg` (per-task payload) | `{stage_id, bead_id, worktree_path, expected_result_path, allowed_files, acceptance_criteria}` rendered into prompt |
| `Send.timeout` | per-stage budget |
| Reducer | `StageMarkerProcessor` adopting markers into ledger |
| Graph execution log | `stage_sessions.v1.json` |
| `RetryPolicy` + `error_handler` | controller's retry-class mapping + BEADS blocked transition |

**Gap:** LangGraph offers no filesystem isolation primitive. Per-Send isolation is *logical*, not filesystem. SwarmDaddy's per-WU worktree is genuinely novel territory — don't look for prior art to copy here.

### 3.2 AutoGen (`Swarm`, `SelectorGroupChat`) — broadcast model is wrong

Sources: [swarm](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/swarm.html), [selector-group-chat](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/selector-group-chat.html), [GroupChatManager design pattern](https://microsoft.github.io/autogen/0.4.5/user-guide/core-user-guide/design-patterns/group-chat.html).

Two team primitives:

- **`SelectorGroupChat`** — LLM-as-router. Calls an LLM with conversation + each agent's `name`/`description` to pick the next speaker. Defaults: `allow_repeated_speaker=False`. Override via `selector_func`.
- **`Swarm`** — tool-call-driven handoff. Next speaker = whoever the last `HandoffMessage` named. Each `AssistantAgent` declares `handoffs=[...]`; the model emits a handoff via tool calls and the framework reads the target.

**Strong shared property:** all participants broadcast into a single shared message context. Every agent sees every other's output. This is the **opposite** of what SwarmDaddy needs.

**Stage-completion equivalent:** none per-stage. Run-level termination conditions only:
- `HandoffTermination(target="user")`
- `TextMentionTermination("TERMINATE")` — closest to `STAGE_COMPLETE` but only run-level.

**Concurrency:** strictly turn-based; no built-in fan-out. The docs explicitly call out a footgun: with parallel tool calling enabled, `Swarm` reads the *last* `HandoffMessage` and discards the rest. Recommendation: disable `parallel_tool_calls`.

**`GroupChatManager` as design pattern:** owns participant selection and publishes `RequestToSpeak` to the chosen specialist. The manager is explicit control flow, not a worker. Useful framing for SwarmDaddy's dispatcher = manager (not implementer).

**Verdict for SwarmDaddy:** **reject** the broadcast bus model. Keep sub-agent prompts narrowly scoped to their work unit. Borrow only the "manager owns transitions" framing.

### 3.3 OpenAI Swarm — the `context_variables` pattern

Sources: [repo](https://github.com/openai/swarm), [core.py](https://raw.githubusercontent.com/openai/swarm/main/swarm/core.py), [types.py](https://raw.githubusercontent.com/openai/swarm/main/swarm/types.py). (Project archived; OpenAI says use Agents SDK.)

A handoff is a Python function exposed to the LLM as a tool. The function returns either an `Agent` or a `Result(value=..., agent=..., context_variables=...)`. If the result carries an `agent`, the run loop swaps `active_agent` on the next iteration.

**Run loop shape:**

```python
active_agent = agent
while len(history) - init_len < max_turns and active_agent:
    completion = self.get_chat_completion(active_agent, history, ...)
    message = completion.choices[0].message
    history.append(...)
    if not message.tool_calls or not execute_tools:
        break  # ← termination = "no tool calls"
    partial_response = self.handle_tool_calls(message.tool_calls, ...)
    history.extend(partial_response.messages)
    context_variables.update(partial_response.context_variables)
    if partial_response.agent:
        active_agent = partial_response.agent
```

Termination is **implicit**: the active agent emits a message with no tool calls.

**The genuinely useful pattern: `context_variables`.** A flat `dict` that:
- Is `deepcopy`'d at run start and merged per-tool.
- Is **stripped from the JSON schema exposed to the model** (`__CTX_VARS_NAME__ = "context_variables"`; `params["properties"].pop(__CTX_VARS_NAME__, None)`).
- Is injected into any function whose signature includes `context_variables`.

The LLM never sees / cannot manipulate it. This is real prior art for "controller-managed state that flows into specialists but isn't touchable by the LLM."

**Concurrency:** strictly one active agent. If LLM emits multiple parallel `transfer_to_X` calls, only the *last* sticks (each `Result(agent=...)` overwrites `active_agent`). README is explicit about this footgun.

**Failure handling:** none. Functions raise out of `handle_tool_calls`. No retry, no fallback agent.

**Mapping for SwarmDaddy:**

- **Steal:** `context_variables` shape — controller renders per-WU metadata (bead_id, worktree_path, attempt number) into the prefix prompt of each Task call. The dispatcher LLM should not be able to forge or mutate it.
- **Steal (inverted):** SwarmDaddy's explicit `STAGE_COMPLETE` / `STAGE_FAILED` markers are a **deliberate inversion** of Swarm's "no tool call = done" implicit signal. The dispatcher continues across many stages — implicit termination doesn't work. Make markers strict, regex-anchored at line start, documented as a controller contract.
- **Reject:** the run-loop shape (too sequential).

### 3.4 Pydantic AI — typed result-ledger discipline

Sources: [repo](https://github.com/pydantic/pydantic-ai), [multi-agent](https://pydantic.dev/docs/ai/guides/multi-agent-applications/), [deferred-tools](https://pydantic.dev/docs/ai/tools-toolsets/deferred-tools/), [graph parallel beta](https://pydantic.dev/docs/ai/graph/beta/parallel/), [durable execution](https://pydantic.dev/docs/ai/integrations/durable_execution/overview/).

Patterns relevant to SwarmDaddy:

- **Deferred tools** end a run with `DeferredToolRequests` containing `{tool_name, args, tool_call_id}`. External work runs, then application code resumes the same message history with `DeferredToolResults` keyed by `tool_call_id`. Metadata can carry an application task id distinct from the model's tool-call id — maps to SwarmDaddy's `stage_id` / BEADS id / `expected_result_path` split.
- **Failed external work** can return `ModelRetry` for the tool call — typed analogue of `STAGE_FAILED` + retry-class mapping.
- **Pydantic Graph (beta)** supports broadcast fan-out, iterable/async-iterable `map()` fan-out, join nodes, reducers. Internal markers: `EndMarker`, `ErrorMarker`, `GraphTaskRequest`, `GraphTask`.
- **Durable execution** integrations (Temporal, DBOS, Prefect, Restate) preserve agent progress across restarts. Temporal explicitly separates deterministic workflow code from I/O activities and requires stable agent/toolset identity for replay.
- **Toolsets and capabilities** filter tools, wrap execution, observe event streams, create fresh per-run instances for mutable state isolation.
- Documented `SubAgentCapability` surface: `task`, `check_task`, `wait_tasks`, `list_active_tasks`, cancellation, nested subagents, runtime agent creation.

**Marker equivalent:** typed tool-call IDs + `DeferredToolRequests`/`DeferredToolResults`, graph task/end/error markers, join/reducer outputs, durable workflow history. **Stronger than prose markers because identity and result routing are explicit data.**

**Worktree equivalent:** none first-class. Closest: per-run toolset/capability isolation, sandboxed code execution, durable workflow boundaries. **Don't treat sandbox/file abstractions as a replacement for controller-created git worktrees.**

**Design lesson:** keep SwarmDaddy's live `STAGE_COMPLETE`/`STAGE_FAILED` marker protocol for Claude stream adoption, but make every marker reconcile against stable controller-issued ids and structured result files.

---

## 4. External Priors — Plugin/Pattern Repos

### 4.1 metaswarm (dsifry/metaswarm)

Sources: [repo](https://github.com/dsifry/metaswarm), [orchestrated-execution SKILL](https://raw.githubusercontent.com/dsifry/metaswarm/main/skills/orchestrated-execution/SKILL.md), [worktree guide](https://raw.githubusercontent.com/dsifry/metaswarm/main/guides/worktree-development.md), [external-tools SKILL](https://raw.githubusercontent.com/dsifry/metaswarm/main/skills/external-tools/SKILL.md), `agents/swarm-coordinator-agent.md`.

The most directly comparable prior. BEADS-backed. Real coordination code lives in agent/skill markdown — no orchestrator binary; Claude Code itself executes the protocol from prompts.

- **Marker equivalent:** no out-of-band stdout markers. Sub-agent completion signaled by Task `tool_result`. Structure enforced via prompt-required output schemas. Implementer reports use `DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT`. Cross-issue state in JSONL files (`.beads/agents/active-assignments.jsonl`, `.beads/agents/conflict-registry.jsonl`).
- **Worktree equivalent:** worktrees are first-class but **operator-pre-provisioned as a slot pool** (`agent-1`, `agent-2`, ...). Coordinator picks from the pool; doesn't `git worktree add`.
- **Loop:** `IMPLEMENT → VALIDATE → ADVERSARIAL REVIEW → COMMIT`, fresh `Task()` per phase. Orchestrator only spawns subagents and writes the plan; never edits code itself.
- **Sub-agent typing:** inline role-spec via `Task()` prompts. `agents/` directory is consumed by reference from the orchestrator's prompt, not via plugin-namespaced subagent_types.
- **State persistence:** BEADS source of truth + `.beads/agents/*.jsonl` + `.beads/plans/<plan-id>.md`.
- **Concurrency:** parallel `Task()` calls in one assistant message for *independent* work (e.g., 3-reviewer Plan Review Gate panel). Sequential between phases.
- **Cautionary tales (gold):** the "What the Orchestrator MUST NOT Do" list:
  - "Coverage is close enough at 92%, proceeding to commit"
  - "Adversarial review found issues but they're minor, committing anyway"
  - "Fix applied, skipping re-review since the fix is straightforward"
  - "5 FAILs encountered, moving to next work unit without resolution"
- **Anchoring bias rule (load-bearing):** "On re-review after FAIL, the orchestrator MUST spawn a **new** review subagent. Never pass previous findings to the new reviewer." Max 3 retry cycles before human escalation.

**Steal:** four-status vocabulary; fresh-reviewer rule; JSONL state-file shape; the "orchestrator MUST NOT" list as a literal design invariant.

**Reject:** operator-pre-provisioned worktree pool. SwarmDaddy's per-WU worktree creation is finer-grained and avoids slot-recycling concurrency issues.

### 4.2 superpowers (obra/superpowers)

Sources: [repo](https://github.com/obra/superpowers), [worktrees SKILL](https://raw.githubusercontent.com/obra/superpowers/main/skills/using-git-worktrees/SKILL.md), [subagent-driven-development SKILL](https://github.com/obra/superpowers/blob/main/skills/subagent-driven-development/SKILL.md).

A skill library, not a runtime. Orchestration lives in skill markdown that teaches the parent Claude how to dispatch.

- **Marker equivalent:** no stdout markers; status reporting prompt-enforced with same `DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT` vocabulary as metaswarm. Spec reviewer returns `✅ Spec compliant` or `❌ Issues found: [list with file:line refs]`.
- **Worktree equivalent:** advisory, not enforced. `using-git-worktrees/SKILL.md` is a parent-session skill — the parent moves into a worktree before invoking subagent-driven-development; subagents inherit that worktree as cwd. **No per-subagent worktree.** Directory selection priority: `.worktrees/` → `worktrees/` → `~/.config/superpowers/worktrees/<project>/`. Verifies `.gitignore` before creating.
- **Sub-agent typing:** mostly `Task tool (general-purpose)` + prompt templates. Plugin-namespaced `subagent_type` appears once: `Task tool (superpowers:code-reviewer)`. Pattern: standardize via prompt templates, escape to plugin agents only for the most reusable role.
- **State persistence:** TodoWrite (in-session) only. No external store. Plans read once from a markdown file; tasks extracted into TodoWrite.
- **Concurrency:** parallel for independent problem domains (e.g., 3 unrelated test files broken). Sequential when shared state likely. Subagent-driven-development is sequential (one task at a time, two-stage review per task).
- **Don't-trust-the-report framing (verbatim):** "The implementer finished suspiciously quickly. Their report may be incomplete, inaccurate, or optimistic. You MUST verify everything independently."
- **Curated context principle:** "They should never inherit your session's context or history — you construct exactly what they need."
- **Explicit warning:** don't dispatch multiple implementation subagents in parallel when conflicts are likely.

**Steal:** four-status vocabulary; "don't trust the report" framing in spec-review prompt; curated-context principle (controller renders exactly what the subagent needs).

### 4.3 mco (mco-org/mco)

Sources: [README](https://github.com/mco-org/mco/blob/main/README.md), `runtime/review_engine.py`, `runtime/orchestrator.py`, `runtime/types.py`, `runtime/schemas/review_findings.schema.json`.

Not a Claude Code plugin — Python multi-CLI orchestrator that fans out one prompt to N agent CLIs (claude, codex, gemini, qwen, opencode) in parallel and aggregates JSON findings. Different problem domain, but the marker/aggregation patterns are highly applicable.

- **Marker equivalent: strict JSON contract enforced via prompt + schema validation.**

  ```python
  STRICT_JSON_CONTRACT = (
      "Return JSON only. Use this exact shape: "
      '{"findings":[{"finding_id":"<id>","severity":"critical|high|medium|low",'
      '"category":"bug|security|performance|maintainability|test-gap","title":"<title>",'
      '"evidence":{"file":"<path>","line":null,"symbol":null,"snippet":"<snippet>"},'
      '"recommendation":"<fix>","confidence":0.0,"fingerprint":"<stable-hash>"}]}. '
      "If no findings, return {\"findings\":[]}."
  )
  ```

  Schema lives at `runtime/schemas/review_findings.schema.json` and is JSON-schema-validated. The orchestrator counts `parse_success_count` / `parse_failure_count` / `schema_valid_count` / `dropped_findings_count` per `ReviewResult`. Streaming via JSONL events through a `stream_callback`.
- **Worktree equivalent:** none per provider. Same `repo_root`, processes isolated, **path-scope-level** via prompt-injected `Scope:` and `Allowed Paths:` — advisory, not filesystem-enforced.
- **State machine:** `DRAFT → QUEUED → DISPATCHED → RUNNING → {RETRYING|AGGREGATING|FAILED|...}; AGGREGATING → COMPLETED | PARTIAL_SUCCESS | FAILED`. `VALID_TRANSITIONS` is a strict whitelist; illegal transitions raise.
- **Concurrency:** parallel via `ThreadPoolExecutor` + `as_completed`. Each provider in a separate thread, retries via `OrchestratorRuntime.run_with_retry`.
- **Failure taxonomy** (explicit, in `runtime/types.py`):
  - Retryable: `RETRYABLE_TIMEOUT`, `RETRYABLE_RATE_LIMIT`, `RETRYABLE_TRANSIENT_NETWORK`
  - Non-retryable: `NON_RETRYABLE_AUTH`, `NON_RETRYABLE_INVALID_INPUT`, `NON_RETRYABLE_UNSUPPORTED_CAPABILITY`, `NORMALIZATION_ERROR`
  - `PARTIAL_SUCCESS` is a real terminal state. `dropped_findings_count` surfaced separately, not silently dropped.

**Steal:** strict JSON contract + per-output schema validation + parse/schema accounting if SwarmDaddy ever wants structured per-stage payloads (file lists, test counts). Steal the retryable/non-retryable taxonomy verbatim. Steal `PARTIAL_SUCCESS` as a legitimate terminal state.

**Reject:** parallel-by-default for multi-model. SwarmDaddy fans out N different tasks to one model — different problem.

### 4.4 everything-claude-code (affaan-m/everything-claude-code) — closest worktree-fanout prior in code

Sources: `scripts/orchestrate-worktrees.js`, `scripts/lib/tmux-worktree-orchestrator.js` (~17.8 KB), `scripts/lib/state-store/{index,migrations,queries}.js`.

A working tmux+worktree orchestrator. Closest external code to what SwarmDaddy is building.

- **Marker equivalent: file-based, not stdout.** Each worker writes to three files in a coordination dir:

  ```js
  const taskFilePath    = path.join(workerCoordinationDir, 'task.md');
  const handoffFilePath = path.join(workerCoordinationDir, 'handoff.md');
  const statusFilePath  = path.join(workerCoordinationDir, 'status.md');
  ```

  Worker prompt explicitly says: *"The worker launcher captures your response in `<handoff_file>` automatically. The worker launcher updates `<status_file>` automatically."* The launcher (external tool, not the worker) emits markers. Workers told **"Do not spawn subagents or external agents for this task. Report results in your final response."**
- **Worktree equivalent: full per-worker `git worktree add` with seeded paths.** Each worker:

  ```js
  const branchName    = `orchestrator-${sessionName}-${workerSlug}`;
  const worktreePath  = path.join(worktreeRoot, `${repoName}-${sessionName}-${workerSlug}`);
  ```

  Pre-flight: `git rev-parse --is-inside-work-tree` and `tmux -V`. Branch-collision check (`branchExists`).
- **`overlaySeedPaths` pattern:** copies specified paths from `repoRoot` into the worktree (via `fs.cpSync`) so workers can see uncommitted plan files. Validates seed paths stay inside `repoRoot` (path-traversal guard).
- **Atomic rollback:** `rollbackCreatedResources` removes worktrees, deletes branch, tears down tmux session, cleans coord dir if any setup step fails.
- **Dispatcher:** the tmux+shell wrapper, **not an LLM**. Each pane: `tmux send-keys -t <pane> 'cd <worktree> && <launchCommand>'`.
- **State persistence:** SQLite via sql.js + JSON columns. DB at `~/.claude/ecc/state.db`. Tables: sessions, skill_runs, skill_versions, decisions, install_state, governance_events. ~19 KB of query functions, migrations in `migrations.js`.
- **Concurrency:** all workers in parallel as tmux panes (`split-window` per worker, `select-layout tiled`). No serialization between workers; coordination is human-mediated via the coordination dir.
- **Gap (relative to SwarmDaddy):** no stuck/zombie worker detection — relies on user attaching to tmux.

**Steal:**
- `overlaySeedPaths` pattern (~30 LoC) for sharing uncommitted plan docs into worktrees, with path-stays-inside-repo validation.
- Atomic rollback on setup failure (worktree creation, branch creation, coord-dir creation undone in reverse).
- Pre-flight collision check (analog of `tmux has-session`) — generic "don't clobber existing run" guard.

**Reject:**
- Tmux-as-orchestrator. Hands coordination back to the human. SwarmDaddy's dispatcher Claude doing real-time supervision via marker parsing is strictly better for hands-off operation. Tmux can stay as a debug attachment surface only.

### 4.5 everything-claude-code (affaan-m) — README/catalog only

Source: [repo README](https://github.com/affaan-m/everything-claude-code).

Useful as a role/skill catalog prior. Documents git worktrees as a parallelization topic and subagent orchestration patterns (the context problem, iterative retrieval). No concrete machine-readable marker protocol found in the README surface relative to SwarmDaddy's needs. **Not the dispatcher runtime source of truth.**

---

## 5. Local Repo Archaeology

Commands run:

- `git log --all --stat -- role-specs/agent-dispatcher.md py/swarm_do/pipeline/phase_pump.py`
- `git log --all --oneline -- py/swarm_do/pipeline/stage_invocation.py py/swarm_do/pipeline/stage_sessions.py py/swarm_do/pipeline/orchestrator_stream.py permissions/dispatcher.json agents/agent-dispatcher.md role-specs/agent-dispatcher.md schemas/stage_sessions.schema.json`
- `git show --stat --oneline 274ab18cb19bc737059d3fc981b5ef7606a6107d`

Path note: the user-supplied `swarm-do/role-specs/agent-dispatcher.md` is parent-relative from the git root. From the workspace dir `/Users/mstefanko/.claude/plugins/marketplaces/mstefanko-plugins`, the correct path is `role-specs/agent-dispatcher.md`.

**Commit `274ab18` ("putting quality lanes back", 2026-05-02) introduced:**

- `agents/agent-dispatcher.md`
- `role-specs/agent-dispatcher.md`
- `permissions/dispatcher.json`
- `py/swarm_do/pipeline/stage_invocation.py`
- `py/swarm_do/pipeline/stage_sessions.py`
- `py/swarm_do/pipeline/orchestrator_stream.py`
- `schemas/stage_sessions.schema.json`
- phase-pump integration and tests

These files are not dead history — they still exist in the current tree.

**Current state vs the fanout plan:**

| Component | Current state | Fan-out gap |
| --- | --- | --- |
| `stage_invocation.py` | expands preset graph stages, fan-out, provider, merge stages, lenses, upstream ids, expected result paths | no `subagent_type`, `worktree_path`, `bead_id`, `allowed_files`, `acceptance_criteria` fields on `StageInvocation` |
| `render_orchestrator_brief()` | renders `Task(subagent_type="general-purpose", prompt=...)` and `STAGE_COMPLETE` | hardcodes `general-purpose`; no per-unit worktree prompts |
| `stage_sessions.py` | durable per-stage ledger: `pending`, `in_progress`, `adopted`, `failed`, `blocked`, `skipped` | adequate as ledger; reconcile every marker against `stage_id` |
| `orchestrator_stream.py` | parses bounded `STAGE_COMPLETE` and `STAGE_FAILED` lines | adequate for synthesized markers |
| `phase_pump.py` | prepares stage controller, initializes stage sessions, creates stage BEADS children when an epic exists, writes coordinator settings, runs `claude -p --output-format stream-json --verbose`, processes markers live, writes phase result/handoff if stages complete | `_prepare_stage_controller()` doesn't call `materialize_unit_execution_worktree()` for each work unit |
| `execution_worktree.py` | `materialize_unit_execution_worktree()` and `merge_unit_execution_worktree()` exist with tests | not wired from phase dispatcher preparation |
| `permissions/dispatcher.json` | allows `Task` | should use `Agent`; consider `Agent(<allowed types>)` shape |
| `ClaudeStreamParser` | extracts assistant text and final result; ignores tool_use blocks | does not retain `parent_tool_use_id`; fine for marker text, insufficient for per-subagent progress telemetry |
| `parse_transcript_task_invocations()` | recognizes tool name `Task` | should also recognize `Agent` |
| Tests | streaming foundation covered: `test_phase_pump_streaming.py`, `test_stage_quality.py`, `test_claude_stream.py`, launcher/recovery/core split tests, execution-worktree unit-worktree tests | dispatcher fanout end-to-end tests do not exist |

---

## 6. Risks (ordered by "would-break-the-design" severity)

1. **Tool inventory inherit-only-then-narrow (§2.4).** If the dispatcher launches without Write/Edit in its inherited pool, no subagent gets them — full stop.
   **Action:** add a "dispatcher launch contract" section to the plan pinning either `--dangerously-skip-permissions` OR an explicit `--allowedTools` / settings allow-list that is a superset of every subagent role's needs.

2. **Permission mode inherit-with-precedence (§2.3).** Parent `bypassPermissions` / `acceptEdits` / `auto` overrides subagent frontmatter. Cannot have heterogeneous trust levels per role under a bypassed parent.
   **Action:** if graduated trust is required, dispatcher must launch in `default` mode — inverting the current launch contract. Document the trade-off explicitly.

3. **`parent_tool_use_id` is undocumented (§2.1).** Per-frame routing relies on a field name observed but never seen in official docs.
   **Action:** default to consuming the final `tool_result` per Agent invocation (always present); keep verbose-stream parsing as strictly optional observability.

4. **`--max-turns` semantics for sub-agents undocumented (§2.6).** If parent `--max-turns` debits subagent internal turns, dispatcher could die early.
   **Action:** CI test — dispatcher with `--max-turns=5` spawning a subagent that internally takes 20 turns; verify parent counter only advances by Agent tool_use block count.

5. **Concurrency cap unknown (§2.7).** If 32 fanned-out subagents in one assistant message silently serialize or drop, throughput model is wrong.
   **Action:** parallel-fanout stress test for N ∈ {2, 4, 8, 16}. Cap fanout in dispatcher's role prompt to N=8 until measured.

6. **Plugin namespacing in `subagent_type` parameter (§2.2).** Documented for `/agents` UI, not explicitly for the Agent tool input.
   **Action:** test from dispatcher — does `subagent_type: "swarmdaddy:agent-writer"` resolve when the agent ships only as a plugin, or do we need bare `agent-writer`?

7. **`subagent_type` resolution failure mode undocumented.** If a typo silently falls back to `general-purpose`, typed-fanout guarantees are illusory.
   **Action:** test with deliberate typo; capture exact error/fallback. Build a startup precondition check that lists all role-types the dispatcher will use and verifies each resolves.

---

## 7. Recommended Plan Amendments

Distilled from both memos, ordered by impact.

1. **Rename the new mode to `fanout`, but extend current dispatcher files** rather than creating a parallel orchestration module. The work in commit `274ab18` is the foundation.

2. **Use LangGraph `Send`-with-typed-arg as the canonical mental model.** Each Agent tool call carries a typed payload (`stage_id`, `bead_id`, `worktree_path`, `expected_result_path`, `allowed_files`, `acceptance_criteria`) that the controller pre-computed. Don't make the subagent re-derive paths from broadcast context. (Reference: [LangGraph types.py](https://github.com/langchain-ai/langgraph/blob/main/libs/langgraph/langgraph/types.py).)

3. **Add a "dispatcher launch contract" section to the plan.** Pin: `--dangerously-skip-permissions` OR explicit allowlist superset of every role's needs (resolution from §6 risk #1). Document the graduated-trust trade-off (§6 risk #2).

4. **Add a `subagent_type` field to `StageInvocation`**, defaulting from `agent_role`. For plugin-scoped names, verify exact resolution once with `claude -p` (§6 risks #6, #7) before depending on `swarmdaddy:agent-writer` in the dispatcher prompt.

5. **Wire `materialize_unit_execution_worktree()` from `_prepare_stage_controller()`.** The repo already has the worktree helper; phase dispatcher preparation just doesn't call it. Steal everything-cc's atomic rollback for setup failures and the `overlaySeedPaths` pattern (with `path-stays-inside-repo` guard) for sharing uncommitted plan docs.

6. **Render per-unit prompts with explicit `worktree_path`, `project_root`, `expected_result_path`, `allowed_files`, `bead_id`, and acceptance criteria.** Treat metadata as controller-injected (OpenAI Swarm `context_variables` pattern) — the dispatcher LLM should not be able to forge or mutate these. The controller never trusts metadata the dispatcher *writes* — only what it reads back from BEADS.

7. **Update role and permission fragments to use `Agent` terminology.** `permissions/dispatcher.json` should switch from `Task` to `Agent`. Optionally use `Agent(<allowed types>)` to constrain spawnable subagents. Preserve `Task` fixture compatibility where needed; the SDK aliases both for stream parsers.

8. **Keep markers as the live adoption signal; treat stage result JSON + `stage_sessions.v1.json` + BEADS as the durable source of truth.** Borrow Pydantic AI's deferred-result discipline: every marker reconciles by stable `stage_id` against the controller ledger, the expected result path, and (when available) the originating Agent tool-use id. Borrow metaswarm's invariant: **the dispatcher never trusts worker prose. It checks result files, commits, BEADS state, and review verdict artifacts.**

9. **Consider expanding the marker grammar to four statuses:** `DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT`. Map `STAGE_COMPLETE` → `DONE` for compatibility, but add the richer space — especially `DONE_WITH_CONCERNS` (passes the marker but flags follow-ups for next phase) and `NEEDS_CONTEXT` (re-spawn with more context, not retry blindly). De-facto Claude Code convention from metaswarm + superpowers.

10. **Adopt the metaswarm "fresh `Task()` for every review" rule as a design invariant.** On re-review after FAIL, controller MUST spawn a brand-new review subagent with no prior findings. Anchoring bias is real. Cap retry cycles at 3 before BEADS-blocked + human escalation.

11. **Adopt mco's failure taxonomy verbatim** for retry classification: `RETRYABLE_{TIMEOUT,RATE_LIMIT,TRANSIENT_NETWORK}` vs `NON_RETRYABLE_{AUTH,INVALID_INPUT,UNSUPPORTED_CAPABILITY}` + `NORMALIZATION_ERROR`. `PARTIAL_SUCCESS` should be a real terminal state (some stages adopted, some blocked; phase result preserves both).

12. **If subagent internal progress matters, extend `ClaudeStreamParser`** to emit assistant/tool frames with `parent_tool_use_id` and count `Agent` tool-use starts. If only completion matters, current assistant-text marker parsing is enough. Treat `parent_tool_use_id` parsing as best-effort observability (§6 risk #3).

13. **Do not rely on plugin-subagent `permissionMode`.** Use session settings / tool allowlists, or project/user/CLI-defined agents (`--agents` JSON), if permission mode must differ by role.

14. **Consider `--include-partial-messages` only if token/tool-call streaming is required.** `--verbose` + `stream-json` already supports the marker-adoption path per local experiments and current tests.

15. **Reject the AutoGen broadcast-bus model.** Keep subagent prompts narrowly scoped to their work unit. Borrow only the "manager owns transitions" framing.

16. **Reject the everything-cc tmux-as-orchestrator approach.** SwarmDaddy's dispatcher Claude doing real-time marker supervision is strictly better for hands-off operation. Keep tmux as a debug attachment surface only.

17. **Add validation suite tests for §6 risks #4–#7 before Phase 1.** Specifically: parent-vs-subagent turn accounting, parallel fanout stress test (N ∈ {2, 4, 8, 16}), plugin-namespaced `subagent_type` resolution, typo fallback behavior.

---

## 8. Honest Grading of Priors

| Repo / framework | Coordination depth | Code/patterns we can steal |
| --- | --- | --- |
| **LangGraph** | Cleanest formal fan-out shape (`Send` + `Command`) | `Send.arg` as `StageInvocation` payload; `Command(goto=[Send,...])` as supervisor return shape; per-target retry/error_handler split |
| **Pydantic AI** | Strongest typed-result discipline | Stable tool_call_id reconciliation; `DeferredToolRequests`/`Results`; failure taxonomy |
| **OpenAI Swarm** | Simplest run-loop; archived | `context_variables` pattern (controller-only state, stripped from model schema); explicit-marker rationale (inversion of "no tool call = done") |
| **AutoGen** | Broadcast-bus is wrong domain | "Manager owns transitions" framing only; reject the bus |
| **metaswarm** | Real protocol in markdown; high | Four-status vocabulary; fresh-reviewer rule; "MUST NOT" list; JSONL state files; BEADS-as-source-of-truth |
| **superpowers** | Skill library, no runtime | Same status vocabulary; "don't trust the report" framing; curated-context principle |
| **mco** | Real Python runtime; wrong domain (multi-model consensus) | Strict JSON contract + schema validation + parse accounting; failure taxonomy; `PARTIAL_SUCCESS` as terminal state; state machine whitelist |
| **everything-cc (orchestrate-worktrees)** | Closest worktree-fanout in code | `git worktree add` + `overlaySeedPaths` + atomic rollback + branch-collision check |
| **everything-cc (catalog repo)** | README-level only | Role catalog reference, not runtime |

None of the priors solve SwarmDaddy's exact problem (one Claude dispatcher emitting parseable stage markers while controller pre-creates BEADS + worktrees + result paths and adopts markers live). The work is to combine: superpowers' single-dispatcher-session simplicity + everything-cc's per-worker worktree isolation + mco's strict-output-contract discipline + metaswarm's fresh-reviewer/status-vocabulary discipline + Pydantic AI's typed-id reconciliation + LangGraph's `Send.arg` payload model — anchored by Anthropic-official subagent semantics.
