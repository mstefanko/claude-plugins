"""Read-only SQLite projection over canonical JSON run state.

JSON files remain the source of truth. This module rebuilds a per-run mirror at
``<data>/runs/<run-id>/state.mirror.sqlite`` so status, doctor, trace, eval,
and future TUI readers can query one derived shape without mutating canonical
state. The global ``telemetry/run_events.jsonl`` ledger is stream-scanned and
filtered by run id; this is intentionally O(total local run events) for v1.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

try:
    import fcntl
except ImportError:  # pragma: no cover - v1 is POSIX-only by design.
    fcntl = None  # type: ignore[assignment]

from swarm_do.telemetry.schemas import load_schema, validate_value

from .paths import resolve_data_dir
from .policies import normalize_retry_policy
from .run_state import active_run_path, checkpoint_path, utc_now


PROJECTOR_SCHEMA_VERSION = 1
MIRROR_FILENAME = "state.mirror.sqlite"
SUPPORTED_SCHEMA_VERSIONS: dict[str, set[int]] = {
    "active_run": {1},
    "checkpoint": {1},
    "prepared_plan": {1},
    "phase_sessions": {1},
    "stage_sessions": {1},
    "evidence": {1},
}
_NONDETERMINISTIC_COLUMNS = {
    ("artifact_sources", "read_at"),
    ("projector_meta", "projected_at"),
}
_PHASE_STATUS_KEYS = (
    "phase_id",
    "phase_index",
    "title",
    "depends_on_phase_ids",
    "status",
    "lease_owner",
    "lease_expires_at",
    "attempt",
    "session_name",
    "started_at",
    "completed_at",
    "result_path",
    "handoff_path",
    "last_error",
    "max_session_attempts",
    "next_retry_at",
    "last_failure_kind",
    "last_launcher_error",
    "retry_exhausted_at",
    "blocked_reason",
    "retry_policy_decision",
    "blocked_at",
    "launch_dir",
    "command_path",
    "parent_pid",
    "child_pid",
    "process_group_id",
    "prompt_sha",
    "expected_result_path",
    "expected_handoff_path",
    "launch_metadata_error",
    "recovery_context_path",
    "evidence_path",
    "attempt_history",
)


class ProjectionError(RuntimeError):
    """Raised when the mirror cannot be safely rebuilt."""


@dataclass(frozen=True)
class ProjectionWarning:
    kind: str
    source: str | None
    message: str
    details: dict[str, Any] | None = None


@dataclass(frozen=True)
class ProjectionResult:
    run_id: str
    mirror_path: str
    projected_at: str
    schema_version: int
    source_count: int
    warning_count: int
    row_counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MirrorDiff:
    table: str
    primary_key: str
    column: str
    expected: Any
    actual: Any

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class _Source:
    kind: str
    path: Path
    sha256: str
    size_bytes: int
    mtime_ns: int
    payload: dict[str, Any] | None


def mirror_path_for(run_id: str, *, data_dir: Path | None = None) -> Path:
    base = data_dir or resolve_data_dir()
    return base / "runs" / run_id / MIRROR_FILENAME


def schema_sql(*, strict: bool | None = None) -> str:
    sql = Path(__file__).with_name("state_projector_schema.sql").read_text(encoding="utf-8")
    use_strict = sqlite3.sqlite_version_info >= (3, 37, 0) if strict is None else strict
    if use_strict:
        return sql
    return sql.replace(") STRICT;", ");")


def project_run(run_id: str, *, data_dir: Path | None = None) -> ProjectionResult:
    base = data_dir or resolve_data_dir()
    mirror_path = mirror_path_for(run_id, data_dir=base)
    run_dir = base / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    with _projector_lock(run_dir):
        tmp_path = _tmp_mirror_path(mirror_path)
        try:
            result = _project_to_path(run_id, data_dir=base, db_path=tmp_path)
            _check_database(tmp_path)
            _fsync_file(tmp_path)
            os.replace(tmp_path, mirror_path)
            _fsync_dir(mirror_path.parent)
            return ProjectionResult(
                run_id=run_id,
                mirror_path=str(mirror_path),
                projected_at=result.projected_at,
                schema_version=result.schema_version,
                source_count=result.source_count,
                warning_count=result.warning_count,
                row_counts=result.row_counts,
            )
        except Exception:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass
            raise


def diff_mirror(run_id: str, *, data_dir: Path | None = None) -> list[MirrorDiff]:
    base = data_dir or resolve_data_dir()
    live_path = mirror_path_for(run_id, data_dir=base)
    if not live_path.is_file():
        raise FileNotFoundError(f"state mirror not found: {live_path}")
    tmp_path = _tmp_mirror_path(live_path, suffix=".diff.tmp")
    try:
        _project_to_path(run_id, data_dir=base, db_path=tmp_path)
        return _compare_databases(expected=tmp_path, actual=live_path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def query_mirror(run_id: str, sql: str, *, data_dir: Path | None = None) -> list[dict[str, Any]]:
    path = mirror_path_for(run_id, data_dir=data_dir)
    if not path.is_file():
        raise FileNotFoundError(f"state mirror not found: {path}")
    with closing(sqlite3.connect(_sqlite_ro_uri(path), uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql).fetchall()
    return [dict(row) for row in rows]


def load_phase_status_from_mirror(run_id: str, *, data_dir: Path | None = None) -> dict[str, Any] | None:
    """Best-effort phase-status view from a fresh mirror.

    Stale or corrupt mirrors raise sqlite errors or return ``None`` so callers
    can fall back to canonical JSON readers.
    """

    base = data_dir or resolve_data_dir()
    path = mirror_path_for(run_id, data_dir=base)
    if not path.is_file():
        raise FileNotFoundError(f"state mirror not found: {path}")
    _assert_sources_current(path)
    with closing(sqlite3.connect(_sqlite_ro_uri(path), uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        run_row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if run_row is None:
            return None
        phase_rows = conn.execute(
            "SELECT * FROM phases WHERE run_id = ? ORDER BY phase_index, phase_id",
            (run_id,),
        ).fetchall()
        attempt_rows = conn.execute(
            "SELECT * FROM phase_attempts WHERE run_id = ? ORDER BY phase_id, attempt",
            (run_id,),
        ).fetchall()
    attempts_by_phase: dict[str, list[dict[str, Any]]] = {}
    for row in attempt_rows:
        item = dict(row)
        attempts_by_phase.setdefault(str(item["phase_id"]), []).append(_attempt_history_from_row(item))
    phases = [_phase_status_row(dict(row), attempts_by_phase.get(str(row["phase_id"]), [])) for row in phase_rows]
    next_phase = next((phase for phase in phases if phase.get("status") == "pending" and _deps_complete(phases, phase)), None)
    active = next((phase for phase in phases if phase.get("status") in {"leased", "running"}), None)
    retry_waiting = next((phase for phase in phases if phase.get("status") == "retry_waiting"), None)
    blocked = next((phase for phase in phases if phase.get("status") in {"blocked", "needs_input"}), None)
    retry_exhausted = next((phase for phase in phases if phase.get("status") == "retry_exhausted"), None)
    stale = next((phase for phase in phases if phase.get("status") == "stale"), None)
    failed = next((phase for phase in phases if phase.get("status") == "failed"), None)
    if phases and all(phase.get("status") == "complete" for phase in phases):
        overall = "complete"
        recommended = None
    elif active is not None:
        overall = str(active["status"])
        recommended = f"bin/swarm phases status {run_id}"
    elif retry_waiting is not None:
        overall = "retry_waiting"
        recommended = f"bin/swarm phases recover {run_id}"
    elif blocked is not None:
        overall = str(blocked["status"])
        recommended = f"bin/swarm phases status {run_id}"
    elif retry_exhausted is not None:
        overall = "retry_exhausted"
        recommended = f"bin/swarm phases status {run_id}"
    elif stale is not None:
        overall = "stale"
        recommended = f"bin/swarm phases recover {run_id}"
    elif failed is not None:
        overall = "failed"
        recommended = f"bin/swarm phases status {run_id}"
    elif next_phase is not None:
        overall = "ready"
        recommended = f"bin/swarm do --prepared {run_id} --phase-sessions auto"
    else:
        overall = "waiting" if phases else str(run_row["status"])
        recommended = f"bin/swarm phases status {run_id}" if phases else None
    return {
        "run_id": run_id,
        "status": overall,
        "state_path": str(base / "runs" / run_id / "phase_sessions.v1.json"),
        "prepared_artifact_path": run_row["prepared_artifact_path"],
        "prepared_plan_sha": run_row["prepared_plan_sha"],
        "updated_at": run_row["updated_at"],
        "retry_policy": _json_mapping_or_none(run_row["retry_policy_json"]),
        "next_phase": next_phase,
        "active_phase": active,
        "phases": phases,
        "dependency_status": _dependency_status(phases, next_phase) if overall == "waiting" else [],
        "recommended_command": recommended,
    }


def _project_to_path(run_id: str, *, data_dir: Path, db_path: Path) -> ProjectionResult:
    projected_at = utc_now()
    warnings: list[ProjectionWarning] = []
    sources: list[_Source] = []
    source_payloads: dict[str, dict[str, Any] | None] = {}
    run_dir = data_dir / "runs" / run_id

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(schema_sql())
        conn.execute("BEGIN")
        for source in _read_sources(run_id, data_dir=data_dir, run_dir=run_dir, warnings=warnings):
            sources.append(source)
            source_payloads[source.kind] = source.payload
        run_row = _run_row(run_id, source_payloads, data_dir=data_dir, projected_at=projected_at)
        conn.execute(
            """
            INSERT INTO runs (
              run_id, schema_version, bd_epic_id, status, prepared_artifact_path,
              prepared_plan_path, prepared_plan_sha, prepared_inspect_path,
              retry_policy_json, integration_branch_head, active_phase_id,
              active_phase_index, active_attempt, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            run_row,
        )
        _insert_artifact_sources(conn, run_id, sources, read_at=projected_at)
        phase_state = source_payloads.get("phase_sessions")
        phases = _phase_rows(run_id, phase_state)
        conn.executemany(
            """
            INSERT INTO phases (
              run_id, phase_id, phase_index, title, status, depends_on_phase_ids,
              attempt, session_name, lease_owner, lease_host, lease_pid,
              lease_command, lease_expires_at, started_at, completed_at,
              result_path, handoff_path, last_error, last_failure_kind,
              payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            phases,
        )
        attempt_rows = _phase_attempt_rows(run_id, phase_state, data_dir=data_dir, run_dir=run_dir, warnings=warnings)
        conn.executemany(
            """
            INSERT INTO phase_attempts (
              run_id, phase_id, attempt, generated_at, session_name, launcher,
              status, launch_dir, evidence_path, command_path, prompt_path,
              source_prompt_path, stdout_path, stderr_path, result_path,
              handoff_path, prompt_sha, source_prompt_sha, settings_sha,
              parent_pid, child_pid, process_group_id, returncode, started_at,
              completed_at, elapsed_seconds, failure_kind, failure_details_json,
              recovery_json, metrics_json, partial_artifacts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            attempt_rows,
        )
        event_rows = list(_event_rows(run_id, data_dir=data_dir, warnings=warnings))
        conn.executemany(
            """
            INSERT INTO events (
              run_id, event_seq, timestamp, event_type, bd_epic_id, phase_id,
              work_unit_id, child_bead_ids_json, reason, retry_count,
              handoff_count, integration_branch_head, details_json, schema_ok,
              payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            event_rows,
        )
        _insert_warnings(conn, run_id, warnings)
        combined = _combined_source_sha(sources)
        for key, value in {
            "schema_version": str(PROJECTOR_SCHEMA_VERSION),
            "sqlite_version": sqlite3.sqlite_version,
            "projected_at": projected_at,
            "json_source_sha_combined": combined,
        }.items():
            conn.execute("INSERT INTO projector_meta (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
        row_counts = _row_counts(conn)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return ProjectionResult(
        run_id=run_id,
        mirror_path=str(db_path),
        projected_at=projected_at,
        schema_version=PROJECTOR_SCHEMA_VERSION,
        source_count=len(sources),
        warning_count=len(warnings),
        row_counts=row_counts,
    )


def _read_sources(
    run_id: str,
    *,
    data_dir: Path,
    run_dir: Path,
    warnings: list[ProjectionWarning],
) -> Iterator[_Source]:
    active = _read_source("active_run", active_run_path(data_dir), warnings=warnings, optional=True)
    if active is not None and active.payload is not None and active.payload.get("run_id") != run_id:
        warnings.append(ProjectionWarning("missing_optional", str(active.path), f"active run points at {active.payload.get('run_id')}, not {run_id}"))
    elif active is not None:
        yield active

    for kind, path, optional in (
        ("checkpoint", checkpoint_path(data_dir, run_id), True),
        ("prepared_plan", run_dir / "prepared_plan.v1.json", True),
        ("phase_sessions", run_dir / "phase_sessions.v1.json", True),
    ):
        source = _read_source(kind, path, warnings=warnings, optional=optional)
        if source is not None:
            yield source

    phase_state = _read_json_if_known("phase_sessions", run_dir / "phase_sessions.v1.json", warnings)
    phase_ids = _phase_ids(phase_state)
    for phase_id in phase_ids:
        candidates = [
            run_dir / "phases" / phase_id / "stage_sessions.v1.json",
            run_dir / "stage-sessions" / f"{phase_id}.json",
        ]
        source = next((_read_source("stage_sessions", path, warnings=warnings, optional=True) for path in candidates if path.is_file()), None)
        if source is not None:
            yield source
        else:
            warnings.append(ProjectionWarning("missing_optional", str(candidates[0]), "stage-session state not present"))

    for evidence_path in sorted((run_dir / "phase_launches").glob("*/attempt-*/evidence.json")):
        source = _read_source("evidence", evidence_path, warnings=warnings, optional=True)
        if source is not None:
            yield source

    for path in (
        data_dir / "worktrees" / run_id / "manifest.json",
        data_dir / "worktrees" / run_id / "integration" / "manifest.json",
    ):
        source = _read_source("worktree_manifest", path, warnings=warnings, optional=True, validate_schema=False)
        if source is not None:
            yield source

    events_path = data_dir / "telemetry" / "run_events.jsonl"
    if events_path.is_file():
        yield _source_from_bytes("run_events", events_path, payload=None)
    else:
        warnings.append(ProjectionWarning("missing_optional", str(events_path), "run_events.jsonl not present"))


def _read_source(
    kind: str,
    path: Path,
    *,
    warnings: list[ProjectionWarning],
    optional: bool,
    validate_schema: bool = True,
) -> _Source | None:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        if optional:
            warnings.append(ProjectionWarning("missing_optional", str(path), "source not present"))
            return None
        raise
    except OSError as exc:
        warnings.append(ProjectionWarning("unparseable", str(path), str(exc)))
        return None
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        warnings.append(ProjectionWarning("unparseable", str(path), str(exc)))
        return _source_from_bytes(kind, path, payload=None, raw=raw)
    if not isinstance(value, dict):
        warnings.append(ProjectionWarning("unparseable", str(path), "source root must be an object"))
        return _source_from_bytes(kind, path, payload=None, raw=raw)
    if validate_schema and not _schema_known(kind, value, path, warnings):
        return _source_from_bytes(kind, path, payload=None, raw=raw)
    return _source_from_bytes(kind, path, payload=value, raw=raw)


def _read_json_if_known(kind: str, path: Path, warnings: list[ProjectionWarning]) -> dict[str, Any] | None:
    source = _read_source(kind, path, warnings=warnings, optional=True)
    return source.payload if source is not None else None


def _source_from_bytes(kind: str, path: Path, *, payload: dict[str, Any] | None, raw: bytes | None = None) -> _Source:
    data = raw if raw is not None else path.read_bytes()
    stat = path.stat()
    return _Source(
        kind=kind,
        path=path,
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        mtime_ns=int(stat.st_mtime_ns),
        payload=payload,
    )


def _schema_known(kind: str, value: Mapping[str, Any], path: Path, warnings: list[ProjectionWarning]) -> bool:
    supported = SUPPORTED_SCHEMA_VERSIONS.get(kind)
    if supported is None:
        return True
    version = value.get("schema_version")
    if version in supported:
        return True
    warnings.append(
        ProjectionWarning(
            "unknown_schema_version",
            str(path),
            f"{kind} schema_version {version!r} is not supported",
            {"supported": sorted(supported)},
        )
    )
    return False


def _run_row(
    run_id: str,
    payloads: Mapping[str, dict[str, Any] | None],
    *,
    data_dir: Path,
    projected_at: str,
) -> tuple[Any, ...]:
    active = payloads.get("active_run") or {}
    checkpoint = payloads.get("checkpoint") or {}
    phase_state = payloads.get("phase_sessions") or {}
    prepared = payloads.get("prepared_plan") or {}
    phases = [phase for phase in phase_state.get("phases") or [] if isinstance(phase, Mapping)]
    status = (
        _string_or_none(active.get("status"))
        or _string_or_none(checkpoint.get("status"))
        or _phase_overall_status(phases)
        or _string_or_none(prepared.get("status"))
        or "incomplete"
    )
    active_phase = next((phase for phase in phases if phase.get("status") in {"leased", "running"}), None)
    prepared_path = data_dir / "runs" / run_id / "prepared_plan.v1.json"
    prepared_plan_path = _string_or_none(active.get("prepared_plan_path") or checkpoint.get("prepared_plan_path"))
    if prepared_plan_path is None and prepared_path.is_file():
        prepared_plan_path = str(prepared_path)
    prepared_sha = (
        _sha_or_none(active.get("prepared_plan_sha"))
        or _sha_or_none(checkpoint.get("prepared_plan_sha"))
        or _sha_or_none(phase_state.get("prepared_plan_sha"))
        or _sha_file_or_none(prepared_path)
    )
    return (
        run_id,
        int(active.get("schema_version") or checkpoint.get("schema_version") or phase_state.get("schema_version") or 1),
        _string_or_none(active.get("bd_epic_id") or checkpoint.get("bd_epic_id")),
        status,
        _string_or_none(active.get("prepared_artifact_path") or checkpoint.get("prepared_artifact_path") or phase_state.get("prepared_artifact_path")),
        prepared_plan_path,
        prepared_sha,
        _string_or_none(active.get("prepared_inspect_path") or checkpoint.get("prepared_inspect_path")),
        _json_or_none(_normalized_retry_policy_for_status(phase_state)),
        _sha40_or_none(active.get("integration_branch_head") or checkpoint.get("integration_branch_head")),
        _string_or_none((active_phase or {}).get("phase_id") or active.get("phase_id") or checkpoint.get("phase_id")),
        _int_or_none((active_phase or {}).get("phase_index") or active.get("phase_session_phase_index") or checkpoint.get("phase_session_phase_index")),
        _int_or_none((active_phase or {}).get("attempt") or active.get("phase_session_attempt") or checkpoint.get("phase_session_attempt")),
        _string_or_none(active.get("updated_at") or checkpoint.get("written_at") or phase_state.get("updated_at")) or "1970-01-01T00:00:00Z",
    )


def _phase_rows(run_id: str, phase_state: Mapping[str, Any] | None) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    if not isinstance(phase_state, Mapping):
        return rows
    for index, phase in enumerate(phase_state.get("phases") or []):
        if not isinstance(phase, Mapping):
            continue
        phase_id = str(phase.get("phase_id") or "")
        if not phase_id:
            continue
        rows.append(
            (
                run_id,
                phase_id,
                _int_or_none(phase.get("phase_index")) if _int_or_none(phase.get("phase_index")) is not None else index,
                str(phase.get("title") or phase_id),
                str(phase.get("status") or "pending"),
                json.dumps(_string_list(phase.get("depends_on_phase_ids")), sort_keys=True),
                int(phase.get("attempt") or 0),
                _string_or_none(phase.get("session_name")),
                _string_or_none(phase.get("lease_owner")),
                _string_or_none(phase.get("lease_host")),
                _int_or_none(phase.get("lease_pid")),
                _string_or_none(phase.get("lease_command")),
                _string_or_none(phase.get("lease_expires_at")),
                _string_or_none(phase.get("started_at")),
                _string_or_none(phase.get("completed_at")),
                _string_or_none(phase.get("result_path")),
                _string_or_none(phase.get("handoff_path")),
                _string_or_none(phase.get("last_error")),
                _string_or_none(phase.get("last_failure_kind")),
                json.dumps(dict(phase), sort_keys=True, separators=(",", ":")),
            )
        )
    return rows


def _phase_attempt_rows(
    run_id: str,
    phase_state: Mapping[str, Any] | None,
    *,
    data_dir: Path,
    run_dir: Path,
    warnings: list[ProjectionWarning],
) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    if not isinstance(phase_state, Mapping):
        return rows
    for phase in phase_state.get("phases") or []:
        if not isinstance(phase, Mapping):
            continue
        phase_id = str(phase.get("phase_id") or "")
        records = [item for item in phase.get("attempt_history") or [] if isinstance(item, Mapping)]
        attempt = _int_or_none(phase.get("attempt")) or 0
        if attempt > 0 and not any((_int_or_none(item.get("attempt")) or 0) == attempt for item in records):
            records.append(phase)
        for record in records:
            attempt_no = _int_or_none(record.get("attempt") or phase.get("attempt")) or 0
            if attempt_no <= 0:
                continue
            rows.append(_phase_attempt_row(run_id, phase_id, attempt_no, phase, record, data_dir=data_dir, run_dir=run_dir, warnings=warnings))
    return rows


def _phase_attempt_row(
    run_id: str,
    phase_id: str,
    attempt: int,
    phase: Mapping[str, Any],
    record: Mapping[str, Any],
    *,
    data_dir: Path,
    run_dir: Path,
    warnings: list[ProjectionWarning],
) -> tuple[Any, ...]:
    launch_dir = _path_from_value(record.get("launch_dir") or phase.get("launch_dir"), data_dir=data_dir)
    if launch_dir is None:
        launch_dir = run_dir / "phase_launches" / phase_id / f"attempt-{attempt}"
    evidence_path = _path_from_value(record.get("evidence_path") or phase.get("evidence_path"), data_dir=data_dir)
    if evidence_path is None:
        evidence_path = launch_dir / "evidence.json"
    evidence = _read_source("evidence", evidence_path, warnings=warnings, optional=True)
    manifest = evidence.payload if evidence is not None and evidence.payload is not None else {}
    paths = manifest.get("paths") if isinstance(manifest.get("paths"), Mapping) else {}
    hashes = manifest.get("hashes") if isinstance(manifest.get("hashes"), Mapping) else {}
    process = manifest.get("process") if isinstance(manifest.get("process"), Mapping) else {}
    failure = manifest.get("failure") if isinstance(manifest.get("failure"), Mapping) else {}
    recovery = manifest.get("recovery") if isinstance(manifest.get("recovery"), Mapping) else {}
    metrics = manifest.get("metrics") if isinstance(manifest.get("metrics"), Mapping) else {}
    artifacts = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), Mapping) else {}
    return (
        run_id,
        phase_id,
        attempt,
        _string_or_none(manifest.get("generated_at")) or _string_or_none(record.get("completed_at") or phase.get("completed_at")) or utc_now(),
        _string_or_none(manifest.get("session_name") or record.get("session_name") or phase.get("session_name")),
        _string_or_none(manifest.get("launcher") or record.get("launcher")),
        _string_or_none(manifest.get("status") or record.get("status") or phase.get("status")) or "unknown",
        _string_or_none(paths.get("launch_dir")) or str(launch_dir),
        _string_or_none(paths.get("evidence_path")) or str(evidence_path),
        _string_or_none(paths.get("command_path") or record.get("command_path") or phase.get("command_path")),
        _string_or_none(paths.get("prompt_path")),
        _string_or_none(paths.get("source_prompt_path")),
        _string_or_none(paths.get("stdout_path")),
        _string_or_none(paths.get("stderr_path")),
        _string_or_none(paths.get("result_path") or record.get("result_path") or phase.get("result_path")),
        _string_or_none(paths.get("handoff_path") or record.get("handoff_path") or phase.get("handoff_path")),
        _sha_or_none(hashes.get("prompt_sha") or record.get("prompt_sha")),
        _sha_or_none(hashes.get("source_prompt_sha")),
        _sha_or_none(hashes.get("settings_sha")),
        _int_or_none(process.get("parent_pid") or record.get("parent_pid") or phase.get("parent_pid")),
        _int_or_none(process.get("child_pid") or record.get("child_pid") or phase.get("child_pid")),
        _int_or_none(process.get("process_group_id") or record.get("process_group_id") or phase.get("process_group_id")),
        _int_or_none(process.get("returncode") if process.get("returncode") is not None else record.get("returncode")),
        _string_or_none(process.get("started_at") or record.get("started_at") or phase.get("started_at")),
        _string_or_none(process.get("completed_at") or record.get("completed_at") or phase.get("completed_at")),
        _float_or_none(process.get("elapsed_seconds") if process.get("elapsed_seconds") is not None else record.get("elapsed_seconds")),
        _string_or_none(failure.get("failure_kind") or record.get("failure_kind") or phase.get("last_failure_kind")),
        _json_or_none(failure),
        _json_or_none(recovery),
        _json_or_none(metrics),
        1 if bool(artifacts.get("partial_artifacts") or record.get("partial_artifacts")) else 0,
    )


def _event_rows(run_id: str, *, data_dir: Path, warnings: list[ProjectionWarning]) -> Iterator[tuple[Any, ...]]:
    path = data_dir / "telemetry" / "run_events.jsonl"
    if not path.is_file():
        return
    schema = load_schema("run_events")
    event_seq = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, 1):
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                warnings.append(ProjectionWarning("unparseable", f"{path}:{line_no}", str(exc)))
                continue
            if not isinstance(payload, dict):
                warnings.append(ProjectionWarning("unparseable", f"{path}:{line_no}", "run event row must be an object"))
                continue
            if payload.get("run_id") != run_id:
                continue
            errors = validate_value(payload, schema)
            schema_ok = not errors
            if errors:
                warnings.append(ProjectionWarning("unsupported_event_type", f"{path}:{line_no}", "; ".join(errors)))
            yield (
                run_id,
                event_seq,
                _string_or_none(payload.get("timestamp")) or "",
                _string_or_none(payload.get("event_type") or payload.get("kind")) or "unknown",
                _string_or_none(payload.get("bd_epic_id")),
                _string_or_none(payload.get("phase_id")),
                _string_or_none(payload.get("work_unit_id")),
                _json_or_none(payload.get("child_bead_ids")),
                _string_or_none(payload.get("reason")),
                _int_or_none(payload.get("retry_count")),
                _int_or_none(payload.get("handoff_count")),
                _sha40_or_none(payload.get("integration_branch_head")),
                _json_or_none(payload.get("details")),
                1 if schema_ok and payload.get("schema_ok", True) is not False else 0,
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
            )
            event_seq += 1


def _insert_artifact_sources(conn: sqlite3.Connection, run_id: str, sources: Sequence[_Source], *, read_at: str) -> None:
    conn.executemany(
        """
        INSERT INTO artifact_sources (
          run_id, kind, path, sha256, size_bytes, mtime_ns, read_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (run_id, source.kind, str(source.path), source.sha256, source.size_bytes, source.mtime_ns, read_at)
            for source in sources
        ],
    )


def _insert_warnings(conn: sqlite3.Connection, run_id: str, warnings: Sequence[ProjectionWarning]) -> None:
    conn.executemany(
        """
        INSERT INTO projection_warnings (
          run_id, warn_seq, kind, source, message, details_json
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                run_id,
                index,
                warning.kind,
                warning.source,
                warning.message,
                _json_or_none(warning.details),
            )
            for index, warning in enumerate(warnings)
        ],
    )


def _check_database(path: Path) -> None:
    with closing(sqlite3.connect(_sqlite_ro_uri(path), uri=True)) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise ProjectionError(f"sqlite integrity_check failed: {integrity[0] if integrity else 'no result'}")
        fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk_rows:
            raise ProjectionError(f"sqlite foreign_key_check failed: {fk_rows!r}")


def _compare_databases(*, expected: Path, actual: Path) -> list[MirrorDiff]:
    with (
        closing(sqlite3.connect(_sqlite_ro_uri(expected), uri=True)) as exp,
        closing(sqlite3.connect(_sqlite_ro_uri(actual), uri=True)) as act,
    ):
        exp.row_factory = sqlite3.Row
        act.row_factory = sqlite3.Row
        tables = [row[0] for row in exp.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        for table in tables:
            exp_rows = _normalized_table_rows(exp, table)
            act_rows = _normalized_table_rows(act, table)
            if exp_rows == act_rows:
                continue
            return [_first_table_diff(table, exp_rows, act_rows)]
    return []


def _normalized_table_rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
    selected = [column for column in columns if (table, column) not in _NONDETERMINISTIC_COLUMNS]
    sql = f"SELECT {', '.join(selected)} FROM {table} ORDER BY {', '.join(selected)}"
    rows = [dict(row) for row in conn.execute(sql)]
    if table == "projector_meta":
        rows = [row for row in rows if row.get("key") != "projected_at"]
    return rows


def _first_table_diff(table: str, expected: list[dict[str, Any]], actual: list[dict[str, Any]]) -> MirrorDiff:
    max_len = max(len(expected), len(actual))
    for index in range(max_len):
        if index >= len(expected):
            return MirrorDiff(table, f"row[{index}]", "<row>", None, actual[index])
        if index >= len(actual):
            return MirrorDiff(table, f"row[{index}]", "<row>", expected[index], None)
        exp = expected[index]
        act = actual[index]
        if exp == act:
            continue
        for column in sorted(set(exp) | set(act)):
            if exp.get(column) != act.get(column):
                return MirrorDiff(table, _primary_key(table, exp, act, index), column, exp.get(column), act.get(column))
    return MirrorDiff(table, "<unknown>", "<unknown>", expected, actual)


def _primary_key(table: str, expected: Mapping[str, Any], actual: Mapping[str, Any], index: int) -> str:
    row = expected or actual
    keys = {
        "runs": ("run_id",),
        "phases": ("run_id", "phase_id"),
        "phase_attempts": ("run_id", "phase_id", "attempt"),
        "events": ("run_id", "event_seq"),
        "artifact_sources": ("run_id", "kind", "path"),
        "projection_warnings": ("run_id", "warn_seq"),
        "projector_meta": ("key",),
    }.get(table)
    if not keys:
        return f"row[{index}]"
    return "|".join(str(row.get(key)) for key in keys)


def _assert_sources_current(mirror_path: Path) -> None:
    with closing(sqlite3.connect(_sqlite_ro_uri(mirror_path), uri=True)) as conn:
        rows = conn.execute("SELECT path, sha256, size_bytes, mtime_ns FROM artifact_sources").fetchall()
    for path_text, sha, size, mtime in rows:
        path = Path(str(path_text))
        try:
            raw = path.read_bytes()
            stat = path.stat()
        except OSError as exc:
            raise sqlite3.DatabaseError(f"mirror source is no longer readable: {path}") from exc
        if hashlib.sha256(raw).hexdigest() != sha or len(raw) != size or int(stat.st_mtime_ns) != int(mtime):
            raise sqlite3.DatabaseError(f"mirror source is stale: {path}")


def _row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    return {table: int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]) for table in tables}


@contextmanager
def _projector_lock(run_dir: Path) -> Iterator[None]:
    if fcntl is None:
        raise ProjectionError("state projector locks require fcntl")
    lock_path = run_dir / ".projector.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _tmp_mirror_path(mirror_path: Path, *, suffix: str = ".tmp") -> Path:
    stamp = f"{os.getpid()}.{time.time_ns()}"
    return mirror_path.parent / f".{mirror_path.name}.{stamp}{suffix}"


def _sqlite_ro_uri(path: Path) -> str:
    return path.resolve(strict=False).as_uri() + "?mode=ro"


def _fsync_file(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _combined_source_sha(sources: Sequence[_Source]) -> str:
    digest = hashlib.sha256()
    for source in sorted(sources, key=lambda item: (item.kind, str(item.path))):
        digest.update(source.kind.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(source.path).encode("utf-8"))
        digest.update(b"\0")
        digest.update(source.sha256.encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _phase_overall_status(phases: Sequence[Mapping[str, Any]]) -> str | None:
    if not phases:
        return None
    statuses = {str(phase.get("status") or "") for phase in phases}
    if statuses == {"complete"}:
        return "complete"
    for status in ("running", "leased", "retry_waiting", "blocked", "needs_input", "retry_exhausted", "stale", "failed"):
        if status in statuses:
            return status
    return "ready" if "pending" in statuses else "incomplete"


def _phase_ids(phase_state: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(phase_state, Mapping):
        return []
    return [
        str(phase.get("phase_id"))
        for phase in phase_state.get("phases") or []
        if isinstance(phase, Mapping) and phase.get("phase_id")
    ]


def _normalized_retry_policy_for_status(phase_state: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(phase_state, Mapping):
        return None
    retry_policy = phase_state.get("retry_policy") if isinstance(phase_state.get("retry_policy"), Mapping) else None
    return normalize_retry_policy(retry_policy)


def _phase_status_row(row: Mapping[str, Any], attempts: list[dict[str, Any]]) -> dict[str, Any]:
    payload = _json_mapping(row.get("payload_json"))
    if payload:
        summary = {key: payload.get(key) for key in _PHASE_STATUS_KEYS}
        if not isinstance(summary.get("attempt_history"), list):
            summary["attempt_history"] = []
        return summary
    return {key: _phase_status_fallback_value(row, key, attempts) for key in _PHASE_STATUS_KEYS}


def _phase_status_fallback_value(row: Mapping[str, Any], key: str, attempts: list[dict[str, Any]]) -> Any:
    if key == "depends_on_phase_ids":
        return _json_list(row.get("depends_on_phase_ids"))
    if key == "attempt_history":
        return attempts
    return row.get(key)


def _attempt_history_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    failure = _json_mapping(row.get("failure_details_json"))
    return {
        "attempt": row.get("attempt"),
        "launcher": row.get("launcher"),
        "started_at": row.get("started_at"),
        "completed_at": row.get("completed_at"),
        "launch_dir": row.get("launch_dir"),
        "result_path": row.get("result_path"),
        "handoff_path": row.get("handoff_path"),
        "failure_kind": row.get("failure_kind"),
        "retry_decision": failure.get("retry_decision"),
        "evidence_path": row.get("evidence_path"),
    }


def _deps_complete(phases: Sequence[Mapping[str, Any]], phase: Mapping[str, Any]) -> bool:
    by_id = {item.get("phase_id"): item for item in phases}
    return all(by_id.get(dep, {}).get("status") == "complete" for dep in phase.get("depends_on_phase_ids") or [])


def _dependency_status(phases: Sequence[Mapping[str, Any]], next_phase: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    phase = next_phase
    if phase is None:
        phase = next((item for item in phases if item.get("status") == "pending"), None)
    if phase is None:
        return []
    by_id = {item.get("phase_id"): item for item in phases}
    rows: list[dict[str, Any]] = []
    for dep in phase.get("depends_on_phase_ids") or []:
        dep_phase = by_id.get(dep)
        rows.append({"phase_id": dep, "status": dep_phase.get("status") if isinstance(dep_phase, Mapping) else "missing"})
    return rows


def _path_from_value(value: Any, *, data_dir: Path) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    candidates = (data_dir / value, path)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return path


def _json_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _json_list(value: Any) -> list[str]:
    try:
        parsed = json.loads(str(value))
    except Exception:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _json_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _json_mapping_or_none(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return dict(parsed) if isinstance(parsed, Mapping) else None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value != "" else None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _sha_or_none(value: Any) -> str | None:
    if isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value):
        return value
    return None


def _sha_file_or_none(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _sha40_or_none(value: Any) -> str | None:
    if isinstance(value, str) and len(value) == 40 and all(ch in "0123456789abcdef" for ch in value):
        return value
    return None


__all__ = [
    "MIRROR_FILENAME",
    "MirrorDiff",
    "ProjectionError",
    "ProjectionResult",
    "ProjectionWarning",
    "diff_mirror",
    "load_phase_status_from_mirror",
    "mirror_path_for",
    "project_run",
    "query_mirror",
    "schema_sql",
]
