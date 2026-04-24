"""Registry smoke tests: ledger coverage + fallback ordering + on-disk schema files."""

from __future__ import annotations

import unittest

from swarm_do.telemetry.registry import LEDGERS


class RegistrySmokeTests(unittest.TestCase):
    def test_five_ledgers_registered(self) -> None:
        self.assertEqual(
            set(LEDGERS.keys()),
            {"runs", "findings", "outcomes", "adjudications", "finding_outcomes"},
        )

    def test_findings_fallback_v2_first(self) -> None:
        order = LEDGERS["findings"].fallback_order
        self.assertEqual(len(order), 2)
        self.assertIn("v2", order[0].name)
        self.assertNotIn("v2", order[1].name)

    def test_adjudications_fallback_v2_first(self) -> None:
        order = LEDGERS["adjudications"].fallback_order
        self.assertEqual(len(order), 2)
        self.assertIn("v2", order[0].name)
        self.assertNotIn("v2", order[1].name)

    def test_all_fallback_paths_exist_on_disk(self) -> None:
        for name, ledger in LEDGERS.items():
            for path in ledger.fallback_order:
                self.assertTrue(
                    path.is_file(),
                    msg=f"{name}: fallback schema missing on disk: {path}",
                )

    def test_filenames_are_canonical(self) -> None:
        expected = {
            "runs": "runs.jsonl",
            "findings": "findings.jsonl",
            "outcomes": "outcomes.jsonl",
            "adjudications": "adjudications.jsonl",
            "finding_outcomes": "finding_outcomes.jsonl",
        }
        for name, fname in expected.items():
            self.assertEqual(LEDGERS[name].filename, fname)


if __name__ == "__main__":
    unittest.main()
