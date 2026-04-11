"""CLI entry point with argparse subcommands."""

import argparse
import os
import signal
import sys

import json

from . import db as db_module
from .gather import run_gather
from .evaluate import get_pending_repos, save_verdicts


# -- Dashboard state directory & file paths --

_DASHBOARD_STATE_DIR = os.path.join(os.path.expanduser("~"), ".tech-radar")


def _dashboard_pidfile():
    """Return path to the dashboard PID/port file (web mode)."""
    return os.path.join(_DASHBOARD_STATE_DIR, "dashboard.pid")


def _dashboard_panefile():
    """Return path to the cmux pane state file."""
    return os.path.join(_DASHBOARD_STATE_DIR, "dashboard-pane.json")


def _is_process_alive(pid, expected_name="tech-radar"):
    """Check if a process is alive AND matches expected name (avoid PID reuse)."""
    import subprocess as _sp
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    # Verify process name on macOS to guard against PID reuse
    try:
        result = _sp.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True, text=True, timeout=2,
        )
        cmd_line = result.stdout.strip()
        return expected_name in cmd_line or "textual" in cmd_line
    except Exception:
        # If ps fails, fall back to optimistic (process exists)
        return True


def _cleanup_stale_processes():
    """Kill any orphan dashboard processes left by previous runs."""
    import subprocess as _sp
    try:
        result = _sp.run(
            ["pgrep", "-f", "tech-radar dashboard"],
            capture_output=True, text=True, timeout=5,
        )
        my_pid = os.getpid()
        parent_pid = os.getppid()
        for line in result.stdout.strip().splitlines():
            try:
                pid = int(line.strip())
                if pid in (my_pid, parent_pid):
                    continue
                if _is_process_alive(pid, "tech-radar"):
                    os.kill(pid, signal.SIGTERM)
            except (ValueError, OSError):
                pass
    except Exception:
        pass

    # Also clean stale textual-serve processes
    try:
        result = _sp.run(
            ["pgrep", "-f", "textual-serve"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.strip().splitlines():
            try:
                pid = int(line.strip())
                if _is_process_alive(pid, "textual"):
                    os.kill(pid, signal.SIGTERM)
            except (ValueError, OSError):
                pass
    except Exception:
        pass


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


def cmd_evaluate_pending(args):
    """Output pending repos as JSON to stdout."""
    database = db_module.open_db(args.db)
    result = get_pending_repos(database)
    print(json.dumps(result, indent=2))


def cmd_evaluate_save(args):
    """Read verdict JSON from stdin and save to DB."""
    database = db_module.open_db(args.db)
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


def _run_tui(db_path):
    """Launch the Textual TUI dashboard directly."""
    from .dashboard import TechRadarApp
    app = TechRadarApp(db_path=db_path)
    app.run()


def cmd_dashboard(args):
    """Launch the interactive TUI dashboard."""
    # --kill: explicit cleanup of all dashboard processes
    if getattr(args, "kill", False):
        print("Cleaning up dashboard processes...")
        _cleanup_stale_processes()
        # Remove state files
        for path in (_dashboard_pidfile(), _dashboard_panefile()):
            try:
                os.remove(path)
                print(f"  Removed {path}")
            except OSError:
                pass
        print("Done.")
        return

    if args.web:
        _launch_web_dashboard(args)
    elif _in_cmux():
        _launch_cmux_dashboard(args)
    else:
        _run_tui(args.db)


def _in_cmux() -> bool:
    """Return True if running inside cmux with CLI available (and not already spawned)."""
    import shutil
    if os.environ.get("TECH_RADAR_CMUX_PANE"):
        return False
    return bool(os.environ.get("CMUX_WORKSPACE_ID")) and shutil.which("cmux") is not None


def _cmux_pane_alive(surface_id):
    """Check if a cmux pane is still active by reading its screen."""
    import subprocess as _sp
    try:
        surface_arg = surface_id if surface_id.startswith("surface:") else f"surface:{surface_id}"
        result = _sp.run(
            ["cmux", "read-screen", "--surface", surface_arg],
            capture_output=True, text=True, timeout=3,
        )
        return result.returncode == 0
    except Exception:
        return False


def _read_cmux_pane_state():
    """Read saved cmux pane state. Returns (surface_id,) or None."""
    panefile = _dashboard_panefile()
    if not os.path.exists(panefile):
        return None
    try:
        with open(panefile) as f:
            data = json.loads(f.read())
        surface_id = data.get("surface_id")
        if surface_id and _cmux_pane_alive(surface_id):
            return surface_id
        # Stale — clean up
        os.remove(panefile)
    except (OSError, json.JSONDecodeError, KeyError):
        try:
            os.remove(panefile)
        except OSError:
            pass
    return None


def _write_cmux_pane_state(surface_id):
    """Save cmux pane state for singleton detection."""
    panefile = _dashboard_panefile()
    os.makedirs(os.path.dirname(panefile), exist_ok=True)
    with open(panefile, "w") as f:
        f.write(json.dumps({"surface_id": surface_id}))


def _launch_cmux_dashboard(args):
    """Launch dashboard TUI in a new cmux pane (split right), with singleton guard."""
    import re
    import shlex
    import subprocess
    import time

    # Singleton: check if a dashboard pane already exists
    existing_surface = _read_cmux_pane_state()
    if existing_surface:
        print(f"Tech Radar dashboard already running in cmux pane (surface {existing_surface}).")
        return

    # Clean up any orphan processes before launching
    _cleanup_stale_processes()

    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    entry = os.path.join(script_dir, "tech-radar")
    # TECH_RADAR_CMUX_PANE=1 prevents recursive cmux spawning
    cmd = f"TECH_RADAR_CMUX_PANE=1 {shlex.quote(sys.executable)} {shlex.quote(entry)} dashboard"
    if args.db:
        cmd += f" --db {shlex.quote(args.db)}"

    try:
        # Create a right-split pane and parse the surface ID from output
        result = subprocess.run(
            ["cmux", "new-pane", "--direction", "right"],
            check=True,
            capture_output=True,
            text=True,
        )
        # Output: "OK surface:7 pane:7 workspace:4"
        match = re.search(r"surface:(\S+)", result.stdout)
        surface = match.group(1) if match else None

        # Save pane state for singleton detection
        if surface:
            _write_cmux_pane_state(surface)

        surface_flag = f"surface:{surface}" if surface else None

        # Wait for the shell to initialize before sending the command
        send_args = ["cmux", "send"]
        if surface_flag:
            send_args += ["--surface", surface_flag]

        # Poll read-screen until we see a prompt (up to 2s)
        for _ in range(8):
            time.sleep(0.25)
            screen = subprocess.run(
                ["cmux", "read-screen"] + (["--surface", surface_flag] if surface_flag else []),
                capture_output=True, text=True,
            )
            if screen.stdout.strip():
                break

        send_args.append(cmd + "\n")
        subprocess.run(send_args, check=True, capture_output=True, text=True)
        print("Tech Radar dashboard opened in cmux split pane.")
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        detail = getattr(e, "stderr", str(e))
        print(f"cmux launch failed: {detail}", file=sys.stderr)
        print("Falling back to --web mode.", file=sys.stderr)
        # Clean up pane state on failure
        try:
            os.remove(_dashboard_panefile())
        except OSError:
            pass
        _launch_web_dashboard(args)


def _running_dashboard_url():
    """If a dashboard is already running, return its URL; otherwise None."""
    import socket

    pidfile = _dashboard_pidfile()
    if not os.path.exists(pidfile):
        return None
    try:
        with open(pidfile) as f:
            data = json.loads(f.read())
        pid, port = data["pid"], data["port"]
        # Check process alive AND matches expected name (guards against PID reuse)
        if not _is_process_alive(pid, "tech-radar"):
            raise OSError("stale pid")
        # Check if port is actually listening
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            s.connect(("localhost", port))
        return f"http://localhost:{port}"
    except (OSError, KeyError, json.JSONDecodeError, ConnectionRefusedError):
        # Stale pidfile — clean up
        try:
            os.remove(pidfile)
        except OSError:
            pass
        return None


def _write_dashboard_pidfile(port):
    """Write PID file with current process ID and port."""
    pidfile = _dashboard_pidfile()
    os.makedirs(os.path.dirname(pidfile), exist_ok=True)
    with open(pidfile, "w") as f:
        f.write(json.dumps({"pid": os.getpid(), "port": port}))


def _cleanup_dashboard_pidfile(*_args):
    """Remove PID file on exit (works as both atexit and signal handler)."""
    try:
        os.remove(_dashboard_pidfile())
    except OSError:
        pass


def _launch_web_dashboard(args):
    """Launch dashboard in browser via textual-serve."""
    import atexit
    import shlex
    import socket

    # Clean up any orphan processes before launching
    _cleanup_stale_processes()

    # Check for already-running instance — just print URL, never auto-open browser
    existing = _running_dashboard_url()
    if existing:
        print(f"Dashboard already running at {existing}")
        return

    try:
        from textual_serve.server import Server
    except ImportError:
        print("textual-serve not installed. Install with:", file=sys.stderr)
        req_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "requirements.txt")
        print(f"  pip3 install -r {req_path}", file=sys.stderr)
        sys.exit(1)

    # Find a free port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        port = s.getsockname()[1]

    # Write PID file and register cleanup via atexit AND signal handlers
    _write_dashboard_pidfile(port)
    atexit.register(_cleanup_dashboard_pidfile)

    # Install signal handlers so PID file is cleaned even on SIGTERM/SIGINT
    def _signal_cleanup(signum, frame):
        _cleanup_dashboard_pidfile()
        sys.exit(128 + signum)

    signal.signal(signal.SIGTERM, _signal_cleanup)
    signal.signal(signal.SIGINT, _signal_cleanup)

    # Build the command that textual-serve will spawn
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    entry = os.path.join(script_dir, "tech-radar")
    serve_cmd = f"{shlex.quote(sys.executable)} {shlex.quote(entry)} dashboard"
    if args.db:
        serve_cmd += f" --db {shlex.quote(args.db)}"

    url = f"http://localhost:{port}"
    print(f"Starting tech-radar dashboard at {url}")
    print("Press Ctrl+C to stop.\n")

    server = Server(command=serve_cmd, host="localhost", port=port,
                    title="Tech Radar Dashboard")
    server.serve()


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
    eval_sub = p_eval.add_subparsers(dest="eval_command", help="Evaluate subcommands")

    p_eval_pending = eval_sub.add_parser("pending", help="Output pending repos as JSON to stdout")
    p_eval_pending.add_argument("--db", default=None, help="Path to database (default: ~/.tech-radar/radar.db)")
    p_eval_pending.set_defaults(func=cmd_evaluate_pending)

    p_eval_save = eval_sub.add_parser("save", help="Read verdict JSON from stdin and save to DB")
    p_eval_save.add_argument("--db", default=None, help="Path to database (default: ~/.tech-radar/radar.db)")
    p_eval_save.add_argument("--tokens-in", type=int, default=None, help="Input tokens used during evaluation")
    p_eval_save.add_argument("--tokens-out", type=int, default=None, help="Output tokens used during evaluation")
    p_eval_save.add_argument("--web-searches", type=int, default=None, help="Web searches performed during evaluation")
    p_eval_save.set_defaults(func=cmd_evaluate_save)

    # Default: show help if no subcommand
    p_eval.set_defaults(func=lambda args: p_eval.print_help() or sys.exit(1))

    # -- dashboard --
    p_dashboard = subparsers.add_parser("dashboard", help="Launch interactive TUI dashboard")
    p_dashboard.add_argument("--db", default=None, help="Path to database (default: ~/.tech-radar/radar.db)")
    p_dashboard.add_argument("--web", action="store_true", help="Launch in browser via textual-serve instead of terminal TUI")
    p_dashboard.add_argument("--kill", action="store_true", help="Kill all running dashboard processes and clean up state files")
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
