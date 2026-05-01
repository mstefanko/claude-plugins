from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from swarm_do.pipeline.phase_evidence import read_attempt_evidence_manifest
from swarm_do.pipeline.phase_recovery import reconcile_phase_sessions
from swarm_do.pipeline.phase_sessions import (
    claim_next_phase,
    init_phase_sessions,
    phase_handoff_path,
    phase_result_path,
    phase_session_path,
    record_phase_result,
    start_phase,
)
from swarm_do.pipeline.tests.phase_session_fixtures import make_prepared_run


class PhaseEvidenceTests(unittest.TestCase):
    def test_successful_result_recording_writes_redacted_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            started = start_phase(run_id, "1", launcher="manual", lease_owner="owner-1", data_dir=data)
            result_path = _write_result(data, run_id, started["phase"], status="complete")

            recorded = record_phase_result(run_id, "1", json_file=result_path, expected_status="complete", data_dir=data)

            evidence_path = Path(recorded["phase"]["evidence_path"])
            self.assertEqual(evidence_path.name, "evidence.json")
            self.assertEqual(evidence_path.parent.name, "attempt-1")
            manifest = read_attempt_evidence_manifest(evidence_path)
            self.assertEqual(manifest["status"], "complete")
            self.assertTrue(manifest["artifacts"]["result_valid"])
            self.assertFalse(manifest["redaction"]["contains_raw_prompt"])
            self.assertNotIn("Implement phase 1.", evidence_path.read_text(encoding="utf-8"))

    def test_manifest_schema_rejects_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            started = start_phase(run_id, "1", launcher="manual", lease_owner="owner-1", data_dir=data)
            result_path = _write_result(data, run_id, started["phase"], status="complete")
            recorded = record_phase_result(run_id, "1", json_file=result_path, expected_status="complete", data_dir=data)
            evidence_path = Path(recorded["phase"]["evidence_path"])
            payload = json.loads(evidence_path.read_text(encoding="utf-8"))
            payload["raw_prompt"] = "nope"
            evidence_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "unexpected property"):
                read_attempt_evidence_manifest(evidence_path)

    def test_manifest_schema_rejects_missing_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            started = start_phase(run_id, "1", launcher="manual", lease_owner="owner-1", data_dir=data)
            result_path = _write_result(data, run_id, started["phase"], status="complete")
            recorded = record_phase_result(run_id, "1", json_file=result_path, expected_status="complete", data_dir=data)
            evidence_path = Path(recorded["phase"]["evidence_path"])
            payload = json.loads(evidence_path.read_text(encoding="utf-8"))
            payload["paths"].pop("launch_dir")
            evidence_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "missing required property 'launch_dir'"):
                read_attempt_evidence_manifest(evidence_path)

    def test_cli_evidence_payload_returns_redacted_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            started = start_phase(run_id, "1", launcher="manual", lease_owner="owner-1", data_dir=data)
            result_path = _write_result(data, run_id, started["phase"], status="complete")
            record_phase_result(run_id, "1", json_file=result_path, expected_status="complete", data_dir=data)

            from unittest import mock
            from swarm_do.pipeline.cli import _phase_evidence_payload

            with mock.patch("swarm_do.pipeline.cli.resolve_data_dir", return_value=data):
                payload, exit_code = _phase_evidence_payload(run_id, phase_id="1", attempt=1, raw_local=False)

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["count"], 1)
            manifest = payload["manifests"][0]
            self.assertEqual(manifest["phase_id"], "1")
            self.assertIn("evidence_path", manifest)
            self.assertNotIn("paths", manifest)

    def test_retry_recovery_manifest_records_failure_taxonomy_and_paths(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            start_phase(run_id, "1", launcher="claude-print", lease_owner="owner-1", data_dir=data)
            state_path = phase_session_path(run_id, data_dir=data)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["phases"][0]["lease_expires_at"] = "2026-01-01T00:00:00Z"
            state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            reconcile_phase_sessions(run_id, data_dir=data, repo_root=repo, now=datetime(2026, 4, 29, tzinfo=UTC))

            state = json.loads(state_path.read_text(encoding="utf-8"))
            history = state["phases"][0]["attempt_history"][0]
            manifest = read_attempt_evidence_manifest(Path(history["evidence_path"]))
            self.assertEqual(manifest["failure"]["failure_kind"], "lease_expired_no_artifacts")
            self.assertEqual(manifest["failure"]["failure_category"], "lifecycle")
            self.assertEqual(manifest["failure"]["retry_decision"], "retry")
            self.assertEqual(manifest["failure"]["policy_action"], "retry_after_backoff")
            self.assertEqual(manifest["failure"]["policy_reason"], "normal_retry")
            self.assertEqual(manifest["failure"]["policy_inputs"]["failure_kind"], "lease_expired_no_artifacts")
            self.assertTrue(Path(manifest["recovery"]["recovery_context_path"]).is_file())

    def test_safe_worktree_evidence_manifest_includes_git_base_ref_and_copied_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            started = start_phase(run_id, "1", launcher="manual", lease_owner="owner-1", data_dir=data)
            _write_command(
                data,
                run_id,
                "1",
                1,
                {
                    "execution_workspace_mode": "safe-worktree",
                    "git_base_ref": "main",
                    "git_base_sha": "0" * 40,
                    "copied_ignored_artifacts": [
                        {
                            "relative_path": "data/runs/example/prepared_plan.v1.json",
                            "kind": "prepared_artifact",
                        }
                    ],
                },
            )
            result_path = _write_result(data, run_id, started["phase"], status="complete")

            recorded = record_phase_result(run_id, "1", json_file=result_path, expected_status="complete", data_dir=data)

            manifest = read_attempt_evidence_manifest(Path(recorded["phase"]["evidence_path"]))
            self.assertEqual(manifest["workspace"]["git_base_ref"], "main")
            self.assertEqual(
                manifest["workspace"]["copied_ignored_artifacts"][0]["kind"],
                "prepared_artifact",
            )


def _write_result(data: Path, run_id: str, phase: dict, *, status: str) -> Path:
    phase_id = phase["phase_id"]
    attempt = int(phase["attempt"])
    result_path = phase_result_path(run_id, phase_id, attempt, data_dir=data)
    handoff_path = phase_handoff_path(run_id, phase_id, attempt, data_dir=data)
    state = json.loads(phase_session_path(run_id, data_dir=data).read_text(encoding="utf-8"))
    prepared = json.loads((data / "runs" / run_id / "prepared_plan.v1.json").read_text(encoding="utf-8"))
    phase_sha = next(item["content_sha"] for item in prepared["phase_map"] if item["phase_id"] == phase_id)
    now = "2026-04-29T00:00:00Z"
    handoff = {
        "schema_version": 1,
        "run_id": run_id,
        "phase_id": phase_id,
        "phase_attempt": attempt,
        "status": status,
        "written_at": now,
        "summary": status,
        "decisions": [],
        "changed_files": ["docs/phase-1.md"],
        "completed_work_units": [],
        "open_items": [],
        "blockers": [],
        "do_not_retry": [],
        "validation_summary": [],
        "artifacts": [],
        "next_phase_context": [],
    }
    result = {
        "schema_version": 1,
        "run_id": run_id,
        "phase_id": phase_id,
        "phase_attempt": attempt,
        "status": status,
        "launcher": "manual",
        "session_name": phase["session_name"],
        "prepared_plan_sha": state["prepared_plan_sha"],
        "phase_content_sha": phase_sha,
        "started_at": phase["started_at"],
        "completed_at": now,
        "handoff_path": str(handoff_path),
        "summary": status,
        "completed_work_units": [],
        "failed_work_units": [],
        "blocked_reason": None,
        "needs_input": [],
        "validation": [],
        "artifacts": [],
        "error": None,
    }
    handoff_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    handoff_path.write_text(json.dumps(handoff, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result_path


def _write_command(data: Path, run_id: str, phase_id: str, attempt: int, payload: dict) -> Path:
    path = data / "runs" / run_id / "phase_launches" / phase_id / f"attempt-{attempt}" / "command.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    unittest.main()
