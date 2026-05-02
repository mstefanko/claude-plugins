"""Read-only derived traces for durable SwarmDaddy run artifacts.

Trace schema v1 is additive-only: removing or renaming a field requires a
schema_version bump, while adding an optional field does not. The trace is a
derived view over the file-based run contract and never becomes source state.
Free-form prompt, stdout, stderr, result, handoff, and evidence content is not
inlined; trace records paths, digests, and selected structured metadata only.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from .paths import resolve_data_dir
from .phase_decisions import SHARED_DECISIONS_FILENAME
from .phase_evidence import MANIFEST_FILENAME
from .phase_sessions import STATE_FILENAME as PHASE_STATE_FILENAME
from .run_state import active_run_path
from .stage_sessions import STATE_FILENAME as STAGE_STATE_FILENAME


TRACE_SCHEMA_VERSION = 1
RUN_EVENT_RECENT_LIMIT = 200


@dataclass(frozen=True)
class TraceWarning:
    kind: str
    path: str
    detail: str


@dataclass(frozen=True)
class ArtifactRef:
    path: str
    family: str
    size_bytes: int
    sha256: str
    schema: dict[str, str] | None = None


@dataclass(frozen=True)
class PhaseTrace:
    phase_id: str
    phase_index: int | None
    title: str | None
    status: str | None
    attempt: int | None
    started_at: str | None
    completed_at: str | None
    depends_on_phase_ids: list[str]
    status_transitions: list[str]


@dataclass(frozen=True)
class AttemptTrace:
    phase_id: str
    attempt_number: int
    launcher: str | None
    command_json_path: str | None
    prompt_path: str | None
    stdout_path: str | None
    stdout_stream_path: str | None
    stderr_path: str | None
    stderr_stream_path: str | None
    result_path: str | None
    handoff_path: str | None
    evidence_path: str | None
    failure_kind: str | None
    retry_decision: str | None
    tokens: dict[str, int] | None
    cost_usd: float | None
    changed_files: list[str] | None
    stage_controller: dict[str, Any] | None
    stream_metadata: dict[str, Any] | None


@dataclass(frozen=True)
class ProviderReviewTrace:
    path: str
    schema: dict[str, str]
    selected_providers: list[str]
    min_success: int | None
    max_parallel: int | None
    status: str | None
    status_reason: str | None


@dataclass(frozen=True)
class WorktreeObservation:
    path: str
    schema: dict[str, str] | None
    adoption_state: str | None
    drift_kind: str | None
    branch: str | None
    base_sha: str | None


@dataclass(frozen=True)
class RunEventRow:
    seq: int
    event_type: str
    timestamp: str | None
    phase_id: str | None
    work_unit_id: str | None
    details: dict[str, Any] | None


@dataclass(frozen=True)
class RunTrace:
    schema_version: int
    run_id: str
    data_dir: str
    run_dir: str
    source_paths: dict[str, str]
    source_digests: dict[str, str]
    phases: list[PhaseTrace]
    attempts: list[AttemptTrace]
    provider_reviews: list[ProviderReviewTrace]
    worktree_observations: list[WorktreeObservation]
    run_event_summary: dict[str, Any]
    run_event_recent: list[RunEventRow]
    artifacts: list[ArtifactRef]
    warnings: list[TraceWarning]
    unrecognized_artifacts: list[str]
    summary: dict[str, int]


def build_run_trace(
    run_id: str,
    *,
    data_dir: Path | None = None,
    load_full_events: bool = False,
) -> RunTrace:
    base = data_dir or resolve_data_dir()
    run_dir = base / "runs" / run_id
    if not run_dir.is_dir():
        raise FileNotFoundError(f"run directory not found: {run_dir}")
    return build_trace_from_run_dir(
        run_dir,
        run_id=run_id,
        data_dir=base,
        events_path=base / "telemetry" / "run_events.jsonl",
        active_path=active_run_path(base),
        worktree_manifest_path=base / "worktrees" / run_id / "manifest.json",
        load_full_events=load_full_events,
    )


def build_trace_from_run_dir(
    run_dir: Path,
    *,
    run_id: str | None = None,
    data_dir: Path | None = None,
    events_path: Path | None = None,
    active_path: Path | None = None,
    worktree_manifest_path: Path | None = None,
    load_full_events: bool = False,
) -> RunTrace:
    run_root = Path(run_dir)
    if not run_root.is_dir():
        raise FileNotFoundError(f"run directory not found: {run_root}")
    base = Path(data_dir) if data_dir is not None else _infer_data_dir(run_root)
    warnings: list[TraceWarning] = []
    source_paths: dict[str, str] = {}
    source_digests: dict[str, str] = {}

    prepared_path = run_root / "prepared_plan.v1.json"
    phase_state_path = run_root / PHASE_STATE_FILENAME
    if not prepared_path.is_file():
        raise FileNotFoundError(f"prepared artifact not found: {prepared_path}")
    if not phase_state_path.is_file():
        raise FileNotFoundError(f"phase-session state not found: {phase_state_path}")

    prepared = _read_json_object(prepared_path, family="prepared_plan", warnings=warnings, base=base)
    phase_state = _read_json_object(phase_state_path, family="phase_sessions", warnings=warnings, base=base)
    if prepared is None:
        raise ValueError(f"prepared artifact is unreadable: {prepared_path}")
    if phase_state is None:
        raise ValueError(f"phase-session state is unreadable: {phase_state_path}")

    resolved_run_id = str(run_id or phase_state.get("run_id") or prepared.get("run_id") or run_root.name)
    _record_source("prepared_plan", prepared_path, source_paths, source_digests, base=base)
    _record_source("phase_sessions", phase_state_path, source_paths, source_digests, base=base)

    shared_path = run_root / SHARED_DECISIONS_FILENAME
    if shared_path.is_file():
        _read_json_object(shared_path, family="shared_decisions", warnings=warnings, base=base)
        _record_source("shared_decisions", shared_path, source_paths, source_digests, base=base)

    active = active_path if active_path is not None else base / "active-run.json"
    if active.is_file():
        _read_json_object(active, family="active_run", warnings=warnings, base=base)
        _record_source("active_run", active, source_paths, source_digests, base=base)
    else:
        warnings.append(TraceWarning("missing_optional_artifact", _rel(active, base), "active-run.json not present"))

    events = _read_run_events(
        events_path if events_path is not None else base / "telemetry" / "run_events.jsonl",
        run_id=resolved_run_id,
        warnings=warnings,
        source_paths=source_paths,
        source_digests=source_digests,
        base=base,
    )

    provider_reviews = _provider_reviews(run_root, warnings, source_paths, source_digests, base)
    worktree_observations = _worktree_observations(
        run_root,
        worktree_manifest_path if worktree_manifest_path is not None else base / "worktrees" / resolved_run_id / "manifest.json",
        warnings,
        source_paths,
        source_digests,
        base,
    )
    stage_session_paths = sorted(run_root.glob(f"phases/*/{STAGE_STATE_FILENAME}"), key=lambda item: _rel(item, run_root))
    for path in stage_session_paths:
        _read_json_object(path, family="stage_sessions", warnings=warnings, base=base)
        _record_source("stage_sessions", path, source_paths, source_digests, base=base)

    phases = _phase_traces(phase_state, events)
    attempts = _attempt_traces(run_root, phase_state, warnings, source_paths, source_digests, base)
    artifacts, unrecognized = _artifact_refs(run_root)
    run_event_recent = events if load_full_events else events[-RUN_EVENT_RECENT_LIMIT:]
    summary = {
        "phases": len(phases),
        "attempts": len(attempts),
        "warnings": len(warnings),
        "unrecognized": len(unrecognized),
    }
    return RunTrace(
        schema_version=TRACE_SCHEMA_VERSION,
        run_id=resolved_run_id,
        data_dir=str(base.resolve(strict=False)),
        run_dir=str(run_root.resolve(strict=False)),
        source_paths=dict(sorted(source_paths.items())),
        source_digests=dict(sorted(source_digests.items())),
        phases=phases,
        attempts=attempts,
        provider_reviews=provider_reviews,
        worktree_observations=worktree_observations,
        run_event_summary=_run_event_summary(events, events_path if events_path is not None else base / "telemetry" / "run_events.jsonl", base),
        run_event_recent=run_event_recent,
        artifacts=artifacts,
        warnings=sorted(warnings, key=lambda item: (item.kind, item.path, item.detail)),
        unrecognized_artifacts=unrecognized,
        summary=summary,
    )


def trace_to_dict(trace: RunTrace) -> dict[str, Any]:
    return asdict(trace)


def trace_to_json(trace: RunTrace) -> str:
    return json.dumps(trace_to_dict(trace), indent=2, sort_keys=True) + "\n"


def _infer_data_dir(run_dir: Path) -> Path:
    if run_dir.parent.name == "runs":
        return run_dir.parent.parent
    return run_dir.parent


def _read_json_object(
    path: Path,
    *,
    family: str,
    warnings: list[TraceWarning],
    base: Path,
) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        warnings.append(TraceWarning(f"missing_{family}", _rel(path, base), "artifact not present"))
        return None
    except json.JSONDecodeError as exc:
        warning_kind = "malformed_result" if _is_result_path(path) else f"malformed_{family}"
        warnings.append(TraceWarning(warning_kind, _rel(path, base), str(exc)))
        return None
    except OSError as exc:
        warnings.append(TraceWarning(f"unreadable_{family}", _rel(path, base), str(exc)))
        return None
    if not isinstance(value, dict):
        warnings.append(TraceWarning(f"invalid_{family}", _rel(path, base), "root must be a JSON object"))
        return None
    return value


def _read_run_events(
    path: Path,
    *,
    run_id: str,
    warnings: list[TraceWarning],
    source_paths: dict[str, str],
    source_digests: dict[str, str],
    base: Path,
) -> list[RunEventRow]:
    if not path.is_file():
        warnings.append(TraceWarning("missing_optional_artifact", _rel(path, base), "run_events.jsonl not present"))
        return []
    _record_source("run_events", path, source_paths, source_digests, base=base)
    rows: list[RunEventRow] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        warnings.append(TraceWarning("unreadable_run_events", _rel(path, base), str(exc)))
        return []
    for index, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            warnings.append(TraceWarning("malformed_run_event", f"{_rel(path, base)}:{index}", str(exc)))
            continue
        if not isinstance(value, dict):
            warnings.append(TraceWarning("invalid_run_event", f"{_rel(path, base)}:{index}", "row must be an object"))
            continue
        if value.get("run_id") not in (None, run_id):
            continue
        details = value.get("details") if isinstance(value.get("details"), dict) else None
        rows.append(
            RunEventRow(
                seq=_event_seq(value, len(rows) + 1),
                event_type=str(value.get("event_type") or value.get("kind") or "unknown"),
                timestamp=str(value.get("timestamp")) if value.get("timestamp") is not None else None,
                phase_id=str(value.get("phase_id")) if value.get("phase_id") is not None else _phase_id_from_details(details),
                work_unit_id=str(value.get("work_unit_id")) if value.get("work_unit_id") is not None else None,
                details=dict(details) if details is not None else None,
            )
        )
    return sorted(rows, key=lambda row: (row.seq, row.timestamp or "", row.event_type))


def _event_seq(value: Mapping[str, Any], fallback: int) -> int:
    for key in ("seq", "sequence", "event_seq"):
        candidate = value.get(key)
        if isinstance(candidate, int) and not isinstance(candidate, bool):
            return candidate
    return fallback


def _phase_id_from_details(details: Mapping[str, Any] | None) -> str | None:
    if details is None:
        return None
    value = details.get("phase_id")
    return str(value) if value is not None else None


def _phase_traces(phase_state: Mapping[str, Any], events: list[RunEventRow]) -> list[PhaseTrace]:
    phases: list[PhaseTrace] = []
    for phase in phase_state.get("phases") or []:
        if not isinstance(phase, Mapping):
            continue
        phase_id = str(phase.get("phase_id") or "")
        transitions = _status_transitions(phase_id, str(phase.get("status") or ""), events)
        phases.append(
            PhaseTrace(
                phase_id=phase_id,
                phase_index=_int_or_none(phase.get("phase_index")),
                title=str(phase.get("title")) if phase.get("title") is not None else None,
                status=str(phase.get("status")) if phase.get("status") is not None else None,
                attempt=_int_or_none(phase.get("attempt")),
                started_at=str(phase.get("started_at")) if phase.get("started_at") is not None else None,
                completed_at=str(phase.get("completed_at")) if phase.get("completed_at") is not None else None,
                depends_on_phase_ids=[str(item) for item in phase.get("depends_on_phase_ids") or [] if isinstance(item, str)],
                status_transitions=transitions,
            )
        )
    return sorted(phases, key=lambda item: (item.phase_id, item.started_at or ""))


_EVENT_STATUS = {
    "phase_session_initialized": "pending",
    "phase_session_claimed": "leased",
    "phase_session_started": "running",
    "phase_attempt_retry_scheduled": "retry_waiting",
    "phase_attempt_retry_ready": "pending",
    "phase_attempt_abandoned": "pending",
    "phase_attempt_retry_exhausted": "retry_exhausted",
    "phase_session_completed": "complete",
    "phase_session_failed": "failed",
    "phase_session_blocked": "blocked",
    "phase_session_needs_input": "needs_input",
    "phase_session_reset": "pending",
}


def _status_transitions(phase_id: str, current_status: str, events: list[RunEventRow]) -> list[str]:
    statuses: list[str] = ["pending"]
    for row in events:
        if row.phase_id != phase_id:
            continue
        status = None
        if row.details and isinstance(row.details.get("status"), str):
            status = str(row.details["status"])
        status = status or _EVENT_STATUS.get(row.event_type)
        if status and status != statuses[-1]:
            statuses.append(status)
    if current_status and current_status != statuses[-1]:
        statuses.append(current_status)
    return statuses


def _attempt_traces(
    run_dir: Path,
    phase_state: Mapping[str, Any],
    warnings: list[TraceWarning],
    source_paths: dict[str, str],
    source_digests: dict[str, str],
    base: Path,
) -> list[AttemptTrace]:
    attempts: list[AttemptTrace] = []
    seen: set[tuple[str, int]] = set()
    for phase in phase_state.get("phases") or []:
        if not isinstance(phase, Mapping):
            continue
        phase_id = str(phase.get("phase_id") or "")
        history = [item for item in phase.get("attempt_history") or [] if isinstance(item, Mapping)]
        if not history and _int_or_none(phase.get("attempt")):
            history = [phase]
        for record in history:
            attempt_number = _int_or_none(record.get("attempt")) or 0
            if attempt_number <= 0:
                continue
            key = (phase_id, attempt_number)
            if key in seen:
                continue
            seen.add(key)
            attempts.append(
                _attempt_trace_from_record(
                    run_dir,
                    phase_id,
                    attempt_number,
                    record,
                    warnings,
                    source_paths,
                    source_digests,
                    base,
                )
            )
    return sorted(attempts, key=lambda item: (item.phase_id, item.attempt_number))


def _attempt_trace_from_record(
    run_dir: Path,
    phase_id: str,
    attempt_number: int,
    record: Mapping[str, Any],
    warnings: list[TraceWarning],
    source_paths: dict[str, str],
    source_digests: dict[str, str],
    base: Path,
) -> AttemptTrace:
    launch_dir = _path_from_value(record.get("launch_dir"), base=base)
    if launch_dir is None:
        launch_dir = run_dir / "phase_launches" / phase_id / f"attempt-{attempt_number}"
    command_path = _path_from_value(record.get("command_path"), base=base) or launch_dir / "command.json"
    command = _read_json_object(command_path, family="command", warnings=warnings, base=base) if command_path.is_file() else None
    if command_path.is_file():
        _record_source("command", command_path, source_paths, source_digests, base=base)
    prompt_path = _first_existing_path(
        _path_from_value((command or {}).get("prompt_path"), base=base),
        launch_dir / "prompt.txt",
        launch_dir / "dispatcher.launcher.prompt.md",
    )
    stdout_path = _first_existing_path(launch_dir / "stdout.txt")
    stdout_stream_path = _first_existing_path(launch_dir / "stdout.stream.jsonl")
    stderr_path = _first_existing_path(launch_dir / "stderr.txt")
    stderr_stream_path = _first_existing_path(launch_dir / "stderr.stream.txt")
    result_path = _first_existing_path(
        _path_from_value(record.get("result_path") or (command or {}).get("result_path"), base=base),
        run_dir / "phase_results" / phase_id / f"attempt-{attempt_number}.result.json",
        launch_dir / "result.json",
    )
    handoff_path = _first_existing_path(
        _path_from_value(record.get("handoff_path") or (command or {}).get("handoff_path"), base=base),
        run_dir / "phase_handoffs" / phase_id / f"attempt-{attempt_number}.handoff.json",
        launch_dir / "handoff.json",
    )
    evidence_path = _first_existing_path(
        _path_from_value(record.get("evidence_path"), base=base),
        launch_dir / MANIFEST_FILENAME,
    )
    evidence = _read_optional_structured("evidence", evidence_path, warnings, source_paths, source_digests, base)
    if result_path is not None:
        _read_json_object(result_path, family="result", warnings=warnings, base=base)
        _record_source("result", result_path, source_paths, source_digests, base=base)
    if handoff_path is not None:
        _read_json_object(handoff_path, family="handoff", warnings=warnings, base=base)
        _record_source("handoff", handoff_path, source_paths, source_digests, base=base)
    for family, path in (
        ("prompt", prompt_path),
        ("stdout", stdout_path),
        ("stdout_stream", stdout_stream_path),
        ("stderr", stderr_path),
        ("stderr_stream", stderr_stream_path),
    ):
        if path is not None:
            _record_source(family, path, source_paths, source_digests, base=base)
    metrics = evidence.get("metrics") if isinstance(evidence.get("metrics"), Mapping) else {}
    failure = evidence.get("failure") if isinstance(evidence.get("failure"), Mapping) else {}
    artifacts = evidence.get("artifacts") if isinstance(evidence.get("artifacts"), Mapping) else {}
    tokens = _tokens(metrics)
    changed_files = _string_list(record.get("changed_files"))
    if not changed_files:
        changed_files = _string_list(artifacts.get("changed_files"))
    return AttemptTrace(
        phase_id=phase_id,
        attempt_number=attempt_number,
        launcher=_string_or_none(record.get("launcher") or (command or {}).get("launcher") or evidence.get("launcher")),
        command_json_path=_rel_or_none(command_path if command_path.is_file() else None, base),
        prompt_path=_rel_or_none(prompt_path, base),
        stdout_path=_rel_or_none(stdout_path, base),
        stdout_stream_path=_rel_or_none(stdout_stream_path, base),
        stderr_path=_rel_or_none(stderr_path, base),
        stderr_stream_path=_rel_or_none(stderr_stream_path, base),
        result_path=_rel_or_none(result_path, base),
        handoff_path=_rel_or_none(handoff_path, base),
        evidence_path=_rel_or_none(evidence_path, base),
        failure_kind=_string_or_none(record.get("failure_kind") or failure.get("failure_kind")),
        retry_decision=_string_or_none(record.get("retry_decision") or failure.get("retry_decision")),
        tokens=tokens,
        cost_usd=_float_or_none(metrics.get("total_cost_usd") if metrics else record.get("cost_usd")),
        changed_files=changed_files if changed_files else None,
        stage_controller=_dict_or_none((command or {}).get("stage_controller")),
        stream_metadata=_dict_or_none((command or {}).get("stream_metadata")),
    )


def _read_optional_structured(
    family: str,
    path: Path | None,
    warnings: list[TraceWarning],
    source_paths: dict[str, str],
    source_digests: dict[str, str],
    base: Path,
) -> dict[str, Any]:
    if path is None:
        return {}
    value = _read_json_object(path, family=family, warnings=warnings, base=base)
    _record_source(family, path, source_paths, source_digests, base=base)
    return value or {}


def _provider_reviews(
    run_dir: Path,
    warnings: list[TraceWarning],
    source_paths: dict[str, str],
    source_digests: dict[str, str],
    base: Path,
) -> list[ProviderReviewTrace]:
    traces: list[ProviderReviewTrace] = []
    paths = sorted(
        {path for path in run_dir.rglob("*provider-review.manifest.json") if path.is_file()},
        key=lambda item: _rel(item, run_dir),
    )
    for path in paths:
        payload = _read_json_object(path, family="provider_review", warnings=warnings, base=base)
        _record_source("provider_review", path, source_paths, source_digests, base=base)
        if payload is None:
            continue
        selection = payload.get("selection") if isinstance(payload.get("selection"), Mapping) else {}
        selected = selection.get("selected_providers") or selection.get("selected") or payload.get("selected_providers")
        traces.append(
            ProviderReviewTrace(
                path=_rel(path, base),
                schema=_schema_record("provider_review", payload.get("schema_version")),
                selected_providers=_string_list(selected),
                min_success=_int_or_none(selection.get("min_success") or payload.get("min_success")),
                max_parallel=_int_or_none(selection.get("max_parallel") or payload.get("max_parallel")),
                status=_string_or_none(payload.get("status")),
                status_reason=_string_or_none(payload.get("status_reason")),
            )
        )
    return traces


def _worktree_observations(
    run_dir: Path,
    manifest_path: Path,
    warnings: list[TraceWarning],
    source_paths: dict[str, str],
    source_digests: dict[str, str],
    base: Path,
) -> list[WorktreeObservation]:
    paths: list[Path] = []
    if manifest_path.is_file():
        paths.append(manifest_path)
    local = run_dir / "worktree-manifest.json"
    if local.is_file() and local not in paths:
        paths.append(local)
    if not paths:
        warnings.append(TraceWarning("missing_optional_artifact", _rel(manifest_path, base), "worktree manifest not present"))
        return []
    observations: list[WorktreeObservation] = []
    for path in sorted(paths, key=lambda item: _rel(item, base)):
        payload = _read_json_object(path, family="worktree_manifest", warnings=warnings, base=base)
        _record_source("worktree_manifest", path, source_paths, source_digests, base=base)
        if payload is None:
            continue
        drift = payload.get("drift") if isinstance(payload.get("drift"), Mapping) else {}
        observations.append(
            WorktreeObservation(
                path=_rel(path, base),
                schema=_schema_record("worktree_manifest", payload.get("schema_version")) if payload.get("schema_version") is not None else None,
                adoption_state=_string_or_none(payload.get("adoption_state")),
                drift_kind=_string_or_none(drift.get("kind") or payload.get("drift_kind")),
                branch=_string_or_none(payload.get("branch") or payload.get("run_execution_branch")),
                base_sha=_string_or_none(payload.get("base_sha") or payload.get("git_base_sha")),
            )
        )
    return observations


def _artifact_refs(run_dir: Path) -> tuple[list[ArtifactRef], list[str]]:
    artifacts: list[ArtifactRef] = []
    unrecognized: list[str] = []
    for path in sorted((item for item in run_dir.rglob("*") if item.is_file()), key=lambda item: _rel(item, run_dir)):
        rel = _rel(path, run_dir)
        family = _classify_artifact(rel)
        schema = None
        if path.suffix == ".json":
            payload = _safe_json_object(path)
            if payload is not None and payload.get("schema_version") is not None:
                schema = _schema_record(family, payload.get("schema_version"))
        artifacts.append(
            ArtifactRef(
                path=rel,
                family=family,
                size_bytes=path.stat().st_size,
                sha256=_sha256_file(path),
                schema=schema,
            )
        )
        if family == "unclassified":
            unrecognized.append(rel)
    return artifacts, unrecognized


def _classify_artifact(rel: str) -> str:
    name = Path(rel).name
    parts = Path(rel).parts
    if rel == "prepared_plan.v1.json":
        return "prepared_plan"
    if rel == PHASE_STATE_FILENAME:
        return "phase_sessions"
    if rel == SHARED_DECISIONS_FILENAME:
        return "shared_decisions"
    if name == STAGE_STATE_FILENAME and len(parts) >= 3 and parts[0] == "phases":
        return "stage_sessions"
    if name == "provider-review.manifest.json" or name.endswith(".provider-review.manifest.json"):
        return "provider_review"
    if name == "command.json":
        return "command"
    if name in {"prompt.txt", "dispatcher.launcher.prompt.md"}:
        return "prompt"
    if name in {"stdout.txt", "stdout.stream.jsonl", "stderr.txt", "stderr.stream.txt"}:
        return "launcher_output"
    if name in {"result.json", "handoff.json", MANIFEST_FILENAME}:
        return "attempt_artifact"
    if len(parts) >= 3 and parts[0] in {"phase_results", "phase_handoffs"}:
        return "attempt_artifact"
    if name.startswith("post_writer_report"):
        return "post_writer_report"
    if name == "provider-findings.json":
        return "provider_findings"
    if name.endswith(".lock"):
        return "lock"
    return "unclassified"


def _run_event_summary(events: list[RunEventRow], path: Path, base: Path) -> dict[str, Any]:
    kinds: dict[str, int] = {}
    for row in events:
        kinds[row.event_type] = kinds.get(row.event_type, 0) + 1
    return {
        "count": len(events),
        "kinds": dict(sorted(kinds.items())),
        "last_seq": events[-1].seq if events else None,
        "path": _rel(path, base),
    }


def _record_source(
    family: str,
    path: Path,
    source_paths: dict[str, str],
    source_digests: dict[str, str],
    *,
    base: Path,
) -> None:
    rel = _rel(path, base)
    key = family
    suffix = 2
    while key in source_paths and source_paths[key] != rel:
        key = f"{family}#{suffix}"
        suffix += 1
    source_paths[key] = rel
    if path.is_file():
        source_digests[rel] = _sha256_file(path)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_json_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def _schema_record(family: str, version: Any) -> dict[str, str]:
    return {"family": family, "version_str": "" if version is None else str(version)}


def _tokens(metrics: Mapping[str, Any]) -> dict[str, int] | None:
    input_tokens = _int_or_none(metrics.get("input_tokens"))
    output_tokens = _int_or_none(metrics.get("output_tokens"))
    if input_tokens is None and output_tokens is None:
        return None
    return {"input": input_tokens or 0, "output": output_tokens or 0}


def _first_existing_path(*paths: Path | None) -> Path | None:
    for path in paths:
        if path is not None and path.is_file():
            return path
    return None


def _path_from_value(value: Any, *, base: Path) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else base / path


def _rel_or_none(path: Path | None, base: Path) -> str | None:
    return _rel(path, base) if path is not None else None


def _rel(path: Path, base: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(base.resolve(strict=False)).as_posix()
    except ValueError:
        return str(path.resolve(strict=False))


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, Mapping) else None


def _string_or_none(value: Any) -> str | None:
    return str(value) if value is not None else None


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _float_or_none(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _is_result_path(path: Path) -> bool:
    return path.name == "result.json" or path.name.endswith(".result.json")


__all__ = [
    "ArtifactRef",
    "AttemptTrace",
    "PhaseTrace",
    "ProviderReviewTrace",
    "RUN_EVENT_RECENT_LIMIT",
    "RunEventRow",
    "RunTrace",
    "TRACE_SCHEMA_VERSION",
    "TraceWarning",
    "WorktreeObservation",
    "build_run_trace",
    "build_trace_from_run_dir",
    "trace_to_dict",
    "trace_to_json",
]
