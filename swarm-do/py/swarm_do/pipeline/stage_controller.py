"""Live, idempotent processing for controller-owned stage markers."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping

from .execution_worktree import RunExecutionWorktreeError, commit_stage_artifacts
from .orchestrator_stream import StageMarker, parse_stage_markers
from .phase_beads import close_stage_child, mark_stage_blocked
from .phase_sessions import PhaseSessionError
from .post_writer import changed_files_from_worktree_diff
from .run_state import append_run_event, utc_now, validate_run_event
from .stage_invocation import StageInvocation
from .stage_sessions import (
    STATUS_ADOPTED,
    TERMINAL_STATUSES,
    claim_stage,
    load_stage_sessions,
    record_stage_adopted,
    record_stage_blocked,
    record_stage_failed,
)
from .unit_session_adopter import adopt_unit_stage


@dataclass
class MarkerDecision:
    marker: StageMarker
    outcome: Literal[
        "adopted",
        "duplicate",
        "amended",
        "pending",
        "rejected_unknown_stage",
        "rejected_invalid_path",
        "rejected_invalid_result",
        "adopted_with_concerns",
        "blocked_recorded",
        "needs_input_recorded",
        "failed_recorded",
    ]
    commit_sha: str | None = None
    reason: str | None = None


class _PendingStageResult(FileNotFoundError):
    """Raised when a marker is valid but its result file is not visible yet."""


class _InvalidStageResultPath(ValueError):
    """Raised when a marker points outside the controller stage result area."""


class StageMarkerProcessor:
    def __init__(
        self,
        *,
        run_id: str,
        phase_id: str,
        phase_attempt: int,
        stage_invocations: list[StageInvocation],
        prepared: Mapping[str, Any],
        workspace_metadata: Mapping[str, Any],
        launch_dir: Path,
        data_dir: Path,
    ) -> None:
        self.run_id = run_id
        self.phase_id = phase_id
        self.phase_attempt = int(phase_attempt)
        self.stage_invocations = list(stage_invocations)
        self.prepared = dict(prepared)
        self.workspace_metadata = dict(workspace_metadata)
        self.launch_dir = Path(launch_dir)
        self.data_dir = Path(data_dir)
        self._owner_thread = threading.current_thread()
        self._by_id = {stage.stage_id: stage for stage in self.stage_invocations}
        self._allowed_files = _phase_allowed_files(self.prepared, self.phase_id)
        self._run_excludes = _run_artifact_excludes(self.run_id, self.workspace_metadata)
        self._marker_payloads: list[dict[str, Any]] = []
        self._pending: list[tuple[StageMarker, dict[str, Any]]] = []
        self._commits: list[str] = []
        self._latest_diff: Mapping[str, Any] | None = None
        self._had_controller_failure = False
        self._duplicate_marker_count = 0
        self._amended_count = 0
        self._rejected_marker_count = 0
        self._rejected_unknown_stage = 0
        self._rejected_invalid_path = 0
        self._rejected_invalid_result = 0
        self._failed_recorded_count = 0

    def process_text(self, text: str) -> list[MarkerDecision]:
        """Parse marker lines from text and process them on the owner thread."""

        self._assert_owner_thread()
        decisions: list[MarkerDecision] = []
        decisions.extend(self._retry_pending())
        for marker in parse_stage_markers(text):
            decisions.append(self.process_marker(marker))
        return decisions

    def process_marker(self, marker: StageMarker) -> MarkerDecision:
        self._assert_owner_thread()
        payload = marker.to_dict()
        self._marker_payloads.append(payload)
        return self._process_marker(marker, payload, append_pending=True)

    def finish(self) -> dict[str, Any]:
        self._assert_owner_thread()
        self._retry_pending()
        current = self._load_current_state()
        adopted_by_id = {
            str(stage.get("stage_id")): stage
            for stage in current.get("stages") or []
            if isinstance(stage, Mapping) and stage.get("status") == STATUS_ADOPTED
        }
        expected_stage_ids = set(self._by_id)
        completed = (
            bool(expected_stage_ids)
            and expected_stage_ids.issubset(adopted_by_id)
            and not self._pending
            and not self._had_controller_failure
        )
        commits = list(dict.fromkeys([*self._commits, *_ledger_commits(adopted_by_id, self.stage_invocations)]))
        changed = changed_files_from_worktree_diff(self._latest_diff or {}) if self._latest_diff else []
        completed_work_units = _work_units_for_status(adopted_by_id, self.stage_invocations, STATUS_ADOPTED)
        failed_work_units = _failed_work_units(current, self.stage_invocations)
        return {
            "live": True,
            "completed": completed,
            "markers": self._marker_payloads,
            "commits": commits,
            "commit_sha": commits[-1] if commits else None,
            "worktree_diff": _normalized_worktree_diff(self._latest_diff) if self._latest_diff else None,
            "changed_files": changed,
            "completed_work_units": completed_work_units,
            "failed_work_units": failed_work_units,
            "pending_marker_count": len(self._pending),
            "duplicate_marker_count": self._duplicate_marker_count,
            "amended_count": self._amended_count,
            "rejected_marker_count": self._rejected_marker_count,
            "rejected_unknown_stage": self._rejected_unknown_stage,
            "rejected_invalid_path": self._rejected_invalid_path,
            "rejected_invalid_result": self._rejected_invalid_result,
            "failed_recorded_count": self._failed_recorded_count,
        }

    def _process_marker(
        self,
        marker: StageMarker,
        payload: dict[str, Any],
        *,
        append_pending: bool,
    ) -> MarkerDecision:
        invocation = self._by_id.get(marker.stage_id)
        if invocation is None:
            payload["controller_status"] = "unknown_stage_marker"
            self._reject("unknown_stage")
            return MarkerDecision(marker, "rejected_unknown_stage", reason="unknown_stage_marker")

        terminal = self._terminal_stage(marker.stage_id)
        if terminal is not None:
            amended = self._maybe_amend_terminal(marker, terminal)
            if amended:
                payload["controller_status"] = "amended"
                self._amended_count += 1
                commit_sha = _optional_str((marker.raw or {}).get("commit_sha")) or _optional_str(terminal.get("commit_sha"))
                if commit_sha:
                    self._commits.append(commit_sha)
                return MarkerDecision(marker, "amended", commit_sha=commit_sha)
            payload["controller_status"] = "duplicate"
            self._duplicate_marker_count += 1
            return MarkerDecision(marker, "duplicate", commit_sha=_optional_str(terminal.get("commit_sha")))

        if marker.kind == "failed":
            record_stage_failed(
                self.run_id,
                self.phase_id,
                marker.stage_id,
                marker.failure_kind or "stage_failed",
                marker.notes,
                data_dir=self.data_dir,
            )
            self._mark_stage_bead_blocked(marker)
            self._had_controller_failure = True
            self._failed_recorded_count += 1
            payload["controller_status"] = "failed_recorded"
            return MarkerDecision(marker, "failed_recorded", reason=marker.failure_kind or "stage_failed")

        claim_stage(self.run_id, self.phase_id, marker.stage_id, data_dir=self.data_dir)
        try:
            stage_result = self._load_valid_stage_result(marker, expected_result_path=invocation.expected_result_path)
        except _PendingStageResult as exc:
            payload["controller_status"] = "pending"
            if append_pending:
                self._pending.append((marker, payload))
            return MarkerDecision(marker, "pending", reason=str(exc))
        except _InvalidStageResultPath as exc:
            payload["controller_status"] = "stage_result_invalid"
            record_stage_failed(
                self.run_id,
                self.phase_id,
                marker.stage_id,
                "stage_result_invalid",
                str(exc),
                data_dir=self.data_dir,
            )
            self._had_controller_failure = True
            self._reject("invalid_path")
            return MarkerDecision(marker, "rejected_invalid_path", reason=str(exc))
        except PhaseSessionError as exc:
            payload["controller_status"] = "stage_result_invalid"
            record_stage_failed(
                self.run_id,
                self.phase_id,
                marker.stage_id,
                "stage_result_invalid",
                str(exc),
                data_dir=self.data_dir,
            )
            self._had_controller_failure = True
            self._reject("invalid_result")
            return MarkerDecision(marker, "rejected_invalid_result", reason=str(exc))

        payload["validated_result_path"] = str(stage_result["path"])
        result_payload = stage_result["payload"]
        result_status = _stage_result_status(result_payload)
        if result_status in {"blocked", "needs_input", "failed"}:
            failure_kind = _stage_result_failure_kind(result_payload, default=result_status)
            notes = _stage_result_notes(result_payload)
            if result_status == "blocked":
                record_stage_blocked(
                    self.run_id,
                    self.phase_id,
                    marker.stage_id,
                    failure_kind,
                    notes,
                    data_dir=self.data_dir,
                )
                outcome = "blocked_recorded"
            elif result_status == "needs_input":
                record_stage_blocked(
                    self.run_id,
                    self.phase_id,
                    marker.stage_id,
                    failure_kind,
                    notes,
                    data_dir=self.data_dir,
                )
                outcome = "needs_input_recorded"
            else:
                record_stage_failed(
                    self.run_id,
                    self.phase_id,
                    marker.stage_id,
                    failure_kind,
                    notes,
                    data_dir=self.data_dir,
                )
                outcome = "failed_recorded"
            self._mark_stage_bead_blocked(marker, failure_kind=failure_kind, notes=notes)
            self._had_controller_failure = True
            self._failed_recorded_count += 1
            payload["controller_status"] = outcome
            payload["stage_result_status"] = result_status
            return MarkerDecision(marker, outcome, reason=failure_kind)

        commit_sha: str | None = None
        adopted_notes = _stage_result_notes(result_payload) if result_status == "complete_with_concerns" else None
        unit_adoption: Mapping[str, Any] | None = None
        try:
            unit_adoption = adopt_unit_stage(
                run_id=self.run_id,
                phase_id=self.phase_id,
                invocation=invocation,
                stage_result=result_payload,
                data_dir=self.data_dir,
                workspace_metadata=self.workspace_metadata,
                commit_subject=marker.commit_subject or marker.summary or "stage artifacts",
                writer_summary=marker.summary or str(result_payload.get("summary") or f"stage {marker.stage_id} completed"),
            )
            if unit_adoption is not None and unit_adoption.get("status") == "merged":
                self._latest_diff = unit_adoption.get("worktree_diff") if isinstance(unit_adoption.get("worktree_diff"), Mapping) else self._latest_diff
                commit_sha = _optional_str(unit_adoption.get("integration_head_sha")) or _optional_str(unit_adoption.get("commit_sha"))
                if commit_sha:
                    self._commits.append(commit_sha)
                payload["unit_adoption"] = dict(unit_adoption)
            elif _has_commit_target(self.workspace_metadata):
                record = commit_stage_artifacts(
                    _commit_target_from_workspace(self.prepared, self.workspace_metadata),
                    allowed_files=self._allowed_files,
                    run_artifact_excludes=self._run_excludes,
                    commit_subject=marker.commit_subject or marker.summary or "stage artifacts",
                    writer_summary=marker.summary or f"stage {marker.stage_id} completed",
                    stage_id=marker.stage_id,
                )
                self._latest_diff = record.worktree_diff
                commit_sha = record.commit_sha
                if commit_sha:
                    self._commits.append(commit_sha)
        except RunExecutionWorktreeError as exc:
            record_stage_failed(
                self.run_id,
                self.phase_id,
                marker.stage_id,
                "adoptable_artifacts_uncommittable",
                str(exc),
                data_dir=self.data_dir,
            )
            self._had_controller_failure = True
            self._failed_recorded_count += 1
            payload["controller_status"] = "adoptable_artifacts_uncommittable"
            return MarkerDecision(marker, "failed_recorded", reason=str(exc))

        record_stage_adopted(
            self.run_id,
            self.phase_id,
            marker.stage_id,
            commit_sha=commit_sha,
            result_path=marker.result_path,
            transcript_path=self.launch_dir / "stdout.txt",
            notes=adopted_notes,
            data_dir=self.data_dir,
        )
        self._close_stage_bead(marker.stage_id, commit_sha=commit_sha)
        self._append_stage_event(marker.stage_id, commit_sha=commit_sha, work_unit_id=invocation.work_unit_id, unit_adoption=unit_adoption)
        payload["controller_status"] = "adopted_with_concerns" if result_status == "complete_with_concerns" else "adopted"
        payload["stage_result_status"] = result_status
        return MarkerDecision(
            marker,
            "adopted_with_concerns" if result_status == "complete_with_concerns" else "adopted",
            commit_sha=commit_sha,
        )

    def _retry_pending(self) -> list[MarkerDecision]:
        if not self._pending:
            return []
        pending = self._pending
        self._pending = []
        decisions: list[MarkerDecision] = []
        for marker, payload in pending:
            decisions.append(self._process_marker(marker, payload, append_pending=True))
        return decisions

    def _load_valid_stage_result(self, marker: StageMarker, *, expected_result_path: Path) -> dict[str, Any]:
        result_path = self._validated_stage_result_path(marker.result_path, expected_result_path=expected_result_path)
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise _PendingStageResult(f"stage result pending: {result_path}") from exc
        except Exception as exc:
            raise PhaseSessionError(f"stage_result_unreadable: {result_path}: {exc}") from exc
        self._validate_stage_result(payload, result_path=result_path, marker=marker)
        return {"path": result_path, "payload": payload}

    def _validated_stage_result_path(self, raw_path: str | None, *, expected_result_path: Path) -> Path:
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise _InvalidStageResultPath("stage_result_path_invalid: missing result_path")
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            raise _InvalidStageResultPath(f"stage_result_path_invalid: result_path must be absolute: {raw_path}")
        root = (self.data_dir / "runs" / self.run_id / "phases" / self.phase_id / "stage_results").resolve(strict=False)
        resolved = path.resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise _InvalidStageResultPath(f"stage_result_path_invalid: result_path escapes stage_results: {raw_path}") from exc
        return resolved

    def _validate_stage_result(self, payload: Any, *, result_path: Path, marker: StageMarker) -> None:
        if not isinstance(payload, Mapping):
            raise PhaseSessionError(f"stage_result_invalid: {result_path}: root must be an object")
        errors: list[str] = []
        for key, expected in (
            ("run_id", self.run_id),
            ("phase_id", self.phase_id),
            ("phase_attempt", self.phase_attempt),
            ("stage_id", marker.stage_id),
        ):
            if key not in payload:
                errors.append(f"missing required property: {key}")
            elif payload.get(key) != expected:
                errors.append(f"$.{key}: expected {expected!r}, got {payload.get(key)!r}")
        if "status" not in payload:
            errors.append("missing required property: status")
        elif _stage_result_status(payload) not in _STAGE_RESULT_STATUSES:
            errors.append(
                "$.status: expected one of "
                + ", ".join(sorted(_STAGE_RESULT_STATUSES))
                + f", got {payload.get('status')!r}"
            )
        if errors:
            raise PhaseSessionError(f"stage_result_invalid: {result_path}: {'; '.join(errors)}")

    def _maybe_amend_terminal(self, marker: StageMarker, terminal: Mapping[str, Any]) -> bool:
        if terminal.get("status") != STATUS_ADOPTED:
            return False
        commit_sha = _optional_str((marker.raw or {}).get("commit_sha"))
        if not commit_sha or terminal.get("commit_sha"):
            return False
        record_stage_adopted(
            self.run_id,
            self.phase_id,
            marker.stage_id,
            commit_sha=commit_sha,
            result_path=marker.result_path,
            transcript_path=self.launch_dir / "stdout.txt",
            data_dir=self.data_dir,
        )
        return True

    def _terminal_stage(self, stage_id: str) -> Mapping[str, Any] | None:
        state = self._load_current_state()
        for stage in state.get("stages") or []:
            if isinstance(stage, Mapping) and stage.get("stage_id") == stage_id and stage.get("status") in TERMINAL_STATUSES:
                return stage
        return None

    def _load_current_state(self) -> dict[str, Any]:
        return load_stage_sessions(self.run_id, self.phase_id, data_dir=self.data_dir)

    def _reject(self, kind: str) -> None:
        self._had_controller_failure = True
        self._rejected_marker_count += 1
        if kind == "unknown_stage":
            self._rejected_unknown_stage += 1
        elif kind == "invalid_path":
            self._rejected_invalid_path += 1
        elif kind == "invalid_result":
            self._rejected_invalid_result += 1

    def _mark_stage_bead_blocked(
        self,
        marker: StageMarker,
        *,
        failure_kind: str | None = None,
        notes: str | None = None,
    ) -> None:
        mark_stage_blocked(
            _stage_bead_id(self.run_id, self.phase_id, marker.stage_id, data_dir=self.data_dir),
            failure_kind=failure_kind or marker.failure_kind or "stage_failed",
            notes=notes or marker.notes,
        )

    def _close_stage_bead(self, stage_id: str, *, commit_sha: str | None) -> None:
        close_stage_child(_stage_bead_id(self.run_id, self.phase_id, stage_id, data_dir=self.data_dir), commit_sha=commit_sha)

    def _append_stage_event(
        self,
        stage_id: str,
        *,
        commit_sha: str | None,
        work_unit_id: str | None,
        unit_adoption: Mapping[str, Any] | None,
    ) -> None:
        row = {
            "run_id": self.run_id,
            "timestamp": utc_now(),
            "event_type": "stage_adopted",
            "bd_epic_id": None,
            "phase_id": self.phase_id,
            "work_unit_id": work_unit_id,
            "child_bead_ids": None,
            "reason": None,
            "retry_count": None,
            "handoff_count": None,
            "integration_branch_head": commit_sha,
            "details": {
                "stage_id": stage_id,
                "commit_sha": commit_sha,
                "unit_adoption": dict(unit_adoption) if isinstance(unit_adoption, Mapping) else None,
            },
            "schema_ok": True,
        }
        validate_run_event(row, error_cls=PhaseSessionError)
        append_run_event(self.data_dir, row)

    def _assert_owner_thread(self) -> None:
        if threading.current_thread() is not threading.main_thread() and self._owner_thread is not threading.current_thread():
            raise RuntimeError("StageMarkerProcessor is not thread-safe")


def _ledger_commits(adopted_by_id: Mapping[str, Mapping[str, Any]], invocations: list[StageInvocation]) -> list[str]:
    commits: list[str] = []
    for invocation in invocations:
        commit_sha = _optional_str(adopted_by_id.get(invocation.stage_id, {}).get("commit_sha"))
        if commit_sha:
            commits.append(commit_sha)
    return commits


_STAGE_RESULT_STATUSES = {"complete", "complete_with_concerns", "blocked", "needs_input", "failed"}
_STAGE_RESULT_STATUS_ALIASES = {
    "done": "complete",
    "done_with_concerns": "complete_with_concerns",
    "needs_context": "needs_input",
}


def _stage_result_status(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        return ""
    value = payload.get("status")
    if not isinstance(value, str):
        return ""
    normalized = value.strip().lower()
    return _STAGE_RESULT_STATUS_ALIASES.get(normalized, normalized)


def _stage_result_failure_kind(payload: Mapping[str, Any], *, default: str) -> str:
    for key in ("failure_kind", "failure_reason", "blocked_reason"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return default


def _stage_result_notes(payload: Mapping[str, Any]) -> str | None:
    for key in ("notes", "summary", "blocked_reason"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value[:500]
    needs = payload.get("needs_input")
    if isinstance(needs, list):
        text = "; ".join(str(item) for item in needs if isinstance(item, str))
        return text[:500] if text else None
    return None


def _work_units_for_status(
    stages_by_id: Mapping[str, Mapping[str, Any]],
    invocations: list[StageInvocation],
    status: str,
) -> list[str]:
    out: list[str] = []
    for invocation in invocations:
        if not invocation.work_unit_id:
            continue
        if stages_by_id.get(invocation.stage_id, {}).get("status") == status and invocation.work_unit_id not in out:
            out.append(invocation.work_unit_id)
    return out


def _failed_work_units(current: Mapping[str, Any], invocations: list[StageInvocation]) -> list[str]:
    stages_by_id = {
        str(stage.get("stage_id")): stage
        for stage in current.get("stages") or []
        if isinstance(stage, Mapping)
    }
    out: list[str] = []
    for invocation in invocations:
        if not invocation.work_unit_id:
            continue
        if stages_by_id.get(invocation.stage_id, {}).get("status") in {"failed", "blocked"} and invocation.work_unit_id not in out:
            out.append(invocation.work_unit_id)
    return out


def _stage_bead_id(run_id: str, phase_id: str, stage_id: str, *, data_dir: Path) -> str | None:
    try:
        state = load_stage_sessions(run_id, phase_id, data_dir=data_dir)
    except Exception:
        return None
    for stage in state.get("stages") or []:
        if isinstance(stage, Mapping) and stage.get("stage_id") == stage_id and isinstance(stage.get("bead_id"), str):
            return str(stage["bead_id"])
    return None


def _phase_allowed_files(prepared: Mapping[str, Any], phase_id: str) -> list[str]:
    from .paths import REPO_ROOT

    descriptor = (prepared.get("work_unit_artifacts") or {}).get(phase_id)
    artifact = descriptor.get("artifact") if isinstance(descriptor, Mapping) and isinstance(descriptor.get("artifact"), Mapping) else None
    if artifact is None and isinstance(descriptor, Mapping) and isinstance(descriptor.get("path"), str):
        try:
            artifact_path = Path(str(prepared.get("repo_root") or REPO_ROOT)) / str(descriptor["path"])
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        except Exception:
            artifact = None
    allowed: list[str] = []
    if isinstance(artifact, Mapping):
        for unit in artifact.get("work_units") or []:
            if not isinstance(unit, Mapping):
                continue
            for value in unit.get("allowed_files") or unit.get("files") or []:
                if isinstance(value, str) and value not in allowed:
                    allowed.append(value)
    return allowed or ["**/*"]


def _run_artifact_excludes(run_id: str, workspace_metadata: Mapping[str, Any]) -> list[str]:
    project_subdir = str(workspace_metadata.get("project_subdir") or "").strip("/")
    rel = f"data/runs/{run_id}"
    return [str(Path(project_subdir) / rel) if project_subdir else rel]


def _commit_target_from_workspace(prepared: Mapping[str, Any], workspace_metadata: Mapping[str, Any]) -> dict[str, Any]:
    safe_git = workspace_metadata.get("safe_git_worktree_root") or workspace_metadata.get("launcher_repo_root")
    project_subdir = workspace_metadata.get("project_subdir")
    if not isinstance(project_subdir, str):
        project_subdir = ""
    base_sha = workspace_metadata.get("git_base_sha") or prepared.get("git_base_sha")
    return {
        "safe_git_root": str(safe_git),
        "project_subdir": str(project_subdir or ""),
        "base_sha": str(base_sha or "HEAD"),
    }


def _has_commit_target(workspace_metadata: Mapping[str, Any]) -> bool:
    return isinstance(workspace_metadata.get("safe_git_worktree_root") or workspace_metadata.get("launcher_repo_root"), str)


def _normalized_worktree_diff(value: Any) -> dict[str, list[str]]:
    source = value if isinstance(value, Mapping) else {}
    return {
        key: [str(item) for item in source.get(key, []) if isinstance(item, str)]
        for key in ("committed", "staged", "unstaged", "untracked")
    }


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


__all__ = ["MarkerDecision", "StageMarkerProcessor"]
