"""Thin owner-facing wrapper for phase-session state.

The durable JSON shape and mutation rules stay in ``phase_sessions.py``. This
module gives newer runtime code a small seam to depend on without learning the
private state-machine helpers.
"""

from __future__ import annotations

import os
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Mapping

from . import phase_sessions as _phase_sessions
from .policies import ResolvedPolicyUpdate


PhaseArtifactContractError = _phase_sessions.PhaseArtifactContractError
PhaseSessionError = _phase_sessions.PhaseSessionError
PhaseSessionLockTimeout = _phase_sessions.PhaseSessionLockTimeout


def init_phase_sessions(
    run_id: str,
    *,
    data_dir: Path | None = None,
    repo_root: Path | None = None,
    mode: str = "cli-pump",
    policy_update: ResolvedPolicyUpdate | None = None,
) -> dict[str, Any]:
    return _phase_sessions.init_phase_sessions(
        run_id,
        data_dir=data_dir,
        repo_root=repo_root,
        mode=mode,
        policy_update=policy_update,
    )


def load_phase_sessions(run_id: str, *, data_dir: Path | None = None) -> dict[str, Any]:
    return _phase_sessions.load_phase_sessions(run_id, data_dir=data_dir)


def record_phase_result(
    run_id: str,
    phase_id: str,
    *,
    json_file: str | os.PathLike[str],
    expected_status: str | None = None,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    return _phase_sessions.record_phase_result(
        run_id,
        phase_id,
        json_file=json_file,
        expected_status=expected_status,
        data_dir=data_dir,
    )


def abandon_attempt_and_retry(
    run_id: str,
    phase_id: str,
    *,
    failure_kind: str,
    data_dir: Path | None = None,
    launcher_error: str | None = None,
    next_retry_at: str | None = None,
    retry_after_seconds: int | None = None,
    attempt_record: Mapping[str, Any] | None = None,
    assume_locked: bool = False,
) -> dict[str, Any]:
    return _phase_sessions.abandon_attempt_and_retry(
        run_id,
        phase_id,
        failure_kind=failure_kind,
        data_dir=data_dir,
        launcher_error=launcher_error,
        next_retry_at=next_retry_at,
        retry_after_seconds=retry_after_seconds,
        attempt_record=attempt_record,
        assume_locked=assume_locked,
    )


def phase_session_path(run_id: str, *, data_dir: Path | None = None) -> Path:
    return _phase_sessions.phase_session_path(run_id, data_dir=data_dir)


def phase_session_lock_path(run_id: str, *, data_dir: Path | None = None) -> Path:
    return _phase_sessions.phase_session_lock_path(run_id, data_dir=data_dir)


def phase_result_path(
    run_id: str,
    phase_id: str,
    attempt: int,
    *,
    data_dir: Path | None = None,
) -> Path:
    return _phase_sessions.phase_result_path(run_id, phase_id, attempt, data_dir=data_dir)


def phase_handoff_path(
    run_id: str,
    phase_id: str,
    attempt: int,
    *,
    data_dir: Path | None = None,
) -> Path:
    return _phase_sessions.phase_handoff_path(run_id, phase_id, attempt, data_dir=data_dir)


def locked_phase_sessions(
    run_id: str,
    *,
    data_dir: Path | None = None,
    timeout_seconds: float = 10.0,
) -> AbstractContextManager[None]:
    return _phase_sessions.locked_phase_sessions(
        run_id,
        data_dir=data_dir,
        timeout_seconds=timeout_seconds,
    )


class JsonPhaseSessionStore:
    """Path-bound adapter over the existing phase-session owner module."""

    def __init__(self, *, data_dir: Path | None = None, repo_root: Path | None = None) -> None:
        self.data_dir = Path(data_dir) if data_dir is not None else None
        self.repo_root = Path(repo_root) if repo_root is not None else None

    def init(
        self,
        run_id: str,
        *,
        mode: str = "cli-pump",
        policy_update: ResolvedPolicyUpdate | None = None,
    ) -> dict[str, Any]:
        return init_phase_sessions(
            run_id,
            data_dir=self.data_dir,
            repo_root=self.repo_root,
            mode=mode,
            policy_update=policy_update,
        )

    def record_result(
        self,
        run_id: str,
        phase_id: str,
        *,
        json_file: Path,
        expected_status: str | None = None,
    ) -> dict[str, Any]:
        return record_phase_result(
            run_id,
            phase_id,
            json_file=json_file,
            expected_status=expected_status,
            data_dir=self.data_dir,
        )

    def state_path(self, run_id: str) -> Path:
        return phase_session_path(run_id, data_dir=self.data_dir)

    def result_path(self, run_id: str, phase_id: str, attempt: int) -> Path:
        return phase_result_path(run_id, phase_id, attempt, data_dir=self.data_dir)

    def handoff_path(self, run_id: str, phase_id: str, attempt: int) -> Path:
        return phase_handoff_path(run_id, phase_id, attempt, data_dir=self.data_dir)

    def lock(self, run_id: str, *, timeout_seconds: float = 10.0) -> AbstractContextManager[None]:
        return locked_phase_sessions(
            run_id,
            data_dir=self.data_dir,
            timeout_seconds=timeout_seconds,
        )


__all__ = [
    "JsonPhaseSessionStore",
    "PhaseArtifactContractError",
    "PhaseSessionError",
    "PhaseSessionLockTimeout",
    "abandon_attempt_and_retry",
    "init_phase_sessions",
    "load_phase_sessions",
    "locked_phase_sessions",
    "phase_handoff_path",
    "phase_result_path",
    "phase_session_lock_path",
    "phase_session_path",
    "record_phase_result",
]
