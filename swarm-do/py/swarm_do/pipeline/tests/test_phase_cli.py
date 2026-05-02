from __future__ import annotations

import argparse
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from swarm_do.pipeline.cli import _build_parser, _phase_evidence_payload, cmd_phases, cmd_worktrees
from swarm_do.pipeline.operator_decisions import operator_decisions_path, record
from swarm_do.pipeline.phase_pump import pump_phases
from swarm_do.pipeline.phase_sessions import init_phase_sessions
from swarm_do.pipeline.tests.phase_session_fixtures import make_prepared_run


class PhaseCliEvidenceTests(unittest.TestCase):
    def test_happy_path_does_not_create_operator_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)

            result = pump_phases(run_id, launcher="fake-test", max_phases=None, data_dir=data)

            self.assertEqual("complete", result["status"])
            self.assertFalse(operator_decisions_path(run_id, data_dir=data).exists())

    def test_phase_redo_records_operator_decision_row(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            args = argparse.Namespace(
                phases_command="redo",
                run_id=run_id,
                phase="1",
                hard=False,
                rebuild_worktree=False,
                archive_branch=False,
                force=False,
                launcher="fake-test",
                max_phases="1",
                init=False,
                no_doctor=True,
                max_budget_usd=None,
                policy_profile=None,
                max_failed_attempt_cost_usd=None,
                max_failed_run_cost_usd=None,
                max_phase_attempt_budget_usd=None,
                json=True,
            )

            out = io.StringIO()
            with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_DATA": str(data)}):
                with redirect_stdout(out):
                    exit_code = cmd_phases(args)

            self.assertEqual(0, exit_code, out.getvalue())
            artifact = json.loads(operator_decisions_path(run_id, data_dir=data).read_text(encoding="utf-8"))
            self.assertEqual(1, len(artifact["decisions"]))
            self.assertEqual("retry_phase", artifact["decisions"][0]["kind"])

    def test_operator_decision_apply_threads_confirm_token_from_parser(self) -> None:
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
            parser = _build_parser()
            args = parser.parse_args(
                [
                    "operator-decision",
                    "apply",
                    run_id,
                    decision["decision_id"],
                    "--confirm",
                    decision["decision_id"][:8],
                    "--json",
                ]
            )
            out = io.StringIO()

            with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_DATA": str(data)}):
                with redirect_stdout(out):
                    exit_code = args.func(args)

            payload = json.loads(out.getvalue())
            self.assertEqual(2, exit_code)
            self.assertEqual("kind-not-integrated", payload["error"])

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


class WorktreeLegacyGuardTests(unittest.TestCase):
    def test_integrate_run_parser_is_registered(self) -> None:
        args = _build_parser().parse_args(
            [
                "worktrees",
                "integrate-run",
                "01ARZ3NDEKTSV4RRFFQ69G5FAV",
                "--data-dir",
                "/tmp/swarm-data",
                "--apply",
                "--json",
            ]
        )

        self.assertEqual(args.worktrees_command, "integrate-run")
        self.assertEqual(args.run_id, "01ARZ3NDEKTSV4RRFFQ69G5FAV")
        self.assertEqual(args.data_dir, "/tmp/swarm-data")
        self.assertTrue(args.apply)
        self.assertIs(args.func, cmd_worktrees)

    def test_legacy_worktree_mutators_refuse_sensitive_repo_without_override(self) -> None:
        commands = [
            _worktree_args("ensure-integration"),
            _worktree_args("add-unit"),
            _worktree_args("merge"),
        ]
        for args in commands:
            with self.subTest(command=args.worktrees_command):
                err = io.StringIO()
                with mock.patch("swarm_do.pipeline.execution_workspace.is_sensitive_path", return_value=True):
                    with redirect_stderr(err):
                        exit_code = cmd_worktrees(args)

                self.assertEqual(exit_code, 1)
                self.assertIn("legacy source-checkout worktrees are disabled for sensitive repos", err.getvalue())

    def test_legacy_worktree_mutators_allow_sensitive_repo_with_explicit_override(self) -> None:
        commands = [
            (
                _worktree_args("ensure-integration", allow_source_worktree=True),
                "swarm_do.pipeline.worktrees.ensure_integration_branch",
                "swarm/run/integration",
            ),
            (
                _worktree_args("add-unit", allow_source_worktree=True),
                "swarm_do.pipeline.worktrees.add_unit_worktree",
                (Path("/tmp/unit"), "swarm/run/unit"),
            ),
            (
                _worktree_args("merge", allow_source_worktree=True),
                "swarm_do.pipeline.worktrees.merge_unit_branch",
                SimpleNamespace(
                    integration_branch="swarm/run/integration",
                    unit_branch="swarm/run/unit",
                    head_sha="abc123",
                ),
            ),
        ]
        for args, target, return_value in commands:
            with self.subTest(command=args.worktrees_command):
                out = io.StringIO()
                with mock.patch("swarm_do.pipeline.execution_workspace.is_sensitive_path", return_value=True), mock.patch(
                    target,
                    return_value=return_value,
                ):
                    with redirect_stdout(out):
                        exit_code = cmd_worktrees(args)

                self.assertEqual(exit_code, 0)
                self.assertTrue(out.getvalue().strip())


def _worktree_args(command: str, *, allow_source_worktree: bool = False) -> argparse.Namespace:
    return argparse.Namespace(
        worktrees_command=command,
        repo="/tmp/sensitive-repo",
        run_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
        unit_id="unit-1",
        base_ref="HEAD",
        integration_branch="swarm/run/integration",
        unit_branch="swarm/run/unit",
        allow_source_worktree=allow_source_worktree,
        json=True,
    )


if __name__ == "__main__":
    unittest.main()
