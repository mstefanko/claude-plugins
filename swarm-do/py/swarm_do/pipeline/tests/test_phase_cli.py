from __future__ import annotations

import argparse
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from swarm_do.pipeline.cli import _phase_evidence_payload, cmd_phases
from swarm_do.pipeline.phase_pump import pump_phases
from swarm_do.pipeline.phase_sessions import init_phase_sessions
from swarm_do.pipeline.tests.phase_session_fixtures import make_prepared_run


class PhaseCliEvidenceTests(unittest.TestCase):
    def test_evidence_attempt_requires_phase(self) -> None:
        err = io.StringIO()
        args = argparse.Namespace(
            phases_command="evidence",
            run_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
            phase=None,
            attempt=1,
            raw_local=False,
            json=True,
        )

        with redirect_stderr(err):
            exit_code = cmd_phases(args)

        self.assertEqual(exit_code, 1)
        self.assertIn("--attempt requires --phase", err.getvalue())

    def test_evidence_raw_local_requires_json(self) -> None:
        err = io.StringIO()
        args = argparse.Namespace(
            phases_command="evidence",
            run_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
            phase="1",
            attempt=1,
            raw_local=True,
            json=False,
        )

        with redirect_stderr(err):
            exit_code = cmd_phases(args)

        self.assertEqual(exit_code, 1)
        self.assertIn("--raw-local requires --json", err.getvalue())

    def test_evidence_selectors_and_redaction_contract(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=2)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            result = pump_phases(run_id, launcher="fake-test", max_phases=None, data_dir=data)
            self.assertEqual(result["status"], "complete")

            with mock.patch("swarm_do.pipeline.cli.resolve_data_dir", return_value=data):
                all_payload, all_code = _phase_evidence_payload(run_id, phase_id=None, attempt=None, raw_local=False)
                phase_payload, phase_code = _phase_evidence_payload(run_id, phase_id="1", attempt=None, raw_local=False)
                exact_payload, exact_code = _phase_evidence_payload(run_id, phase_id="1", attempt=1, raw_local=False)
                raw_payload, raw_code = _phase_evidence_payload(run_id, phase_id="1", attempt=1, raw_local=True)

        self.assertEqual(all_code, 0)
        self.assertEqual(all_payload["count"], 2)
        self.assertEqual(phase_code, 0)
        self.assertEqual(phase_payload["count"], 1)
        self.assertEqual(exact_code, 0)
        self.assertEqual(exact_payload["count"], 1)
        redacted = exact_payload["manifests"][0]
        self.assertIn("evidence_path", redacted)
        self.assertNotIn("paths", redacted)
        self.assertEqual(raw_code, 0)
        raw_manifest = raw_payload["manifests"][0]
        self.assertIn("paths", raw_manifest)
        self.assertIn("redaction", raw_manifest)
        self.assertFalse(raw_manifest["redaction"]["contains_raw_prompt"])

    def test_evidence_broad_old_run_can_return_zero_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)

            with mock.patch("swarm_do.pipeline.cli.resolve_data_dir", return_value=data):
                payload, exit_code = _phase_evidence_payload(run_id, phase_id=None, attempt=None, raw_local=False)

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["count"], 0)

    def test_evidence_specific_selector_without_manifest_exits_two(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)

            with mock.patch("swarm_do.pipeline.cli.resolve_data_dir", return_value=data):
                payload, exit_code = _phase_evidence_payload(run_id, phase_id="1", attempt=1, raw_local=False)

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["count"], 0)

    def test_evidence_missing_state_or_invalid_manifest_exits_three(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data = Path(td) / "data"
            data.mkdir()
            with mock.patch("swarm_do.pipeline.cli.resolve_data_dir", return_value=data):
                missing_payload, missing_code = _phase_evidence_payload(
                    "01ARZ3NDEKTSV4RRFFQ69G5FAV",
                    phase_id=None,
                    attempt=None,
                    raw_local=False,
                )
            self.assertEqual(missing_code, 3)
            self.assertIn("error", missing_payload)

        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            result = pump_phases(run_id, launcher="fake-test", max_phases=None, data_dir=data)
            self.assertEqual(result["status"], "complete")
            manifest_path = data / "runs" / run_id / "phase_launches" / "1" / "attempt-1" / "evidence.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["unexpected"] = True
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with mock.patch("swarm_do.pipeline.cli.resolve_data_dir", return_value=data):
                invalid_payload, invalid_code = _phase_evidence_payload(run_id, phase_id="1", attempt=1, raw_local=False)

        self.assertEqual(invalid_code, 3)
        self.assertIn("unexpected property", invalid_payload["error"])


if __name__ == "__main__":
    unittest.main()
