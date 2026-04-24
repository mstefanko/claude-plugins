"""Contract-doc generator for swarm-do telemetry and role documentation.

Regenerates marker-bounded blocks in README files from authoritative sources:
  - ``swarm_do.telemetry.gen docs``          → ledger table in schemas/telemetry/README.md
  - ``swarm_do.telemetry.gen readme-section`` → telemetry commands table in swarm-do/README.md

Markers follow the convention ``<!-- BEGIN/END: generated-by <module> <subcommand> -->``.
Content between markers is fully replaced on each write; do not hand-edit inside them.
Run with ``--check`` (or via ``bin/swarm-telemetry --test --check-docs``) to detect drift without writing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, Sequence

from .registry import LEDGERS, PLUGIN_ROOT

# Marker strings (exact, case-sensitive)
MARKER_BEGIN_TELEMETRY_DOCS = "<!-- BEGIN: generated-by swarm_do.telemetry.gen docs -->"
MARKER_END_TELEMETRY_DOCS = "<!-- END: generated-by swarm_do.telemetry.gen docs -->"

MARKER_BEGIN_TELEMETRY_README = "<!-- BEGIN: generated-by swarm_do.telemetry.gen readme-section -->"
MARKER_END_TELEMETRY_README = "<!-- END: generated-by swarm_do.telemetry.gen readme-section -->"


def render_ledger_table(ledgers: Dict[str, object]) -> str:
    """Render a Markdown table with columns: Ledger | Filename | Schema | Fallback count.

    Args:
        ledgers: Dictionary of ledger name -> Ledger object

    Returns:
        Markdown table as string
    """
    lines = [
        "| Ledger | Filename | Schema | Fallback count |",
        "|--------|----------|--------|----------------|",
    ]
    for ledger_name in sorted(ledgers.keys()):
        ledger = ledgers[ledger_name]
        try:
            schema_rel = ledger.schema_path.relative_to(PLUGIN_ROOT)
        except ValueError:
            # In tests or when PLUGIN_ROOT is mocked, just use the path as-is
            schema_rel = ledger.schema_path
        fallback_count = len(ledger.fallback_order)
        lines.append(
            f"| {ledger.name} | {ledger.filename} | `{schema_rel}` | {fallback_count} |"
        )
    return "\n".join(lines)


def render_telemetry_commands_table(subcommands: Dict[str, str]) -> str:
    """Render CLI commands table: Command | Description.

    Args:
        subcommands: Dictionary of command name -> help text

    Returns:
        Markdown table as string
    """
    lines = [
        "| Subcommand | What it does |",
        "|------------|--------------|",
    ]
    for cmd_name in sorted(subcommands.keys()):
        help_text = subcommands[cmd_name]
        # Escape pipes in help text
        help_text = help_text.replace("|", "\\|")
        lines.append(f"| `{cmd_name}` | {help_text} |")
    return "\n".join(lines)


def replace_between_markers(
    content: str, begin_marker: str, end_marker: str, new_body: str
) -> str:
    """Replace content between begin/end markers (inclusive of markers).

    Args:
        content: File content as string
        begin_marker: The BEGIN marker line
        end_marker: The END marker line
        new_body: New content to insert (excluding markers)

    Returns:
        Modified content with markers and new body

    Raises:
        ValueError: If markers are not found in content
    """
    lines = content.split("\n")

    begin_idx = None
    end_idx = None

    for i, line in enumerate(lines):
        if line.strip() == begin_marker:
            begin_idx = i
        elif line.strip() == end_marker:
            end_idx = i

    if begin_idx is None:
        raise ValueError(f"BEGIN marker not found: {begin_marker}")
    if end_idx is None:
        raise ValueError(f"END marker not found: {end_marker}")
    if begin_idx >= end_idx:
        raise ValueError(f"BEGIN marker comes after END marker")

    # Replace from begin to end (inclusive)
    new_lines = (
        lines[:begin_idx]
        + [begin_marker, new_body, end_marker]
        + lines[end_idx + 1 :]
    )
    return "\n".join(new_lines)


def cmd_docs_write() -> int:
    """Regenerate the telemetry ledger table in schemas/telemetry/README.md."""
    readme_path = PLUGIN_ROOT / "swarm-do" / "schemas" / "telemetry" / "README.md"

    # Create file if it doesn't exist
    if not readme_path.exists():
        readme_path.parent.mkdir(parents=True, exist_ok=True)
        initial_content = (
            f"{MARKER_BEGIN_TELEMETRY_DOCS}\n"
            f"(placeholder)\n"
            f"{MARKER_END_TELEMETRY_DOCS}\n"
        )
        readme_path.write_text(initial_content)

    content = readme_path.read_text()
    ledger_table = render_ledger_table(LEDGERS)

    try:
        new_content = replace_between_markers(
            content, MARKER_BEGIN_TELEMETRY_DOCS, MARKER_END_TELEMETRY_DOCS, ledger_table
        )
    except ValueError as e:
        print(f"Error in {readme_path}: {e}", file=sys.stderr)
        return 1

    readme_path.write_text(new_content)
    return 0


def cmd_docs_check() -> int:
    """Check if telemetry ledger table is up-to-date."""
    readme_path = PLUGIN_ROOT / "swarm-do" / "schemas" / "telemetry" / "README.md"

    if not readme_path.exists():
        print(f"Error: {readme_path} does not exist", file=sys.stderr)
        return 1

    content = readme_path.read_text()

    # Extract current content between markers
    lines = content.split("\n")
    begin_idx = None
    end_idx = None

    for i, line in enumerate(lines):
        if line.strip() == MARKER_BEGIN_TELEMETRY_DOCS:
            begin_idx = i
        elif line.strip() == MARKER_END_TELEMETRY_DOCS:
            end_idx = i

    if begin_idx is None or end_idx is None:
        print(f"Error: markers not found in {readme_path}", file=sys.stderr)
        return 1

    current_body = "\n".join(lines[begin_idx + 1 : end_idx]).strip()
    expected_body = render_ledger_table(LEDGERS)

    if current_body != expected_body:
        print(f"Drift detected in {readme_path}:")
        print("\nExpected:")
        print(expected_body)
        print("\nActual:")
        print(current_body)
        return 1

    return 0


def cmd_readme_section_write() -> int:
    """Regenerate the telemetry commands table in swarm-do/README.md."""
    readme_path = PLUGIN_ROOT / "swarm-do" / "README.md"

    if not readme_path.exists():
        print(f"Error: {readme_path} does not exist", file=sys.stderr)
        return 1

    content = readme_path.read_text()

    # Build subcommands dict from cli.py
    subcommands = _get_telemetry_subcommands()
    commands_table = render_telemetry_commands_table(subcommands)

    try:
        new_content = replace_between_markers(
            content,
            MARKER_BEGIN_TELEMETRY_README,
            MARKER_END_TELEMETRY_README,
            commands_table,
        )
    except ValueError as e:
        print(f"Error in {readme_path}: {e}", file=sys.stderr)
        return 1

    readme_path.write_text(new_content)
    return 0


def cmd_readme_section_check() -> int:
    """Check if telemetry commands table is up-to-date."""
    readme_path = PLUGIN_ROOT / "swarm-do" / "README.md"

    if not readme_path.exists():
        print(f"Error: {readme_path} does not exist", file=sys.stderr)
        return 1

    content = readme_path.read_text()

    # Extract current content between markers
    lines = content.split("\n")
    begin_idx = None
    end_idx = None

    for i, line in enumerate(lines):
        if line.strip() == MARKER_BEGIN_TELEMETRY_README:
            begin_idx = i
        elif line.strip() == MARKER_END_TELEMETRY_README:
            end_idx = i

    if begin_idx is None or end_idx is None:
        print(f"Error: markers not found in {readme_path}", file=sys.stderr)
        return 1

    current_body = "\n".join(lines[begin_idx + 1 : end_idx]).strip()

    subcommands = _get_telemetry_subcommands()
    expected_body = render_telemetry_commands_table(subcommands)

    if current_body != expected_body:
        print(f"Drift detected in {readme_path}:")
        print("\nExpected:")
        print(expected_body)
        print("\nActual:")
        print(current_body)
        return 1

    return 0


def _get_telemetry_subcommands() -> Dict[str, str]:
    """Extract subcommand names and help texts from telemetry CLI."""
    # Import here to avoid circular imports
    from . import cli

    subcommands = {}

    # Build parser to extract subcommand help
    parser = cli._build_parser()

    # Parse the formatted help output to extract subcommand descriptions
    help_output = parser.format_help()
    lines = help_output.split("\n")

    in_subcommands_section = False
    current_cmd = None

    for line in lines:
        # Skip until we reach the "positional arguments:" section
        if line.strip() == "positional arguments:":
            in_subcommands_section = True
            continue

        if not in_subcommands_section:
            continue

        # Stop at the "options:" section
        if line.strip() == "options:":
            break

        # Skip empty lines and the SUBCOMMAND line
        if not line.strip() or line.strip() == "SUBCOMMAND":
            continue

        # Check for a command line (starts with exactly 4 spaces and has a command name)
        if line.startswith("    ") and not line.startswith("      "):
            # This is a command line (4 spaces indentation, no more)
            parts = line.strip().split(None, 1)
            if parts:
                current_cmd = parts[0]
                help_text = parts[1] if len(parts) > 1 else ""
                subcommands[current_cmd] = help_text.strip()
        # If line starts with more than 4 spaces and we have a current command, it's continuation
        elif current_cmd and line.startswith("      "):
            # Continuation line (more than 4 spaces indentation)
            subcommands[current_cmd] += " " + line.strip()

    return subcommands


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for gen subcommands."""
    parser = argparse.ArgumentParser(
        prog="swarm_do.telemetry.gen",
        description="Contract-doc generator for telemetry READMEs.",
        add_help=True,
    )

    subparsers = parser.add_subparsers(dest="subcommand", metavar="SUBCOMMAND")

    docs_parser = subparsers.add_parser(
        "docs", add_help=True, help="Regenerate telemetry ledger table in schemas/telemetry/README.md."
    )
    docs_group = docs_parser.add_mutually_exclusive_group(required=True)
    docs_group.add_argument(
        "--write", action="store_true", help="Write generated content to file."
    )
    docs_group.add_argument(
        "--check", action="store_true", help="Check for drift; exit 1 if different."
    )

    readme_parser = subparsers.add_parser(
        "readme-section",
        add_help=True,
        help="Regenerate telemetry commands table in swarm-do/README.md.",
    )
    readme_group = readme_parser.add_mutually_exclusive_group(required=True)
    readme_group.add_argument(
        "--write", action="store_true", help="Write generated content to file."
    )
    readme_group.add_argument(
        "--check", action="store_true", help="Check for drift; exit 1 if different."
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Main entry point."""
    args = list(sys.argv[1:] if argv is None else argv)

    if not args or args[0] in ("-h", "--help"):
        parser = _build_parser()
        parser.print_help()
        return 0

    parser = _build_parser()
    ns = parser.parse_args(args)

    if ns.subcommand == "docs":
        if ns.write:
            return cmd_docs_write()
        elif ns.check:
            return cmd_docs_check()
    elif ns.subcommand == "readme-section":
        if ns.write:
            return cmd_readme_section_write()
        elif ns.check:
            return cmd_readme_section_check()

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
