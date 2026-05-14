from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

MODES = ("gather", "compare", "analyze")
BACKENDS = ("claude", "codex")
SCOPES = ("codebase", "web", "mixed")
EFFORTS = ("low", "medium", "high")
WORKER_STATUSES = ("complete", "complete_with_concerns", "needs_context", "blocked")
CONFIDENCES = ("high", "medium", "low")
COMPARE_SCORE_FIELDS = ("evidence", "coherence", "tradeoff_honesty", "rebuttals")
ANALYZE_SCORE_FIELDS = ("step_atomicity", "citation_grounding", "assumption_transparency", "coherence")
ANALYZE_LOSER_POSITIONS = ("agrees", "disagrees", "not_covered", "adds")


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
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", work_id):
        raise ValidationError("id must be a slug matching ^[A-Za-z0-9][A-Za-z0-9._-]*$")

    if data["type"] not in MODES:
        raise ValidationError(f'type must be one of: {", ".join(MODES)} (got {data["type"]!r})')

    if not isinstance(data["goal"], str) or not data["goal"].strip():
        raise ValidationError("goal must be a non-empty string")
    if not isinstance(data["background"], str):
        raise ValidationError("background must be a string")

    providers = _validate_providers(data["providers"])
    judge = _validate_judge(data["judge"], providers)
    budgets = _validate_budgets(data["budgets"])

    normalized = dict(data)
    normalized["providers"] = providers
    normalized["judge"] = judge
    normalized["budgets"] = budgets
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
    return {"wall_clock_seconds": value["wall_clock_seconds"], "max_output_bytes": value["max_output_bytes"]}


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
    return data


def _validate_claims(value: Any, label: str) -> None:
    if not isinstance(value, list):
        raise ValidationError(f"{label} must be an array")
    for index, claim in enumerate(value):
        _validate_mapping_claim(claim, f"{label}[{index}]", require_sources=False)


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
        if not isinstance(value["sources"], list) or any(source not in ("A", "B") for source in value["sources"]):
            raise ValidationError(f'{label}.sources must contain only "A" and "B"')
    else:
        if "id" not in value or not isinstance(value["id"], str):
            raise ValidationError(f"{label}.id must be a string")


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
    {{ "id": "claude", "backend": "claude", "model": "claude-sonnet-4-6", "effort": "high", "scope": "{scopes[0]}" }},
    {{ "id": "codex",  "backend": "codex",  "model": "gpt-5.5",           "effort": "high", "scope": "{scopes[1]}" }}
  ],
  "judge":   {{ "backend": "claude", "model": "claude-opus-4-7", "effort": "high" }},
  "budgets": {{ "wall_clock_seconds": 900, "max_output_bytes": 60000 }}
}}
"""
