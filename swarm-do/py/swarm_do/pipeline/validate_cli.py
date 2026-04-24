"""`swarm-validate` entry point."""

from __future__ import annotations

import argparse
import sys

from .cli import cmd_preset_dry_run
from .validation import validate_preset_and_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="swarm-validate")
    parser.add_argument("preset")
    parser.add_argument("--plan", dest="plan_path", default=None)
    parser.add_argument("--budget", dest="budget", action="store_true")
    args = parser.parse_args(argv)

    result, preset, pipeline, _ = validate_preset_and_pipeline(
        args.preset,
        plan_path=args.plan_path,
        include_budget=args.budget or bool(args.plan_path),
    )
    if result.budget:
        b = result.budget
        print(f"budget: phases={b.phase_count} agents={b.agent_count} cost=${b.estimated_cost_usd:.4f} wall={b.estimated_wall_clock_seconds}s")
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    for error in result.errors:
        print(f"error: {error}", file=sys.stderr)
    if result.ok:
        print(f"validation OK: {args.preset}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
