from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline.phase_attempts import summarize_phase_attempts
from swarm_do.pipeline.phase_sessions import claim_next_phase, init_phase_sessions, phase_session_path, start_phase
from swarm_do.pipeline.tests.phase_session_fixtures import make_prepared_run


class PhaseAttemptSummaryTests(unittest.TestCase):
    def test_valid_claude_stdout_produces_provider_cost_and_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            start_phase(run_id, "1", launcher="claude-print", lease_owner="owner-1", data_dir=data)
            _write_stdout(
                data,
                run_id,
                "1",
                1,
                {
                    "total_cost_usd": 0.42,
                    "usage": {
                        "input_tokens": 10,
                        "cache_creation_input_tokens": 2,
                        "cache_read_input_tokens": 3,
                        "output_tokens": 4,
                    },
                    "permission_denials": [{"tool": "Bash"}],
                },
            )

            summary = summarize_phase_attempts(run_id, data_dir=data)

            self.assertEqual(summary["cost"]["total_usd"], 0.42)
            self.assertEqual(summary["cost"]["unknown_attempt_count"], 0)
            row = summary["attempts"]["rows"][0]
            self.assertEqual(row["cost_confidence"], "provider_reported")
            self.assertEqual(row["input_tokens"], 10)
            self.assertEqual(row["permission_denial_count"], 1)

    def test_missing_and_invalid_stdout_are_unknown_not_zero(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            start_phase(run_id, "1", launcher="claude-print", lease_owner="owner-1", data_dir=data)

            missing = summarize_phase_attempts(run_id, data_dir=data)
            self.assertEqual(missing["cost"]["total_usd"], 0.0)
            self.assertEqual(missing["cost"]["unknown_attempt_count"], 1)
            self.assertIsNone(missing["attempts"]["rows"][0]["total_cost_usd"])

            stdout = data / "runs" / run_id / "phase_launches" / "1" / "attempt-1" / "stdout.txt"
            stdout.parent.mkdir(parents=True, exist_ok=True)
            stdout.write_text("not-json", encoding="utf-8")
            invalid = summarize_phase_attempts(run_id, data_dir=data)
            self.assertEqual(invalid["cost"]["unknown_attempt_count"], 1)
            self.assertIn("stdout_parse_error", invalid["attempts"]["rows"][0])

    def test_archived_attempts_are_summarized_without_rows_until_requested(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            archive = data / "runs" / run_id / ".archived-test" / "phase_launches" / "1" / "attempt-1"
            archive.mkdir(parents=True, exist_ok=True)
            (archive / "stdout.txt").write_text(json.dumps({"total_cost_usd": 1.25}), encoding="utf-8")

            summary = summarize_phase_attempts(run_id, data_dir=data)
            self.assertEqual(summary["cost"]["archived_provider_reported_usd"], 1.25)
            self.assertEqual(summary["attempts"]["rows"], [])

            with_archived = summarize_phase_attempts(run_id, data_dir=data, include_archived=True)
            self.assertEqual(len(with_archived["attempts"]["rows"]), 1)
            self.assertTrue(with_archived["attempts"]["rows"][0]["archived"])

    def test_cost_conflict_preserves_both_sources(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            start_phase(run_id, "1", launcher="claude-print", lease_owner="owner-1", data_dir=data)
            _write_stdout(
                data,
                run_id,
                "1",
                1,
                {"total_cost_usd": 1.0, "modelUsage": {"claude": {"costUSD": 2.0}}},
            )

            summary = summarize_phase_attempts(run_id, data_dir=data)
            row = summary["attempts"]["rows"][0]
            self.assertEqual(row["cost_confidence"], "conflict")
            self.assertEqual(row["provider_reported_total_cost_usd"], 1.0)
            self.assertEqual(row["model_usage_cost_usd"], 2.0)
            self.assertIsNone(row["total_cost_usd"])
            self.assertEqual(summary["cost"]["total_usd"], 0.0)
            self.assertEqual(summary["cost"]["failed_usd"], 0.0)
            self.assertEqual(summary["cost"]["unknown_attempt_count"], 1)

    def test_legacy_command_without_settings_path_is_readable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            start_phase(run_id, "1", launcher="claude-print", lease_owner="owner-1", data_dir=data)
            launch = data / "runs" / run_id / "phase_launches" / "1" / "attempt-1"
            launch.mkdir(parents=True, exist_ok=True)
            (launch / "command.json").write_text(
                json.dumps({"returncode": 0, "result_path": "legacy.result.json", "handoff_path": "legacy.handoff.json"}),
                encoding="utf-8",
            )
            _write_stdout(data, run_id, "1", 1, {"total_cost_usd": 0.01})

            summary = summarize_phase_attempts(run_id, data_dir=data)

            row = summary["attempts"]["rows"][0]
            self.assertEqual(row["launcher_returncode"], 0)
            self.assertEqual(summary["cost"]["total_usd"], 0.01)

    def test_legacy_attempt_history_derives_taxonomy_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
            start_phase(run_id, "1", launcher="claude-print", lease_owner="owner-1", data_dir=data)
            path = phase_session_path(run_id, data_dir=data)
            state = json.loads(path.read_text(encoding="utf-8"))
            phase = state["phases"][0]
            phase["attempt_history"].append(
                {
                    "attempt": 1,
                    "failure_kind": "launcher_nonzero_no_artifacts",
                    "retry_decision": "retry",
                    "adopted": False,
                    "partial_artifacts": False,
                    "artifact_error_kinds": [],
                    "changed_files": [],
                }
            )
            path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            summary = summarize_phase_attempts(run_id, data_dir=data)

            row = summary["attempts"]["rows"][0]
            self.assertEqual(row["failure_category"], "launcher")
            self.assertEqual(row["failure_retry_class"], "retry")
            self.assertEqual(summary["last_failure"], None)


def _write_stdout(data: Path, run_id: str, phase_id: str, attempt: int, payload: dict) -> None:
    path = data / "runs" / run_id / "phase_launches" / phase_id / f"attempt-{attempt}" / "stdout.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
