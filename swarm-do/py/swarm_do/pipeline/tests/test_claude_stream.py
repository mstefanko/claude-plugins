from __future__ import annotations

import unittest
from pathlib import Path

from swarm_do.pipeline.claude_stream import ClaudeStreamParser
from swarm_do.pipeline.orchestrator_stream import parse_stage_markers


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "claude_stream"


class ClaudeStreamParserTests(unittest.TestCase):
    def test_assistant_text_extracted(self) -> None:
        parser = ClaudeStreamParser()
        chunks = _feed_fixture(parser, "success_with_stage_markers.jsonl")

        text_chunks = [chunk for chunk in chunks if chunk.kind == "assistant_text"]
        self.assertEqual(len(text_chunks), 1)
        self.assertIn("STAGE_COMPLETE", text_chunks[0].text)

    def test_final_result_captured(self) -> None:
        parser = ClaudeStreamParser()
        chunks = _feed_fixture(parser, "result_only_no_markers.jsonl")

        result = [chunk for chunk in chunks if chunk.kind == "result"]
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].raw_frame["session_id"], "s3")
        self.assertTrue(parser.metadata()["final_result_seen"])

    def test_malformed_line_increments_count_no_raise(self) -> None:
        parser = ClaudeStreamParser()
        chunks = _feed_fixture(parser, "malformed_then_success.jsonl")

        self.assertEqual(chunks[0].kind, "malformed")
        self.assertEqual(parser.metadata()["parse_error_count"], 1)
        self.assertIsNotNone(parser.metadata()["first_parse_error"])

    def test_unknown_frame_type_counted_in_metadata(self) -> None:
        parser = ClaudeStreamParser()
        _feed_fixture(parser, "unknown_frame_types.jsonl")

        ignored = parser.metadata()["ignored_frame_types"]
        self.assertEqual(ignored["system"], 1)
        self.assertEqual(ignored["user"], 1)
        self.assertEqual(ignored["mystery"], 1)

    def test_tool_use_block_in_assistant_message_ignored(self) -> None:
        parser = ClaudeStreamParser()
        chunks = _feed_fixture(parser, "unknown_frame_types.jsonl")

        self.assertNotIn("assistant_text", [chunk.kind for chunk in chunks])
        self.assertGreaterEqual(parser.metadata()["ignored_frame_types"]["tool_use"], 1)
        self.assertEqual(parser.metadata()["tool_use_counts"]["Task"], 1)
        self.assertEqual(parser.metadata()["agent_tool_use_names"], ["Agent", "Task"])
        self.assertEqual(parser.metadata()["agent_tool_use_count"], 1)

    def test_marker_in_assistant_text_round_trips_through_parse_stage_markers(self) -> None:
        parser = ClaudeStreamParser()
        chunks = _feed_fixture(parser, "success_with_stage_markers.jsonl")
        text = "\n".join(chunk.text for chunk in chunks if chunk.kind == "assistant_text")

        markers = parse_stage_markers(text)

        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0].stage_id, "writer")


def _feed_fixture(parser: ClaudeStreamParser, name: str):
    return [parser.feed_line(line) for line in (FIXTURE_DIR / name).read_text(encoding="utf-8").splitlines()]


if __name__ == "__main__":
    unittest.main()
