# SwarmDaddy API Design and Implementation Plan

Date: 2026-05-02
Status: proposed implementation plan, revised after API contract review on 2026-05-03
Repo snapshot: `swarm-do@543bb08a4c933559904a6d79a87fd4a2fa149e5a`
Source context:

- `docs/swarmdaddy-runtime-foundations-adoption-plan-2026-05-02.md`
- `docs/runtime-foundations/README.md`
- `docs/runtime-foundations/phase-7-operator-decisions-plan.md`
- `py/swarm_do/pipeline/state_projector.py`
- `py/swarm_do/pipeline/phase_sessions.py`
- `py/swarm_do/pipeline/stage_sessions.py`
- `py/swarm_do/pipeline/operator_decisions.py`
- `schemas/telemetry/run_events.schema.json`
- `pyproject.toml`

Revision note:

This revision resolves the contract blockers from review: API identity,
wire-format errors, mutating idempotency, event cursor backing, server
lifecycle, prompt privacy, and Step 10 scope. A writer must not start API code
until the Step 0 ADR lands and the locked contract decisions below are accepted.

## Review Resolution Checklist

| Review item | Validation | Revision |
|---|---|---|
| Identity/operator derivation | Phase 7 requires an `operator` string and current bearer-token sketch had no principal identity. | Added per-token principal config and rejected arbitrary `X-Operator` by default. |
| Error contract undefined | Existing plan referenced error names without a wire shape. | Added RFC 9457 problem-details envelope and initial error-code registry. |
| Idempotency unspecified | Phase 7 minute-bucket duplicate detection is not enough for HTTP retries. | Added required `Idempotency-Key`, scope, TTL, mismatch behavior, and durable ledger location. |
| Cursor backing undecided | Mirror has an `events` table, but `run_events.jsonl` is the append-only source available today. | Pinned V1 event cursors to JSONL byte offsets behind opaque tokens. |
| Pydantic/TUI precedent false | `pyproject.toml` has no Pydantic dependency and the TUI marker is Textual-only. | Removed the precedent claim; Pydantic is only in the optional `api` group. |
| Server lifecycle missing | Existing code supports atomic JSON reads, mirror fallback, and phase-session locks. | Added one-process/one-data-dir lifecycle, polling SSE, mirror rebuild behavior, and lock rules. |
| ADR Step 0 not gated | ADR 0009 slot is available and should define the API boundary first. | Made Step 0 a hard prereq before Step 1+. |
| Step 10 too vague | Starting runs crosses from observation to orchestration. | Split Step 10 into deferred 10A/10B/10C/10D gates. |
| Operator-input privacy vague | Phase 7 stores local command payloads and emits redacted summaries. | Specified API-visible redaction fields and banned raw input from API events/cards/prompts. |
| n8n SSE casing/path | n8n workflow node type is `n8n-nodes-base.sseTrigger`; docs URL is currently lower-case. | Added explicit camel-case node type guidance for examples. |
| Severity mapping unsourced | `schemas/telemetry/run_events.schema.json` enumerates event types. | Sourced the table from that enum and added a default rule. |
| `attention.prompt_count` source unclear | Prompt projection can be computed before the prompt route exists. | Defined it as a local `OperatorPrompt` projection reused by future prompt endpoints. |
| `/v1/version` overlap | Capabilities can carry version metadata. | Dropped `/v1/version` from V1. |
| n8n events endpoint duplicate | n8n can consume the generic events endpoints. | Removed `/v1/integrations/n8n/events` from V1. |
| Missing tests | Review called out path redaction, OpenAPI stability, and needs-input resume. | Added those tests to Step 1, Step 3, and Step 9 acceptance gates. |

## Objective

Add a clean, optional API surface around SwarmDaddy so other services can
observe runs and eventually drive controlled operator actions.

The API is secondary to the CLI and TUI. V1 should make live read access easy
for Home Assistant cards, n8n polling/notifications, simple mobile viewers, and
web dashboards. Mutating commands should arrive only after the read API is
stable, and should route through the existing audited command model rather than
becoming another state writer.

## Senior Implementation Decision

Build the API as a read-model facade first.

SwarmDaddy already has the right internal shape for V1:

- Phase 4.5 introduced a per-run read-only SQLite mirror at
  `runs/<run-id>/state.mirror.sqlite`. JSON remains canonical.
- `phase_status()` already uses the mirror when available and falls back to
  canonical JSON.
- `RunTrace` already provides a derived run view from canonical artifacts.
- `stage_sessions.v1.json` is a durable ledger for live stage state.
- Phase result and handoff artifacts already include human-readable fields.
- Phase 7 introduced `operator_decisions.v1.json` as the audit spine for future
  mutating recovery commands.

The API should not write canonical JSON, `state.mirror.sqlite`, or telemetry
ledgers directly. It should call existing owner modules on the read side and,
later, a narrow command adapter on the write side.

## Contract Decisions Locked By Review

These decisions close the open API-contract questions. Treat them as part of
the V1 contract unless a later ADR explicitly supersedes them.

### 1. Identity model

Options considered:

- Single shared bearer token plus arbitrary `X-Operator`.
- Per-token identity config.
- Full user accounts or OAuth.

Recommendation:

Use per-token identity config. `auth.py` must resolve every accepted token to
an `ApiPrincipal` with `token_id`, `operator`, and `scopes`. The `operator`
string uses the Phase 7 format, such as `local:mstefanko` or `ci:n8n`, and must
be validated by the same operator rules used by `operator_decisions.py`.

For the simple env-var path, `SWARM_API_TOKEN` maps to one principal. Its
operator is `SWARM_API_OPERATOR` when set, otherwise `default_operator()` from
`operator_decisions.py`. The richer config file path is:

```text
${CLAUDE_PLUGIN_DATA}/api/tokens.v1.json
```

Example:

```json
{
  "schema_version": 1,
  "tokens": [
    {
      "token_id": "mobile",
      "token_sha256": "<sha256-of-token>",
      "operator": "local:mstefanko",
      "scopes": ["read:runs", "read:events", "command:retry"]
    },
    {
      "token_id": "n8n",
      "token_sha256": "<sha256-of-token>",
      "operator": "ci:n8n",
      "scopes": ["read:runs", "read:events"]
    }
  ]
}
```

Reject arbitrary `X-Operator` in production mode. A header that can relabel a
shared token makes the audit string spoofable. If a local debug override is ever
needed, gate it behind `--dev-allow-operator-header` and disable it whenever
`--host` is not loopback.

### 2. Error envelope

Options considered:

- Ad hoc `{"error": "...", "message": "..."}` responses.
- RFC 9457 Problem Details with SwarmDaddy extensions.
- FastAPI validation errors passed through unchanged.

Recommendation:

Use RFC 9457 Problem Details for every non-2xx API error. RFC 9457 is the
successor to RFC 7807, and preserves the `application/problem+json` media type.
The stable SwarmDaddy machine field is `code`.

