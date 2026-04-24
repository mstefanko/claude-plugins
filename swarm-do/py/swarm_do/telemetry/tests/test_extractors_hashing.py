"""Parity-frozen tests for stable_finding_hash_v1.

These assertions match exact SHA-256 hex for pinned inputs; changing them
means changing the algorithm (which requires a _v2 bump, not a test edit).
"""

from __future__ import annotations

import hashlib
import re
import unittest

from swarm_do.telemetry.extractors.hashing import stable_finding_hash_v1


HEX_RE = re.compile(r"^[0-9a-f]{64}$")


class StableFindingHashV1Tests(unittest.TestCase):
    def test_pinned_input_matches_known_sha256(self) -> None:
        got = stable_finding_hash_v1(
            "internal/api/foo.go", "correctness", 47, "null pointer deref"
        )
        # Independent reference hash: bucket = 47 // 10 = 4.
        want = hashlib.sha256(
            b"internal/api/foo.go|correctness|4|null pointer deref"
        ).hexdigest()
        self.assertEqual(got, want)
        self.assertRegex(got, HEX_RE)

    def test_bucket_groups_neighbors(self) -> None:
        h47 = stable_finding_hash_v1("a.go", "boundary", 47, "x")
        h49 = stable_finding_hash_v1("a.go", "boundary", 49, "x")
        h52 = stable_finding_hash_v1("a.go", "boundary", 52, "x")
        self.assertEqual(h47, h49, "47 and 49 both bucket to 4 — hashes must match")
        self.assertNotEqual(h47, h52, "47 (bucket 4) vs 52 (bucket 5) must differ")

    def test_bucket_boundary_transitions_at_multiples_of_ten(self) -> None:
        h49 = stable_finding_hash_v1("a.go", "boundary", 49, "x")
        h50 = stable_finding_hash_v1("a.go", "boundary", 50, "x")
        self.assertNotEqual(h49, h50, "49 (bucket 4) vs 50 (bucket 5) must differ")

    def test_non_ascii_summary_produces_valid_hex(self) -> None:
        got = stable_finding_hash_v1("a.go", "style", 1, "espaço em branco com acentuação")
        self.assertRegex(got, HEX_RE)
        self.assertEqual(len(got), 64)

    def test_line_zero_maps_to_bucket_zero(self) -> None:
        # Legacy bash floor-divides; Python // matches for non-negative ints.
        h0 = stable_finding_hash_v1("a.go", "info", 0, "x")
        h9 = stable_finding_hash_v1("a.go", "info", 9, "x")
        self.assertEqual(h0, h9)


if __name__ == "__main__":
    unittest.main()
