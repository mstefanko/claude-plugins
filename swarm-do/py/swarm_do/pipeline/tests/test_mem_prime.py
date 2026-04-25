from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline.mem_prime import DispatchFileAdapter, LocalSqliteAdapter, prime_for_unit


class MemPrimeTests(unittest.TestCase):
    def test_dispatch_file_adapter_renders_prior_context(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "runs" / "run-1" / "mem_prime"
            path.mkdir(parents=True)
            (path / "unit-a.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "unit_id": "unit-a",
                        "axis": "topic",
                        "obs_types": ["decision"],
                        "hits": [
                            {
                                "id": 1,
                                "title": "Use custom lint for work-unit migration",
                                "date": "2026-04-24",
                                "type": "decision",
                                "body": "JSON Schema is descriptive; runtime lint owns compatibility.",
                            }
                        ],
                        "stats": {"hit_count": 1, "title_only": False, "tokens": 10},
                        "skipped_reason": None,
                    }
                ),
                encoding="utf-8",
            )
            result = prime_for_unit({"id": "unit-a"}, "run-1", adapter=DispatchFileAdapter(root), max_tokens=50)
        self.assertIsNotNone(result.rendered_section_md)
        self.assertIn("Prior context", result.rendered_section_md or "")
        self.assertEqual(result.stats["mem_prime_axis"], "topic")
        self.assertEqual(result.stats["mem_prime_hit_count"], 1)

    def test_unit_override_skips_prime(self) -> None:
        result = prime_for_unit({"id": "unit-a", "mem_prime": False}, "run-1")
        self.assertIsNone(result.rendered_section_md)
        self.assertEqual(result.stats["mem_prime_skipped_reason"], "unit_override")

    def test_local_sqlite_adapter_reads_fixture_hits(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "mem.db"
            with sqlite3.connect(db) as conn:
                conn.execute("create table observations (unit_id text, id integer, title text, date text, type text, body text)")
                conn.execute(
                    "insert into observations values (?, ?, ?, ?, ?, ?)",
                    ("unit-a", 1, "Parser gotcha", "2026-04-24", "discovery", "Keep headings phase-scoped."),
                )
            result = prime_for_unit({"id": "unit-a"}, "run-1", adapter=LocalSqliteAdapter(db))
        self.assertIn("Parser gotcha", result.rendered_section_md or "")


if __name__ == "__main__":
    unittest.main()