```json
{
  "type": "https://swarmdaddy.local/problems/kind-not-integrated",
  "title": "Operator decision kind is not integrated",
  "status": 409,
  "code": "kind_not_integrated",
  "detail": "retry_phase is integrated; resume_with_input is record-only",
  "instance": "/v1/runs/01HYEXAMPLERUNID000000000/commands",
  "request_id": "req_01HY...",
  "fields": {
    "kind": "resume_with_input",
    "integrated_kinds": ["retry_phase"]
  }
}
```

Initial error-code registry:

| Code | HTTP | When |
|---|---:|---|
| `unauthorized` | 401 | Missing, malformed, or unknown bearer token |
| `forbidden` | 403 | Authenticated token lacks required scope |
| `validation_error` | 422 | Request body or query parameters fail schema |
| `run_not_found` | 404 | Run directory or run record is absent |
| `phase_not_found` | 404 | Phase id is not present in the run |
| `artifact_not_found` | 404 | Requested artifact is absent |
| `artifact_unreadable` | 500 | Existing artifact cannot be read or parsed |
| `cursor_invalid` | 400 | Cursor cannot be decoded or has the wrong version |
| `cursor_scope_mismatch` | 400 | Cursor belongs to another endpoint/run/filter scope |
| `cursor_stale` | 410 | Cursor points outside the current event log |
| `limit_invalid` | 422 | `limit` is outside the allowed range |
| `command_disabled` | 403 | Mutating commands are not enabled |
| `kind_unknown` | 422 | Command kind is not a known Phase 7 kind |
| `kind_not_integrated` | 409 | Known kind is not in `INTEGRATED_KINDS` |
| `idempotency_key_required` | 400 | Mutating request omitted `Idempotency-Key` |
| `idempotency_key_invalid` | 400 | Key is too long, empty, or contains unsafe bytes |
| `idempotency_key_conflict` | 409 | Same scoped key used with a different request hash |
| `idempotency_in_progress` | 409 | Same scoped key is already executing |
| `run_locked` | 409 | Phase-session lock cannot be acquired |
| `decision_already_applied` | 409 | Destructive decision was already applied |
| `confirm_required` | 409 | Destructive kind needs a confirm token |
| `unsupported_media_type` | 415 | Request body media type is unsupported |
| `internal_error` | 500 | Unexpected server failure |

Map internal hyphenated Phase 7 errors, such as `kind-not-integrated`, to the
API's snake-case `code` values at the HTTP boundary.

### 3. Idempotency semantics

Options considered:

- Trust Phase 7's minute-bucket duplicate detection.
- Store idempotency records only in memory.
- Store a durable API idempotency ledger keyed by request scope.

Recommendation:

Every mutating endpoint requires `Idempotency-Key`. The API must keep a durable
ledger at:

```text
${CLAUDE_PLUGIN_DATA}/api/<data_dir_id>/idempotency.v1.sqlite
```

The key scope is:

```text
data_dir_id + token_id + method + route_template + run_id + idempotency_key
```

The request hash is canonical JSON over method, route template, path params,
query params, and request body. Header values other than the idempotency key and
auth principal are excluded.

Semantics:

- Missing key: `400 idempotency_key_required`.
- Same scope and same request hash, already complete: return the cached status,
  headers, and body with `Idempotent-Replay: true`.
- Same scope and different request hash: `409 idempotency_key_conflict`; do not
  mutate state.
- Same scope still running: `409 idempotency_in_progress`.
- TTL: cache completed responses for 24 hours by default, configurable by
  `--idempotency-ttl-hours`. Cleanup is opportunistic.
- Store only the idempotency-key SHA-256, never the raw key.

The API command adapter must not rely on Phase 7's minute-based duplicate
detection. The idempotency ledger is the HTTP retry source of truth and must
store `status`, `request_hash`, `operator_decision_id`, `response_status`,
`response_body`, `created_at`, and `expires_at`. The command adapter reserves
the row before recording a decision, writes `operator_decision_id` immediately
after record, and writes the final cached response after apply. If a process
dies with an incomplete row and no safe cached outcome, retries keep returning
`409 idempotency_in_progress` with recovery guidance; they must not silently
re-run a possibly applied mutation.

### 4. Event cursor backing

Options considered:

- Mirror `events.event_seq`.
- `RunTrace.run_event_recent` sequence values.
- Raw `telemetry/run_events.jsonl` byte offsets hidden behind opaque cursors.

Recommendation:

Pin V1 cursors to `telemetry/run_events.jsonl` byte offsets, but keep the wire
token opaque. This is the least surprising backing source because
`run_events.jsonl` is append-only today and is already the source read by
`RunTrace` and the TUI event helpers.

Cursor payload, before signing/encoding, contains:

```json
{
  "version": 1,
  "source": "run_events_jsonl",
  "scope": "run_events",
  "run_id": "01HYEXAMPLERUNID000000000",
  "offset": 12345,
  "line_sha256": "<last-emitted-line-sha256-or-null>"
}
```

The encoded cursor must not expose local file paths, raw line numbers, or raw
SQLite row ids. If the JSONL file is truncated, rotated, unreadable, or the
cursor scope does not match the endpoint, return `410 cursor_stale` or
`400 cursor_scope_mismatch` with guidance to relist from no cursor.

`GET /v1/runs/{run_id}/events` without `after` starts at byte offset 0. SSE
without `after` starts at current EOF for live-only streaming; clients that need
backfill should call the polling endpoint first and then connect with
`next_cursor`.

### 5. Concurrent mutation behavior

Options considered:

- Freeze a read snapshot for every API request.
- Acquire phase-session locks for reads.
- Rely on atomic file writes for reads and reserve locks for commands.

Recommendation:

V1 reads are live, not snapshot-isolated. Read endpoints must tolerate concurrent
phase-session updates by using existing atomic JSON artifacts, read-only mirror
checks, and fallback behavior in `phase_status()`. Do not take the
phase-session lock for read endpoints; that would make dashboards compete with
the pump.

Mutating endpoints must acquire the same `locked_phase_sessions(run_id)` lock
used by Phase 7 apply. If the lock cannot be acquired within the configured
timeout, return `409 run_locked`.

### 6. Version metadata

Options considered:

- Keep both `/v1/version` and `/v1/capabilities`.
- Put version fields only in health.
- Use `/v1/capabilities` as the only version/capability contract.

Recommendation:

Drop `/v1/version` from V1. `/v1/health` is liveness only.
`/v1/capabilities` is the stable metadata endpoint and includes `api_version`,
`package_version`, `schema_versions`, command status, auth mode, and event
cursor version.

### 7. Pagination on non-event lists

Options considered:

- No pagination outside events.
- Offset pagination.
- Cursor pagination only where list size can grow without a natural bound.

Recommendation:

Use cursor pagination for `/v1/runs` and `/v1/runs/{run_id}/artifacts`; use no
pagination for per-run phases, stages, attempts, cards, and prompts in V1.
Those per-run lists are naturally bounded by the prepared plan and stage
artifacts, and clients benefit from receiving a complete run view.

Defaults:

```text
limit default: 50
limit max: 200
sort: updated_at desc for runs, path asc for artifacts
```

Events keep their dedicated JSONL-offset cursor model.

