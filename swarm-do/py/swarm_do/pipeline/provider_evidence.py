"""Prompt-safe summaries for provider review artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence


DEFAULT_MAX_FINDINGS = 5
DEFAULT_MAX_ERRORS = 5
_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def provider_evidence_summary_from_file(
    artifact_path: str | Path,
    *,
    max_findings: int = DEFAULT_MAX_FINDINGS,
    max_errors: int = DEFAULT_MAX_ERRORS,
) -> str:
    path = Path(artifact_path)
    artifact = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(artifact, Mapping):
        raise ValueError("provider evidence artifact root must be an object")
    return provider_evidence_summary(
        artifact,
        artifact_path=str(path),
        max_findings=max_findings,
        max_errors=max_errors,
    )


def provider_evidence_summary(
    artifact: Mapping[str, Any],
    *,
    artifact_path: str | None = None,
    max_findings: int = DEFAULT_MAX_FINDINGS,
    max_errors: int = DEFAULT_MAX_ERRORS,
) -> str:
    """Render bounded normalized evidence for downstream review prompts.

    The summary intentionally avoids raw stdout, stderr, last-message content,
    provider evidence snippets, and provider reasoning. It uses only normalized
    artifact metadata, finding summaries, locations, consensus fields, and
    normalized provider error rows.
    """

    if max_findings < 0 or max_errors < 0:
        raise ValueError("max_findings and max_errors must be >= 0")

    provider = _text(artifact.get("provider"), "unknown")
    status = _text(artifact.get("status"), "unknown")
    schema_version = _text(artifact.get("schema_version"), "unknown")
    source_artifact = artifact_path or _text(artifact.get("source_artifact_path"), "")
    provider_count = _int_text(artifact.get("provider_count"))
    selected = _string_list(artifact.get("selected_providers"))
    configured = _string_list(artifact.get("configured_providers"))
    launched = _string_list(artifact.get("launched_providers"))
    schema_valid = _string_list(artifact.get("schema_valid_providers"))
    min_success = artifact.get("min_success")
    status_reason = _text(artifact.get("status_reason"), "")

    lines = ["Provider Review Evidence"]
    lines.append(f"- artifact: {source_artifact or 'unknown'}")
    status_line = f"- status: {provider} {status} ({schema_version})"
    if status_reason:
        status_line += f" - {_clip(status_reason, 220)}"
    lines.append(status_line)

    provider_bits = []
    if configured:
        provider_bits.append(f"configured={_join(configured)}")
    if selected:
        provider_bits.append(f"selected={_join(selected)}")
    if launched:
        provider_bits.append(f"launched={_join(launched)}")
    if schema_valid:
        provider_bits.append(f"schema_valid={_join(schema_valid)}")
    provider_bits.append(f"provider_count={provider_count}")
    if isinstance(min_success, int):
        provider_bits.append(f"min_success={min_success}")
    lines.append("- providers: " + "; ".join(provider_bits))

    policy = artifact.get("consensus_policy")
    if isinstance(policy, Mapping):
        policy_bits = []
        secondary = _text(policy.get("secondary_cluster_promotion"), "")
        single = _text(policy.get("single_provider_findings"), "")
        stock_min = policy.get("stock_auto_min_success")
        if secondary:
            policy_bits.append(f"secondary_cluster_promotion={secondary}")
        if single:
            policy_bits.append(f"single_provider_findings={single}")
        if isinstance(stock_min, int):
            policy_bits.append(f"stock_auto_min_success={stock_min}")
        if policy_bits:
            lines.append("- consensus_policy: " + "; ".join(policy_bits))

    findings = [item for item in artifact.get("findings") or [] if isinstance(item, Mapping)]
    sorted_findings = sorted(findings, key=_finding_sort_key)
    shown_findings = sorted_findings[:max_findings]
    lines.append(f"- findings: {len(shown_findings)} shown of {len(findings)}")
    for finding in shown_findings:
        lines.append("  - " + _finding_line(finding))

    errors = [item for item in artifact.get("provider_errors") or [] if isinstance(item, Mapping)]
    shown_errors = errors[:max_errors]
    lines.append(f"- provider_errors: {len(shown_errors)} shown of {len(errors)}")
    for error in shown_errors:
        lines.append("  - " + _error_line(error))

    return "\n".join(lines)


def _finding_sort_key(finding: Mapping[str, Any]) -> tuple[int, float, str, str, int]:
    severity = _text(finding.get("severity"), "info").lower()
    score = finding.get("consensus_score")
    numeric_score = float(score) if isinstance(score, (int, float)) and not isinstance(score, bool) else -1.0
    return (
        _SEVERITY_RANK.get(severity, 99),
        -numeric_score,
        _text(finding.get("file_path"), ""),
        _text(finding.get("summary"), "").lower(),
        _int_or_zero(finding.get("line_start")),
    )


def _finding_line(finding: Mapping[str, Any]) -> str:
    severity = _text(finding.get("severity"), "info")
    category = _text(finding.get("category"), "uncategorized")
    location = _location(finding)
    consensus = _text(finding.get("consensus_level"), "unknown")
    score = finding.get("consensus_score")
    score_text = f"{float(score):.6f}" if isinstance(score, (int, float)) and not isinstance(score, bool) else "n/a"
    detected_by = _join(_string_list(finding.get("detected_by"))) or "unknown"
    summary = _clip(_text(finding.get("summary"), ""), 260)
    prefix = f"{severity}/{category}"
    if location:
        prefix += f" {location}"
    return f"{prefix} {consensus} score={score_text} detected_by={detected_by}: {summary}"


def _error_line(error: Mapping[str, Any]) -> str:
    provider = _text(error.get("provider"), "unknown")
    error_class = _text(error.get("provider_error_class"), "error")
    message = _clip(_text(error.get("message"), ""), 220)
    schema_mode = _text(error.get("schema_mode"), "")
    prefix = f"{provider} {error_class}"
    if schema_mode:
        prefix += f" schema_mode={schema_mode}"
    return f"{prefix}: {message}"


def _location(finding: Mapping[str, Any]) -> str:
    path = _text(finding.get("file_path"), "")
    if not path:
        return ""
    start = finding.get("line_start")
    end = finding.get("line_end")
    if isinstance(start, int) and isinstance(end, int) and end != start:
        return f"{path}:{start}-{end}"
    if isinstance(start, int):
        return f"{path}:{start}"
    return path


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _join(items: Sequence[str]) -> str:
    return ",".join(items)


def _text(value: Any, default: str) -> str:
    if value is None:
        return default
    text = str(value)
    return text if text else default


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "..."


def _int_text(value: Any) -> str:
    return str(value) if isinstance(value, int) and not isinstance(value, bool) else "unknown"


def _int_or_zero(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0
