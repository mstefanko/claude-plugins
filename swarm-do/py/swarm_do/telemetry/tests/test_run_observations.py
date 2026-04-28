from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from swarm_do.telemetry.run_observations import (
    analyze_backend_output,
    analyze_backend_output_file,
)


def _event(payload: dict) -> str:
    return json.dumps({"type": "response_item", "payload": payload})


def _call(name: str, arguments: dict, call_id: str) -> str:
    return _event(
        {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(arguments),
            "call_id": call_id,
        }
    )


class RunObservationAnalysisTests(unittest.TestCase):
    def test_buckets_reads_positions_markers_and_codex_cache(self) -> None:
        text = "\n".join(
            [
                _call("exec_command", {"cmd": "rg -n \"foo\" py tests"}, "call-1"),
                _call("exec_command", {"cmd": "bd show bd-1 --json"}, "call-2"),
                _call("Read", {"file_path": "py/swarm_do/pipeline/plan.py"}, "call-3"),
                _call("Read", {"file_path": "py/swarm_do/pipeline/plan.py"}, "call-4"),
                _call("apply_patch", {}, "call-5"),
                _call(
                    "exec_command",
                    {"cmd": "python3 -m unittest discover -s py -p 'test_*.py'"},
                    "call-6",
                ),
                json.dumps(
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "agent_message",
                            "message": "## Status: NEEDS_CONTEXT\n[UNVERIFIED] gap\nNEEDS_RESEARCH",
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "token_count",
                            "info": {
                                "total_token_usage": {
                                    "input_tokens": 1000,
                                    "cached_input_tokens": 250,
                                    "output_tokens": 100,
                                }
                            },
                        },
                    }
                ),
                '{"work_unit_id":"unit-a","tool_calls":6}',
            ]
        )

        details = analyze_backend_output(text, role="agent-analysis")

        self.assertEqual(details["role"], "agent-analysis")
        self.assertEqual(details["stage_id"], "agent-analysis")
        self.assertEqual(details["unit_id"], "unit-a")
        self.assertEqual(details["tool_call_count"], 6)
        self.assertEqual(details["tool_category_counts"]["shell-rg"], 1)
        self.assertEqual(details["tool_category_counts"]["shell-bd"], 1)
        self.assertEqual(details["tool_category_counts"]["read"], 2)
        self.assertEqual(details["tool_category_counts"]["edit"], 1)
        self.assertEqual(details["tool_category_counts"]["shell-test"], 1)
        self.assertEqual(details["bd_show_count"], 1)
        self.assertEqual(details["source_read_count"], 2)
        self.assertEqual(
            details["repeated_read_histogram"],
            [{"file_path": "py/swarm_do/pipeline/plan.py", "count": 2}],
        )
        self.assertEqual(details["first_edit_tool_call_index"], 5)
        self.assertEqual(details["first_test_tool_call_index"], 6)
        self.assertEqual(details["markers"]["needs_context_count"], 1)
        self.assertEqual(details["markers"]["needs_research_count"], 1)
        self.assertEqual(details["markers"]["unverified_count"], 1)
        self.assertEqual(details["token_usage"]["cache_read_input_tokens"], 250)
        self.assertEqual(details["token_usage"]["cache_hit_ratio"], 0.25)

    def test_shell_file_reads_feed_repeated_read_histogram(self) -> None:
        text = "\n".join(
            [
                _call("exec_command", {"cmd": "sed -n '1,80p' roles/agent-writer/shared.md"}, "call-1"),
                _call("exec_command", {"cmd": "nl -ba roles/agent-writer/shared.md | sed -n '104,110p'"}, "call-2"),
            ]
        )

        details = analyze_backend_output(text, role="agent-writer")

        self.assertEqual(details["tool_category_counts"]["read"], 2)
        self.assertEqual(
            details["repeated_read_histogram"],
            [{"file_path": "roles/agent-writer/shared.md", "count": 2}],
        )

    def test_anthropic_cache_creation_and_read_ratio(self) -> None:
        text = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "usage": {
                        "input_tokens": 100,
                        "cache_creation_input_tokens": 20,
                        "cache_read_input_tokens": 80,
                        "output_tokens": 30,
                    }
                },
            }
        )

        details = analyze_backend_output(text, role="agent-research")

        self.assertEqual(details["token_usage"]["input_tokens"], 100)
        self.assertEqual(details["token_usage"]["cache_creation_input_tokens"], 20)
        self.assertEqual(details["token_usage"]["cache_read_input_tokens"], 80)
        self.assertEqual(details["token_usage"]["cache_hit_ratio"], 0.4)

    def test_read_before_edit_tracks_pre_and_post_edit_reads(self) -> None:
        text = "\n".join(
            [
                _call("Read", {"file_path": "src/a.py"}, "call-1"),
                _call("Read", {"file_path": "src/a.py"}, "call-2"),
                _call("Edit", {"file_path": "src/a.py", "old_string": "x", "new_string": "y"}, "call-3"),
                _call("Read", {"file_path": "src/a.py"}, "call-4"),
                _call("Read", {"file_path": "src/never-edited.py"}, "call-5"),
            ]
        )

        details = analyze_backend_output(text, role="agent-writer")

        rbe = details["read_before_edit"]
        self.assertEqual(rbe["reads_before_first_edit"], 2)
        self.assertEqual(rbe["reads_after_first_edit"], 1)
        self.assertEqual(rbe["total_reads_on_edited_files"], 3)
        self.assertEqual(rbe["ratio"], round(2 / 3, 6))
        self.assertEqual(
            rbe["per_file"],
            [
                {
                    "file_path": "src/a.py",
                    "reads_before_first_edit": 2,
                    "reads_after_first_edit": 1,
                    "edit_count": 1,
                }
            ],
        )

    def test_apply_patch_envelope_yields_edit_paths(self) -> None:
        patch = (
            "*** Begin Patch\n"
            "*** Update File: src/foo.py\n"
            "@@\n-old\n+new\n"
            "*** Add File: src/bar.py\n"
            "@@\n+brand new\n"
            "*** End Patch\n"
        )
        text = "\n".join(
            [
                _call("Read", {"file_path": "src/foo.py"}, "call-1"),
                _call("apply_patch", {"input": patch}, "call-2"),
            ]
        )

        details = analyze_backend_output(text, role="agent-writer")

        rbe = details["read_before_edit"]
        per_file = {row["file_path"]: row for row in rbe["per_file"]}
        self.assertIn("src/foo.py", per_file)
        self.assertIn("src/bar.py", per_file)
        self.assertEqual(per_file["src/foo.py"]["reads_before_first_edit"], 1)
        self.assertEqual(per_file["src/foo.py"]["edit_count"], 1)
        self.assertEqual(per_file["src/bar.py"]["reads_before_first_edit"], 0)
        self.assertEqual(per_file["src/bar.py"]["edit_count"], 1)

    def test_tool_output_bytes_codex_function_call_output(self) -> None:
        text = "\n".join(
            [
                _call("Read", {"file_path": "src/a.py"}, "call-1"),
                _call("exec_command", {"cmd": "bd show bd-1"}, "call-2"),
                _event(
                    {
                        "type": "function_call_output",
                        "call_id": "call-1",
                        "output": "hello world",  # 11 bytes
                    }
                ),
                _event(
                    {
                        "type": "function_call_output",
                        "call_id": "call-2",
                        "output": "bd payload " * 4,  # 44 bytes
                    }
                ),
            ]
        )

        details = analyze_backend_output(text, role="agent-writer")

        out = details["tool_output_bytes"]
        self.assertEqual(out["by_category"]["read"], 11)
        self.assertEqual(out["by_category"]["shell-bd"], 44)
        self.assertEqual(out["bd_show_output_bytes"], 44)
        self.assertEqual(out["total_tool_output_bytes"], 55)
        self.assertEqual(out["unmatched_output_bytes"], 0)

    def test_tool_output_bytes_anthropic_tool_result_block(self) -> None:
        text = json.dumps(
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_42",
                            "content": [
                                {"type": "text", "text": "abcdefghij"}  # 10 bytes
                            ],
                        }
                    ]
                },
            }
        )
        # Pair the tool_result with a corresponding tool_use call so categories match.
        text = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_42",
                            "name": "Read",
                            "input": {"file_path": "src/a.py"},
                        }
                    ]
                },
            }
        ) + "\n" + text

        details = analyze_backend_output(text, role="agent-writer")
        self.assertEqual(details["tool_output_bytes"]["by_category"]["read"], 10)
        self.assertEqual(details["tool_output_bytes"]["total_tool_output_bytes"], 10)

    def test_no_edits_yields_null_ratio(self) -> None:
        text = _call("Read", {"file_path": "src/a.py"}, "call-1")
        details = analyze_backend_output(text, role="agent-research")
        self.assertIsNone(details["read_before_edit"]["ratio"])
        self.assertEqual(details["read_before_edit"]["per_file"], [])

    def test_file_cli_path_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.jsonl"
            path.write_text(
                _call("exec_command", {"cmd": "bd show bd-2 --json"}, "call-1") + "\n",
                encoding="utf-8",
            )

            details = analyze_backend_output_file(path, role="agent-clarify")

        self.assertEqual(details["tool_category_counts"]["shell-bd"], 1)
        self.assertEqual(details["bd_show_count"], 1)
        self.assertEqual(details["source_read_count"], 0)


if __name__ == "__main__":
    unittest.main()
