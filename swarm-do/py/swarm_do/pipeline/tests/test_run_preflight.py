from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from swarm_do.pipeline.beads_health import beads_where
from swarm_do.pipeline.providers import ProviderCheck
from swarm_do.pipeline.run_preflight import record_run_preflight_completed, run_preflight


RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"


class BeadsHealthTests(unittest.TestCase):
    def test_beads_where_uses_bd_where(self) -> None:
        calls: list[list[str]] = []

        def runner(argv, **kwargs):
            calls.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, stdout="/tmp/repo/.beads\n", stderr="")

        result = beads_where(
            Path("/tmp/repo"),
            which=lambda cmd: "/bin/bd" if cmd == "bd" else None,
            runner=runner,
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.rig, "/tmp/repo/.beads")
        self.assertEqual(calls, [["bd", "where"]])


class RunPreflightTests(unittest.TestCase):
    def test_preflight_records_valid_event_after_successful_checks(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data = Path(td) / "data"
            repo = Path(td) / "repo"
            repo.mkdir()
            with mock.patch(
                "swarm_do.pipeline.run_preflight.beads_where",
                return_value=SimpleNamespace(
                    ok=True,
                    summary="Beads rig detected",
                    remediation=None,
                    as_dict=lambda: {"ok": True, "rig": str(repo / ".beads")},
                ),
            ), mock.patch(
                "swarm_do.pipeline.providers.provider_doctor",
                return_value=SimpleNamespace(
                    checks=(ProviderCheck("backend:claude", "ok", "claude version probe completed", {"path": "/bin/claude"}),)
                ),
            ), mock.patch(
                "swarm_do.pipeline.session_capabilities.doctor_report",
                return_value={
                    "launchers": [
                        {"name": "claude-print", "eligible": True, "hard_blockers": [], "warnings": []}
                    ]
                },
            ):
                report = run_preflight(
                    run_id=RUN_ID,
                    target_repo=repo,
                    data_dir=data,
                    preset="default",
                    graph_source="stock-ref",
                    graph_source_name="default",
                    launchers=("claude-print",),
                    git_base_sha="a" * 40,
                )
                self.assertTrue(report.ok, report.as_dict())
                record_run_preflight_completed(run_id=RUN_ID, report=report, data_dir=data)

            events = [
                json.loads(line)
                for line in (data / "telemetry" / "run_events.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(events[-1]["event_type"], "run_preflight_completed")
            self.assertTrue(events[-1]["details"]["ok"])

    def test_preflight_blocks_zero_git_base_and_bad_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            with mock.patch(
                "swarm_do.pipeline.run_preflight.beads_where",
                return_value=SimpleNamespace(ok=True, summary="ok", remediation=None, as_dict=lambda: {"ok": True}),
            ), mock.patch(
                "swarm_do.pipeline.providers.provider_doctor",
                return_value=SimpleNamespace(checks=()),
            ), mock.patch(
                "swarm_do.pipeline.session_capabilities.doctor_report",
                return_value={"launchers": [{"name": "claude-print", "eligible": False, "hard_blockers": ["missing"]}]},
            ):
                report = run_preflight(
                    run_id=RUN_ID,
                    target_repo=repo,
                    data_dir=Path(td) / "data",
                    launchers=("claude-print",),
                    git_base_sha="0" * 40,
                )

        self.assertIn("prepared-git-base-zero", report.blocker_ids)
        self.assertIn("launcher:claude-print", report.blocker_ids)


if __name__ == "__main__":
    unittest.main()
