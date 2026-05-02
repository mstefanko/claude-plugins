from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from swarm_do.pipeline import operator_decisions
from swarm_do.pipeline.operator_decisions import (
    OperatorDecisionError,
    apply,
    operator_decisions_path,
    record,
)
from swarm_do.pipeline.phase_sessions import claim_next_phase, init_phase_sessions, phase_session_path, start_phase
from swarm_do.pipeline.tests.phase_session_fixtures import make_prepared_run


class OperatorDecisionTests(unittest.TestCase):
    def test_record_is_idempotent_within_minute(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            payload = {"phase_id": "1", "reason": "try again"}

            with mock.patch("swarm_do.pipeline.operator_decisions.utc_now", return_value="2026-05-02T17:30:41Z"):
                first = record(run_id, "retry_phase", payload, data_dir=data, operator="local:test")
                second = record(run_id, "retry_phase", payload, data_dir=data, operator="local:test")

            self.assertEqual(first["decision"]["decision_id"], second["decision"]["decision_id"])
            artifact = _artifact(data, run_id)
            self.assertEqual(1, len(artifact["decisions"]))

    def test_apply_is_append_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = _running_run(Path(td))
            decision = record(
                run_id,
                "retry_phase",
                {"phase_id": "1", "reason": "operator retry"},
                data_dir=data,
                operator="local:test",
            )["decision"]
            before = _artifact(data, run_id)
            before_decisions = json.dumps(before["decisions"], sort_keys=True)
            before_events = len(before["events"])

            result = apply(run_id, decision["decision_id"], data_dir=data)

            self.assertTrue(result["applied"])
            after = _artifact(data, run_id)
            self.assertEqual(before_decisions, json.dumps(after["decisions"], sort_keys=True))
            self.assertEqual(before_events + 1, len(after["events"]))
            state = json.loads(phase_session_path(run_id, data_dir=data).read_text(encoding="utf-8"))
            history = state["phases"][0]["attempt_history"]
            self.assertEqual(decision["decision_id"], history[-1]["operator_decision_id"])

    def test_destructive_kind_requires_confirm_token(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            decision = record(
                run_id,
                "rebuild_worktree",
                {"phase_id": "1", "reason": "fresh tree", "archive_branch": False},
                data_dir=data,
                operator="local:test",
            )["decision"]

            with self.assertRaises(OperatorDecisionError) as ctx:
                apply(run_id, decision["decision_id"], data_dir=data)

            self.assertEqual("confirm-required", ctx.exception.error)
            self.assertEqual(decision["decision_id"][:8], ctx.exception.details["confirm_token"])

    def test_resume_with_input_payload_is_redacted_in_run_events(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            secret = "operator pasted a private token"

            record(
                run_id,
                "resume_with_input",
                {"phase_id": "1", "input": {"answer": secret}},
                data_dir=data,
                operator="local:test",
            )

            event = [row for row in _run_events(data) if row["event_type"] == "operator_decision_recorded"][-1]
            summary = event["details"]["payload_summary"]
            self.assertTrue(summary["redacted"])
            self.assertIn("sha1", summary)
            self.assertNotIn(secret, json.dumps(event, sort_keys=True))

    def test_apply_acquires_phase_session_lock(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = _running_run(Path(td))
            decision = record(
                run_id,
                "retry_phase",
                {"phase_id": "1", "reason": "operator retry"},
                data_dir=data,
                operator="local:test",
            )["decision"]

            with mock.patch(
                "swarm_do.pipeline.operator_decisions.locked_phase_sessions",
                wraps=operator_decisions.locked_phase_sessions,
            ) as lock:
                apply(run_id, decision["decision_id"], data_dir=data)

            lock.assert_called()

    def test_apply_on_destructive_kind_already_applied_is_controlled_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = _running_run(Path(td))
            decision = record(
                run_id,
                "retry_phase",
                {"phase_id": "1", "reason": "operator retry"},
                data_dir=data,
                operator="local:test",
            )["decision"]
            apply(run_id, decision["decision_id"], data_dir=data)

            with self.assertRaises(OperatorDecisionError) as ctx:
                apply(run_id, decision["decision_id"], data_dir=data)

            self.assertEqual("decision-already-applied", ctx.exception.error)
            self.assertEqual(2, ctx.exception.exit_code)

    def test_apply_on_nondestructive_kind_already_applied_is_noop(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            decision = record(
                run_id,
                "abort_phase",
                {"phase_id": "1", "reason": "operator abort"},
                data_dir=data,
                operator="local:test",
            )["decision"]
            _append_applied_event(data, run_id, decision["decision_id"])
            before = len(_artifact(data, run_id)["events"])

            result = apply(run_id, decision["decision_id"], data_dir=data)

            self.assertFalse(result["applied"])
            self.assertTrue(result["noop"])
            self.assertEqual(before + 1, len(_artifact(data, run_id)["events"]))

    def test_record_rejects_unknown_payload_keys(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)

            with self.assertRaises(OperatorDecisionError) as ctx:
                record(
                    run_id,
                    "retry_phase",
                    {"phase_id": "1", "reason": "try again", "extra": True},
                    data_dir=data,
                    operator="local:test",
                )

            self.assertEqual("invalid-payload", ctx.exception.error)
            self.assertEqual(["extra"], ctx.exception.details["unknown_keys"])

    def test_record_fails_when_run_directory_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data = Path(td) / "data"
            data.mkdir()

            with self.assertRaises(OperatorDecisionError) as ctx:
                record(
                    "01ARZ3NDEKTSV4RRFFQ69G5FAV",
                    "retry_phase",
                    {"phase_id": "1", "reason": "try again"},
                    data_dir=data,
                    operator="local:test",
                )

            self.assertEqual("run-not-found", ctx.exception.error)


def _running_run(tmp: Path) -> tuple[Path, Path, str]:
    repo, data, run_id = make_prepared_run(tmp, phase_count=1)
    init_phase_sessions(run_id, data_dir=data, repo_root=repo)
    claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="owner-1")
    start_phase(run_id, "1", launcher="claude-print", lease_owner="owner-1", data_dir=data)
    return repo, data, run_id


def _artifact(data: Path, run_id: str) -> dict:
    path = operator_decisions_path(run_id, data_dir=data)
    return json.loads(path.read_text(encoding="utf-8"))


def _append_applied_event(data: Path, run_id: str, decision_id: str) -> None:
    path = operator_decisions_path(run_id, data_dir=data)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.setdefault("events", []).append(
        {
            "event_id": "ode-test-applied",
            "decision_id": decision_id,
            "event_type": "applied",
            "created_at": "2026-05-02T17:31:00Z",
            "status": "applied",
            "applied_at": "2026-05-02T17:31:00Z",
            "applied_event_path": str(data / "telemetry" / "run_events.jsonl"),
        }
    )
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run_events(data: Path) -> list[dict]:
    path = data / "telemetry" / "run_events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    unittest.main()
