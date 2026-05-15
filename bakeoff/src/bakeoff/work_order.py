from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

MODES = ("gather", "compare", "analyze")
INIT_KINDS = (*MODES, "review")
SCOPE_ENFORCEMENTS = ("advisory", "best_effort", "required")
MODE_EFFORT_DEFAULTS = {
    "gather": {"worker": "high", "judge": "xhigh"},
    "compare": {"worker": "high", "judge": "xhigh"},
    "analyze": {"worker": "high", "judge": "xhigh"},
}
BACKENDS = ("claude", "codex")
SCOPES = ("codebase", "web", "mixed")
EFFORTS = ("low", "medium", "high", "xhigh")
WORKER_STATUSES = ("complete", "complete_with_concerns", "needs_context", "blocked")
CONFIDENCES = ("high", "medium", "low")
COMPARE_SCORE_FIELDS = ("evidence", "coherence", "tradeoff_honesty", "rebuttals")
ANALYZE_SCORE_FIELDS = ("step_atomicity", "citation_grounding", "assumption_transparency", "coherence")
ANALYZE_LOSER_POSITIONS = ("agrees", "disagrees", "not_covered", "adds")
ANALYZE_FOLLOWUP_KINDS = ("bug", "risk", "doc_drift", "test_gap", "follow_up")
TRIAGE_CLASSIFICATIONS = ("real_issue", "false_positive", "plan_doc_drift", "product_decision", "needs_repro", "already_fixed", "evidence_gap")
TRIAGE_ACTIONS = ("fix_now", "document", "defer", "ignore", "reproduce")
TRIAGE_SEVERITIES = ("high", "medium", "low", "none")
SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
FACET_KEYS = ("id", "kind", "focus", "include", "exclude", "notes")
FACET_RESERVED_IDS = {"judge", "provider", "providers", "worker", "workers"}
FACET_STRING_MAX_CHARS = 500
FACET_TOTAL_TEXT_MAX_CHARS = 4096
FACET_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


class ValidationError(ValueError):
    """Raised when a work order or model artifact violates the v1 contract."""


def strip_jsonc_comments(text: str) -> str:
    """Strip JSONC line/block comments without touching comment markers in strings."""
    out: list[str] = []
    i = 0
    state = "normal"
    escaped = False

    while i < len(text):
        char = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""

        if state == "line_comment":
            if char == "\n":
                out.append(char)
                state = "normal"
            i += 1
            continue

        if state == "block_comment":
            if char == "*" and nxt == "/":
                out.append(" ")
                i += 2
                state = "normal"
            else:
                out.append("\n" if char == "\n" else " ")
                i += 1
            continue

        if state == "string":
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                state = "normal"
            i += 1
            continue

        if char == '"':
            out.append(char)
            state = "string"
            i += 1
        elif char == "/" and nxt == "/":
            out.append(" ")
            i += 2
            state = "line_comment"
        elif char == "/" and nxt == "*":
            out.append(" ")
            i += 2
            state = "block_comment"
        else:
            out.append(char)
            i += 1

    return "".join(out)


def load_work_order(path: str | Path) -> dict[str, Any]:
    """Load a JSONC work order and return a normalized, validated dict."""
    source = Path(path)
    try:
        data = json.loads(strip_jsonc_comments(source.read_text(encoding="utf-8")))
    except FileNotFoundError as exc:
        raise ValidationError(f"{source}: work order not found") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{source}: invalid JSONC after comment stripping: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ValidationError("work order must be a JSON object")
    return validate_work_order(data)


