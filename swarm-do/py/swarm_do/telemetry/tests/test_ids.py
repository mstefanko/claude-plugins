"""ULID generator smoke tests: length, Crockford alphabet, uniqueness."""

from __future__ import annotations

import re
import unittest

from swarm_do.telemetry.ids import new_ulid


ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


class UlidTests(unittest.TestCase):
    def test_length_is_26(self) -> None:
        self.assertEqual(len(new_ulid()), 26)

    def test_matches_crockford_pattern(self) -> None:
        for _ in range(20):
            self.assertRegex(new_ulid(), ULID_RE)

    def test_100_distinct_values(self) -> None:
        ulids = {new_ulid() for _ in range(100)}
        self.assertEqual(len(ulids), 100)
        for u in ulids:
            self.assertRegex(u, ULID_RE)


if __name__ == "__main__":
    unittest.main()
