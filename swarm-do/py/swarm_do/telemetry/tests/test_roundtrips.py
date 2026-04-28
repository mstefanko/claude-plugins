from __future__ import annotations

import unittest

from swarm_do.telemetry.subcommands.roundtrips import aggregate_roundtrips


def _run(role: str, unit: str, ts: str, **extras) -> dict:
    return {
        "role": role,
        "work_unit_id": unit,
        "timestamp_start": ts,
        "wall_clock_seconds": 1.5,
        **extras,
    }


class RoundtripAggregationTests(unittest.TestCase):
    def test_groups_writer_and_review_runs_per_unit(self) -> None:
        rows = [
            _run("agent-writer", "unit-1", "2026-04-28T10:00:00Z", writer_status="ok"),
            _run("agent-spec-review", "unit-1", "2026-04-28T10:01:00Z", review_verdict="fail"),
            _run("agent-writer", "unit-1", "2026-04-28T10:02:00Z", writer_status="ok", unit_retry_count=1),
            _run("agent-review", "unit-1", "2026-04-28T10:03:00Z", review_verdict="approve"),
        ]

        report = aggregate_roundtrips(rows)

        self.assertEqual(report["summary"]["unit_count"], 1)
        self.assertEqual(report["summary"]["writer_runs_total"], 2)
        unit = report["units"][0]
        self.assertEqual(unit["unit_id"], "unit-1")
        self.assertEqual(unit["writer_runs"], 2)
        self.assertEqual(unit["spec_review_runs"], 1)
        self.assertEqual(unit["review_runs"], 1)
        self.assertEqual(unit["max_retry_count"], 1)
        self.assertEqual(unit["writer_statuses"], ["ok", "ok"])
        self.assertEqual(unit["spec_review_verdicts"], ["fail"])
        self.assertEqual(unit["review_verdicts"], ["approve"])

    def test_filters_by_variant_and_unit(self) -> None:
        rows = [
            _run("agent-writer", "unit-1", "2026-04-28T10:00:00Z", variant="A"),
            _run("agent-writer", "unit-1", "2026-04-28T10:01:00Z", variant="B"),
            _run("agent-writer", "unit-2", "2026-04-28T10:02:00Z", variant="A"),
        ]

        only_a = aggregate_roundtrips(rows, variant="A")
        self.assertEqual(only_a["summary"]["unit_count"], 2)

        only_unit1 = aggregate_roundtrips(rows, unit_id="unit-1")
        self.assertEqual(only_unit1["summary"]["unit_count"], 1)
        self.assertEqual(only_unit1["units"][0]["writer_runs"], 2)

    def test_skips_rows_without_unit_id(self) -> None:
        rows = [
            _run("agent-writer", None, "2026-04-28T10:00:00Z"),
            _run("agent-writer", "unit-1", "2026-04-28T10:01:00Z"),
        ]
        report = aggregate_roundtrips(rows)
        self.assertEqual(report["summary"]["unit_count"], 1)


if __name__ == "__main__":
    unittest.main()
