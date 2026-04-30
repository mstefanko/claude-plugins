from __future__ import annotations

import unittest

from swarm_do.pipeline.failure_taxonomy import failure_kind_details, known_failure_kinds, taxonomy_markdown


class FailureTaxonomyTests(unittest.TestCase):
    def test_known_failure_kind_returns_operational_details(self) -> None:
        details = failure_kind_details("launcher_nonzero_no_artifacts")

        self.assertEqual(details["failure_category"], "launcher")
        self.assertEqual(details["failure_retry_class"], "retry")
        self.assertEqual(details["failure_operator_title"], "Launcher exited before artifacts")
        self.assertTrue(details["failure_known"])

    def test_unknown_child_reported_failure_is_child_controlled(self) -> None:
        details = failure_kind_details("worker_custom_failure")

        self.assertEqual(details["failure_kind"], "worker_custom_failure")
        self.assertEqual(details["failure_category"], "child_result")
        self.assertEqual(details["failure_retry_class"], "child_controlled")
        self.assertFalse(details["failure_known"])

    def test_taxonomy_markdown_includes_all_known_values(self) -> None:
        markdown = taxonomy_markdown()

        for kind in known_failure_kinds():
            self.assertIn(f"`{kind}`", markdown)


if __name__ == "__main__":
    unittest.main()
