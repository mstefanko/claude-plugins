#!/usr/bin/env python3
"""Configurable fake `claude` CLI for phase-pump subprocess tests."""

from __future__ import annotations

import json
import os
import sys
import time


def main() -> int:
    sys.stdin.read()
    frames = json.loads(os.environ.get("SWARM_FAKE_CLAUDE_FRAMES", "[]"))
    exit_code = int(os.environ.get("SWARM_FAKE_CLAUDE_EXIT_CODE", "0"))
    delay_ms = int(os.environ.get("SWARM_FAKE_CLAUDE_DELAY_MS", "0"))
    if "--output-format" in sys.argv:
        fmt = sys.argv[sys.argv.index("--output-format") + 1]
    else:
        fmt = "json"
    if fmt == "json" and not frames:
        frames = [{"type": "result", "result": "{}"}]
    for frame in frames:
        if isinstance(frame, str):
            print(frame, flush=True)
        else:
            print(json.dumps(frame), flush=True)
        if delay_ms:
            time.sleep(delay_ms / 1000)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