### 8. Multi-tenant data dir

Options considered:

- Route-level tenant/data-dir parameter.
- Token-to-data-dir multiplexing inside one server.
- One API server process per data dir.

Recommendation:

V1 is single-tenant: one server process serves one resolved data dir. The CLI
accepts `--data-dir` using existing `resolve_data_dir()` behavior. Capability
responses may include a non-secret `data_dir_id` fingerprint, but must never
include the absolute data-dir path unless a local debug flag is enabled.

Run multiple server instances on different ports for multiple data dirs. Do not
put data-dir selection into public routes.

### 9. Step 10 scope

Options considered:

- Keep Step 10 as a broad "configure and start runs" milestone.
- Delete Step 10 entirely.
- Split it into a deferred mini-epic with separate gates.

Recommendation:

Keep Step 10 only as a deferred mini-epic. Split it into read-only config
discovery, dry-run validation, accepted-artifact start, and explicit plan-request
start. No Step 10 write surface may start until V1 reads, SSE, command
idempotency, and remote response are stable.

## Research Method

This plan borrows API patterns from mature automation/orchestration systems.
These references were checked on 2026-05-02, with the n8n SSE node URL
spot-checked again on 2026-05-03. They are product documentation URLs rather
than pinned source commits; implementation agents must re-check the linked docs
before adopting exact endpoint details.

When a future implementation borrows code-level shapes from a repository rather
than product docs, use the runtime-foundations pin format:

```text
project@<commit-sha> path/to/file:<lines>
```

## Borrowed API Patterns

### Home Assistant - dashboard-friendly state resources

References:

- <https://developers.home-assistant.io/docs/api/rest/>
- <https://developers.home-assistant.io/docs/api/websocket/>
- <https://www.home-assistant.io/integrations/sensor.rest/>

Observed pattern:

- REST API uses bearer-token authentication.
- State is exposed as simple JSON resources such as `/api/states`.
- WebSocket clients authenticate first, then subscribe to events.
- RESTful Sensor can poll one JSON endpoint and expose selected fields as state
  and attributes for Lovelace cards.

SwarmDaddy adaptation:

- Provide one Home Assistant optimized endpoint:

```http
GET /v1/home-assistant/state
Authorization: Bearer <token>
```

Example response shape:

```json
{
  "state": "running",
  "message": "Phase 2 is running: Apply runtime read model",
  "severity": "info",
  "run_id": "01HYEXAMPLERUNID000000000",
  "active_phase_id": "2",
  "progress": {
    "phases_total": 5,
    "phases_complete": 1,
    "stages_total": 8,
    "stages_adopted": 3
  },
  "needs_input": [],
  "attributes": {
    "next_phase": "3",
    "last_event_type": "phase_session_started",
    "updated_at": "2026-05-02T18:00:00Z"
  }
}
```

Comment:

Do not make Home Assistant parse raw phase-session artifacts. Give it one small,
stable, card-friendly object.

### n8n - polling first, outbound webhooks later

References:

- <https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.httprequest/>
- <https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/>
- <https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.ssetrigger/>

Observed pattern:

- HTTP Request nodes work well with simple JSON polling endpoints.
- Webhook nodes work well when another service actively posts events to n8n.
- SSE is available, but it is less universal than polling or outbound webhooks.

SwarmDaddy adaptation:

- V1: support polling with an opaque cursor.

```http
GET /v1/runs/{run_id}/events?after=<cursor>&limit=100
Authorization: Bearer <token>
```

- V1.1: add outbound webhook subscriptions after read API stability.

```http
POST /v1/webhook-subscriptions
```

Example future subscription:

```json
{
  "url": "https://n8n.example/webhook/swarmdaddy",
  "event_types": [
    "phase_session_needs_input",
    "phase_session_failed",
    "phase_session_completed",
    "operator_decision_applied"
  ],
  "secret_ref": "local-keychain-or-config-ref"
}
```

Comment:

Polling is simpler and safer for local V1. Outbound webhooks add credential,
retry, signing, and delivery-state concerns, so they should be a follow-up.
The n8n workflow node type is camel-case `n8n-nodes-base.sseTrigger`; keep
examples on that node type even though the public documentation URL is currently
lower-case.

### GitHub Actions - separate resources from operations

References:

- <https://docs.github.com/en/rest/actions/workflow-runs>
- <https://docs.github.com/en/rest/actions/workflow-jobs>

Observed pattern:

- Workflow runs and jobs are read resources.
- Operational actions such as rerun, cancel, approve, and download logs are
  separate endpoints.
- Runs have `status` and terminal `conclusion` style fields.

SwarmDaddy adaptation:

- Keep read resources clean:

```http
GET /v1/runs/{run_id}
GET /v1/runs/{run_id}/phases
GET /v1/runs/{run_id}/stages
GET /v1/runs/{run_id}/attempts
```

- Put future operations behind a command endpoint:

```http
POST /v1/runs/{run_id}/commands
```

Example future command:

```json
{
  "kind": "retry_phase",
  "payload": {
    "phase_id": "2",
    "reason": "operator requested retry from mobile"
  }
}
```

Comment:

Avoid RPC-style endpoints like `/retry-phase` and `/cancel-run` until the command
catalog is stable. A command resource maps better to Phase 7 audit records and
idempotency.

### Kubernetes and Argo - watch streams need cursors

References:

- <https://kubernetes.io/docs/reference/using-api/api-concepts/>
- <https://argo-workflows.readthedocs.io/en/latest/rest-api/>

Observed pattern:

- List and watch are related but distinct concerns.
- Watch streams need a position token, resource version, or other cursor.
- Clients must recover from stale cursors by relisting.

SwarmDaddy adaptation:

- V1 events endpoint returns an opaque cursor.
- V1 SSE endpoint accepts the same cursor.
- The cursor is not a public sequence contract. It may encode a mirror event seq,
  telemetry file offset, source digest, or later canonical SQLite event id.

Example response:

```json
{
  "run_id": "01HYEXAMPLERUNID000000000",
  "next_cursor": "v1:events:0000000000001234",
  "events": [
    {
      "cursor": "v1:events:0000000000001233",
      "type": "phase_session_started",
      "timestamp": "2026-05-02T18:00:00Z",
      "phase_id": "2",
      "severity": "info",
      "message": "Phase 2 started"
    }
  ]
}
```

Comment:

Do not expose raw line numbers or SQLite row ids as the API contract. Keep
cursors opaque so Phase 9 can change the backing store without breaking clients.

### FastAPI - optional modular HTTP layer

References:

- <https://fastapi.tiangolo.com/tutorial/bigger-applications/>
- <https://fastapi.tiangolo.com/tutorial/metadata/>
- <https://fastapi.tiangolo.com/how-to/extending-openapi/>

Observed pattern:

- `APIRouter` keeps larger APIs modular.
- OpenAPI, Swagger UI, and ReDoc are generated by default; current FastAPI
  generates OpenAPI 3.1 by default.
- Pydantic models produce typed request/response contracts.

SwarmDaddy adaptation:

