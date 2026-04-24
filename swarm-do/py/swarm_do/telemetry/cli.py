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

from .registry import LEDGERS, PLUGIN_ROOT


LEGACY_SCRIPT = PLUGIN_ROOT / "swarm-do" / "bin" / "swarm-telemetry.legacy"


def _parse_days_type(s: str) -> int:
    """Parse a days argument of format 'Nd' (e.g., '90d').

    Raises argparse.ArgumentTypeError if format is invalid.
    """
    import re
    match = re.match(r"^(\d+)d$", s)
    if not match:
        raise argparse.ArgumentTypeError(f"invalid format: {s!r}; expected format: Nd (e.g., 90d)")
    return int(match.group(1))


SUBCOMMANDS = (
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

    # Add purge subcommand (Phase 2 native Python implementation).
    purge_parser = subparsers.add_parser("purge", add_help=True, help="Purge rows older than retention window")
    purge_parser.add_argument(
        "--older-than",
        dest="older_than",
        type=_parse_days_type,
        required=True,
        metavar="Nd",
        help="purge rows older than N days (format: Nd, e.g., 90d)",
    )
    purge_parser.add_argument(
        "--ledger",
        dest="ledger",
        choices=sorted(LEDGERS.keys()),
        default=None,
        help="purge a specific ledger; if omitted, purges all ledgers",
    )
    purge_parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="report what would be purged without modifying files",
    )

    # Add dump subcommand (Phase 3 native Python implementation).
    dump_parser = subparsers.add_parser(
        "dump",
        add_help=True,
        help="Pretty-print a JSONL ledger as a JSON array.",
    )
    dump_parser.add_argument(
        "ledger",
        choices=sorted(LEDGERS.keys()),
        help="ledger name (runs | findings | outcomes | adjudications | finding_outcomes)",
    )

    # Add validate subcommand (Phase 3 native Python implementation).
    validate_parser = subparsers.add_parser(
        "validate",
        add_help=True,
        help="Validate every ledger row against its JSON schema.",
    )
    validate_parser.add_argument(
        "ledger",
        nargs="?",
        default=None,
        help="optional ledger name; omit to validate all ledgers",
    )

    # Add query subcommand (Phase 3 native Python implementation).
    query_parser = subparsers.add_parser(
        "query",
        add_help=True,
        help="Execute SQL against all ledgers loaded into sqlite3 :memory:.",
    )
    query_parser.add_argument(
        "sql",
        help="SQL statement (single argument; quote appropriately)",
    )

    # Add legacy subcommands (Phase 1 passthrough).
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

    # Dispatch purge to native Python implementation.
    if ns.subcommand == "purge":
        from .subcommands import purge as _purge_cmd
        return _purge_cmd.run(ns)

    # Dispatch dump to native Python implementation (Phase 3 commit 1).
    if ns.subcommand == "dump":
        from .subcommands import dump as _dump_cmd
        return _dump_cmd.run(ns)

    # Dispatch validate to native Python implementation (Phase 3 commit 2).
    if ns.subcommand == "validate":
        from .subcommands import validate as _validate_cmd
        return _validate_cmd.run(ns)

    # Dispatch query to native Python implementation (Phase 3 commit 3).
    if ns.subcommand == "query":
        from .subcommands import query as _query_cmd
        return _query_cmd.run(ns)

    # Rebuild the argv for the legacy script: subcommand + pass-through rest.
    rest = getattr(ns, "rest", []) or []
    return _delegate([ns.subcommand, *rest])


if __name__ == "__main__":
    sys.exit(main())
