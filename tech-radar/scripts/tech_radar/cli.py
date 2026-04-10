"""CLI entry point with argparse subcommands."""

import argparse
import sys

from . import db as db_module


def cmd_migrate(args):
    """Migrate history.json into the SQLite database."""
    database = db_module.open_db(args.db)
    history_path = args.history if hasattr(args, "history") and args.history else None
    db_module.migrate_from_history(database, history_path)


def cmd_status(args):
    """Show database statistics."""
    import os
    db_path = args.db or db_module.DEFAULT_DB_PATH
    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}")
        print("Run 'tech-radar migrate' first to create it from history.json")
        sys.exit(1)

    database = db_module.open_db(db_path)

    repo_count = list(database.execute("SELECT COUNT(*) FROM repos").fetchall())[0][0]
    scan_count = list(database.execute("SELECT COUNT(*) FROM scans").fetchall())[0][0]
    snapshot_count = list(database.execute("SELECT COUNT(*) FROM scan_snapshots").fetchall())[0][0]
    verdict_count = list(database.execute("SELECT COUNT(*) FROM verdicts").fetchall())[0][0]
    annotation_count = list(database.execute("SELECT COUNT(*) FROM annotations").fetchall())[0][0]

    # Pending verdicts: snapshots with needs_verdict=1 and no verdict
    pending = list(database.execute(
        """SELECT COUNT(*) FROM scan_snapshots ss
           WHERE ss.needs_verdict = 1
           AND NOT EXISTS (
               SELECT 1 FROM verdicts v
               WHERE v.repo_id = ss.repo_id AND v.scan_id = ss.scan_id
           )"""
    ).fetchall())[0][0]

    # Last scan date
    last_scan = list(database.execute(
        "SELECT scan_date FROM scans ORDER BY id DESC LIMIT 1"
    ).fetchall())
    last_scan_date = last_scan[0][0] if last_scan else "none"

    # Schema version
    meta = list(database.execute("SELECT schema_version FROM meta LIMIT 1").fetchall())
    schema_ver = meta[0][0] if meta else "unknown"

    print(f"Tech Radar Database: {db_path}")
    print(f"  Schema version:    {schema_ver}")
    print(f"  Repos:             {repo_count}")
    print(f"  Scans:             {scan_count}")
    print(f"  Snapshots:         {snapshot_count}")
    print(f"  Verdicts:          {verdict_count}")
    print(f"  Annotations:       {annotation_count}")
    print(f"  Pending verdicts:  {pending}")
    print(f"  Last scan date:    {last_scan_date}")


def cmd_stub(name):
    """Return a stub handler for not-yet-implemented subcommands."""
    def handler(args):
        print(f"'{name}' is not yet implemented (coming in a later phase).")
    return handler


def build_parser():
    """Build the argparse parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="tech-radar",
        description="Tech Radar — persistent SQLite-backed technology scanning system",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # -- migrate --
    p_migrate = subparsers.add_parser("migrate", help="Import history.json into the database")
    p_migrate.add_argument("--db", default=None, help="Path to database (default: ~/.tech-radar/radar.db)")
    p_migrate.add_argument("--history", default=None, help="Path to history.json (default: ~/.tech-radar/history.json)")
    p_migrate.set_defaults(func=cmd_migrate)

    # -- status --
    p_status = subparsers.add_parser("status", help="Show database statistics")
    p_status.add_argument("--db", default=None, help="Path to database (default: ~/.tech-radar/radar.db)")
    p_status.set_defaults(func=cmd_status)

    # -- stubs for future phases --
    for name, helptext in [
        ("gather", "Scan GitHub and HN for trending repos"),
        ("evaluate", "Run Claude evaluation on pending repos"),
        ("dashboard", "Launch interactive TUI dashboard"),
        ("export", "Export scan results to Obsidian markdown"),
        ("annotate", "Add annotations to repos"),
        ("search", "Search repos and verdicts via FTS"),
    ]:
        p = subparsers.add_parser(name, help=helptext)
        p.add_argument("--db", default=None, help="Path to database (default: ~/.tech-radar/radar.db)")
        p.set_defaults(func=cmd_stub(name))

    return parser


def main():
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