- Use FastAPI as an optional dependency group, not a core dependency.
- Keep the HTTP layer thin.
- Keep read-model functions usable by CLI/TUI tests without importing FastAPI.

Comment:

FastAPI is modern and productive, but the CLI cold-start budget still matters.
Optional dependencies keep the core SwarmDaddy path clean.

### 2026 alternatives check

References:

- <https://spec.openapis.org/oas/latest.html>
- <https://www.openapis.org/blog/2025/09/23/announcing-openapi-v3-2>
- <https://www.rfc-editor.org/rfc/rfc9457.html>
- <https://docs.litestar.dev/latest/usage/openapi/index.html>
- <https://docs.litestar.dev/latest/usage/plugins/problem_details.html>
- <https://connexion.readthedocs.io/en/stable/>
- <https://typespec.io/docs/emitters/openapi3/reference/>
- <https://www.asyncapi.com/docs/reference/specification/v3.0.0>
- <https://modelcontextprotocol.io/docs/learn/architecture>
- <https://modelcontextprotocol.io/specification/2025-11-25/basic/transports>

OpenAPI remains the right V1 contract target. The OpenAPI Specification is still
the standard language-agnostic description for HTTP APIs. OpenAPI 3.2 was
released on 2025-09-19 and adds stronger support for streaming media types such
as `text/event-stream` and `application/jsonl`, which fits this plan's SSE and
JSONL event model. However, FastAPI currently emits OpenAPI 3.1 by default, and
the Python ecosystem's OpenAPI 3.2 tooling is still catching up. V1 should keep
generated OpenAPI 3.1 unless a concrete client generator needs 3.2; the event
docs can describe SSE/JSONL behavior manually until the framework/tooling path
is proven.

Litestar is the strongest Python framework alternative to FastAPI. It has
first-class OpenAPI support, supports dataclasses, `TypedDict`, Pydantic, and
msgspec models, and includes an RFC 9457 Problem Details plugin. This makes it
especially attractive if the ADR's cold-start or dependency benchmark rejects
Pydantic as an API dependency. It is not the default recommendation because
FastAPI has the larger ecosystem, simpler contributor familiarity, and enough
functionality for a thin optional facade. The Step 0 ADR should list Litestar as
the fallback framework if FastAPI import cost or schema customization becomes a
real blocker.

Starlette directly, Falcon, aiohttp, Quart, and APIFlask are viable but weaker
fits. Starlette would minimize framework weight, but SwarmDaddy would then own
more validation, schema, docs, and problem-response glue. Falcon and aiohttp are
good low-level API/server frameworks, but they do not reduce this plan's main
risk: stable typed contracts with low implementation drag. Quart and APIFlask
are reasonable Flask-family choices, but they do not beat FastAPI/Litestar for
typed OpenAPI-first ergonomics in a new optional API package.

Connexion and TypeSpec are credible spec-first alternatives, but not V1 defaults.
Connexion turns an OpenAPI document into routing, auth, validation, and Swagger
UI behavior, which is useful when external client teams need a contract before
server implementation. TypeSpec can author a higher-level contract and emit
OpenAPI. Both add a second source of truth unless SwarmDaddy commits to
design-first API development. This plan should stay code-first generated
OpenAPI for V1, with an OpenAPI golden test as the contract guard. Revisit
Connexion or TypeSpec only if SDK generation or external API governance becomes
a first-class requirement.

AsyncAPI is not a V1 replacement for OpenAPI. It describes message-driven APIs
and event-driven architecture across brokers and protocols. SwarmDaddy V1 is
HTTP polling plus SSE, not a brokered event platform. AsyncAPI becomes relevant
only if outbound webhooks or broker-based event delivery becomes a public
integration surface with independent subscribers.

MCP is not a substitute for the public local API. MCP is a JSON-RPC protocol for
AI applications to discover and invoke tools, resources, and prompts, with stdio
and Streamable HTTP transports. It is interesting for a future "LLM operator"
surface, but Home Assistant, n8n, mobile viewers, and web dashboards need plain
HTTP JSON resources, stable auth, and OpenAPI-shaped docs. Do not route V1
through MCP. If MCP is added later, implement it as another adapter over the
same `read_model.py` and command adapter; do not let it become a second state
owner.

GraphQL, gRPC, JSON:API, and JSON-RPC were also checked conceptually and remain
out of scope. GraphQL is useful when clients need flexible nested queries; this
plan needs predictable card/status/event resources. gRPC is strong for
high-throughput typed service-to-service RPC but adds protobuf tooling and is a
poor fit for Home Assistant and simple curl/n8n usage. JSON:API standardizes
resource documents but would force envelope/relationship machinery over run
artifacts that are already display projections. JSON-RPC would be a worse fit
than REST for dashboard-friendly read resources and would blur command/resource
boundaries.

Conclusion:

The plan remains sound with two amendments: use RFC 9457 wording for problem
details, and record Litestar as the explicit fallback if FastAPI plus Pydantic
fails the optional-dependency or schema-control benchmark. OpenAPI remains the
right contract target; FastAPI remains the recommended V1 implementation layer;
OpenAPI 3.2 and AsyncAPI should be watched for streaming/event docs, but should
not delay V1.

## Current SwarmDaddy Anchors

### Read side

`py/swarm_do/pipeline/state_projector.py`:

- `state.mirror.sqlite` is explicitly read-only derived state.
- `query_mirror()` already opens SQLite with a read-only URI.
- `load_phase_status_from_mirror()` provides a status shape usable by API cards.

`py/swarm_do/pipeline/phase_sessions.py`:

- `phase_status()` is the existing high-level read API for CLI, TUI, and resume.
- It prefers the mirror and falls back to JSON.

`py/swarm_do/pipeline/run_trace.py`:

- `RunTrace` includes phases, attempts, provider reviews, events, artifacts, and
  warnings.
- This is a strong source for detailed read endpoints.

`py/swarm_do/pipeline/stage_sessions.py`:

- `stage_sessions.v1.json` is durable per-phase stage state.
- The read-only SQLite mirror records `stage_sessions` as an artifact source, but
  does not yet expose a first-class `stages` table.

`schemas/phase_result.schema.json` and `schemas/phase_handoff.schema.json`:

- Both already contain human-readable summary fields.
- `phase_result` has `summary`, `blocked_reason`, `needs_input`, `validation`,
  `artifacts`, and `error`.
- `phase_handoff` has `summary`, `decisions`, `open_items`, `blockers`,
  `validation_summary`, `artifacts`, and `next_phase_context`.

Conclusion:

V1 should project existing result/handoff/stage/run data into display models. It
should not add new markdown files or new stage artifacts just to serve cards.

### Command side

`py/swarm_do/pipeline/operator_decisions.py`:

- Artifact: `runs/<run-id>/operator_decisions.v1.json`.
- Kinds:

```text
resume_with_input
retry_phase
skip_best_effort_stage
reset_phase
rebuild_worktree
archive_attempt
cancel_run
abort_phase
accept_provider_partial
```

- Currently integrated for apply:

```python
INTEGRATED_KINDS = {"retry_phase"}
```

