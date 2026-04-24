"""swarm-telemetry Python entry point.

Phase 1 contract: top-level argparse exposes the same subcommand surface as
the legacy bash implementation, but every subcommand is currently a
pass-through to `swarm-telemetry.legacy`. Later phases will replace each
subparser's handler with a native Python implementation.

Help text is intentionally thin. `--help` at the top level lists the
subcommands; per-subcommand help is deferred to the legacy script (each
subparser uses add_help=False and accepts REMAINDER args).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from typing import List, Sequence

from .registry import PLUGIN_ROOT


LEGACY_SCRIPT = PLUGIN_ROOT / "swarm-do" / "bin" / "swarm-telemetry.legacy"

SUBCOMMANDS = (
    "dump",
    "validate",
    "query",
    "report",
    "sample-for-adjudication",
    "join-outcomes",
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="swarm-telemetry",
        description=(
            "swarm-do telemetry CLI. Phase 1 thin shim: all subcommands "
            "delegate to swarm-telemetry.legacy. Phase 2+ will port them "
            "to native Python incrementally."
        ),
        add_help=True,
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="run the legacy self-test suite (delegates to swarm-telemetry.legacy --test).",
    )

    subparsers = parser.add_subparsers(dest="subcommand", metavar="SUBCOMMAND")
    for name in SUBCOMMANDS:
        sub = subparsers.add_parser(name, add_help=False, help=f"{name} (delegates to legacy)")
        sub.add_argument("rest", nargs=argparse.REMAINDER)
    return parser


def _delegate(argv: Sequence[str]) -> int:
    """Invoke the legacy bash script with the given argv list and return its exit code."""
    cmd: List[str] = ["bash", str(LEGACY_SCRIPT), *argv]
    result = subprocess.run(cmd)
    return result.returncode


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    # Short-circuit --test so `swarm-telemetry --test` hits the legacy self-test
    # without forcing users to type a subcommand.
    if args and args[0] == "--test":
        return _delegate(args)

    parser = _build_parser()
    # Special-case -h/--help at the top level: argparse handles it and exits 0.
    if not args or args[0] in ("-h", "--help"):
        parser.parse_args(args)
        return 0

    ns = parser.parse_args(args)

    if ns.test:
        return _delegate(["--test"])

    if not ns.subcommand:
        parser.print_help()
        return 0

    # Rebuild the argv for the legacy script: subcommand + pass-through rest.
    rest = getattr(ns, "rest", []) or []
    return _delegate([ns.subcommand, *rest])


if __name__ == "__main__":
    sys.exit(main())
