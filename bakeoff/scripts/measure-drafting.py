#!/usr/bin/env python3
"""
Measure pre-preview drafting cost from a Claude Code transcript JSONL.

Output is plain key: value lines so the operator can append them to the
experiment log without reformatting.

Assumptions:
  - Transcript is a Claude Code session JSONL (one JSON object per line).
  - Entries have `type` of `user`, `assistant`, or other (system, hook, ...).
  - User messages have `message.content` as string or list of blocks.
  - Assistant messages have `message.content` as a list of blocks; tool calls
    are blocks with `type: tool_use`.
  - Timestamps are ISO 8601 with trailing `Z`.

Stop detection:
  - Default: first assistant message whose text matches a regex covering
    common preview / question / warning markers.
  - Override with --stop-line N to pick the line yourself when auto-detect
    misses or misfires.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_STOP_PATTERN = (
    # Preview headers (most-specific markers first)
    r"\*\*(?:Draft preview|Work order preview|Preview)\*\*"
    r"|draft preview"
    r"|approval-ready preview"
    # Approval prompts
    r"|Approve and run"
    r"|Write, validate, and run"
    r"|Reply\s*[`']?(?:yes|y|approve)"
    r"|write and run"
    # Compact preview lines
    r"|^\s*-?\s*\*\*providers\*\*:"
    r"|^Providers:"
    # Fallback / warning markers (less reliable; keep last)
    r"|missing\s+(?:verifier|acceptance|criteria|scope|gate)"
    r"|task-fit\s+(?:warning|fail|fails)"
    r"|clarif(?:y|ication)"
)


def parse_timestamp(s):
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def message_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                kind = block.get("type")
                if kind == "text":
                    parts.append(block.get("text", "") or "")
                elif kind == "tool_use":
                    parts.append(f"<tool_use:{block.get('name', '?')}>")
        return "\n".join(parts)
    return ""


def count_tool_uses(content):
    if not isinstance(content, list):
        return 0
    return sum(
        1
        for b in content
        if isinstance(b, dict) and b.get("type") == "tool_use"
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("transcript", type=Path, help="Claude Code session JSONL")
    ap.add_argument(
        "--start-marker",
        default="/bakeoff:run",
        help="substring identifying the user message that starts measurement",
    )
    ap.add_argument(
        "--stop-pattern",
        default=DEFAULT_STOP_PATTERN,
        help="regex; first assistant message matching ends measurement",
    )
    ap.add_argument(
        "--stop-line",
        type=int,
        default=None,
        help="0-indexed line in the JSONL to force as stop (overrides --stop-pattern)",
    )
    ap.add_argument(
        "--verbose",
        action="store_true",
        help="print skipped/non-JSON lines to stderr",
    )
    args = ap.parse_args()

    if not args.transcript.exists():
        print(f"error: transcript not found: {args.transcript}", file=sys.stderr)
        sys.exit(2)

    entries = []
    with args.transcript.open() as f:
        for line_no, raw in enumerate(f):
            raw = raw.strip()
            if not raw:
                continue
            try:
                entries.append((line_no, json.loads(raw)))
            except json.JSONDecodeError as e:
                if args.verbose:
                    print(f"# skip line {line_no}: not JSON ({e})", file=sys.stderr)

    start_idx = None
    start_line = None
    for idx, (line_no, entry) in enumerate(entries):
        if entry.get("type") != "user":
            continue
        text = message_text((entry.get("message") or {}).get("content"))
        if args.start_marker in text:
            start_idx = idx
            start_line = line_no
            start_entry = entry
            break

    if start_idx is None:
        print(
            f"error: no user message containing {args.start_marker!r} found",
            file=sys.stderr,
        )
        sys.exit(3)

    pattern = re.compile(args.stop_pattern, re.IGNORECASE)
    stop_idx = None
    stop_reason = None
    for idx in range(start_idx + 1, len(entries)):
        line_no, entry = entries[idx]
        if args.stop_line is not None:
            if line_no == args.stop_line:
                stop_idx = idx
                stop_reason = f"explicit --stop-line={args.stop_line}"
                break
            continue
        if entry.get("type") != "assistant":
            continue
        text = message_text((entry.get("message") or {}).get("content"))
        m = pattern.search(text)
        if m:
            stop_idx = idx
            stop_reason = f"matched stop-pattern: {m.group(0)!r}"
            break

    if stop_idx is None:
        print(
            f"error: no stop point found after start line {start_line}",
            file=sys.stderr,
        )
        sys.exit(4)

    stop_line, stop_entry = entries[stop_idx]

    turns = 0
    tool_calls = 0
    for idx in range(start_idx + 1, stop_idx + 1):
        _, entry = entries[idx]
        if entry.get("type") == "assistant":
            turns += 1
            tool_calls += count_tool_uses(
                (entry.get("message") or {}).get("content")
            )

    start_ts = parse_timestamp(start_entry.get("timestamp"))
    stop_ts = parse_timestamp(stop_entry.get("timestamp"))
    if start_ts and stop_ts:
        wall = (stop_ts - start_ts).total_seconds()
        wall_s = f"{wall:.3f}"
    else:
        wall_s = "unknown"

    print(f"transcript: {args.transcript}")
    print(f"start_line: {start_line}")
    print(f"stop_line: {stop_line}")
    print(f"stop_reason: {stop_reason}")
    print(f"start_timestamp: {start_entry.get('timestamp')}")
    print(f"stop_timestamp: {stop_entry.get('timestamp')}")
    print(f"wall_seconds_pre_preview: {wall_s}")
    print(f"turns_pre_preview: {turns}")
    print(f"tool_calls_pre_preview: {tool_calls}")


if __name__ == "__main__":
    main()
