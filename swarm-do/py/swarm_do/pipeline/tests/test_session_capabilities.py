from __future__ import annotations

import subprocess
import tempfile
import unittest
import json
from pathlib import Path
from unittest import mock

from swarm_do.pipeline.paths import REPO_ROOT
from swarm_do.pipeline import session_capabilities
from swarm_do.pipeline.session_capabilities import (
    doctor_report,
    extract_claude_print_artifacts,
    parse_claude_print_json,
)


class SessionCapabilitiesTests(unittest.TestCase):
    def test_default_report_keeps_manual_and_fake_test_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report = doctor_report(repo_root=Path(td))
        launchers = {item["name"]: item for item in report["launchers"]}
        self.assertTrue(launchers["manual"]["eligible"])
        self.assertTrue(launchers["fake-test"]["eligible"])
        self.assertFalse(launchers["claude-print"]["eligible"])
        self.assertIn("claude_print_fixtures_missing", launchers["claude-print"]["hard_blockers"])

    def test_live_probe_uses_injected_runner(self) -> None:
        calls = []

        def runner(argv):
            calls.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, stdout="claude 1.0\n", stderr="")

        with tempfile.TemporaryDirectory() as td, mock.patch("shutil.which", return_value="/usr/bin/claude"):
            fixture_dir = Path(td) / "py" / "swarm_do" / "pipeline" / "tests" / "fixtures" / "claude_print"
            fixture_dir.mkdir(parents=True)
            for source in (REPO_ROOT / "py" / "swarm_do" / "pipeline" / "tests" / "fixtures" / "claude_print").glob("*.json"):
                (fixture_dir / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            report = doctor_report(live=True, runner=runner, repo_root=Path(td))
        launchers = {item["name"]: item for item in report["launchers"]}
        self.assertTrue(launchers["claude-print"]["eligible"])
        self.assertTrue(calls)

    def test_claude_print_stream_json_probe_supported(self) -> None:
        def runner(argv):
            if argv[-1] == "--help":
                return subprocess.CompletedProcess(argv, 0, stdout="--output-format text,json,stream-json\n", stderr="")
            return subprocess.CompletedProcess(argv, 0, stdout="claude 1.0\n", stderr="")

        with tempfile.TemporaryDirectory() as td, mock.patch("shutil.which", return_value="/usr/bin/claude-stream-supported"):
            session_capabilities._STREAM_JSON_SUPPORT_CACHE.clear()
            fixture_dir = Path(td) / "py" / "swarm_do" / "pipeline" / "tests" / "fixtures" / "claude_print"
            fixture_dir.mkdir(parents=True)
            for source in (REPO_ROOT / "py" / "swarm_do" / "pipeline" / "tests" / "fixtures" / "claude_print").glob("*.json"):
                (fixture_dir / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            report = doctor_report(live=True, runner=runner, repo_root=Path(td))

        launchers = {item["name"]: item for item in report["launchers"]}
        self.assertTrue(launchers["claude-print"]["details"]["stream_json_supported"])

    def test_claude_print_stream_json_probe_unsupported(self) -> None:
        def runner(argv):
            if argv[-1] == "--help":
                return subprocess.CompletedProcess(argv, 0, stdout="--output-format text,json\n", stderr="")
            return subprocess.CompletedProcess(argv, 0, stdout="claude 1.0\n", stderr="")

        with tempfile.TemporaryDirectory() as td, mock.patch("shutil.which", return_value="/usr/bin/claude-stream-unsupported"):
            session_capabilities._STREAM_JSON_SUPPORT_CACHE.clear()
            fixture_dir = Path(td) / "py" / "swarm_do" / "pipeline" / "tests" / "fixtures" / "claude_print"
            fixture_dir.mkdir(parents=True)
            for source in (REPO_ROOT / "py" / "swarm_do" / "pipeline" / "tests" / "fixtures" / "claude_print").glob("*.json"):
                (fixture_dir / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            report = doctor_report(live=True, runner=runner, repo_root=Path(td))

        launchers = {item["name"]: item for item in report["launchers"]}
        self.assertFalse(launchers["claude-print"]["details"]["stream_json_supported"])

    def test_malformed_claude_print_json_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_claude_print_json("not json")
        with self.assertRaises(ValueError):
            parse_claude_print_json("[]")

    def test_committed_claude_print_fixtures_normalize(self) -> None:
        fixture_dir = REPO_ROOT / "py" / "swarm_do" / "pipeline" / "tests" / "fixtures" / "claude_print"
        for name in ("success.json", "failed.json", "blocked.json", "needs_input.json"):
            payload = parse_claude_print_json((fixture_dir / name).read_text(encoding="utf-8"))
            artifacts = extract_claude_print_artifacts(payload, run_dir=fixture_dir)
            self.assertIn(artifacts["status"], {"complete", "failed", "blocked", "needs_input"})
            self.assertTrue(artifacts["result_path"].startswith(str(fixture_dir)))

    def test_extract_rejects_bad_artifact_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            with self.assertRaises(ValueError):
                extract_claude_print_artifacts({"status": "complete"}, run_dir=run_dir)
            with self.assertRaises(ValueError):
                extract_claude_print_artifacts({"result": json.dumps({"result_path": "x", "handoff_path": "y"})}, run_dir=run_dir)
            with self.assertRaises(ValueError):
                extract_claude_print_artifacts(
                    {"result": json.dumps({"status": "weird", "result_path": "x", "handoff_path": "y"})},
                    run_dir=run_dir,
                )
            with self.assertRaises(ValueError):
                extract_claude_print_artifacts(
                    {"result": json.dumps({"status": "complete", "result_path": "/tmp/outside", "handoff_path": "y"})},
                    run_dir=run_dir,
                )


if __name__ == "__main__":
    unittest.main()
