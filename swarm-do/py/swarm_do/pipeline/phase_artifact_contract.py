"""Shared model-facing phase result and handoff artifact contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence


PHASE_RESULT_STATUSES = ("complete", "failed", "blocked", "needs_input")


def phase_result_template(
    *,
    run_id: str,
    phase_id: str,
    phase_attempt: int,
    launcher: str,
    session_name: str | None,
    prepared_plan_sha: str,
    phase_content_sha: str,
    handoff_path: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "phase_id": phase_id,
        "phase_attempt": phase_attempt,
        "status": "<one of: " + ", ".join(PHASE_RESULT_STATUSES) + ">",
        "launcher": launcher,
        "session_name": session_name,
        "prepared_plan_sha": prepared_plan_sha,
        "phase_content_sha": phase_content_sha,
        "started_at": "<ISO-8601 UTC timestamp, e.g. 2026-04-29T18:00:00Z>",
        "completed_at": "<ISO-8601 UTC timestamp, e.g. 2026-04-29T18:08:00Z>",
        "handoff_path": handoff_path,
        "summary": "<1-3 sentence summary of work done>",
        "completed_work_units": [],
        "failed_work_units": [],
        "blocked_reason": None,
        "needs_input": [],
        "validation": [],
        "artifacts": [],
        "error": None,
    }


def phase_handoff_template(
    *,
    run_id: str,
    phase_id: str,
    phase_attempt: int,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "phase_id": phase_id,
        "phase_attempt": phase_attempt,
        "status": "<same value as result.status>",
        "written_at": "<ISO-8601 UTC timestamp>",
        "summary": "<1-3 sentence handoff summary for the next phase>",
        "decisions": [],
        "changed_files": [],
        "completed_work_units": [],
        "open_items": [],
        "blockers": [],
        "do_not_retry": [],
        "validation_summary": [],
        "artifacts": [],
        "next_phase_context": [],
    }


def phase_artifact_type_rules_markdown() -> str:
    return "\n".join(
        [
            "Array-element type rules (the schemas reject other shapes):",
            "- `result.completed_work_units`, `result.failed_work_units`, `result.needs_input`: each item is a plain string.",
            "- In phase-session mode, `result.completed_work_units` and `handoff.completed_work_units` must stay empty unless you are using a prepared unit id shown in the informational decomposition. Put semantic accomplishments in `summary`, `artifacts`, or `validation`.",
            "- `result.validation`: each item is a JSON object (e.g. `{\"command\": \"pytest\", \"status\": \"passed\"}`).",
            "- `result.artifacts`: each item is a JSON object (e.g. `{\"path\": \"docs/examples/x.json\", \"kind\": \"fixture\"}`).",
            "- `handoff.decisions`, `handoff.changed_files`, `handoff.completed_work_units`, `handoff.open_items`, `handoff.blockers`, `handoff.do_not_retry`, `handoff.validation_summary`, `handoff.next_phase_context`: each item is a plain string. Do NOT use objects.",
            "- `handoff.artifacts`: each item is a JSON object.",
        ]
    )


def phase_artifact_contract_markdown(
    *,
    result_path: Path | str,
    handoff_path: Path | str,
    status_values: Sequence[str] = PHASE_RESULT_STATUSES,
    run_id: str,
    phase_id: str,
    phase_attempt: int,
    launcher: str,
    session_name: str | None,
    prepared_plan_sha: str,
    phase_content_sha: str,
) -> str:
    statuses = tuple(status_values) if status_values else PHASE_RESULT_STATUSES
    result_template = phase_result_template(
        run_id=run_id,
        phase_id=phase_id,
        phase_attempt=phase_attempt,
        launcher=launcher,
        session_name=session_name,
        prepared_plan_sha=prepared_plan_sha,
        phase_content_sha=phase_content_sha,
        handoff_path=str(handoff_path),
    )
    result_template["status"] = "<one of: " + ", ".join(statuses) + ">"
    handoff_template = phase_handoff_template(
        run_id=run_id,
        phase_id=phase_id,
        phase_attempt=phase_attempt,
    )
    return "\n".join(
        [
            "## Launcher Artifact Contract",
            "",
            f"- Write the phase result JSON exactly to: {result_path}",
            f"- Write the phase handoff JSON exactly to: {handoff_path}",
            f"- The result status must be one of: {', '.join(statuses)}",
            "- Identity fields must match phase-session state exactly: `run_id`, `phase_id`, `phase_attempt`, `prepared_plan_sha`, and `phase_content_sha`.",
            "- Return a final JSON object containing status, result_path, handoff_path, and session_name.",
            "- Do not start another orchestrator or mutate the global phase queue.",
            "",
            "Both files are validated against strict JSON schemas. Use these templates verbatim, replacing only the `<...>` placeholder values. Do not add or remove keys.",
            "",
            phase_artifact_type_rules_markdown(),
            "",
            "Phase result JSON template:",
            "```json",
            json.dumps(result_template, indent=2),
            "```",
            "",
            "Phase handoff JSON template:",
            "```json",
            json.dumps(handoff_template, indent=2),
            "```",
        ]
    )


__all__ = [
    "PHASE_RESULT_STATUSES",
    "phase_artifact_contract_markdown",
    "phase_artifact_type_rules_markdown",
    "phase_handoff_template",
    "phase_result_template",
]
