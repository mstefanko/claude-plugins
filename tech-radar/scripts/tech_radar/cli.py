"""CLI entry point with argparse subcommands."""

import argparse
import sys

import json

from . import db as db_module
from .gather import run_gather
from .evaluate import get_pending_repos, save_verdicts


def cmd_gather(args):
    """Run the gather pipeline: scan GitHub/HN and write to DB."""
    summary = run_gather(
        timeframe=args.timeframe,
        source=args.source,
        max_repos=args.max_repos,
        dry_run=args.dry_run,
        show_queries=args.show_queries,
        no_fuzzy=args.no_fuzzy,
        db_path=args.db,
        config_path=args.config,
    )
    # Print summary as JSON to stdout
    print(json.dumps(summary, indent=2))


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


def cmd_evaluate(args):
    """Handle the evaluate subcommand: --pending or --save."""
    database = db_module.open_db(args.db)

    if args.pending:
        result = get_pending_repos(database)
        print(json.dumps(result, indent=2))
    elif args.save:
        raw = sys.stdin.read()
        verdicts_list = json.loads(raw)
        result = save_verdicts(
            database,
            verdicts_list,
            tokens_in=args.tokens_in,
            tokens_out=args.tokens_out,
            web_searches=args.web_searches,
        )
        print(json.dumps(result, indent=2))
    else:
        print("Specify --pending or --save. See 'tech-radar evaluate -h' for usage.")
        sys.exit(1)


def cmd_dashboard(args):
    """Launch the interactive TUI dashboard."""
    from .dashboard import TechRadarApp
    app = TechRadarApp(db_path=args.db)
    app.run()


def cmd_export(args):
    """Export scan results to Obsidian markdown."""
    from .export import export_scan
    db = db_module.open_db(args.db)
    scan_id = None
    if hasattr(args, 'date') and args.date:
        row = db.execute(
            "SELECT id FROM scans WHERE scan_date = ? ORDER BY id DESC LIMIT 1",
            [args.date],
        ).fetchone()
        if row:
            scan_id = row[0]
        else:
            print(f"No scan found for date {args.date}")
            sys.exit(1)
    result = export_scan(db, scan_id=scan_id, output_path=args.output)
    if result != "stdout":
        print(f"Exported to: {result}")


def cmd_annotate(args):
    """Add or update an annotation on a repo."""
    db = db_module.open_db(args.db)
    repo = db_module.get_repo_by_name(db, args.repo)
    if not repo:
        print(f"Repo '{args.repo}' not found")
        sys.exit(1)
    db_module.save_annotation(db, repo["id"], args.status, notes=args.notes, reason=args.reason)
    print(f"Annotated {args.repo} as {args.status}")


def cmd_search(args):
    """Search repos or verdicts via FTS."""
    db = db_module.open_db(args.db)
    results = db_module.search_fts(db, args.query, table=args.table)
    for r in results[:20]:
        if args.table == "repos":
            print(f"  {r['full_name']}: {(r.get('description') or '')[:80]}")
        else:
            print(f"  {(r.get('verdict_text') or '')[:100]}")
    print(f"\n{len(results)} result(s)")


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

    # -- gather --
    p_gather = subparsers.add_parser("gather", help="Scan GitHub and HN for trending repos")
    p_gather.add_argument("--db", default=None, help="Path to database (default: ~/.tech-radar/radar.db)")
    p_gather.add_argument("--timeframe", choices=["weekly", "monthly", "quarterly"],
                          default="monthly", help="Lookback window (default: monthly)")
    p_gather.add_argument("--source", choices=["github", "hn", "all"],
                          default="all", help="Data source (default: all)")
    p_gather.add_argument("--max-repos", type=int, default=None,
                          help="Maximum main repos in output")
    p_gather.add_argument("--dry-run", action="store_true",
                          help="Read from fixtures instead of making HTTP calls")
    p_gather.add_argument("--show-queries", action="store_true",
                          help="Print generated queries to stderr and exit")
    p_gather.add_argument("--no-fuzzy", action="store_true",
                          help="Disable rapidfuzz matching (exact substring only)")
    p_gather.add_argument("--config", default="~/.tech-radar.json",
                          help="Config file path (default: ~/.tech-radar.json)")
    p_gather.set_defaults(func=cmd_gather)

    # -- evaluate --
    p_eval = subparsers.add_parser("evaluate", help="Run Claude evaluation on pending repos")
    p_eval.add_argument("--db", default=None, help="Path to database (default: ~/.tech-radar/radar.db)")
    p_eval.add_argument("--pending", action="store_true", help="Output pending repos as JSON to stdout")
    p_eval.add_argument("--save", action="store_true", help="Read verdict JSON from stdin and save to DB")
    p_eval.add_argument("--tokens-in", type=int, default=None, help="Input tokens used during evaluation")
    p_eval.add_argument("--tokens-out", type=int, default=None, help="Output tokens used during evaluation")
    p_eval.add_argument("--web-searches", type=int, default=None, help="Web searches performed during evaluation")
    p_eval.set_defaults(func=cmd_evaluate)

    # -- dashboard --
    p_dashboard = subparsers.add_parser("dashboard", help="Launch interactive TUI dashboard")
    p_dashboard.add_argument("--db", default=None, help="Path to database (default: ~/.tech-radar/radar.db)")
    p_dashboard.set_defaults(func=cmd_dashboard)

    # -- export --
    p_export = subparsers.add_parser("export", help="Export scan results to Obsidian markdown")
    p_export.add_argument("--db", default=None, help="Path to database (default: ~/.tech-radar/radar.db)")
    p_export.add_argument("--date", default=None, help="Scan date to export (YYYY-MM-DD)")
    p_export.add_argument("--output", default=None, help="Output file path (default: Obsidian vault or stdout)")
    p_export.set_defaults(func=cmd_export)

    # -- annotate --
    p_annotate = subparsers.add_parser("annotate", help="Add annotations to repos")
    p_annotate.add_argument("repo", help="Repo full_name (e.g. owner/repo)")
    p_annotate.add_argument("status", choices=["watching", "tested", "adopted", "rejected", "archived"],
                            help="Annotation status")
    p_annotate.add_argument("--notes", default=None, help="Free-text notes")
    p_annotate.add_argument("--reason", default=None, help="Rejection reason (used with 'rejected' status)")
    p_annotate.add_argument("--db", default=None, help="Path to database (default: ~/.tech-radar/radar.db)")
    p_annotate.set_defaults(func=cmd_annotate)

    # -- search --
    p_search = subparsers.add_parser("search", help="Search repos and verdicts via FTS")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--table", choices=["repos", "verdicts"], default="repos",
                          help="Table to search (default: repos)")
    p_search.add_argument("--db", default=None, help="Path to database (default: ~/.tech-radar/radar.db)")
    p_search.set_defaults(func=cmd_search)

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
