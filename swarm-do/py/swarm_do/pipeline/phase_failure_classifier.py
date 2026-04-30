"""Launcher failure classification for phase-session recovery."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .claude_transcript_diagnostics import TranscriptDiagnostics, diagnose_launch
from .session_capabilities import extract_claude_print_artifacts, parse_claude_print_json


@dataclass(frozen=True)
class FailureClassification:
    failure_kind: str
    last_error: str | None
    transcript_diagnostics: TranscriptDiagnostics | None
    outer: Mapping[str, Any] | None
    metrics: Mapping[str, Any]
    details: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "failure_kind": self.failure_kind,
            "last_error": self.last_error,
            "outer": dict(self.outer or {}),
            "metrics": dict(self.metrics),
            "details": dict(self.details),
            "transcript_diagnostics": self.transcript_diagnostics.to_dict() if self.transcript_diagnostics else None,
        }


def classify_launcher_failure(
    launcher_result: Mapping[str, Any] | None,
    artifact: Mapping[str, Any],
    *,
    changed_files: Sequence[str],
    command_metadata: Mapping[str, Any],
    projects_dir: Path | None = None,
) -> FailureClassification:
    if artifact.get("valid"):
        return _classification("adoptable_artifacts")
    if artifact.get("partial"):
        return _classification("partial_artifacts_invalid")
    if not launcher_result:
        return _classification("lease_expired_no_artifacts")
    reason = launcher_result.get("reason")
    if isinstance(reason, str) and reason:
        return _classification(reason, last_error=reason)
    returncode = launcher_result.get("returncode")
    if isinstance(returncode, int) and returncode != 0:
        return _classification("launcher_nonzero_no_artifacts", metrics={"returncode": returncode})

    stdout = str(launcher_result.get("stdout") or "")
    outer: Mapping[str, Any] | None = None
    metrics: dict[str, Any] = {"returncode": returncode}
    base_kind = "outer_artifacts_missing"
    try:
        outer = parse_claude_print_json(stdout)
        metrics.update(_outer_metrics(outer))
        extract_claude_print_artifacts(outer, run_dir=Path("/definitely-not-used"))
    except ValueError as exc:
        if not stdout:
            base_kind = "outer_json_missing_no_artifacts"
        elif "missing artifact object" in str(exc):
            base_kind = "outer_artifacts_missing"
        else:
            base_kind = "outer_json_invalid_no_artifacts"
    except Exception:
        base_kind = "outer_json_invalid_no_artifacts" if stdout else "outer_json_missing_no_artifacts"

    diagnostics: TranscriptDiagnostics | None = None
    if _is_suspicious_launch(
        base_kind,
        launcher_result=launcher_result,
        command_metadata=command_metadata,
        metrics=metrics,
        changed_files=changed_files,
        stdout=stdout,
    ):
        diagnostics = _safe_diagnose_launch(launcher_result, command_metadata, projects_dir=projects_dir)
        if diagnostics is not None:
            diagnostic = diagnostics.primary_tool_error()
            if diagnostic is not None:
                details = {
                    "tool_name": diagnostic.tool_name,
                    "tool_error_kind": diagnostic.error_kind,
                    "message_excerpt": diagnostic.message_excerpt,
                    "transcript_path": str(diagnostics.transcript_path) if diagnostics.transcript_path else None,
                }
                return _classification(
                    "writer_tool_denied_no_artifacts",
                    last_error=_diagnostic_last_error(diagnostic.tool_name, diagnostic.error_kind, diagnostic.message_excerpt),
                    transcript_diagnostics=diagnostics,
                    outer=outer,
                    metrics=metrics,
                    details=details,
                )
        if _cheap_silent_writer(metrics, changed_files=changed_files, returncode=returncode):
            return _classification(
                "writer_silent_with_turns",
                last_error=_silent_writer_error(metrics),
                transcript_diagnostics=diagnostics,
                outer=outer,
                metrics=metrics,
            )

    return _classification(base_kind, outer=outer, metrics=metrics, transcript_diagnostics=diagnostics)


def _classification(
    failure_kind: str,
    *,
    last_error: str | None = None,
    transcript_diagnostics: TranscriptDiagnostics | None = None,
    outer: Mapping[str, Any] | None = None,
    metrics: Mapping[str, Any] | None = None,
    details: Mapping[str, Any] | None = None,
) -> FailureClassification:
    return FailureClassification(
        failure_kind=failure_kind,
        last_error=last_error,
        transcript_diagnostics=transcript_diagnostics,
        outer=outer,
        metrics=dict(metrics or {}),
        details=dict(details or {}),
    )


def _outer_metrics(outer: Mapping[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for key in ("session_id", "result", "num_turns", "total_cost_usd", "duration_ms"):
        value = outer.get(key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            metrics[key] = value
    return metrics


def _is_suspicious_launch(
    base_kind: str,
    *,
    launcher_result: Mapping[str, Any],
    command_metadata: Mapping[str, Any],
    metrics: Mapping[str, Any],
    changed_files: Sequence[str],
    stdout: str,
) -> bool:
    if not _is_claude_print(command_metadata):
        return False
    if launcher_result.get("returncode") != 0:
        return False
    if base_kind not in {"outer_artifacts_missing", "outer_json_invalid_no_artifacts", "outer_json_missing_no_artifacts"}:
        return False
    return (
        base_kind == "outer_artifacts_missing"
        or _empty_outer_result(metrics)
        or _int_metric(metrics, "num_turns") >= 3
        or _float_metric(metrics, "total_cost_usd") >= 0.10
        or not changed_files
    )


def _is_claude_print(command_metadata: Mapping[str, Any]) -> bool:
    if command_metadata.get("launcher") == "claude-print":
        return True
    argv = command_metadata.get("argv")
    if not isinstance(argv, list) or not argv:
        return False
    executable = Path(str(argv[0])).name
    return "claude" in executable or "--output-format" in {str(item) for item in argv}


def _safe_diagnose_launch(
    launcher_result: Mapping[str, Any],
    command_metadata: Mapping[str, Any],
    *,
    projects_dir: Path | None,
) -> TranscriptDiagnostics | None:
    if os.environ.get("SWARM_CLAUDE_TRANSCRIPT_DIAGNOSTICS", "").strip().lower() in {"0", "false", "no", "off"}:
        return None
    try:
        return diagnose_launch(launcher_result, command_metadata, projects_dir=projects_dir)
    except Exception:
        return None


def _cheap_silent_writer(metrics: Mapping[str, Any], *, changed_files: Sequence[str], returncode: Any) -> bool:
    return (
        returncode == 0
        and _empty_outer_result(metrics)
        and _int_metric(metrics, "num_turns") >= 5
        and not changed_files
    )


def _empty_outer_result(metrics: Mapping[str, Any]) -> bool:
    value = metrics.get("result")
    return isinstance(value, str) and not value.strip()


def _int_metric(metrics: Mapping[str, Any], key: str) -> int:
    value = metrics.get(key)
    return int(value) if isinstance(value, int) else 0


def _float_metric(metrics: Mapping[str, Any], key: str) -> float:
    value = metrics.get(key)
    return float(value) if isinstance(value, (int, float)) else 0.0


def _diagnostic_last_error(tool_name: str | None, error_kind: str, excerpt: str) -> str:
    return f"{tool_name or 'unknown_tool'} {error_kind}: {excerpt}"


def _silent_writer_error(metrics: Mapping[str, Any]) -> str:
    turns = metrics.get("num_turns")
    cost = metrics.get("total_cost_usd")
    if isinstance(cost, (int, float)):
        return f"writer produced no artifacts after {turns} turns and ${cost:.2f}, with an empty final result"
    return f"writer produced no artifacts after {turns} turns, with an empty final result"


__all__ = ["FailureClassification", "classify_launcher_failure"]
