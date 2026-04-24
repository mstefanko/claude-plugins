"""Byte-parity tests for `swarm-telemetry query <sql>` (Phase 3 commit 3).

Fixture exercises COUNT aggregation, ORDER BY, and cross-ledger JOIN so the
SQL execution surface matches the legacy implementation (sqlite3 :memory:
with LEDGER_COLS schema).
"""

from __future__ import annotations

import unittest

from swarm_do.telemetry.tests._parity import FIXTURES_DIR, run_parity


FIXTURE = FIXTURES_DIR / "query" / "populated"
_GOLDEN = FIXTURES_DIR / "query" / "golden"


class QueryParityTests(unittest.TestCase):
    def test_count_runs(self) -> None:
        run_parity(
            "query",
            ["SELECT COUNT(*) AS n FROM runs"],
            FIXTURE,
            test_case=self,
            golden_stdout_path=_GOLDEN / "count_runs.stdout",
            golden_exit_path=_GOLDEN / "count_runs.exit",
        )

    def test_order_by_findings(self) -> None:
        run_parity(
            "query",
            ["SELECT finding_id, severity FROM findings ORDER BY finding_id"],
            FIXTURE,
            test_case=self,
            golden_stdout_path=_GOLDEN / "order_by_findings.stdout",
            golden_exit_path=_GOLDEN / "order_by_findings.exit",
        )

    def test_join_runs_findings(self) -> None:
        run_parity(
            "query",
            [
                "SELECT r.run_id, r.role, f.finding_id, f.severity "
                "FROM runs r JOIN findings f ON f.run_id = r.run_id "
                "ORDER BY r.run_id, f.finding_id"
            ],
            FIXTURE,
            test_case=self,
            golden_stdout_path=_GOLDEN / "join_runs_findings.stdout",
            golden_exit_path=_GOLDEN / "join_runs_findings.exit",
        )

    def test_query_error(self) -> None:
        run_parity(
            "query",
            ["SELECT * FROM no_such_table"],
            FIXTURE,
            test_case=self,
            golden_stdout_path=_GOLDEN / "query_error.stdout",
            golden_exit_path=_GOLDEN / "query_error.exit",
        )


if __name__ == "__main__":
    unittest.main()