Conclusion:

Phase 7 is enough to start designing mutating API commands. It is not enough to
expose every command kind. V1 command work should expose only integrated kinds,
beginning with `retry_phase`. `resume_with_input` should be the next integrated
kind because it unlocks mobile/SMS operator replies.

## API Architecture

Proposed package:

```text
py/swarm_do/api/
  __init__.py
  app.py
  auth.py
  read_model.py
  display.py
  events.py
  commands.py
  idempotency.py
  errors.py
  schemas.py
  routes/
    __init__.py
    health.py
    runs.py
    phases.py
    stages.py
    events.py
    cards.py
    integrations.py
    commands.py
```

Responsibilities:

- `read_model.py`: dependency-light facade over `phase_status`, `RunTrace`,
  `stage_sessions`, operator-decision reads, and mirror queries. No FastAPI
  imports.
- `display.py`: stable human/card/mobile summaries. Converts raw artifacts into
  `RunCard`, `PhaseCard`, `StageCard`, and `OperatorPrompt`.
- `events.py`: event normalization, cursor parsing/formatting, SSE formatting,
  and stale-cursor errors.
- `commands.py`: future adapter over Phase 7 operator decisions. No direct state
  writes.
- `idempotency.py`: durable mutating-request ledger, keyed by auth principal and
  route scope.
- `auth.py`: bearer-token checks, per-token principal derivation, local bind
  defaults, future scopes.
- `errors.py`: RFC 9457 problem detail models and internal-error mapping.
- `schemas.py`: Pydantic models for API request/response contracts.
- `routes/*`: thin HTTP handlers that call the above modules.

Proposed CLI:

```text
bin/swarm api serve [--host 127.0.0.1] [--port 8765] [--token-env SWARM_API_TOKEN]
bin/swarm api openapi [--output docs/api/openapi.json]
```

Dependency policy:

```toml
[project.optional-dependencies]
api = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "pydantic>=2,<3"
]
```

Pydantic belongs only to the optional `api` dependency group unless a separate
cold-start benchmark and ADR broaden the dependency. `swarm`, phase pumping,
the TUI, and simple status commands must not import FastAPI, Uvicorn, or
Pydantic through the API package.

## V1 Read-Only API

### Health and metadata

```http
GET /v1/health
GET /v1/capabilities
```

`/v1/health` is liveness only:

```json
{
  "status": "ok"
}
```

`/v1/capabilities` should say:

- `read_only: true`
- `commands_enabled: false`
- `event_stream: "sse"`
- `api_version`, `package_version`, `schema_versions`, `cursor_version`
- `auth_mode` and the current principal's scopes

Do not add `/v1/version` in V1. It duplicates `/v1/capabilities` and creates
one more metadata endpoint for clients to reconcile.

### Runs

```http
GET /v1/status
GET /v1/runs?limit=20&status=running
GET /v1/runs/{run_id}
GET /v1/runs/{run_id}/trace
GET /v1/runs/{run_id}/artifacts?limit=50
```

Notes:

- `/v1/status` is the default dashboard endpoint. It should include active run,
  current phase, current stage summary, next action, and last significant event.
- `/v1/runs/{run_id}/trace` can be a thin JSON projection of `RunTrace`, with
  local sensitive paths redacted or made relative where possible.
- `/v1/runs` uses cursor pagination with `limit` default 50 and max 200.
- `/v1/runs/{run_id}/artifacts` uses cursor pagination because artifact lists
  can grow with attempts, provider reviews, and future sidecars.

### Phases

```http
GET /v1/runs/{run_id}/phases
GET /v1/runs/{run_id}/phases/{phase_id}
GET /v1/runs/{run_id}/phases/{phase_id}/attempts
GET /v1/runs/{run_id}/phases/{phase_id}/artifacts
```

Notes:

- The primary source should be `phase_status()` for status and
  `summarize_phase_attempts()` for attempt/cost summaries.
- Result and handoff JSON should be loaded only through bounded, schema-aware
  helpers and projected into display objects.

### Stages

```http
GET /v1/runs/{run_id}/stages
GET /v1/runs/{run_id}/phases/{phase_id}/stages
GET /v1/runs/{run_id}/phases/{phase_id}/stages/{stage_id}
```

Notes:

- V1 can read `stage_sessions.v1.json` directly through `load_stage_sessions()`.
- Add a first-class `stages` table to the read-only mirror only after the API
  stage projection proves stable.
- Do not require Phase 9 for this.

### Events

```http
GET /v1/runs/{run_id}/events?after=<cursor>&limit=100&type=phase_session_failed
GET /v1/runs/{run_id}/events/stream?after=<cursor>
GET /v1/events?after=<cursor>&limit=100
```

Event response fields:

```json
{
  "cursor": "v1:events:0000000000001233",
  "type": "phase_session_failed",
  "timestamp": "2026-05-02T18:00:00Z",
  "run_id": "01HYEXAMPLERUNID000000000",
  "phase_id": "2",
  "stage_id": null,
  "severity": "error",
  "message": "Phase 2 failed: launcher exited before artifacts",
  "details": {}
}
```

Initial event severity mapping:

Source enum: `schemas/telemetry/run_events.schema.json`. If a schema-valid
event is not listed here, default it to `info` until docs and tests add a more
specific mapping.

| Severity | Event types |
|---|---|
| `success` | `resume_completed`, `prepare_ready_for_acceptance`, `prepare_accepted`, `phase_session_completed`, `phase_attempt_adopted`, `operator_decision_applied`, `worktree_rebuilt`, `worktree_reset` |
| `warning` | `drift_detected`, `prepare_lint_findings`, `prepare_review_findings`, `prepare_blocking_findings`, `prepare_stale_rejected`, `retry_started`, `retry_exhausted`, `phase_session_blocked`, `phase_session_needs_input`, `phase_attempt_retry_scheduled`, `phase_attempt_retry_exhausted`, `operator_decision_apply_noop`, `operator_decisions_retention_warning` |
| `error` | `prepare_continue_failed`, `phase_session_failed`, `phase_attempt_evidence_failed`, `phase_beads_note_failed`, `worktree_merge_conflict`, `phase_pump_launcher_ineligible` |

### Cards and integrations

```http
GET /v1/runs/{run_id}/cards
GET /v1/home-assistant/state
```

Cards should be explicit API models, not arbitrary raw artifacts:

```json
{
  "run": {
    "run_id": "01HYEXAMPLERUNID000000000",
    "status": "running",
    "title": "Runtime foundations adoption",
    "message": "Phase 2 is running",
    "updated_at": "2026-05-02T18:00:00Z"
  },
  "progress": {
    "phases_complete": 1,
    "phases_total": 5,
    "stages_adopted": 3,
    "stages_total": 8
  },
  "attention": {
    "needs_input": false,
    "blocked": false,
    "failure": false,
    "prompt_count": 0
  },
  "phases": [],
  "stages": [],
  "recent_events": []
}
```

