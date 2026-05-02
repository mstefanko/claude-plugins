"""Structural protocols for durable pipeline state ownership.

This module is intentionally dependency-light: owner modules import these
Protocols, but this module does not import owner modules back.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol


class RunStateTxn(Protocol):
    """Minimal transaction shape for future state-store backends."""

    def __enter__(self) -> "RunStateTxn": ...

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool | None: ...


class RunStateStore(Protocol):
    """Storage seam for run-state mutation backends."""

    def load(self, run_id: str) -> dict[str, Any]: ...

    def begin(self) -> AbstractContextManager[RunStateTxn]: ...


class PreparedArtifactStore(Protocol):
    """Small interface for prepared dispatch artifact mutations."""

    def load(self, run_id: str) -> dict[str, Any]: ...

    def refresh_base(self, run_id: str, **kwargs: Any) -> Any: ...


class PhaseSessionStore(Protocol):
    """Small interface for phase-session state mutations and path lookup."""

    def init(
        self,
        run_id: str,
        *,
        mode: str = "cli-pump",
        policy_update: Any | None = None,
    ) -> dict[str, Any]: ...

    def record_result(self, run_id: str, phase_id: str, *, json_file: Path, expected_status: str | None = None) -> dict[str, Any]: ...

    def state_path(self, run_id: str) -> Path: ...

    def result_path(self, run_id: str, phase_id: str, attempt: int) -> Path: ...

    def handoff_path(self, run_id: str, phase_id: str, attempt: int) -> Path: ...

    def lock(self, run_id: str, *, timeout_seconds: float = 10.0) -> AbstractContextManager[None]: ...


class WorktreeStateStore(Protocol):
    """Small interface for run execution worktree state."""

    def resolve(self, run_id: str, *, source_project_root: Path, prepared_plan: Mapping[str, Any]) -> Any: ...

    def materialize(self, run_id: str, *, source_project_root: Path, prepared_plan: Mapping[str, Any]) -> Any: ...

    def commit_stage_artifacts(
        self,
        resolved: Any,
        *,
        allowed_files: Iterable[str],
        run_artifact_excludes: Iterable[str],
        commit_subject: str,
        writer_summary: str,
        stage_id: str,
    ) -> Any: ...

    def adopt(self, run_id: str, *, apply: bool = False) -> dict[str, Any]: ...

    def integrate(self, run_id: str, *, apply: bool = False) -> dict[str, Any]: ...


class RunEventSink(Protocol):
    """Append-only event sink for run telemetry rows."""

    def append(self, row: Mapping[str, Any]) -> Path: ...

    def validate(self, row: Mapping[str, Any]) -> None: ...


__all__ = [
    "PhaseSessionStore",
    "PreparedArtifactStore",
    "RunEventSink",
    "RunStateStore",
    "RunStateTxn",
    "WorktreeStateStore",
]
