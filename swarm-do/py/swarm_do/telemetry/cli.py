"""swarm-telemetry Python entry point.

Post-Phase-3: every subcommand runs native Python. The legacy bash
implementation at swarm-telemetry.legacy was deleted once all six
subcommand parity tests were green. `--test` now runs the Python test
suite via `python3 -m unittest discover`.
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from .registry import LEDGERS, PLUGIN_ROOT


def _parse_days_type(s: str) -> int:
    """Parse a days argument of format 'Nd' (e.g., '90d')."""
    import re
    match = re.match(r"^(\d+)d$", s)
    if not match:
        raise argparse.ArgumentTypeError(
            f"invalid format: {s!r}; expected format: Nd (e.g., 90d)"
        )
    return int(match.group(1))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="swarm-telemetry",
        description="swarm-do telemetry CLI (native Python).",
        add_help=True,
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="run the Python test suite via unittest discover.",
    )

    subparsers = parser.add_subparsers(dest="subcommand", metavar="SUBCOMMAND")

    purge_parser = subparsers.add_parser(
        "purge", add_help=True, help="Purge rows older than retention window"
    )
    purge_parser.add_argument(
        "--older-than", dest="older_than", type=_parse_days_type,
        required=True, metavar="Nd",
        help="purge rows older than N days (format: Nd, e.g., 90d)",
    )
    purge_parser.add_argument(
        "--ledger", dest="ledger",
        choices=sorted(LEDGERS.keys()), default=None,
        help="purge a specific ledger; if omitted, purges all ledgers",
    )
    purge_parser.add_argument(
        "--dry-run", dest="dry_run", action="store_true",
        help="report what would be purged without modifying files",
    )

    dump_parser = subparsers.add_parser(
        "dump", add_help=True, help="Pretty-print a JSONL ledger as a JSON array.",
    )
    dump_parser.add_argument(
        "ledger", choices=sorted(LEDGERS.keys()),
        help="ledger name (runs | findings | outcomes | adjudications | finding_outcomes)",
    )

    validate_parser = subparsers.add_parser(
        "validate", add_help=True,
        help="Validate every ledger row against its JSON schema.",
    )
    validate_parser.add_argument(
        "ledger", nargs="?", default=None,
        help="optional ledger name; omit to validate all ledgers",
    )

    query_parser = subparsers.add_parser(
        "query", add_help=True,
        help="Execute SQL against all ledgers loaded into sqlite3 :memory:.",
    )
    query_parser.add_argument("sql", help="SQL statement (single argument; quote appropriately)")

    report_parser = subparsers.add_parser(
        "report", add_help=True,
        help="Stratified markdown report from runs.jsonl.",
    )
    report_parser.add_argument("--since", dest="since", default=None)
    report_parser.add_argument("--role", dest="role", default=None)
    report_parser.add_argument(
        "--bucket", dest="bucket", default="role",
        choices=["role", "complexity", "phase_kind", "risk_tag"],
    )

    sfa_parser = subparsers.add_parser(
        "sample-for-adjudication", add_help=True,
        help="Stratified random sample of non-adjudicated findings.",
    )
    sfa_parser.add_argument("--count", dest="count", required=False, default=None)
    sfa_parser.add_argument("--since", dest="since", default=None)
    sfa_parser.add_argument("--output-root", dest="output_root", default=None)

    jo_parser = subparsers.add_parser(
        "join-outcomes", add_help=True,
        help="Correlate findings with post-merge maintainer actions.",
    )
    jo_parser.add_argument("--since", dest="since", default="30d")
    jo_parser.add_argument("--repo", dest="repo", default=None)
    jo_parser.add_argument("--dry-run", dest="dry_run", action="store_true")

    return parser


def _run_self_test() -> int:
    """Run the Python test suite via unittest discover."""
    import unittest
    tests_dir = PLUGIN_ROOT / "swarm-do" / "py" / "swarm_do" / "telemetry" / "tests"
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=str(tests_dir), top_level_dir=str(PLUGIN_ROOT / "swarm-do" / "py"))
    runner = unittest.TextTestRunner(verbosity=1)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    if args and args[0] == "--test":
        return _run_self_test()

    parser = _build_parser()
    if not args or args[0] in ("-h", "--help"):
        parser.parse_args(args)
        return 0

    ns = parser.parse_args(args)

    if getattr(ns, "test", False):
        return _run_self_test()

    if not ns.subcommand:
        parser.print_help()
        return 0

    if ns.subcommand == "purge":
        from .subcommands import purge as _purge_cmd
        return _purge_cmd.run(ns)
    if ns.subcommand == "dump":
        from .subcommands import dump as _dump_cmd
        return _dump_cmd.run(ns)
    if ns.subcommand == "validate":
        from .subcommands import validate as _validate_cmd
        return _validate_cmd.run(ns)
    if ns.subcommand == "query":
        from .subcommands import query as _query_cmd
        return _query_cmd.run(ns)
    if ns.subcommand == "report":
        from .subcommands import report as _report_cmd
        return _report_cmd.run(ns)
    if ns.subcommand == "sample-for-adjudication":
        from .subcommands import sample_for_adjudication as _sfa_cmd
        return _sfa_cmd.run(ns)
    if ns.subcommand == "join-outcomes":
        from .subcommands import join_outcomes as _jo_cmd
        return _jo_cmd.run(ns)

    parser.error(f"unknown subcommand: {ns.subcommand}")
    return 2  # unreachable; parser.error raises SystemExit


if __name__ == "__main__":
    sys.exit(main())