`attention.prompt_count` is not sourced from a later prompt endpoint. It is
derived by the same `OperatorPrompt` projection used by cards: count
`needs_input` arrays from result artifacts and phases currently in
`needs_input`. The future `/v1/runs/{run_id}/prompts` route reuses this helper.

n8n does not need a separate V1 events endpoint. The n8n integration docs should
use `/v1/events` or `/v1/runs/{run_id}/events` directly. Add an integration
alias only if n8n later needs a different wire shape.

## Future Mutating API

Mutating commands should remain disabled by default until V1 read-only is stable.
When enabled, they must use Phase 7 operator decisions.

### Command capability discovery

```http
GET /v1/capabilities/commands
```

Example response:

```json
{
  "commands_enabled": true,
  "integrated_kinds": ["retry_phase"],
  "record_only_kinds": [
    "resume_with_input",
    "reset_phase",
    "cancel_run"
  ],
  "requires_idempotency_key": true,
  "requires_operator": true
}
```

### Command creation

```http
POST /v1/runs/{run_id}/commands
Authorization: Bearer <token>
Idempotency-Key: <stable-client-generated-key>
```

Request:

```json
{
  "kind": "retry_phase",
  "payload": {
    "phase_id": "2",
    "reason": "Retry after fixing provider auth"
  }
}
```

Response:

```json
{
  "command_id": "opdec_...",
  "operator_decision_id": "opdec_...",
  "kind": "retry_phase",
  "status": "applied",
  "applied": true,
  "audit_path": "runs/<run-id>/operator_decisions.v1.json"
}
```

Rules:

- Require `Idempotency-Key` for every mutating request.
- Derive `operator` from the authenticated API identity.
- Refuse non-integrated kinds with RFC 9457 `409 kind_not_integrated`.
- Use the durable idempotency ledger from Contract Decision 3.
- Preserve Phase 7 confirm-token behavior for destructive commands.
- Return controlled conflicts for already-applied destructive decisions.
- Record audit before or with mutation through `operator_decisions.py`.

### Remote answer flow

Target future flow:

1. API surfaces a prompt from a `needs_input` phase.
2. Mobile app, SMS bridge, or n8n notification displays the prompt.
3. Operator responds remotely.
4. API records `resume_with_input`.
5. Runtime applies it and repumps safely.

Endpoints:

```http
GET /v1/runs/{run_id}/prompts
POST /v1/runs/{run_id}/prompts/{prompt_id}/responses
```

Implementation dependency:

`resume_with_input` must become an integrated Phase 7 kind before this endpoint
can mutate runtime state. Until then, prompts can be read-only and responses can
be rejected as `kind_not_integrated`.

Privacy rule:

- `operator_decisions.v1.json` may store `resume_with_input.payload.input`
  verbatim because it is the local durable command payload.
- API responses, cards, event streams, and `run_events.jsonl` projections must
  never expose that raw input.
- API-visible summaries use:

```json
{
  "redacted": true,
  "input_sha256": "<sha256-of-canonical-input-json>",
  "input_size_bytes": 123,
  "input_keys": ["answer"]
}
```

Do not expose the existing Phase 7 `payload_summary.preview` field through API
events.

## Security Model

V1 defaults:

- Bind to `127.0.0.1`.
- Require bearer token unless `--dev-no-auth` is explicitly passed.
- Resolve bearer tokens to per-token principals with `token_id`, `operator`,
  and scopes.
- Never expose raw local files by default.
- Redact absolute sensitive paths in API responses unless an explicit local-only
  debug flag is enabled.
- No CORS by default. Add `--allow-origin` for web apps.
- Commands disabled by default.

Future scopes:

```text
read:runs
read:events
read:artifacts
command:retry
command:respond
command:destructive
admin:webhooks
```

Token storage:

- Start with env var `SWARM_API_TOKEN`, with optional `SWARM_API_OPERATOR` for
  the principal's Phase 7 operator string.
- Add local token config under `${CLAUDE_PLUGIN_DATA}/api/tokens.v1.json`.
- Do not store outbound webhook secrets in run artifacts.

## Server Lifecycle

V1 lifecycle rules:

- One API process serves one resolved data dir.
- One Uvicorn worker is supported. Do not expose a V1 `--workers` flag.
- Read endpoints are live reads over canonical JSON, `phase_status()`, and
  `RunTrace`; they do not hold phase-session locks.
- `phase_status()` may use a fresh mirror and fall back to canonical JSON when
  the mirror is missing, stale, or corrupt. API handlers must not treat a stale
  mirror as a hard failure for dashboard reads.
- SSE reads `telemetry/run_events.jsonl` directly by cursor offset and polls
  file size/mtime at a small interval. Do not add file-watch dependencies in V1.
- SSE heartbeats are required so browser/mobile/n8n clients can detect dead
  connections.
- Mirror rebuilds are independent of SSE. Rebuilding or replacing
  `state.mirror.sqlite` must not disconnect event streams.
- Mutating endpoints acquire the phase-session lock and use the idempotency
  ledger. A read request racing with a mutation may see old or new state, but
  must not see partially written JSON because owner modules use atomic writes.

## Documentation Plan

Add API docs under:

```text
docs/api/
  README.md
  reference.md
  events.md
  security.md
  openapi.json              # generated, optional in repo only if stable
  integrations/
    home-assistant.md
    n8n.md
    mobile-viewer.md
```

Docs responsibilities:

- `docs/api/README.md`: quick start, install optional deps, run server, first
  requests.
- `docs/api/reference.md`: endpoint reference with examples.
- `docs/api/events.md`: event types, severity mapping, cursor behavior, SSE.
- `docs/api/security.md`: auth, local bind, CORS, token handling, command risk.
- `docs/api/integrations/home-assistant.md`: RESTful Sensor YAML example and
  card attribute notes.
- `docs/api/integrations/n8n.md`: polling workflow and future webhook receiver.
- `docs/api/integrations/mobile-viewer.md`: recommended client behavior,
  reconnect, stale cursor, notification model.

README integration:

- Add a short "API" section to `README.md` only after V1 serves real endpoints.
- Keep deeper details in `docs/api/`.

OpenAPI:

- FastAPI should serve `/openapi.json`, `/docs`, and `/redoc`.
- Add `bin/swarm api openapi --output docs/api/openapi.json` after routes
  stabilize.
- Do not manually maintain an OpenAPI file in parallel with route models unless
  a client generator requires it.

## Build Order

### Step 0 - ADR and scope guard

Files:

```text
docs/adr/0009-api-boundary.md
docs/swarmdaddy-api-design-implementation-plan-2026-05-02.md
```

Acceptance:

- ADR states API is optional, read-model first, CLI/TUI primary.
- ADR explicitly rejects direct API writes to canonical state files.
- ADR states Phase 9 is not required for V1.
- ADR records the locked identity, error, idempotency, cursor, lifecycle, and
  single-data-dir decisions from this plan.
- ADR records the 2026 alternatives check: OpenAPI remains the contract target,
  FastAPI remains the default implementation, and Litestar is the fallback if
  FastAPI/Pydantic dependency cost or schema control becomes a blocker.
- No Step 1+ implementation PR starts until ADR 0009 is merged.