def validate_work_order(data: dict[str, Any]) -> dict[str, Any]:
    required = ("schema_version", "id", "type", "goal", "background", "providers", "judge", "budgets")
    for field in required:
        if field not in data:
            raise ValidationError(f"{field} is required")

    if data["schema_version"] != 1:
        raise ValidationError(f'schema_version must equal 1 in v1 (got {data["schema_version"]!r})')

    work_id = data["id"]
    if not isinstance(work_id, str) or not work_id.strip():
        raise ValidationError("id must be a non-empty slug")
    if re.match(r"^TODO[-_]", work_id, re.IGNORECASE):
        raise ValidationError("id must not match the init placeholder rule '^TODO[-_]'")
    if not SLUG_RE.match(work_id):
        raise ValidationError("id must be a slug matching ^[A-Za-z0-9][A-Za-z0-9._-]*$")

    if data["type"] not in MODES:
        raise ValidationError(f'type must be one of: {", ".join(MODES)} (got {data["type"]!r})')

    if not isinstance(data["goal"], str) or not data["goal"].strip():
        raise ValidationError("goal must be a non-empty string")
    if not isinstance(data["background"], str):
        raise ValidationError("background must be a string")

    providers = _validate_providers(data["providers"])
    facet = _validate_facet(data.get("facet"), {provider["id"] for provider in providers})
    judge = _validate_judge(data["judge"], providers)
    budgets = _validate_budgets(data["budgets"])
    scope_policy = _validate_scope_policy(data.get("scope_policy"))

    normalized = dict(data)
    normalized["providers"] = providers
    if facet is None:
        normalized.pop("facet", None)
    else:
        normalized["facet"] = facet
    normalized["judge"] = judge
    normalized["budgets"] = budgets
    normalized["scope_policy"] = scope_policy
    return normalized


