from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from bakeoff import __version__

MODES = ("gather", "compare", "analyze")

ORIENTATION = """\
bakeoff - run the same research task across multiple agents, then judge.

Three modes:
  gather   coverage research
  compare  defended pick
  analyze  thorough explanation

Get started:
  bakeoff init gather
  bakeoff validate gather.work-order.json
  bakeoff research gather.work-order.json
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bakeoff", description="Tiny research bakeoff harness.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subcommands = parser.add_subparsers(dest="command")

    init = subcommands.add_parser("init", help="write an example work order")
    init.add_argument("type", choices=MODES)

    validate = subcommands.add_parser("validate", help="validate and dry-run a work order")
    validate.add_argument("work_order")

    research = subcommands.add_parser("research", help="run a research bakeoff")
    research.add_argument("work_order")

    rerun = subcommands.add_parser("rerun", help="replay a previous work order with a fresh run id")
    rerun.add_argument("run_id")

    subcommands.add_parser("ls", help="list past runs")

    show = subcommands.add_parser("show", help="print a run report")
    show.add_argument("run_id")
    show.add_argument("--judge", action="store_true", help="show judge output")
    show.add_argument("--judge-prompt", action="store_true", help="show judge prompt")

    subcommands.add_parser("doctor", help="check provider CLIs, auth, and local readiness")

    return parser


def _print_orientation() -> int:
    print(ORIENTATION)
    return 0


def _not_implemented(command: str) -> int:
    print(f"bakeoff {command}: scaffolded; Phase 1 implementation pending.", file=sys.stderr)
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    if not args_list:
        return _print_orientation()

    parser = build_parser()
    args = parser.parse_args(args_list)
    if args.command is None:
        return _print_orientation()
    return _not_implemented(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
