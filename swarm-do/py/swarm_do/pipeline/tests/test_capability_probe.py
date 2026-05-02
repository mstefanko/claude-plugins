from __future__ import annotations

import os
import unittest
from unittest import mock

from swarm_do.pipeline.capability_probe import run_capability_probe


class CapabilityProbeTests(unittest.TestCase):
    def test_capability_probe_skips_without_claude_bin(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            payload = run_capability_probe()

        self.assertEqual(payload["status"], "skip")
        self.assertEqual(payload["reason"], "CLAUDE_BIN is unset")


if __name__ == "__main__":
    unittest.main()
