"""Byte-parity tests for `swarm-telemetry report` (Phase 3 commit 4).

Pinned SWARM_TELEMETRY_NOW keeps --since filtering deterministic.
"""

from __future__ import annotations

import unittest

from swarm_do.telemetry.tests._parity import FIXTURES_DIR, run_parity


FIXTURE = FIXTURES_DIR / "report" / "populated"
_GOLDEN = FIXTURES_DIR / "report" / "golden"
ENV = {"SWARM_TELEMETRY_NOW": "2026-04-24T00:00:00Z"}


class ReportParityTests(unittest.TestCase):
    def test_report_default_role_bucket(self) -> None:
        run_parity(
            "report", [], FIXTURE, env_overrides=ENV, test_case=self,
            golden_stdout_path=_GOLDEN / "default_role_bucket.stdout",
        )

    def test_report_bucket_complexity(self) -> None:
        run_parity(
            "report", ["--bucket", "complexity"], FIXTURE,
            env_overrides=ENV, test_case=self,
            golden_stdout_path=_GOLDEN / "bucket_complexity.stdout",
        )

    def test_report_bucket_phase_kind(self) -> None:
        run_parity(
            "report", ["--bucket", "phase_kind"], FIXTURE,
            env_overrides=ENV, test_case=self,
            golden_stdout_path=_GOLDEN / "bucket_phase_kind.stdout",
        )

    def test_report_bucket_risk_tag(self) -> None:
        run_parity(
            "report", ["--bucket", "risk_tag"], FIXTURE,
            env_overrides=ENV, test_case=self,
            golden_stdout_path=_GOLDEN / "bucket_risk_tag.stdout",
        )

    def test_report_since_and_role_filter(self) -> None:
        run_parity(
            "report",
            ["--since", "3d", "--role", "agent-writer"],
            FIXTURE,
            env_overrides=ENV,
            test_case=self,
            golden_stdout_path=_GOLDEN / "since_role_filter.stdout",
        )

    def test_report_no_matches(self) -> None:
        run_parity(
            "report",
            ["--role", "no-such-role"],
            FIXTURE,
            env_overrides=ENV,
            test_case=self,
            golden_stdout_path=_GOLDEN / "no_matches.stdout",
        )


if __name__ == "__main__":
    unittest.main()
