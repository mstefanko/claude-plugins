"""Byte-parity tests for `swarm-telemetry query <sql>` (Phase 3 commit 3).

Fixture exercises COUNT aggregation, ORDER BY, and cross-ledger JOIN so the
SQL execution surface matches the legacy implementation (sqlite3 :memory:
with LEDGER_COLS schema).
"""

from __future__ import annotations

import unittest

from swarm_do.telemetry.tests._parity import FIXTURES_DIR, run_parity


FIXTURE = FIXTURES_DIR / "query" / "populated"


class QueryParityTests(unittest.TestCase):
    def test_count_runs(self) -> None:
        run_parity(
            "query",
            ["SELECT COUNT(*) AS n FROM runs"],
            FIXTURE,
            test_case=self,
        )

    def test_order_by_findings(self) -> None:
        run_parity(
            "query",
            ["SELECT finding_id, severity FROM findings ORDER BY finding_id"],
            FIXTURE,
            test_case=self,
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
        )

    def test_query_error(self) -> None:
        run_parity(
            "query",
            ["SELECT * FROM no_such_table"],
            FIXTURE,
            test_case=self,
        )


if __name__ == "__main__":
    unittest.main()
