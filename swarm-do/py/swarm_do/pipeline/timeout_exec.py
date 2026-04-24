"""Run a command with stdin forwarding and a portable timeout."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


TIMEOUT_RC = 124


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m swarm_do.pipeline.timeout_exec")
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("command is required after --")

    input_bytes = sys.stdin.buffer.read()
    output_path = Path(args.output)
    try:
        proc = subprocess.run(
            command,
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=args.timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        partial = exc.output or b""
        output_path.write_bytes(partial)
        return TIMEOUT_RC
    output_path.write_bytes(proc.stdout or b"")
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
