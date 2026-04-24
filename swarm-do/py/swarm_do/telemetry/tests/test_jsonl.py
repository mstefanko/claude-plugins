"""JSONL stream_read + atomic_write round-trip smoke tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from swarm_do.telemetry.jsonl import atomic_write, stream_read


class JsonlRoundTripTests(unittest.TestCase):
    def test_round_trip_two_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "sample.jsonl"
            rows = [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]
            atomic_write(target, rows)

            readback = list(stream_read(target))
            self.assertEqual(readback, rows)

    def test_stream_read_skips_blank_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "sparse.jsonl"
            target.write_text('{"a":1}\n\n{"a":2}\n', encoding="utf-8")
            self.assertEqual(list(stream_read(target)), [{"a": 1}, {"a": 2}])

    def test_stream_read_missing_raises_file_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does-not-exist.jsonl"
            with self.assertRaises(FileNotFoundError):
                list(stream_read(missing))

    def test_atomic_write_leaves_no_temp_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "t.jsonl"
            atomic_write(target, [{"k": "v"}])
            # Only the final file should remain; no .tmp artifacts.
            files = list(Path(tmp).iterdir())
            self.assertEqual(files, [target])


if __name__ == "__main__":
    unittest.main()
