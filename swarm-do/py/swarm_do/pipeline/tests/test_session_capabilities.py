from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from swarm_do.pipeline.session_capabilities import doctor_report, parse_claude_print_json


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
            (fixture_dir / "success.json").write_text("{}\n", encoding="utf-8")
            report = doctor_report(live=True, runner=runner, repo_root=Path(td))
        launchers = {item["name"]: item for item in report["launchers"]}
        self.assertTrue(launchers["claude-print"]["eligible"])
        self.assertTrue(calls)

    def test_malformed_claude_print_json_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_claude_print_json("not json")
        with self.assertRaises(ValueError):
            parse_claude_print_json("[]")


if __name__ == "__main__":
    unittest.main()
