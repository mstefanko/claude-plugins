"""Live, idempotent processing for controller-owned stage markers."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, Mapping

from .execution_worktree import RunExecutionWorktreeError, commit_stage_artifacts
from .failure_taxonomy import failure_kind_details
from .orchestrator_stream import StageMarker, contains_stage_marker_token, parse_stage_marker_line
from .paths import REPO_ROOT
from .phase_beads import close_stage_child, mark_stage_blocked
from .phase_sessions import PhaseSessionError
from .post_writer import changed_files_from_worktree_diff
from .run_state import append_run_event, utc_now, validate_run_event
from .stage_adoption_journal import (
    checkpoint_adoption_journal,
    incomplete_adoption_journals,
    marker_from_journal,
    start_adoption_journal,
)
from .stage_invocation import StageInvocation
from .stage_sessions import (
    STATUS_ADOPTED,
    TERMINAL_STATUSES,
    claim_stage,
    load_stage_sessions,
    record_stage_adopted,
    record_stage_blocked,
    record_stage_failed,
    record_stage_retry_requested,
)
from .unit_session_adopter import adopt_unit_stage
from .unit_sessions import UnitSessionError, find_unit_session, load_unit_sessions, write_unit_sessions


PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
PHASE_STATUS_PARTIAL_SUCCESS = "partial_success"
MAX_FRESH_REVIEWER_RETRY_CYCLES = 3


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
        "rejected_metadata_tampered",
        "adopted_with_concerns",
        "blocked_recorded",
        "needs_input_recorded",
        "failed_recorded",
        "retry_requested",
    ]
    commit_sha: str | None = None
    reason: str | None = None


class _PendingStageResult(FileNotFoundError):
    """Raised when a marker is valid but its result file is not visible yet."""


class _InvalidStageResultPath(ValueError):
    """Raised when a marker points outside the controller stage result area."""


class _StageMetadataTampered(PhaseSessionError):
    """Raised when marker/result metadata disagrees with controller bindings."""


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
        self._rejected_metadata_tampered = 0
        self._failed_recorded_count = 0
        self._retry_requested_count = 0
        self._stage_result_missing_count = 0
        self._malformed_marker_candidate_count = 0

    def process_text(self, text: str) -> list[MarkerDecision]:
        """Parse marker lines from text and process them on the owner thread."""

        self._assert_owner_thread()
        decisions: list[MarkerDecision] = []
        decisions.extend(self._retry_pending())
        for line in text.splitlines():
            marker = parse_stage_marker_line(line)
            if marker is not None:
                decisions.append(self.process_marker(marker))
            elif contains_stage_marker_token(line):
                self._malformed_marker_candidate_count += 1
        return decisions

    def process_marker(self, marker: StageMarker) -> MarkerDecision:
        self._assert_owner_thread()
        payload = marker.to_dict()
        self._marker_payloads.append(payload)
        return self._process_marker(marker, payload, append_pending=True)

    def finish(self) -> dict[str, Any]:
        self._assert_owner_thread()
        self._retry_pending()
        self._fail_unresolved_pending_markers()
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
        preserved_work_units = _string_list(self.workspace_metadata.get("preserved_work_units"))
        retry_target_work_units = _string_list(self.workspace_metadata.get("retry_target_work_units"))
        stage_work_unit_map = _stage_work_unit_map(self.stage_invocations)
        failed_work_units = _failed_work_units(current, self.stage_invocations)
        retry_requested_work_units = _retry_requested_work_units(current, self.stage_invocations)
        failed_stage_ids = _failed_stage_ids(current)
        merge_status = _merge_status_by_work_unit(
            self.run_id,
            self.phase_id,
            current,
            self.stage_invocations,
            data_dir=self.data_dir,
        )
        terminal_state = _terminal_state_for_summary(
            completed=completed,
            adopted_stage_ids=set(adopted_by_id),
            failed_stage_ids=set(failed_stage_ids),
            had_controller_failure=self._had_controller_failure,
        )
        return {
            "live": True,
            "completed": completed,
            "terminal_state": terminal_state,
            "phase_result_status": PHASE_STATUS_PARTIAL_SUCCESS if terminal_state == PARTIAL_SUCCESS else terminal_state,
            "markers": self._marker_payloads,
            "commits": commits,
            "commit_sha": commits[-1] if commits else None,
            "worktree_diff": _normalized_worktree_diff(self._latest_diff) if self._latest_diff else None,
            "changed_files": changed,
            "completed_work_units": completed_work_units,
            "preserved_work_units": preserved_work_units,
            "retry_target_work_units": retry_target_work_units,
            "stage_work_unit_map": stage_work_unit_map,
            "failed_work_units": failed_work_units,
            "retry_requested_work_units": retry_requested_work_units,
            "failed_stage_ids": failed_stage_ids,
            "merge_status": merge_status,
            "pending_marker_count": len(self._pending),
            "duplicate_marker_count": self._duplicate_marker_count,
            "amended_count": self._amended_count,
            "rejected_marker_count": self._rejected_marker_count,
            "rejected_unknown_stage": self._rejected_unknown_stage,
            "rejected_invalid_path": self._rejected_invalid_path,
            "rejected_invalid_result": self._rejected_invalid_result,
            "rejected_metadata_tampered": self._rejected_metadata_tampered,
            "failed_recorded_count": self._failed_recorded_count,
            "retry_requested_count": self._retry_requested_count,
            "stage_result_missing_count": self._stage_result_missing_count,
            "malformed_marker_candidate_count": self._malformed_marker_candidate_count,
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
            self._repair_terminal_adoption(
                marker.stage_id,
                terminal,
                commit_sha=_optional_str(terminal.get("commit_sha")),
            )
            return MarkerDecision(marker, "duplicate", commit_sha=_optional_str(terminal.get("commit_sha")))

        if marker.kind == "failed":
            return self._record_stage_failure(marker, payload, failure_kind=marker.failure_kind or "stage_failed", notes=marker.notes)

        try:
            validated_result_path = self._validated_stage_result_path(
                marker.result_path,
                expected_result_path=invocation.expected_result_path,
                stage_id=marker.stage_id,
            )
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
        except _StageMetadataTampered as exc:
            return self._record_metadata_tamper(marker, payload, reason=str(exc))

        claim_stage(self.run_id, self.phase_id, marker.stage_id, data_dir=self.data_dir)
        start_adoption_journal(
            data_dir=self.data_dir,
            run_id=self.run_id,
            phase_id=self.phase_id,
            phase_attempt=self.phase_attempt,
            marker=marker,
            invocation=invocation,
        )
        try:
            stage_result = self._load_valid_stage_result(
                marker,
                expected_result_path=invocation.expected_result_path,
                validated_result_path=validated_result_path,
                invocation=invocation,
            )
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
        except _StageMetadataTampered as exc:
            return self._record_metadata_tamper(marker, payload, reason=str(exc))
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
        self._checkpoint_adoption_journal(
            marker.stage_id,
            "result_validated",
            {"result_path": str(stage_result["path"]), "status": _stage_result_status(result_payload)},
        )
        result_status = _stage_result_status(result_payload)
        if result_status in {"blocked", "needs_input", "failed"}:
            failure_kind = _stage_result_failure_kind(result_payload, default=result_status)
            notes = _stage_result_notes(result_payload)
            retry_decision = self._maybe_record_retry_request(marker, payload, failure_kind=failure_kind, notes=notes)
            if retry_decision is not None:
                return retry_decision
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
                if _failure_retry_class(failure_kind) == "human_gate":
                    record_stage_blocked(
                        self.run_id,
                        self.phase_id,
                        marker.stage_id,
                        failure_kind,
                        notes,
                        data_dir=self.data_dir,
                    )
                    outcome = "blocked_recorded"
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
                journal_checkpoint=lambda checkpoint, checkpoint_payload=None: self._checkpoint_adoption_journal(
                    marker.stage_id,
                    checkpoint,
                    checkpoint_payload,
                ),
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
        self._checkpoint_adoption_journal(
            marker.stage_id,
            "stage_recorded",
            {"commit_sha": commit_sha, "result_path": marker.result_path},
        )
        self._close_stage_bead(marker.stage_id, commit_sha=commit_sha)
        self._checkpoint_adoption_journal(marker.stage_id, "bead_closed", {"commit_sha": commit_sha})
        self._append_stage_event(marker.stage_id, commit_sha=commit_sha, work_unit_id=invocation.work_unit_id, unit_adoption=unit_adoption)
        self._checkpoint_adoption_journal(marker.stage_id, "event_appended", {"commit_sha": commit_sha}, completed=True)
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

    def _fail_unresolved_pending_markers(self) -> None:
        if not self._pending:
            return
        pending = self._pending
        self._pending = []
        for marker, payload in pending:
            failure_kind = "stage_result_missing"
            record_stage_failed(
                self.run_id,
                self.phase_id,
                marker.stage_id,
                failure_kind,
                f"stage result still missing at finish: {marker.result_path}",
                data_dir=self.data_dir,
            )
            self._mark_stage_bead_blocked(marker, failure_kind=failure_kind, notes="stage result missing at finish")
            payload["controller_status"] = failure_kind
            self._had_controller_failure = True
            self._failed_recorded_count += 1
            self._stage_result_missing_count += 1

    def _record_stage_failure(
        self,
        marker: StageMarker,
        payload: dict[str, Any],
        *,
        failure_kind: str,
        notes: str | None,
    ) -> MarkerDecision:
        retry_decision = self._maybe_record_retry_request(marker, payload, failure_kind=failure_kind, notes=notes)
        if retry_decision is not None:
            return retry_decision
        if _failure_retry_class(failure_kind) == "human_gate":
            record_stage_blocked(
                self.run_id,
                self.phase_id,
                marker.stage_id,
                failure_kind,
                notes,
                data_dir=self.data_dir,
            )
            self._mark_stage_bead_blocked(marker, failure_kind=failure_kind, notes=notes)
            self._had_controller_failure = True
            self._failed_recorded_count += 1
            payload["controller_status"] = "blocked_recorded"
            return MarkerDecision(marker, "blocked_recorded", reason=failure_kind)
        record_stage_failed(
            self.run_id,
            self.phase_id,
            marker.stage_id,
            failure_kind,
            notes,
            data_dir=self.data_dir,
        )
        self._mark_stage_bead_blocked(marker, failure_kind=failure_kind, notes=notes)
        self._had_controller_failure = True
        self._failed_recorded_count += 1
        payload["controller_status"] = "failed_recorded"
        return MarkerDecision(marker, "failed_recorded", reason=failure_kind)

    def _maybe_record_retry_request(
        self,
        marker: StageMarker,
        payload: dict[str, Any],
        *,
        failure_kind: str,
        notes: str | None,
    ) -> MarkerDecision | None:
        if _failure_retry_class(failure_kind) != "retry":
            return None
        recorded = record_stage_retry_requested(
            self.run_id,
            self.phase_id,
            marker.stage_id,
            failure_kind,
            notes,
            data_dir=self.data_dir,
            fresh_reviewer=True,
        )
        stage = recorded.get("stage") if isinstance(recorded, Mapping) else {}
        retry_cycle = _retry_cycle_count(stage) if isinstance(stage, Mapping) else 0
        payload["controller_status"] = "retry_requested"
        payload["retry_cycle_count"] = retry_cycle
        payload["fresh_reviewer"] = True
        payload["prior_findings"] = "excluded"
        self._retry_requested_count += 1
        if retry_cycle > MAX_FRESH_REVIEWER_RETRY_CYCLES:
            capped_kind = "retry_cycle_cap_exceeded"
            record_stage_blocked(
                self.run_id,
                self.phase_id,
                marker.stage_id,
                capped_kind,
                notes or f"retry cycle cap exceeded after {MAX_FRESH_REVIEWER_RETRY_CYCLES} fresh-reviewer cycles",
                data_dir=self.data_dir,
            )
            self._mark_stage_bead_blocked(marker, failure_kind=capped_kind, notes=notes)
            self._append_human_gate_event(marker.stage_id, failure_kind=capped_kind, work_unit_id=self._by_id[marker.stage_id].work_unit_id)
            self._had_controller_failure = True
            self._failed_recorded_count += 1
            payload["controller_status"] = "retry_cycle_cap_exceeded"
            return MarkerDecision(marker, "blocked_recorded", reason=capped_kind)
        return MarkerDecision(marker, "retry_requested", reason=failure_kind)

    def _record_metadata_tamper(self, marker: StageMarker, payload: dict[str, Any], *, reason: str) -> MarkerDecision:
        failure_kind = "stage_metadata_tampered"
        record_stage_blocked(
            self.run_id,
            self.phase_id,
            marker.stage_id,
            failure_kind,
            reason,
            data_dir=self.data_dir,
        )
        self._mark_stage_bead_blocked(marker, failure_kind=failure_kind, notes=reason)
        invocation = self._by_id.get(marker.stage_id)
        self._append_human_gate_event(
            marker.stage_id,
            failure_kind=failure_kind,
            work_unit_id=invocation.work_unit_id if invocation is not None else None,
        )
        payload["controller_status"] = "stage_metadata_tampered"
        payload["failure_kind"] = failure_kind
        self._had_controller_failure = True
        self._failed_recorded_count += 1
        self._reject("metadata_tampered")
        return MarkerDecision(marker, "rejected_metadata_tampered", reason=reason)

    def _stage_binding_errors(
        self,
        payload: Mapping[str, Any],
        *,
        result_path: Path,
        marker: StageMarker,
        invocation: StageInvocation,
        stage: Mapping[str, Any],
    ) -> list[str]:
        errors: list[str] = []
        expected_path = invocation.expected_result_path.expanduser().resolve(strict=False)
        if result_path.resolve(strict=False) != expected_path:
            errors.append(f"result_path resolved to {result_path.resolve(strict=False)}, expected {expected_path}")
        session_stage_id = stage.get("stage_id")
        if session_stage_id != marker.stage_id:
            errors.append(f"stage session stage_id expected {marker.stage_id!r}, got {session_stage_id!r}")
        for key, expected in (
            ("work_unit_id", invocation.work_unit_id),
            ("worktree_path", str(invocation.worktree_path) if invocation.worktree_path else None),
            ("bead_id", invocation.bead_id),
        ):
            session_value = stage.get(key)
            if session_value != expected:
                errors.append(f"stage session {key} expected {expected!r}, got {session_value!r}")
            if expected is not None and key not in payload:
                errors.append(f"missing required property: {key}")
            elif key in payload and payload.get(key) != expected:
                errors.append(f"result {key} expected {expected!r}, got {payload.get(key)!r}")
        expected_allowed = list(invocation.allowed_files)
        session_allowed = [str(item) for item in stage.get("allowed_files") or [] if isinstance(item, str)]
        if session_allowed != expected_allowed:
            errors.append(f"stage session allowed_files expected {expected_allowed!r}, got {session_allowed!r}")
        if expected_allowed and "allowed_files" not in payload:
            errors.append("missing required property: allowed_files")
        elif "allowed_files" in payload:
            result_allowed = [str(item) for item in payload.get("allowed_files") or [] if isinstance(item, str)]
            if result_allowed != expected_allowed:
                errors.append(f"result allowed_files expected {expected_allowed!r}, got {result_allowed!r}")
        result_path_claim = payload.get("result_path")
        if not isinstance(result_path_claim, str) or not result_path_claim:
            errors.append("missing required property: result_path")
        elif Path(result_path_claim).expanduser().resolve(strict=False) != expected_path:
            errors.append(f"result result_path expected {expected_path}, got {result_path_claim}")
        errors.extend(self._unit_binding_errors(invocation, stage))
        return errors

    def _unit_binding_errors(self, invocation: StageInvocation, stage: Mapping[str, Any]) -> list[str]:
        if invocation.work_unit_id is None:
            return []
        try:
            units = load_unit_sessions(self.run_id, data_dir=self.data_dir)
            unit = find_unit_session(units, self.phase_id, invocation.work_unit_id)
        except UnitSessionError as exc:
            return [f"unit session missing for {invocation.work_unit_id}: {exc}"]
        errors: list[str] = []
        project_root = str(unit.get("project_root") or "")
        if invocation.worktree_path is None or str(invocation.worktree_path) != project_root:
            errors.append(f"unit worktree_path expected {project_root!r}, got {str(invocation.worktree_path) if invocation.worktree_path else None!r}")
        if stage.get("worktree_path") != project_root:
            errors.append(f"stage session worktree_path expected {project_root!r}, got {stage.get('worktree_path')!r}")
        return errors

    def _load_valid_stage_result(
        self,
        marker: StageMarker,
        *,
        expected_result_path: Path,
        validated_result_path: Path | None = None,
        invocation: StageInvocation,
    ) -> dict[str, Any]:
        result_path = validated_result_path or self._validated_stage_result_path(
            marker.result_path,
            expected_result_path=expected_result_path,
            stage_id=marker.stage_id,
        )
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise _PendingStageResult(f"stage result pending: {result_path}") from exc
        except Exception as exc:
            raise PhaseSessionError(f"stage_result_unreadable: {result_path}: {exc}") from exc
        self._validate_stage_result(payload, result_path=result_path, marker=marker, invocation=invocation)
        return {"path": result_path, "payload": payload}

    def _validated_stage_result_path(self, raw_path: str | None, *, expected_result_path: Path, stage_id: str) -> Path:
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
        expected = expected_result_path.expanduser().resolve(strict=False)
        if resolved != expected:
            raise _StageMetadataTampered(
                f"stage_metadata_tampered: marker result_path {resolved} does not match expected {expected}"
            )
        stage = self._stage_session_record(stage_id)
        session_result_path = _optional_str(stage.get("result_path")) if stage is not None else None
        if stage is None:
            raise _StageMetadataTampered(f"stage_metadata_tampered: stage session missing for {stage_id}")
        if session_result_path is None:
            raise _StageMetadataTampered(f"stage_metadata_tampered: stage session result_path missing for {stage_id}")
        session_resolved = Path(session_result_path).expanduser().resolve(strict=False)
        if session_resolved != expected:
            raise _StageMetadataTampered(
                f"stage_metadata_tampered: stage session result_path {session_resolved} does not match expected {expected}"
            )
        return resolved

    def _validate_stage_result(
        self,
        payload: Any,
        *,
        result_path: Path,
        marker: StageMarker,
        invocation: StageInvocation,
    ) -> None:
        if not isinstance(payload, Mapping):
            raise PhaseSessionError(f"stage_result_invalid: {result_path}: root must be an object")
        errors: list[str] = []
        stage = self._stage_session_record(marker.stage_id)
        if stage is None:
            raise _StageMetadataTampered(f"stage_metadata_tampered: stage session missing for {marker.stage_id}")
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
        result_status = _stage_result_status(payload)
        if "status" not in payload:
            errors.append("missing required property: status")
        elif result_status not in _STAGE_RESULT_STATUSES:
            errors.append(
                "$.status: expected one of "
                + ", ".join(sorted(_STAGE_RESULT_STATUSES))
                + f", got {payload.get('status')!r}"
            )
        claimed_failure_kind = _stage_result_claimed_failure_kind(payload)
        if result_status in {"blocked", "needs_input", "failed"} and claimed_failure_kind:
            if _failure_retry_class(claimed_failure_kind) == "human_gate":
                raise _StageMetadataTampered(
                    "stage_metadata_tampered: "
                    f"{result_path}: result failure_kind {claimed_failure_kind!r} is controller-owned human-gate metadata"
                )
        tamper_errors = self._stage_binding_errors(payload, result_path=result_path, marker=marker, invocation=invocation, stage=stage)
        if tamper_errors:
            raise _StageMetadataTampered(f"stage_metadata_tampered: {result_path}: {'; '.join(tamper_errors)}")
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

    def _repair_terminal_adoption(self, stage_id: str, terminal: Mapping[str, Any], *, commit_sha: str | None) -> None:
        if terminal.get("status") != STATUS_ADOPTED:
            return
        invocation = self._by_id.get(stage_id)
        work_unit_id = invocation.work_unit_id if invocation is not None else _optional_str(terminal.get("work_unit_id"))
        self._close_stage_bead(stage_id, commit_sha=commit_sha)
        self._checkpoint_adoption_journal(stage_id, "bead_closed", {"commit_sha": commit_sha})
        self._append_stage_event(stage_id, commit_sha=commit_sha, work_unit_id=work_unit_id, unit_adoption=None)
        self._checkpoint_adoption_journal(stage_id, "event_appended", {"commit_sha": commit_sha}, completed=True)

    def _terminal_stage(self, stage_id: str) -> Mapping[str, Any] | None:
        state = self._load_current_state()
        for stage in state.get("stages") or []:
            if isinstance(stage, Mapping) and stage.get("stage_id") == stage_id and stage.get("status") in TERMINAL_STATUSES:
                return stage
        return None

    def _stage_session_record(self, stage_id: str) -> Mapping[str, Any] | None:
        state = self._load_current_state()
        for stage in state.get("stages") or []:
            if isinstance(stage, Mapping) and stage.get("stage_id") == stage_id:
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
        elif kind == "metadata_tampered":
            self._rejected_metadata_tampered += 1

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
        if self._stage_event_exists(stage_id):
            return
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

    def _stage_event_exists(self, stage_id: str) -> bool:
        path = self.data_dir / "telemetry" / "run_events.jsonl"
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return False
        for line in lines:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            details = row.get("details") if isinstance(row, Mapping) else None
            if (
                isinstance(details, Mapping)
                and row.get("run_id") == self.run_id
                and row.get("phase_id") == self.phase_id
                and row.get("event_type") == "stage_adopted"
                and details.get("stage_id") == stage_id
            ):
                return True
        return False

    def _checkpoint_adoption_journal(
        self,
        stage_id: str,
        checkpoint: str,
        payload: Mapping[str, Any] | None = None,
        *,
        completed: bool | None = None,
    ) -> None:
        checkpoint_adoption_journal(
            data_dir=self.data_dir,
            run_id=self.run_id,
            phase_id=self.phase_id,
            phase_attempt=self.phase_attempt,
            stage_id=stage_id,
            checkpoint=checkpoint,
            payload=payload,
            completed=completed,
        )

    def _append_human_gate_event(self, stage_id: str, *, failure_kind: str, work_unit_id: str | None) -> None:
        row = {
            "run_id": self.run_id,
            "timestamp": utc_now(),
            "event_type": "stage_human_gate",
            "bd_epic_id": None,
            "phase_id": self.phase_id,
            "work_unit_id": work_unit_id,
            "child_bead_ids": None,
            "reason": failure_kind,
            "retry_count": None,
            "handoff_count": None,
            "integration_branch_head": None,
            "details": {
                "stage_id": stage_id,
                "failure_kind": failure_kind,
                "retry_cycle_cap": MAX_FRESH_REVIEWER_RETRY_CYCLES,
                "fresh_reviewer": True,
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


def resume_stage_adoption_journals(
    *,
    run_id: str,
    phase_id: str,
    phase_attempt: int | None = None,
    prepared: Mapping[str, Any],
    workspace_metadata: Mapping[str, Any],
    launch_dir: Path,
    data_dir: Path,
    stage_invocations: list[StageInvocation] | None = None,
) -> dict[str, Any]:
    """Replay incomplete stage adoption journals until they reach terminal checkpoints."""

    journals = incomplete_adoption_journals(
        data_dir=data_dir,
        run_id=run_id,
        phase_id=phase_id,
        phase_attempt=phase_attempt,
    )
    if not journals:
        return {"completed": False, "resumed_adoption_journals": []}
    base_invocations = stage_invocations or _invocations_from_stage_state(run_id, phase_id, data_dir=data_dir)
    resumed: list[dict[str, Any]] = []
    completed = False
    summaries: list[dict[str, Any]] = []
    attempts = sorted({int(journal.get("phase_attempt") or phase_attempt or 0) for journal in journals})
    for attempt in attempts:
        group = [journal for journal in journals if int(journal.get("phase_attempt") or phase_attempt or 0) == attempt]
        processor = StageMarkerProcessor(
            run_id=run_id,
            phase_id=phase_id,
            phase_attempt=attempt,
            stage_invocations=_invocations_for_journal_resume(base_invocations, group),
            prepared=prepared,
            workspace_metadata=workspace_metadata,
            launch_dir=launch_dir,
            data_dir=data_dir,
        )
        for journal in group:
            marker = marker_from_journal(journal)
            if marker is None:
                continue
            decision = processor.process_marker(marker)
            resumed.append(
                {
                    "stage_id": marker.stage_id,
                    "journal_path": journal.get("_path"),
                    "outcome": decision.outcome,
                    "reason": decision.reason,
                }
            )
        summary = processor.finish()
        summaries.append(summary)
        completed = completed or bool(summary.get("completed"))
    summary = dict(summaries[-1] if summaries else {"completed": False})
    summary["completed"] = completed
    summary["resumed_adoption_journals"] = resumed
    return summary


def retry_failed_units(
    *,
    run_id: str,
    phase_id: str,
    unit_ids: list[str] | None = None,
    data_dir: Path,
) -> dict[str, Any]:
    """Prepare retryable failed/pending unit stages for a reduced fanout dispatch."""

    state = load_stage_sessions(run_id, phase_id, data_dir=data_dir)
    selected_units = set(unit_ids or [])
    preserved_work_units: list[str] = []
    retry_target_work_units: list[str] = []
    retry_stage_ids: list[str] = []
    blocked_stage_ids: list[str] = []
    stage_to_work_unit_id: dict[str, str | None] = {}
    now = utc_now()
    for stage in state.get("stages") or []:
        if not isinstance(stage, Mapping):
            continue
        stage_id = str(stage.get("stage_id") or "")
        work_unit_id = _optional_str(stage.get("work_unit_id"))
        stage_to_work_unit_id[stage_id] = work_unit_id
        if work_unit_id and stage.get("status") == STATUS_ADOPTED and work_unit_id not in preserved_work_units:
            preserved_work_units.append(work_unit_id)
        if selected_units and work_unit_id not in selected_units:
            continue
        retryable = _failure_retry_class(_optional_str(stage.get("failure_kind"))) == "retry"
        pending_retry = stage.get("status") == "pending" and bool(stage.get("fresh_reviewer_required"))
        failed_retryable = stage.get("status") == "failed" and retryable
        if not (pending_retry or failed_retryable):
            continue
        retry_cycle = _retry_cycle_count(stage)
        retry_cap_exceeded = retry_cycle > MAX_FRESH_REVIEWER_RETRY_CYCLES or (
            failed_retryable and retry_cycle >= MAX_FRESH_REVIEWER_RETRY_CYCLES
        )
        if retry_cap_exceeded:
            record_stage_blocked(
                run_id,
                phase_id,
                stage_id,
                "retry_cycle_cap_exceeded",
                f"retry cycle cap exceeded after {MAX_FRESH_REVIEWER_RETRY_CYCLES} fresh-reviewer cycles",
                data_dir=data_dir,
            )
            blocked_stage_ids.append(stage_id)
            continue
        if failed_retryable:
            record_stage_retry_requested(
                run_id,
                phase_id,
                stage_id,
                _optional_str(stage.get("failure_kind")) or "sub_agent_error",
                _optional_str(stage.get("notes")),
                data_dir=data_dir,
                fresh_reviewer=True,
            )
        if work_unit_id and work_unit_id not in retry_target_work_units:
            retry_target_work_units.append(work_unit_id)
        retry_stage_ids.append(stage_id)
    _append_unit_retry_history(
        run_id,
        phase_id,
        retry_target_work_units,
        stage_ids=retry_stage_ids,
        data_dir=data_dir,
        recorded_at=now,
    )
    return {
        "run_id": run_id,
        "phase_id": phase_id,
        "preserved_work_units": preserved_work_units,
        "retry_target_work_units": retry_target_work_units,
        "retry_stage_ids": retry_stage_ids,
        "blocked_stage_ids": blocked_stage_ids,
        "stage_to_work_unit_id": stage_to_work_unit_id,
        "fresh_reviewer_required": bool(retry_target_work_units),
    }


def _invocations_from_stage_state(run_id: str, phase_id: str, *, data_dir: Path) -> list[StageInvocation]:
    state = load_stage_sessions(run_id, phase_id, data_dir=data_dir)
    invocations: list[StageInvocation] = []
    for stage in state.get("stages") or []:
        if not isinstance(stage, Mapping):
            continue
        agent_role = str(stage.get("agent_role") or "agent-writer")
        stage_id = str(stage.get("stage_id") or "")
        if not stage_id:
            continue
        result_path = Path(str(stage.get("result_path") or data_dir / "runs" / run_id / "phases" / phase_id / "stage_results" / f"{stage_id}.result.json"))
        invocations.append(
            StageInvocation(
                stage_id=stage_id,
                agent_role=agent_role,
                layer_index=int(stage.get("layer_index") or 0),
                fan_out_key=_optional_str(stage.get("fan_out_key")),
                fan_out_index=stage.get("fan_out_index") if isinstance(stage.get("fan_out_index"), int) else None,
                merge_target=_optional_str(stage.get("merge_target")),
                is_provider_stage=bool(stage.get("is_provider_stage")),
                lens_chain=tuple(str(item) for item in stage.get("lens_chain") or [] if isinstance(item, str)),
                failure_tolerance=str(stage.get("failure_tolerance") or "strict"),
                role_brief_path=_role_brief_path(agent_role),
                expected_result_path=result_path,
                upstream_stage_ids=tuple(str(item) for item in stage.get("upstream_stage_ids") or [] if isinstance(item, str)),
                task_prompt_path=Path(str(stage["task_prompt_path"])) if isinstance(stage.get("task_prompt_path"), str) else None,
                subagent_type=str(stage.get("subagent_type") or ""),
                worktree_path=Path(str(stage["worktree_path"])) if isinstance(stage.get("worktree_path"), str) else None,
                bead_id=_optional_str(stage.get("bead_id")),
                allowed_files=tuple(str(item) for item in stage.get("allowed_files") or [] if isinstance(item, str)),
                acceptance_criteria=str(stage.get("acceptance_criteria") or ""),
                work_unit_id=_optional_str(stage.get("work_unit_id")),
                max_writer_tool_calls=_int_or_default(stage.get("max_writer_tool_calls"), 60),
                max_writer_output_bytes=_int_or_default(stage.get("max_writer_output_bytes"), 60_000),
                max_handoffs=_int_or_default(stage.get("max_handoffs"), 1),
            )
        )
    return invocations


def _invocations_for_journal_resume(
    invocations: list[StageInvocation],
    journals: list[Mapping[str, Any]],
) -> list[StageInvocation]:
    by_id = {invocation.stage_id: invocation for invocation in invocations}
    for journal in journals:
        stage_id = _optional_str(journal.get("stage_id"))
        if not stage_id or stage_id not in by_id:
            continue
        invocation = by_id[stage_id]
        expected_result_path = _optional_str(journal.get("expected_result_path"))
        worktree_path = _optional_str(journal.get("worktree_path"))
        allowed_files = journal.get("allowed_files")
        by_id[stage_id] = replace(
            invocation,
            expected_result_path=Path(expected_result_path) if expected_result_path else invocation.expected_result_path,
            work_unit_id=_optional_str(journal.get("work_unit_id")),
            worktree_path=Path(worktree_path) if worktree_path else None,
            bead_id=_optional_str(journal.get("bead_id")),
            allowed_files=tuple(str(item) for item in allowed_files if isinstance(item, str))
            if isinstance(allowed_files, list)
            else invocation.allowed_files,
        )
    return list(by_id.values())


def _append_unit_retry_history(
    run_id: str,
    phase_id: str,
    unit_ids: list[str],
    *,
    stage_ids: list[str],
    data_dir: Path,
    recorded_at: str,
) -> None:
    if not unit_ids:
        return
    try:
        state = load_unit_sessions(run_id, data_dir=data_dir)
    except UnitSessionError:
        return
    units = []
    changed = False
    for unit in state.get("units") or []:
        if not isinstance(unit, Mapping):
            continue
        current = dict(unit)
        if current.get("phase_id") == phase_id and current.get("unit_id") in unit_ids:
            history = [dict(item) for item in current.get("attempt_history") or [] if isinstance(item, Mapping)]
            next_attempt = max(1, int(current.get("attempt") or 0) + 1)
            row = {
                "attempt": next_attempt,
                "retry_requested_at": recorded_at,
                "retry_stage_ids": list(stage_ids),
                "retry_decision": "unit_redispatch",
                "fresh_reviewer_required": True,
            }
            if not history or history[-1] != row:
                history.append(row)
            current["attempt"] = next_attempt
            current["attempt_history"] = history
            current["writer_status"] = "pending"
            current["post_writer_status"] = "pending"
            current["merge_state"] = "pending"
            current["updated_at"] = recorded_at
            changed = True
        units.append(current)
    if changed:
        next_state = dict(state)
        next_state["units"] = units
        write_unit_sessions(next_state, data_dir=data_dir)


def _role_brief_path(agent_role: str) -> Path:
    if agent_role.startswith("provider:"):
        return REPO_ROOT / "role-specs" / "agent-provider-review.md"
    return REPO_ROOT / "role-specs" / f"{agent_role}.md"


def _stage_work_unit_map(invocations: list[StageInvocation]) -> dict[str, str | None]:
    return {invocation.stage_id: invocation.work_unit_id for invocation in invocations}


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in value or [] if isinstance(item, str)]


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
    return _stage_result_claimed_failure_kind(payload) or default


def _stage_result_claimed_failure_kind(payload: Mapping[str, Any]) -> str | None:
    for key in ("failure_kind", "failure_reason", "blocked_reason"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


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


def _retry_requested_work_units(current: Mapping[str, Any], invocations: list[StageInvocation]) -> list[str]:
    stages_by_id = {
        str(stage.get("stage_id")): stage
        for stage in current.get("stages") or []
        if isinstance(stage, Mapping)
    }
    out: list[str] = []
    for invocation in invocations:
        if not invocation.work_unit_id:
            continue
        stage = stages_by_id.get(invocation.stage_id, {})
        if (
            stage.get("status") == "pending"
            and bool(stage.get("fresh_reviewer_required"))
            and invocation.work_unit_id not in out
        ):
            out.append(invocation.work_unit_id)
    return out


def _failed_stage_ids(current: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    for stage in current.get("stages") or []:
        if not isinstance(stage, Mapping):
            continue
        if stage.get("status") in {"failed", "blocked"} and isinstance(stage.get("stage_id"), str):
            out.append(str(stage["stage_id"]))
    return out


def _merge_status_by_work_unit(
    run_id: str,
    phase_id: str,
    current: Mapping[str, Any],
    invocations: list[StageInvocation],
    *,
    data_dir: Path,
) -> dict[str, str]:
    stages_by_id = {
        str(stage.get("stage_id")): stage
        for stage in current.get("stages") or []
        if isinstance(stage, Mapping)
    }
    unit_merge_state: dict[str, str] = {}
    try:
        unit_state = load_unit_sessions(run_id, data_dir=data_dir)
    except UnitSessionError:
        unit_state = {}
    for unit in unit_state.get("units") or []:
        if not isinstance(unit, Mapping) or unit.get("phase_id") != phase_id:
            continue
        unit_id = _optional_str(unit.get("unit_id")) or _optional_str(unit.get("work_unit_id"))
        merge_state = _optional_str(unit.get("merge_state"))
        if unit_id and merge_state:
            unit_merge_state[unit_id] = merge_state

    out: dict[str, str] = {}
    for invocation in invocations:
        if not invocation.work_unit_id or invocation.work_unit_id in out:
            continue
        stage = stages_by_id.get(invocation.stage_id, {})
        if invocation.work_unit_id in unit_merge_state:
            out[invocation.work_unit_id] = unit_merge_state[invocation.work_unit_id]
        elif stage.get("status") in {"failed", "blocked"}:
            out[invocation.work_unit_id] = "failed"
        elif stage.get("status") == STATUS_ADOPTED:
            out[invocation.work_unit_id] = "skipped"
        else:
            out[invocation.work_unit_id] = "pending"
    return out


def _terminal_state_for_summary(
    *,
    completed: bool,
    adopted_stage_ids: set[str],
    failed_stage_ids: set[str],
    had_controller_failure: bool,
) -> str:
    if completed:
        return "complete"
    if adopted_stage_ids and (failed_stage_ids or had_controller_failure):
        return PARTIAL_SUCCESS
    if failed_stage_ids or had_controller_failure:
        return "failed"
    return "pending"


def _failure_retry_class(failure_kind: str | None) -> str | None:
    details = failure_kind_details(failure_kind)
    value = details.get("failure_retry_class")
    return value if isinstance(value, str) else None


def _retry_cycle_count(stage: Mapping[str, Any]) -> int:
    raw = stage.get("retry_cycle_count") if "retry_cycle_count" in stage else stage.get("attempt")
    if raw is None:
        raw = 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _int_or_default(value: Any, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


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


__all__ = ["MarkerDecision", "StageMarkerProcessor", "resume_stage_adoption_journals", "retry_failed_units"]
