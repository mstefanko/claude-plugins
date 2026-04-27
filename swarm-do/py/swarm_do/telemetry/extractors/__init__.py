"""swarm-do findings extractors (Phase 4).

Dispatches from role name to reviewer-specific extractor implementation.

CLI entrypoint:

    python3 -m swarm_do.telemetry.extractors <input-file> <run-id> <role> <issue-id>
    python3 -m swarm_do.telemetry.extractors --test

Exit codes:
  0 — success, no findings, or fail-open recovery (never raised)
  * — --test mode only; mirrors unittest discover result.

Closes 9b-claude (mstefanko-plugins-7q9) by adding claude_review.py
alongside the Phase 9b codex_review port. The dispatcher recognizes:

  agent-codex-review                    -> codex_review.extract
  agent-review, agent-clean-review,
  agent-code-review                     -> claude_review.extract
  swarm-review, provider-review         -> provider_review.extract
  any other role                        -> skipped (fail-open, stderr warn)

The extractor is fail-open so reviewer telemetry never changes pipeline status.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Sequence


CLAUDE_EXTRACTOR_ROLES = frozenset({"agent-review", "agent-clean-review", "agent-code-review"})
CODEX_EXTRACTOR_ROLES = frozenset({"agent-codex-review"})
PROVIDER_REVIEW_EXTRACTOR_ROLES = frozenset({"swarm-review", "provider-review"})


def _write_rows(rows: List[dict]) -> int:
    """Append rows to ${CLAUDE_PLUGIN_DATA}/telemetry/findings.jsonl.

    Fail-open: any I/O failure logs to stderr and returns 0 so the outer
    pipeline's exit code is never disturbed.
    """
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA", "")
    if not plugin_data:
        print(
            "extract-phase: CLAUDE_PLUGIN_DATA unset — skipping findings write",
            file=sys.stderr,
        )
        return 0

    tel_dir = Path(plugin_data) / "telemetry"
    try:
        tel_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"extract-phase: cannot create {tel_dir}: {exc}", file=sys.stderr)
        return 0

    out_path = tel_dir / "findings.jsonl"
    try:
        with out_path.open("a", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"extract-phase: findings.jsonl not writable: {exc}", file=sys.stderr)
        return 0

    print(
        f"extract-phase: appended {len(rows)} finding(s) to {out_path}",
        file=sys.stderr,
    )
    return 0


def _run_self_test() -> int:
    """Run the extractors test module subset via unittest discover."""
    import unittest

    tests_dir = Path(__file__).resolve().parents[1] / "tests"
    loader = unittest.TestLoader()
    suite = loader.discover(
        start_dir=str(tests_dir),
        pattern="test_extractors_*.py",
        top_level_dir=str(tests_dir.parents[2]),
    )
    runner = unittest.TextTestRunner(verbosity=1)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    # Self-test short-circuit (matches the legacy `extract-phase.sh --test`
    # entrypoint and is load-bearing for the shim's `--test` passthrough).
    if args and args[0] == "--test":
        return _run_self_test()

    parser = argparse.ArgumentParser(
        prog="python3 -m swarm_do.telemetry.extractors",
        description="Extract findings from a reviewer note/JSON into findings.jsonl.",
    )
    parser.add_argument("input_file")
    parser.add_argument("run_id")
    parser.add_argument("role")
    parser.add_argument("issue_id")

    # We prefer fail-open over argparse SystemExit so the caller's pipeline
    # exit code is never changed. Argparse exits with code 2 on missing args;
    # we intercept that and fold it into the legacy warning path.
    try:
        ns = parser.parse_args(args)
    except SystemExit:
        print(
            "extract-phase: usage: <input-file> <run-id> <role> <issue-id>",
            file=sys.stderr,
        )
        return 0

    if ns.role in CODEX_EXTRACTOR_ROLES:
        from .codex_review import extract as _extract
    elif ns.role in CLAUDE_EXTRACTOR_ROLES:
        from .claude_review import extract as _extract
    elif ns.role in PROVIDER_REVIEW_EXTRACTOR_ROLES:
        from .provider_review import extract as _extract
    else:
        print(
            f"extract-phase: role {ns.role!r} not recognized — skipping (fail-open)",
            file=sys.stderr,
        )
        return 0

    if not Path(ns.input_file).is_file():
        print(
            f"extract-phase: input not found: {ns.input_file}",
            file=sys.stderr,
        )
        return 0

    try:
        rows = _extract(ns.input_file, ns.run_id, ns.role, ns.issue_id)
    except Exception as exc:  # noqa: BLE001 — fail-open outer guard
        print(
            f"extract-phase: extractor raised ({type(exc).__name__}): {exc}",
            file=sys.stderr,
        )
        return 0

    if not rows:
        print(
            f"extract-phase: no findings extracted for role {ns.role!r}",
            file=sys.stderr,
        )
        return 0

    return _write_rows(rows)


if __name__ == "__main__":
    sys.exit(main())
