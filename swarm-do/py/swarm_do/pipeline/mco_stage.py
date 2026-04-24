"""Private MCO stage adapter spike.

This module intentionally stays outside the pipeline schema/runtime. It shells
out to MCO in read-only review mode, stores raw artifacts, and normalizes the
machine-readable review output into a draft provider-findings envelope.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from swarm_do.telemetry.extractors.hashing import stable_finding_hash_v1
from swarm_do.telemetry.extractors.paths import normalize_path
from swarm_do.telemetry.ids import new_ulid
from swarm_do.telemetry.schemas import validate_value

from .paths import REPO_ROOT


SCHEMA_VERSION = "provider-findings.v1-draft"
DEFAULT_ROLE = "agent-codex-review"
PROVIDER_FINDINGS_SCHEMA_PATH = REPO_ROOT / "schemas" / "telemetry" / "provider_findings.schema.json"
_SEVERITY_MAP = {
    "warning": "high",
    "error": "critical",
    "critical": "critical",
    "high": "high",
    "medium": "medium",
    "low": "low",
    "info": "info",
}
_CATEGORY_REWRITES = {"types": "types_or_null", "null": "types_or_null"}
_LEADING_VERB_RE = re.compile(r"^[A-Z][a-z]*[a-z] ")
_READ_ONLY_PERMISSIONS = {
    "claude": {"permission_mode": "plan"},
    "codex": {"sandbox": "read-only"},
    "gemini": {"sandbox": "read-only"},
    "opencode": {"sandbox": "read-only"},
    "qwen": {"sandbox": "read-only"},
}


class McoStageError(ValueError):
    """Raised when MCO output cannot satisfy the spike contract."""


class ProviderFindingsSchemaError(McoStageError):
    """Raised when a normalized provider-findings artifact violates its schema."""


def _iso_utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_provider_findings_schema() -> dict[str, Any]:
    with PROVIDER_FINDINGS_SCHEMA_PATH.open("r", encoding="utf-8") as fh:
        schema = json.load(fh)
    if not isinstance(schema, dict):
        raise ProviderFindingsSchemaError(f"{PROVIDER_FINDINGS_SCHEMA_PATH} did not contain a JSON object")
    return schema


def validate_provider_findings_artifact(payload: Mapping[str, Any]) -> None:
    errors = validate_value(dict(payload), load_provider_findings_schema())
    if errors:
        raise ProviderFindingsSchemaError("provider-findings schema violation: " + "; ".join(errors[:5]))


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [value]


def parse_providers(raw: str) -> list[str]:
    providers = [part.strip() for part in raw.split(",") if part.strip()]
    if not providers:
        raise McoStageError("--providers must name at least one provider")
    return providers


def read_only_permissions(providers: Sequence[str]) -> dict[str, dict[str, str]]:
    permissions: dict[str, dict[str, str]] = {}
    unknown: list[str] = []
    for provider in providers:
        known = _READ_ONLY_PERMISSIONS.get(provider)
        if known is None:
            unknown.append(provider)
        else:
            permissions[provider] = dict(known)
    if unknown:
        joined = ", ".join(sorted(unknown))
        raise McoStageError(f"no read-only permission mapping registered for provider(s): {joined}")
    return permissions


def build_mco_review_command(
    *,
    mco_bin: str,
    repo: Path,
    prompt: str,
    providers: Sequence[str],
    timeout_seconds: int,
    task_id: str | None = None,
) -> list[str]:
    provider_csv = ",".join(providers)
    stall_timeout = max(1, min(timeout_seconds, 900))
    command = [
        mco_bin,
        "review",
        "--repo",
        str(repo),
        "--prompt",
        prompt,
        "--providers",
        provider_csv,
        "--json",
        "--strict-contract",
        "--review-hard-timeout",
        str(timeout_seconds),
        "--stall-timeout",
        str(stall_timeout),
        "--enforcement-mode",
        "strict",
        "--provider-permissions-json",
        json.dumps(read_only_permissions(providers), sort_keys=True),
    ]
    if task_id:
        command.extend(["--task-id", task_id])
    return command


def _payload_findings(payload: Mapping[str, Any]) -> list[Any]:
    candidates = [
        payload.get("findings"),
        payload.get("merged_findings"),
        payload.get("results"),
    ]
    for container_name in ("data", "result", "review"):
        container = payload.get(container_name)
        if isinstance(container, Mapping):
            candidates.extend(
                [
                    container.get("findings"),
                    container.get("merged_findings"),
                    container.get("results"),
                ]
            )
    for candidate in candidates:
        if isinstance(candidate, list):
            return candidate
    provider_results = payload.get("provider_results")
    if isinstance(provider_results, Mapping):
        merged: list[Any] = []
        for provider, result in provider_results.items():
            if not isinstance(result, Mapping):
                continue
            for key in ("final_text", "output_text"):
                text = result.get(key)
                if not isinstance(text, str) or not text.strip():
                    continue
                try:
                    nested = json.loads(text)
                except json.JSONDecodeError:
                    continue
                nested_findings = nested.get("findings") if isinstance(nested, Mapping) else None
                if not isinstance(nested_findings, list):
                    continue
                for finding in nested_findings:
                    if isinstance(finding, Mapping):
                        row = dict(finding)
                        row.setdefault("provider", str(provider))
                        merged.append(row)
                    else:
                        merged.append(finding)
                break
        if merged:
            return merged
    raise McoStageError("MCO JSON did not include a findings array")


def _provider_count(payload: Mapping[str, Any], selected_providers: Sequence[str]) -> int:
    for key in ("provider_count", "total_providers", "total_providers_ran", "providers_ran"):
        value = payload.get(key)
        if isinstance(value, int) and value >= 0:
            return value
    for container_name in ("data", "result", "run", "metadata"):
        container = payload.get(container_name)
        if isinstance(container, Mapping):
            count = _provider_count(container, ())
            if count:
                return count
    providers = payload.get("providers")
    if isinstance(providers, Mapping):
        return len(providers)
    if isinstance(providers, list):
        return len(providers)
    provider_results = payload.get("provider_results")
    if isinstance(provider_results, Mapping):
        return len(provider_results)
    return len(selected_providers)


def _provider_errors(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for key in ("provider_errors", "errors"):
        for item in _as_list(payload.get(key)):
            if isinstance(item, Mapping):
                errors.append(
                    {
                        "provider": item.get("provider") or item.get("name"),
                        "provider_error_class": item.get("error_class") or item.get("class") or item.get("type"),
                        "message": item.get("message") or item.get("error") or item.get("detail"),
                    }
                )
    providers = payload.get("providers")
    provider_items: list[Any] = []
    if isinstance(providers, Mapping):
        provider_items = [dict({"provider": key}, **value) if isinstance(value, Mapping) else value for key, value in providers.items()]
    elif isinstance(providers, list):
        provider_items = providers
    provider_results = payload.get("provider_results")
    if isinstance(provider_results, Mapping):
        for provider, result in provider_results.items():
            if not isinstance(result, Mapping):
                continue
            if result.get("success") is True:
                continue
            errors.append(
                {
                    "provider": str(provider),
                    "provider_error_class": result.get("final_error") or result.get("cancel_reason") or "error",
                    "message": result.get("final_text") or result.get("parse_reason") or result.get("response_reason"),
                }
            )
    for item in provider_items:
        if not isinstance(item, Mapping):
            continue
        status = str(item.get("status") or "").lower()
        if status in {"ok", "success", "passed", "completed", ""} and not item.get("error"):
            continue
        errors.append(
            {
                "provider": item.get("provider") or item.get("name"),
                "provider_error_class": item.get("error_class") or item.get("class") or status or "error",
                "message": item.get("message") or item.get("error") or item.get("detail"),
            }
        )
    return errors


def _map_severity(raw: Any) -> str:
    return _SEVERITY_MAP.get(str(raw or "info").lower(), "info")


def _category(raw: Any) -> str:
    value = str(raw or "info").lower()
    return _CATEGORY_REWRITES.get(value, value)


def _short_summary(summary: str) -> str:
    stripped = _LEADING_VERB_RE.sub("", summary, count=1)
    return stripped.lstrip()[:200]


def _parse_location(value: Any) -> tuple[str | None, int | None, int | None]:
    if isinstance(value, Mapping):
        file_path = value.get("file") or value.get("path") or value.get("file_path")
        line_start = value.get("line_start") or value.get("start_line") or value.get("line")
        line_end = value.get("line_end") or value.get("end_line") or line_start
        return (str(file_path) if file_path else None, _to_int(line_start), _to_int(line_end))
    text = str(value or "")
    if not text or ":" not in text:
        return (None, None, None)
    file_raw, _, line_part = text.partition(":")
    if "-" in line_part:
        start_raw, _, end_raw = line_part.partition("-")
    else:
        start_raw = end_raw = line_part
    return (file_raw or None, _to_int(start_raw), _to_int(end_raw))


def _to_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    text = str(value or "").strip()
    return int(text) if text.isdigit() else None


def _finding_location(finding: Mapping[str, Any]) -> tuple[str | None, int | None, int | None]:
    file_raw, line_start, line_end = _parse_location(finding.get("location"))
    evidence = finding.get("evidence")
    if isinstance(evidence, Mapping):
        ev_file, ev_start, ev_end = _parse_location(evidence)
        file_raw = file_raw or ev_file
        line_start = line_start or ev_start
        line_end = line_end or ev_end
    if file_raw is None:
        file_raw = finding.get("file_path") or finding.get("file") or finding.get("path")
    if line_start is None:
        line_start = _to_int(finding.get("line_start") or finding.get("start_line") or finding.get("line"))
    if line_end is None:
        line_end = _to_int(finding.get("line_end") or finding.get("end_line") or line_start)
    return (str(file_raw) if file_raw else None, line_start, line_end)


def _summary(finding: Mapping[str, Any]) -> str:
    for key in ("summary", "rationale", "message", "title", "description"):
        value = finding.get(key)
        if value:
            return str(value)
    return ""


def _detected_by(finding: Mapping[str, Any]) -> list[str]:
    for key in ("detected_by", "providers", "provider_names", "confirmed_by"):
        detected = [str(item) for item in _as_list(finding.get(key)) if str(item)]
        if detected:
            return sorted(set(detected))
    for key in ("provider", "source_provider", "agent"):
        value = finding.get(key)
        if value:
            return [str(value)]
    return []


def _consensus_score(finding: Mapping[str, Any]) -> float | None:
    value = finding.get("consensus_score")
    if isinstance(value, (int, float)):
        return float(value)
    return None


def normalize_mco_review_payload(
    payload: Mapping[str, Any],
    *,
    run_id: str,
    issue_id: str,
    stage_id: str,
    selected_providers: Sequence[str],
    source_artifact_path: str,
    timestamp: str | None = None,
) -> dict[str, Any]:
    findings = _payload_findings(payload)
    provider_count = _provider_count(payload, selected_providers)
    provider_errors = _provider_errors(payload)
    ts = timestamp or _iso_utc_now()
    normalized: list[dict[str, Any]] = []

    for idx, raw in enumerate(findings):
        if not isinstance(raw, Mapping):
            raise McoStageError(f"finding[{idx}] is not an object")
        summary = _summary(raw)
        short_summary = _short_summary(summary)
        category = _category(raw.get("category") or raw.get("type"))
        file_raw, line_start, line_end = _finding_location(raw)
        file_path = normalize_path(file_raw) if file_raw else None
        hash_v1 = None
        if file_path and line_start is not None:
            hash_v1 = stable_finding_hash_v1(file_path, category, line_start, short_summary)
        detected_by = _detected_by(raw)
        row = {
            "finding_id": new_ulid(),
            "run_id": run_id,
            "timestamp": ts,
            "role": DEFAULT_ROLE,
            "issue_id": issue_id,
            "provider": "mco",
            "provider_count": provider_count,
            "detected_by": detected_by,
            "consensus_score": _consensus_score(raw),
            "consensus_level": raw.get("consensus_level"),
            "source_artifact_path": source_artifact_path,
            "provider_error_class": raw.get("provider_error_class"),
            "severity": _map_severity(raw.get("severity")),
            "category": category,
            "summary": summary,
            "short_summary": short_summary,
            "file_path": file_path,
            "line_start": line_start,
            "line_end": line_end,
            "stable_finding_hash_v1": hash_v1,
            "duplicate_cluster_id": None,
            "schema_ok": bool(run_id and issue_id and summary and detected_by),
        }
        normalized.append(row)

    status = "partial" if provider_errors else "ok"
    return {
        "schema_version": SCHEMA_VERSION,
        "provider": "mco",
        "command": "review",
        "status": status,
        "run_id": run_id,
        "issue_id": issue_id,
        "stage_id": stage_id,
        "provider_count": provider_count,
        "selected_providers": list(selected_providers),
        "source_artifact_path": source_artifact_path,
        "provider_errors": provider_errors,
        "findings": normalized,
    }


def error_result(
    *,
    run_id: str,
    issue_id: str,
    stage_id: str,
    command: str,
    selected_providers: Sequence[str],
    source_artifact_path: str,
    provider_error_class: str,
    message: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "provider": "mco",
        "command": command,
        "status": "error",
        "run_id": run_id,
        "issue_id": issue_id,
        "stage_id": stage_id,
        "provider_count": len(selected_providers),
        "selected_providers": list(selected_providers),
        "source_artifact_path": source_artifact_path,
        "provider_errors": [
            {
                "provider": "mco",
                "provider_error_class": provider_error_class,
                "message": message,
            }
        ],
        "findings": [],
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_result(path: Path, payload: Mapping[str, Any]) -> None:
    validate_provider_findings_artifact(payload)
    _write_json(path, payload)


def run_stage(args: argparse.Namespace) -> int:
    providers = parse_providers(args.providers)
    if args.command != "review":
        raise McoStageError("only --command review is supported by the MCO adapter spike")
    if args.timeout_seconds < 1:
        raise McoStageError("--timeout-seconds must be >= 1")
    repo = Path(args.repo).resolve()
    prompt_file = Path(args.prompt_file).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_stdout = output_dir / "mco.stdout.json"
    raw_stderr = output_dir / "mco.stderr.txt"
    result_path = output_dir / "provider-findings.json"

    command = build_mco_review_command(
        mco_bin=args.mco_bin,
        repo=repo,
        prompt=prompt_file.read_text(encoding="utf-8"),
        providers=providers,
        timeout_seconds=args.timeout_seconds,
        task_id=args.task_id,
    )

    try:
        completed = subprocess.run(
            command,
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=args.timeout_seconds + 5,
        )
    except subprocess.TimeoutExpired as exc:
        raw_stdout.write_text(str(exc.stdout or ""), encoding="utf-8")
        raw_stderr.write_text(str(exc.stderr or ""), encoding="utf-8")
        _write_result(
            result_path,
            error_result(
                run_id=args.run_id,
                issue_id=args.issue_id,
                stage_id=args.stage_id,
                command=args.command,
                selected_providers=providers,
                source_artifact_path=str(raw_stdout),
                provider_error_class="timeout",
                message=f"mco review timed out after {args.timeout_seconds}s",
            ),
        )
        return 1
    except OSError as exc:
        _write_result(
            result_path,
            error_result(
                run_id=args.run_id,
                issue_id=args.issue_id,
                stage_id=args.stage_id,
                command=args.command,
                selected_providers=providers,
                source_artifact_path=str(raw_stdout),
                provider_error_class="spawn_error",
                message=str(exc),
            ),
        )
        return 1

    raw_stdout.write_text(completed.stdout, encoding="utf-8")
    raw_stderr.write_text(completed.stderr, encoding="utf-8")

    if completed.returncode != 0:
        _write_result(
            result_path,
            error_result(
                run_id=args.run_id,
                issue_id=args.issue_id,
                stage_id=args.stage_id,
                command=args.command,
                selected_providers=providers,
                source_artifact_path=str(raw_stdout),
                provider_error_class="mco_exit",
                message=f"mco review exited {completed.returncode}",
            ),
        )
        return 1

    try:
        payload = json.loads(completed.stdout)
        if not isinstance(payload, Mapping):
            raise McoStageError("MCO JSON root is not an object")
        normalized = normalize_mco_review_payload(
            payload,
            run_id=args.run_id,
            issue_id=args.issue_id,
            stage_id=args.stage_id,
            selected_providers=providers,
            source_artifact_path=str(raw_stdout),
        )
    except (json.JSONDecodeError, McoStageError) as exc:
        _write_result(
            result_path,
            error_result(
                run_id=args.run_id,
                issue_id=args.issue_id,
                stage_id=args.stage_id,
                command=args.command,
                selected_providers=providers,
                source_artifact_path=str(raw_stdout),
                provider_error_class="malformed_output",
                message=str(exc),
            ),
        )
        return 1

    _write_result(result_path, normalized)
    print(str(result_path))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="swarm-stage-mco")
    parser.add_argument("--repo", required=True, help="repository root to review")
    parser.add_argument("--prompt-file", required=True, help="prompt file read by the adapter and passed to mco review --prompt")
    parser.add_argument("--providers", required=True, help="comma-separated MCO providers")
    parser.add_argument("--command", choices=["review"], default="review")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--output-dir", required=True, help="swarm run artifact directory for raw and normalized output")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--issue-id", required=True)
    parser.add_argument("--stage-id", default="mco-review-spike")
    parser.add_argument("--task-id")
    parser.add_argument("--mco-bin", default="mco")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return run_stage(args)
    except McoStageError as exc:
        print(f"swarm-stage-mco: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
