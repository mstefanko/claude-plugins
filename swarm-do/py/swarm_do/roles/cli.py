"""CLI entrypoint for swarm_do.roles — skeleton (full implementation in phase-5/2)."""
from __future__ import annotations

import argparse
import sys


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m swarm_do.roles",
        description="Role-spec generator for swarm-do.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # gen subcommand
    gen_parser = sub.add_parser("gen", help="Generate role files from role-specs.")
    gen_group = gen_parser.add_mutually_exclusive_group(required=False)
    gen_group.add_argument(
        "--write",
        action="store_true",
        help="Write generated files to disk.",
    )
    gen_group.add_argument(
        "--check",
        action="store_true",
        help="Check generated files match disk; exit 1 if drift detected.",
    )
    gen_parser.add_argument(
        "readme_section",
        nargs="?",
        help="If 'readme-section', generate README section stub.",
    )

    # list subcommand
    sub.add_parser("list", help="List all role-spec names.")

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns exit code.

    Raises NotImplementedError for all subcommands until phase-5/2.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "list":
        raise NotImplementedError("list — implemented in phase-5/2")

    if args.command == "gen":
        if getattr(args, "readme_section", None) == "readme-section":
            raise NotImplementedError("gen readme-section — Phase 6")
        if args.write:
            raise NotImplementedError("gen --write — implemented in phase-5/2")
        if args.check:
            raise NotImplementedError("gen --check — implemented in phase-5/2")
        # no flag: default to --check behaviour
        raise NotImplementedError("gen — implemented in phase-5/2")

    print(f"Unknown command: {args.command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