def _validate_providers(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValidationError("providers must have exactly 2 entries")

    providers: list[dict[str, Any]] = []
    ids: set[str] = set()
    triples: set[tuple[str, str, str]] = set()
    for index, provider in enumerate(value):
        if not isinstance(provider, dict):
            raise ValidationError(f"providers[{index}] must be an object")
        if "facet" in provider:
            raise ValidationError(f"providers[{index}].facet is not supported in v1; use top-level facet")
        normalized = _validate_participant(provider, f"providers[{index}]", require_scope=True)
        provider_id = normalized["id"]
        if provider_id in ids:
            raise ValidationError(f'providers[{index}].id must be unique (duplicate {provider_id!r})')
        ids.add(provider_id)
        triples.add((normalized["backend"], normalized["model"], normalized["scope"]))
        providers.append(normalized)

    if len(triples) == 1:
        raise ValidationError("providers must differ on at least one of backend, model, or scope")
    return providers


def _validate_facet(value: Any, provider_ids: set[str]) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValidationError("facet must be an object")

    unknown = sorted(set(value) - set(FACET_KEYS))
    if unknown:
        raise ValidationError(f"facet has unsupported keys: {', '.join(unknown)}")

    for field in ("id", "focus", "include"):
        if field not in value:
            raise ValidationError(f"facet.{field} is required")

    facet_id = value["id"]
    if not isinstance(facet_id, str) or not facet_id.strip():
        raise ValidationError("facet.id must be a non-empty slug")
    if not SLUG_RE.match(facet_id):
        raise ValidationError("facet.id must be a slug matching ^[A-Za-z0-9][A-Za-z0-9._-]*$")
    if facet_id in provider_ids:
        raise ValidationError("facet.id must not duplicate a provider id")
    if facet_id.lower() in FACET_RESERVED_IDS:
        raise ValidationError("facet.id is reserved")

    kind = value.get("kind", "generic")
    if kind != "generic":
        raise ValidationError('facet.kind must be "generic" when present')

    focus = _normalize_facet_text(value["focus"], "facet.focus")

    include = _validate_facet_string_list(value["include"], "facet.include", min_items=1, max_items=8)
    exclude = _validate_facet_string_list(value.get("exclude", []), "facet.exclude", min_items=0, max_items=8)
    notes = _normalize_facet_text(value["notes"], "facet.notes") if "notes" in value else None
    _validate_facet_total_text(facet_id, kind, focus, include, exclude, notes)

    normalized: dict[str, Any] = {
        "id": facet_id,
        "kind": kind,
        "focus": focus,
        "include": include,
    }
    if "exclude" in value:
        normalized["exclude"] = exclude
    if notes is not None:
        normalized["notes"] = notes
    return normalized


def _validate_facet_string_list(value: Any, label: str, *, min_items: int, max_items: int) -> list[str]:
    if not isinstance(value, list):
        raise ValidationError(f"{label} must be an array of strings")
    if not min_items <= len(value) <= max_items:
        raise ValidationError(f"{label} must contain {min_items}-{max_items} items")
    normalized: list[str] = []
    for index, item in enumerate(value):
        normalized.append(_normalize_facet_text(item, f"{label}[{index}]"))
    return normalized


def _normalize_facet_text(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{label} must be a string")
    normalized = FACET_CONTROL_CHAR_RE.sub(" ", value).strip()
    if not normalized:
        raise ValidationError(f"{label} must be a non-empty string")
    if "</facet>" in normalized.lower():
        raise ValidationError(f"{label} must not contain </facet>")
    if "<" in normalized or ">" in normalized:
        raise ValidationError(f"{label} must not contain angle brackets")
    if "`" in normalized:
        raise ValidationError(f"{label} must not contain backticks")
    if len(normalized) > FACET_STRING_MAX_CHARS:
        raise ValidationError(f"{label} must be at most {FACET_STRING_MAX_CHARS} characters")
    return normalized


def _validate_facet_total_text(
    facet_id: str,
    kind: str,
    focus: str,
    include: list[str],
    exclude: list[str],
    notes: str | None,
) -> None:
    total = (
        len(facet_id)
        + len(kind)
        + len(focus)
        + sum(len(item) for item in include)
        + sum(len(item) for item in exclude)
    )
    if notes is not None:
        total += len(notes)
    if total > FACET_TOTAL_TEXT_MAX_CHARS:
        raise ValidationError(f"facet text must be at most {FACET_TOTAL_TEXT_MAX_CHARS} characters total")


def _validate_judge(value: Any, providers: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError("judge must be an object")
    judge = _validate_participant(value, "judge", require_scope=False)
    judge_pair = (judge["backend"], judge["model"])
    for index, provider in enumerate(providers):
        if judge_pair == (provider["backend"], provider["model"]):
            raise ValidationError(
                f"judge.backend + judge.model must differ from providers[{index}] backend + model"
            )
    return judge


def _validate_participant(value: dict[str, Any], label: str, *, require_scope: bool) -> dict[str, Any]:
    required = ("id", "backend", "model") if require_scope else ("backend", "model")
    for field in required:
        if field not in value:
            raise ValidationError(f"{label}.{field} is required")

    if require_scope and "scope" not in value:
        value = {**value, "scope": "mixed"}
    if "effort" not in value:
        value = {**value, "effort": "high"}

    if require_scope:
        participant_id = value["id"]
        if not isinstance(participant_id, str) or not participant_id.strip():
            raise ValidationError(f"{label}.id must be a non-empty string")
        if participant_id in (".", "..") or not SLUG_RE.match(participant_id):
            raise ValidationError(f"{label}.id must be a slug matching ^[A-Za-z0-9][A-Za-z0-9._-]*$")

    backend = value["backend"]
    if backend not in BACKENDS:
        raise ValidationError(f'{label}.backend must be one of: {", ".join(BACKENDS)} (got {backend!r})')

    model = value["model"]
    if not isinstance(model, str) or not model.strip():
        raise ValidationError(f"{label}.model must be a non-empty string")

    effort = value["effort"]
    if effort not in EFFORTS:
        raise ValidationError(f'{label}.effort must be one of: {", ".join(EFFORTS)} (got {effort!r})')

    normalized = dict(value)
    if require_scope:
        scope = value["scope"]
        if scope not in SCOPES:
            raise ValidationError(f'{label}.scope must be one of: {", ".join(SCOPES)} (got {scope!r})')
    else:
        normalized.pop("scope", None)
        normalized.pop("id", None)
    return normalized


def _validate_budgets(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValidationError("budgets must be an object")
    required = ("wall_clock_seconds", "max_output_bytes")
    for field in required:
        if field not in value:
            raise ValidationError(f"budgets.{field} is required")
        if not isinstance(value[field], int) or value[field] <= 0:
            raise ValidationError(f"budgets.{field} must be a positive integer")
    heartbeat_seconds = value.get("heartbeat_seconds", 60)
    if not isinstance(heartbeat_seconds, int) or heartbeat_seconds < 0:
        raise ValidationError("budgets.heartbeat_seconds must be a non-negative integer")
    output_cap_grace_seconds = value.get("output_cap_grace_seconds", 10)
    if not isinstance(output_cap_grace_seconds, int) or output_cap_grace_seconds < 0:
        raise ValidationError("budgets.output_cap_grace_seconds must be a non-negative integer")
    max_output_overrun_bytes = value.get("max_output_overrun_bytes", value["max_output_bytes"])
    if not isinstance(max_output_overrun_bytes, int) or max_output_overrun_bytes < 0:
        raise ValidationError("budgets.max_output_overrun_bytes must be a non-negative integer")
    return {
        "wall_clock_seconds": value["wall_clock_seconds"],
        "max_output_bytes": value["max_output_bytes"],
        "heartbeat_seconds": heartbeat_seconds,
        "output_cap_grace_seconds": output_cap_grace_seconds,
        "max_output_overrun_bytes": max_output_overrun_bytes,
    }


def _validate_scope_policy(value: Any) -> dict[str, str]:
    if value is None:
        return {"enforcement": "best_effort"}
    if isinstance(value, str):
        enforcement = value
    elif isinstance(value, dict):
        enforcement = value.get("enforcement", "best_effort")
    else:
        raise ValidationError("scope_policy must be an object or one of: advisory, best_effort, required")
    if enforcement not in SCOPE_ENFORCEMENTS:
        raise ValidationError(
            f'scope_policy.enforcement must be one of: {", ".join(SCOPE_ENFORCEMENTS)} (got {enforcement!r})'
        )
    return {"enforcement": enforcement}


def validate_worker_result(data: Any, *, mode: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValidationError("worker final_json must be an object")
    for field in ("status", "claims", "conflicts", "unknowns", "recommended_next_checks"):
        if field not in data:
            raise ValidationError(f"worker final_json.{field} is required")
    if data["status"] not in WORKER_STATUSES:
        raise ValidationError(f'worker final_json.status must be one of: {", ".join(WORKER_STATUSES)}')
    if mode == "compare" and not isinstance(data.get("position"), str):
        raise ValidationError("worker final_json.position is required for compare mode")
    _validate_claims(data["claims"], "worker final_json.claims")
    _validate_string_list(data["unknowns"], "worker final_json.unknowns")
    _validate_string_list(data["recommended_next_checks"], "worker final_json.recommended_next_checks")
    if not isinstance(data["conflicts"], list):
        raise ValidationError("worker final_json.conflicts must be an array")
    return data


def validate_gather_judge_result(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValidationError("gather judge final_json must be an object")
    for field in ("merged_claims", "conflicts", "unknowns_union"):
        if field not in data:
            raise ValidationError(f"gather judge final_json.{field} is required")
    if not isinstance(data["merged_claims"], list):
        raise ValidationError("gather judge final_json.merged_claims must be an array")
    for index, claim in enumerate(data["merged_claims"]):
        _validate_mapping_claim(claim, f"gather judge final_json.merged_claims[{index}]", require_sources=True)
    if not isinstance(data["conflicts"], list):
        raise ValidationError("gather judge final_json.conflicts must be an array")
    _validate_string_list(data["unknowns_union"], "gather judge final_json.unknowns_union")
    if "out_of_facet_claims" in data:
        if not isinstance(data["out_of_facet_claims"], list):
            raise ValidationError("gather judge final_json.out_of_facet_claims must be an array")
        for index, claim in enumerate(data["out_of_facet_claims"]):
            _validate_out_of_facet_claim(claim, f"gather judge final_json.out_of_facet_claims[{index}]")
    return data


def validate_compare_judge_result(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValidationError("compare judge final_json must be an object")
    for field in (
        "relation",
        "scores_a",
        "scores_b",
        "winner",
        "rationale",
        "kept_from_nonwinner",
        "consensus_strongest",
        "consensus_disagreements",
    ):
        if field not in data:
            raise ValidationError(f"compare judge final_json.{field} is required")
    if data["relation"] not in ("consensus", "compare"):
        raise ValidationError('compare judge final_json.relation must be one of: "consensus", "compare"')
    if data["winner"] not in ("A", "B", "tie", None):
        raise ValidationError('compare judge final_json.winner must be one of: "A", "B", "tie", null')
    _validate_score_map(data["scores_a"], "compare judge final_json.scores_a", COMPARE_SCORE_FIELDS)
    _validate_score_map(data["scores_b"], "compare judge final_json.scores_b", COMPARE_SCORE_FIELDS)
    _validate_string_or_list(data["rationale"], "compare judge final_json.rationale")
    for field in ("kept_from_nonwinner", "consensus_strongest", "consensus_disagreements"):
        if not isinstance(data[field], list):
            raise ValidationError(f"compare judge final_json.{field} must be an array")
    return data


def validate_analyze_judge_result(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValidationError("analyze judge final_json must be an object")
    for field in ("scores_a", "scores_b", "spine_winner", "spine_rationale", "claim_verdicts", "additions_from_loser"):
        if field not in data:
            raise ValidationError(f"analyze judge final_json.{field} is required")
    if data["spine_winner"] not in ("A", "B"):
        raise ValidationError('analyze judge final_json.spine_winner must be one of: "A", "B"')
    _validate_score_map(data["scores_a"], "analyze judge final_json.scores_a", ANALYZE_SCORE_FIELDS)
    _validate_score_map(data["scores_b"], "analyze judge final_json.scores_b", ANALYZE_SCORE_FIELDS)
    if not isinstance(data["claim_verdicts"], list):
        raise ValidationError("analyze judge final_json.claim_verdicts must be an array")
    for index, verdict in enumerate(data["claim_verdicts"]):
        _validate_claim_verdict(verdict, f"analyze judge final_json.claim_verdicts[{index}]")
    if not isinstance(data["additions_from_loser"], list):
        raise ValidationError("analyze judge final_json.additions_from_loser must be an array")
    for index, addition in enumerate(data["additions_from_loser"]):
        _validate_loser_addition(addition, f"analyze judge final_json.additions_from_loser[{index}]")
    if "actionable_followups" in data:
        if not isinstance(data["actionable_followups"], list):
            raise ValidationError("analyze judge final_json.actionable_followups must be an array")
        for index, followup in enumerate(data["actionable_followups"]):
            _validate_analyze_followup(followup, f"analyze judge final_json.actionable_followups[{index}]")
    return data


def validate_triage_result(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValidationError("triage final_json must be an object")
    for field in ("schema_version", "status", "summary", "items", "unknowns"):
        if field not in data:
            raise ValidationError(f"triage final_json.{field} is required")
    if data["schema_version"] != 1 or data["status"] != "complete":
        raise ValidationError('triage final_json.status must equal "complete" and schema_version must equal 1')
    if not isinstance(data["items"], list):
        raise ValidationError("triage final_json.items must be an array")
    for index, item in enumerate(data["items"]):
        _validate_triage_item(item, f"triage final_json.items[{index}]")
    _validate_string_list(data["unknowns"], "triage final_json.unknowns")
    return data


def _validate_claims(value: Any, label: str) -> None:
    if not isinstance(value, list):
        raise ValidationError(f"{label} must be an array")
    for index, claim in enumerate(value):
        _validate_mapping_claim(claim, f"{label}[{index}]", require_sources=False)


def _validate_triage_item(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object")
    for field in ("id", "source_finding_id", "source_finding", "classification", "severity", "confidence", "supporting_evidence", "counterevidence", "citation_check_ids", "recommended_action", "rationale"):
        if field not in value:
            raise ValidationError(f"{label}.{field} is required")
    if value["classification"] not in TRIAGE_CLASSIFICATIONS:
        raise ValidationError(f"{label}.classification must be one of: {', '.join(TRIAGE_CLASSIFICATIONS)}")
    if value["severity"] not in TRIAGE_SEVERITIES:
        raise ValidationError(f"{label}.severity must be one of: {', '.join(TRIAGE_SEVERITIES)}")
    if value["confidence"] not in CONFIDENCES:
        raise ValidationError(f"{label}.confidence must be one of: {', '.join(CONFIDENCES)}")
    if value["recommended_action"] not in TRIAGE_ACTIONS:
        raise ValidationError(f"{label}.recommended_action must be one of: {', '.join(TRIAGE_ACTIONS)}")
    _validate_string_list(value["supporting_evidence"], f"{label}.supporting_evidence")
    _validate_string_list(value["counterevidence"], f"{label}.counterevidence")
    _validate_string_list(value["citation_check_ids"], f"{label}.citation_check_ids")


def _validate_mapping_claim(value: Any, label: str, *, require_sources: bool) -> None:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object")
    for field in ("claim", "evidence", "confidence"):
        if field not in value:
            raise ValidationError(f"{label}.{field} is required")
    if not isinstance(value["claim"], str):
        raise ValidationError(f"{label}.claim must be a string")
    _validate_string_list(value["evidence"], f"{label}.evidence")
    if value["confidence"] not in CONFIDENCES:
        raise ValidationError(f'{label}.confidence must be one of: {", ".join(CONFIDENCES)}')
    if require_sources:
        if "sources" not in value:
            raise ValidationError(f"{label}.sources is required")
        if (
            not isinstance(value["sources"], list)
            or not value["sources"]
            or any(source not in ("A", "B") for source in value["sources"])
        ):
            raise ValidationError(f'{label}.sources must contain only "A" and "B"')
    else:
        if "id" not in value or not isinstance(value["id"], str):
            raise ValidationError(f"{label}.id must be a string")


def _validate_out_of_facet_claim(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object")
    for field in ("claim", "evidence", "sources", "reason"):
        if field not in value:
            raise ValidationError(f"{label}.{field} is required")
    if not isinstance(value["claim"], str):
        raise ValidationError(f"{label}.claim must be a string")
    if not isinstance(value["reason"], str):
        raise ValidationError(f"{label}.reason must be a string")
    _validate_string_list(value["evidence"], f"{label}.evidence")
    if (
        not isinstance(value["sources"], list)
        or not value["sources"]
        or any(source not in ("A", "B") for source in value["sources"])
    ):
        raise ValidationError(f'{label}.sources must contain only "A" and "B"')


def _validate_score_map(value: Any, label: str, fields: tuple[str, ...]) -> None:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object")
    for field in fields:
        if field not in value:
            raise ValidationError(f"{label}.{field} is required")
        if not isinstance(value[field], int) or not 1 <= value[field] <= 5:
            raise ValidationError(f"{label}.{field} must be an integer from 1 to 5")


def _validate_claim_verdict(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object")
    if "claim_id" not in value or not isinstance(value["claim_id"], str):
        raise ValidationError(f"{label}.claim_id must be a string")
    if value.get("loser_position") not in ANALYZE_LOSER_POSITIONS:
        raise ValidationError(
            f'{label}.loser_position must be one of: {", ".join(ANALYZE_LOSER_POSITIONS)}'
        )
    if "loser_note" in value and not isinstance(value["loser_note"], str):
        raise ValidationError(f"{label}.loser_note must be a string")


def _validate_loser_addition(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object")
    if "claim" not in value or not isinstance(value["claim"], str):
        raise ValidationError(f"{label}.claim must be a string")
    _validate_string_list(value.get("evidence"), f"{label}.evidence")


def _validate_analyze_followup(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object")
    for field in ("claim", "kind", "severity", "evidence", "recommended_action"):
        if field not in value:
            raise ValidationError(f"{label}.{field} is required")
    if not isinstance(value["claim"], str):
        raise ValidationError(f"{label}.claim must be a string")
    if value["kind"] not in ANALYZE_FOLLOWUP_KINDS:
        raise ValidationError(f"{label}.kind must be one of: {', '.join(ANALYZE_FOLLOWUP_KINDS)}")
    if value["severity"] not in TRIAGE_SEVERITIES:
        raise ValidationError(f"{label}.severity must be one of: {', '.join(TRIAGE_SEVERITIES)}")
    if value["recommended_action"] not in TRIAGE_ACTIONS:
        raise ValidationError(f"{label}.recommended_action must be one of: {', '.join(TRIAGE_ACTIONS)}")
    _validate_string_list(value["evidence"], f"{label}.evidence")


def _validate_string_list(value: Any, label: str) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValidationError(f"{label} must be an array of strings")


def _validate_string_or_list(value: Any, label: str) -> None:
    if isinstance(value, str):
        return
    _validate_string_list(value, label)


def init_template(mode: str) -> str:
    if mode not in MODES:
        raise ValidationError(f'type must be one of: {", ".join(MODES)} (got {mode!r})')
    if mode == "gather":
        scopes = ("codebase", "web")
        goal = "ONE SENTENCE: what coverage are you looking for?"
        background = "MULTI-LINE: relevant files, links, what you already know."
    elif mode == "compare":
        scopes = ("mixed", "mixed")
        goal = "ONE SENTENCE: what decision or comparison should be judged?"
        background = "MULTI-LINE: relevant evidence, constraints, and options."
    else:
        scopes = ("codebase", "codebase")
        goal = "ONE SENTENCE: what subject should be explained thoroughly?"
        background = "MULTI-LINE: relevant files, design notes, links, and questions."
    effort = MODE_EFFORT_DEFAULTS[mode]

    return f"""// bakeoff {mode} work order - edit `id`, `goal`, `background`, then run:
//   bakeoff validate <this-file>
//   bakeoff research <this-file>
{{
  "schema_version": 1,
  "id": "TODO-rename-this",
  "type": "{mode}",
  "goal": "{goal}",
  "background": "{background}",
  "providers": [
    {{ "id": "claude", "backend": "claude", "model": "claude-sonnet-4-6", "effort": "{effort["worker"]}", "scope": "{scopes[0]}" }},
    {{ "id": "codex",  "backend": "codex",  "model": "gpt-5.5",           "effort": "{effort["worker"]}", "scope": "{scopes[1]}" }}
  ],
  "scope_policy": {{ "enforcement": "best_effort" }},
  "judge":   {{ "backend": "claude", "model": "claude-opus-4-7", "effort": "{effort["judge"]}" }},
  "budgets": {{
    "wall_clock_seconds": 900,
    "max_output_bytes": 60000,
    "heartbeat_seconds": 60,
    "output_cap_grace_seconds": 10,
    "max_output_overrun_bytes": 60000
  }}
}}
"""


def review_template() -> str:
    effort = MODE_EFFORT_DEFAULTS["gather"]
    return f"""// bakeoff review recipe - edit `id`, `goal`, `background`, then run:
//   bakeoff validate <this-file>
//   bakeoff research <this-file>
//
// This recipe creates a normal gather work order with a shared code-review
// facet. Bakeoff does not compute branch diffs in v1; paste the branch/diff
// context, changed files, acceptance criteria, and known risks into background.
{{
  "schema_version": 1,
  "id": "TODO-rename-this",
  "type": "gather",
  "goal": "Review the branch diff for actionable defects.",
  "background": "Base branch: TODO. Review branch: TODO. Diff command/output: TODO. Changed files: TODO. Acceptance criteria: TODO. Known risk areas: TODO.",
  "facet": {{
    "id": "code-review",
    "kind": "generic",
    "focus": "Find actionable defects introduced or exposed by the change.",
    "include": [
      "correctness bugs and edge cases",
      "security issues with concrete data-flow or control-flow evidence",
      "user-visible regressions",
      "missing or misleading tests for changed behavior",
      "maintainability risks likely to cause future defects"
    ],
    "exclude": [
      "style-only preferences without project convention evidence",
      "large rewrites unrelated to the changed behavior",
      "speculation without file:line evidence"
    ]
  }},
  "providers": [
    {{ "id": "claude", "backend": "claude", "model": "claude-sonnet-4-6", "effort": "{effort["worker"]}", "scope": "codebase" }},
    {{ "id": "codex",  "backend": "codex",  "model": "gpt-5.5",           "effort": "{effort["worker"]}", "scope": "codebase" }}
  ],
  "scope_policy": {{ "enforcement": "best_effort" }},
  "judge":   {{ "backend": "claude", "model": "claude-opus-4-7", "effort": "{effort["judge"]}" }},
  "budgets": {{
    "wall_clock_seconds": 900,
    "max_output_bytes": 60000,
    "heartbeat_seconds": 60,
    "output_cap_grace_seconds": 10,
    "max_output_overrun_bytes": 60000
  }}
}}
"""