Risk:

Low. Documentation only.

### Step 1 - Pure read model

Files:

```text
py/swarm_do/api/__init__.py
py/swarm_do/api/read_model.py
py/swarm_do/api/display.py
py/swarm_do/api/errors.py
py/swarm_do/api/tests/test_read_model.py
py/swarm_do/api/tests/test_display.py
```

Implementation:

- Add `RunSummary`, `PhaseSummary`, `StageSummary`, `RunCard`,
  `OperatorPrompt` dataclasses or Pydantic-free typed dicts.
- Call `phase_status()` for phase state.
- Call `build_run_trace()` for detailed run state.
- Call `load_stage_sessions()` for stages.
- Load result/handoff JSON only through bounded helper functions.
- Redact or relativize sensitive local paths.
- Implement one path-redaction helper used by trace, cards, events, prompts, and
  artifacts.

Acceptance:

- Tests build cards from temp run fixtures.
- No FastAPI import in `read_model.py` or `display.py`.
- No direct writes to canonical state files.
- Path-redaction round-trip tests cover absolute data-dir paths, repo paths,
  worktree paths, already-relative paths, and values nested in `details`.

Risk:

Low-medium. Main risk is exposing too much local path detail.

### Step 2 - Event cursor model

Files:

```text
py/swarm_do/api/events.py
py/swarm_do/api/tests/test_events.py
```

Implementation:

- Normalize run events into API event objects.
- Read `telemetry/run_events.jsonl` directly and back cursors with byte offsets.
- Add opaque cursor encode/decode with scope validation.
- Support `after`, `limit`, and event-type filters.
- Add RFC 9457 stale-cursor and invalid-cursor error shapes.
- Implement severity and human message mapping from
  `schemas/telemetry/run_events.schema.json`.

Acceptance:

- Cursor tests assert the implementation can resume from a JSONL byte offset
  without exposing the offset as a documented client contract.
- Events can be replayed after a cursor.
- Stale or unknown cursors return controlled errors.
- Cursor scope mismatches are rejected.
- Truncated/rotated JSONL returns `410 cursor_stale`.

Risk:

Medium. Cursor design is easy to regret. Keep it opaque.

### Step 3 - Optional FastAPI server

Files:

```text
py/swarm_do/api/app.py
py/swarm_do/api/auth.py
py/swarm_do/api/schemas.py
py/swarm_do/api/routes/*.py
py/swarm_do/api/tests/test_routes.py
pyproject.toml
```

Implementation:

- Add optional `api` dependency group.
- Build routes with `APIRouter`.
- Add bearer auth with per-token principals.
- Add RFC 9457 problem responses through one exception handler.
- Add `/v1/health`, `/v1/capabilities`, `/v1/status`, run, phase, stage,
  event, card, and Home Assistant routes.
- Add generated OpenAPI metadata.
- Do not add `/v1/version` or `/v1/integrations/n8n/events`.

Acceptance:

- `TestClient` route tests pass with temp data dir.
- Importing `swarm_do.pipeline.cli` does not import FastAPI.
- Auth failures are tested.
- OpenAPI includes stable response model names.
- OpenAPI stability test compares route names, operation ids, and problem
  response schemas against a checked golden.
- Error responses use `application/problem+json` with stable `code` values.

Risk:

Medium. Dependency isolation is the main concern.

### Step 4 - CLI serve command

Files:

```text
py/swarm_do/pipeline/cli.py
bin/swarm
py/swarm_do/api/server.py
py/swarm_do/api/tests/test_cli.py
```

Implementation:

- Add `bin/swarm api serve`.
- Default to `127.0.0.1:8765`.
- Read token from `SWARM_API_TOKEN` by default.
- Read optional principal identity from `SWARM_API_OPERATOR`.
- Accept `--data-dir` but serve exactly one resolved data dir per process.
- Print startup URL and auth mode.
- Fail clearly if optional API deps are missing.
- Start one Uvicorn worker only. Do not expose `--workers` in V1.

Acceptance:

- Missing deps error tells operator how to install optional deps.
- Server command does not affect existing CLI commands.
- Local smoke test can start and query `/v1/health`.
- Startup output never prints the bearer token or absolute data dir unless an
  explicit local debug flag is enabled.

Risk:

Low-medium.

### Step 5 - Docs and integration examples

Files:

```text
docs/api/README.md
docs/api/reference.md
docs/api/events.md
docs/api/security.md
docs/api/integrations/home-assistant.md
docs/api/integrations/n8n.md
docs/api/integrations/mobile-viewer.md
README.md
```

Implementation:

- Add quick start and curl examples.
- Add Home Assistant RESTful Sensor example.
- Add n8n polling workflow example.
- Add event severity table.
- Add security caveats, error envelope examples, idempotency semantics, cursor
  behavior, and single-data-dir lifecycle notes.

Acceptance:

- Docs match implemented endpoint names.
- README only links to API docs after V1 works.
- Examples avoid assuming mutating commands exist.
- n8n docs use the generic `/v1/events` endpoints and the camel-case workflow
  node type `n8n-nodes-base.sseTrigger`.

Risk:

Low.

### Step 6 - SSE stream

Files:

```text
py/swarm_do/api/events.py
py/swarm_do/api/routes/events.py
py/swarm_do/api/tests/test_event_stream.py
```

Implementation:

- Add `GET /v1/runs/{run_id}/events/stream`.
- Use Server-Sent Events for browser/mobile/n8n-compatible live reads.
- Send heartbeats.
- Support `after` cursor.
- Poll `telemetry/run_events.jsonl` size/mtime; do not use file-watch APIs in
  V1.
- Do not depend on the SQLite mirror for SSE.
- Return `cursor_stale` when reconnecting from a stale cursor; clients then
  poll/relist and reconnect.

Acceptance:

- Stream emits normalized events.
- Reconnect with latest cursor avoids duplicates where possible.
- Stale cursor returns controlled relist guidance.
- Heartbeats are emitted at a documented interval.
- Mirror rebuilds during SSE do not interrupt the stream.

Risk:

Medium. Long-lived HTTP behavior can be fiddly, but it is isolated.

### Step 7 - Outbound webhook subscriptions

Files:

```text
py/swarm_do/api/webhooks.py
py/swarm_do/api/routes/webhooks.py
py/swarm_do/api/tests/test_webhooks.py
docs/api/integrations/n8n.md
```

Implementation:

- Add optional outbound event delivery for n8n.
- Store local subscription config outside run artifacts.
- Sign requests with HMAC.
- Add retry/backoff and delivery status.

Acceptance:

- Disabled by default.
- Delivery is idempotent by event cursor/id.
- Secrets are not written into run artifacts or telemetry details.

Risk:

Medium-high. This is why it is after V1.

### Step 8 - Command API for integrated Phase 7 kinds

Files:

```text
py/swarm_do/api/commands.py
py/swarm_do/api/routes/commands.py
py/swarm_do/api/tests/test_commands.py
docs/api/security.md
docs/api/reference.md
```

Implementation:

- Add `GET /v1/capabilities/commands`.
- Add `POST /v1/runs/{run_id}/commands`.
- Support only `operator_decisions.INTEGRATED_KINDS`.
- Require `Idempotency-Key` and implement the durable idempotency ledger.
- Derive operator identity from `ApiPrincipal`, never arbitrary request body
  fields.
- Return command/audit status.

Acceptance:

- Non-integrated kinds return RFC 9457 `409 kind_not_integrated`.
- Duplicate idempotency key returns original command result.
- Same idempotency key with mismatched payload returns
  `409 idempotency_key_conflict` and does not mutate state.
- `retry_phase` route produces the same state/audit behavior as CLI apply.
- Destructive command behavior is tested before any destructive kind is exposed.
- Run lock contention returns `409 run_locked`.

Risk:

Medium. Phase 7 provides the audit model, but not all command integrations.

### Step 9 - Remote answer flow

Files:

```text
py/swarm_do/api/prompts.py
py/swarm_do/api/routes/prompts.py
py/swarm_do/api/tests/test_prompts.py
py/swarm_do/pipeline/operator_decisions.py
py/swarm_do/pipeline/tests/test_operator_decisions.py
```

Implementation:

- Define `OperatorPrompt` projection from `needs_input`, blockers, and handoff
  open items.
- Integrate `resume_with_input` in Phase 7 apply path.
- Add prompt response endpoint after integration.
- Normalize free-form operator input into API-visible redaction metadata:
  `redacted`, `input_sha256`, `input_size_bytes`, and `input_keys`.

Acceptance:

- Needs-input phase appears as a prompt.
- Remote response records an operator decision.
- Applying response can safely continue the run.
- Free-form operator input is never present in API events, cards, prompt lists,
  or normalized run-event details.
- End-to-end needs_input -> prompt -> response -> resume test passes.

Risk:

Medium-high. This is the highest-value future feature and should be built only
after command API discipline is proven.

### Step 10 - Configure and start runs (deferred mini-epic)

Files:

```text
py/swarm_do/api/routes/configuration.py
py/swarm_do/api/routes/run_creation.py
docs/api/reference.md
```

Step 10A - Read-only configuration discovery:

- `GET /v1/config/presets`
- `GET /v1/config/pipelines`
- `GET /v1/config/defaults`
- No writes, no prepare, no dispatch.

Step 10B - Dry-run validation:

- `POST /v1/run-requests/validate`
- Reuse existing prepare validation helpers.
- Return a proposed command/plan summary and problem details for validation
  failures.

Step 10C - Start from an accepted prepared artifact:

- `POST /v1/runs`
- Body references an already accepted prepared artifact.
- Requires idempotency key and a command scope such as `command:start`.
- Reuses existing dispatch helpers; does not create API-only run state.

Step 10D - Start from an explicit plan request:

- Deferred until 10C is stable.
- Runs prepare through existing CLI/pipeline owner functions.
- Must define upload/file-reference rules and path-redaction behavior before
  implementation.

Acceptance:

- API start path reuses existing prepare/dispatch helpers.
- No API-only run creation state.
- CLI/TUI behavior stays canonical.
- Each substep has its own route tests, auth tests, idempotency tests, and
  OpenAPI stability updates.
- Step 10C/10D are not scheduled until V1 reads, SSE, command idempotency, and
  remote response are stable.

Risk:

High. This crosses from observing SwarmDaddy into orchestrating it. Defer until
read API, command API, and remote response flows are stable.

## Phase 7 vs Phase 9 Decision

Phase 7 is sufficient to begin the mutating-command audit and API design.

Phase 9 is ideal for long-term transactional hardening because it couples state
mutation and audit append in one SQLite transaction. It is not required for V1
read-only API work and should not block the first command API.

Use this rule:

- V1 read-only: no Phase 7 or Phase 9 dependency.
- First command API: requires Phase 7 integrated kind coverage plus the API
  idempotency ledger.
- Remote response API: requires `resume_with_input` integration in Phase 7.
- Broad destructive commands or multi-client mutation: re-evaluate Phase 9.

## Risks and Mitigations

| Risk | Severity | Mitigation |
|---|---:|---|
| API becomes a second state owner | High | Route all reads/writes through owner modules and Phase 7 adapter. Add fence tests if needed. |
| Local sensitive paths leak to mobile/Home Assistant/n8n | High | Redact/relativize by default. Add explicit debug flag for local-only raw paths. |
| Optional HTTP deps slow CLI cold start | Medium | Keep FastAPI imports inside `py/swarm_do/api`. Optional dependency group only. |
| Cursor design freezes wrong storage detail | Medium | Opaque cursors only. No raw line number or SQL id contract. |
| Idempotency bug replays a mutating command | High | Require `Idempotency-Key`, durable ledger, payload-hash conflict checks, and replay tests before command API ships. |
| Operator audit identity is spoofable | High | Derive `operator` from authenticated token principal. Reject arbitrary operator headers by default. |
| Error contract splinters across routes | Medium | One RFC 9457 problem-details helper and OpenAPI golden tests. |
| Card schema is too raw for Home Assistant | Medium | Add `display.py` projection models. Keep Home Assistant endpoint compact. |
| Mutating API outruns Phase 7 integration | High | Capabilities endpoint exposes only integrated kinds. Reject record-only kinds. |
| Webhooks create delivery/secrets burden | Medium-high | Defer to V1.1. Polling first. Store secrets outside run artifacts. |
| Phase 9 pressure returns too early | Medium | Keep the existing Phase 9 objective trigger. API alone is not a trigger. |

## Non-Goals

- No hosted public API server.
- No remote multi-user auth system in V1.
- No direct SQL query endpoint.
- No raw artifact download endpoint in V1.
- No command endpoints in V1 read-only.
- No new markdown artifacts solely for API cards.
- No Phase 9 canonical SQLite migration as part of API V1.

## Review Gate

Every API implementation PR should close with:

- changed files;
- endpoint list added or changed;
- tests added and tests run;
- dependency impact;
- auth/security impact;
- error-code impact;
- idempotency impact for any mutating route;
- local-path redaction check;
- OpenAPI stability check when routes or schemas change;
- statement that CLI/TUI behavior remains primary;
- statement that no direct canonical-state writer was added.

## Initial Dogfood Recipe

1. Start a known temp run fixture.
2. Serve API on localhost:

```bash
SWARM_API_TOKEN=dev-token bin/swarm api serve --host 127.0.0.1 --port 8765
```

3. Query status:

```bash
curl -H "Authorization: Bearer dev-token" http://127.0.0.1:8765/v1/status
```

4. Query Home Assistant state:

```bash
curl -H "Authorization: Bearer dev-token" http://127.0.0.1:8765/v1/home-assistant/state
```

5. Poll events:

```bash
curl -H "Authorization: Bearer dev-token" "http://127.0.0.1:8765/v1/events?limit=10"
```

6. Verify:

- no raw absolute sensitive paths in default responses;
- `phases status` CLI still returns the same status;
- TUI still opens without API optional deps installed;
- API responses remain useful when the mirror is missing and JSON fallback is
  used.
