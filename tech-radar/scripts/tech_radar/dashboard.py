"""Interactive TUI dashboard for Tech Radar, built with Textual."""

import json
import os
import webbrowser
from datetime import datetime, timezone

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import ScrollableContainer
from textual.screen import ModalScreen
from textual.widgets import (
    DataTable,
    Footer,
    Input,
    Static,
    Tabs,
    Tab,
    TextArea,
    Button,
)
from textual.widgets._data_table import RowKey

from . import db as db_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SPARKLINE_CHARS = "▁▂▃▄▅▆▇█"

CATEGORY_ABBREV = {
    "stack": "stk",
    "integration": "int",
    "plugin": "plg",
    "general": "gen",
}

STATUS_EMOJI = {
    "watching": "👀",
    "tested": "✅",
    "rejected": "❌",
    "adopted": "🏆",
    "new": "—",
}

SORT_COLUMNS = ["stars", "delta", "category", "name"]


def _sparkline(values: list[int | float]) -> str:
    """Render a unicode block-character sparkline from a list of numbers."""
    if len(values) < 2:
        return f"{len(values)} data point(s)"
    lo, hi = min(values), max(values)
    span = hi - lo if hi != lo else 1
    return "".join(
        SPARKLINE_CHARS[min(int((v - lo) / span * (len(SPARKLINE_CHARS) - 1)), len(SPARKLINE_CHARS) - 1)]
        for v in values
    )


def _format_stars(n: int | None) -> str:
    if n is None:
        return "—"
    return f"{n:,}"


def _format_delta_pct(pct: float | None) -> str:
    if pct is None:
        return "—"
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def _staleness(scan_date_str: str | None) -> tuple[str, str]:
    """Return (label, css_class) for staleness indicator."""
    if not scan_date_str:
        return ("unknown", "stale-red")
    try:
        scan_dt = datetime.fromisoformat(scan_date_str.replace("Z", "+00:00"))
        if scan_dt.tzinfo is None:
            scan_dt = scan_dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return ("unknown", "stale-red")
    now = datetime.now(timezone.utc)
    days = (now - scan_dt).days
    if days <= 7:
        return (f"{days}d ago", "stale-green")
    elif days <= 30:
        return (f"{days}d ago", "stale-yellow")
    else:
        return (f"{days}d ago", "stale-red")


def _truncate(s: str, maxlen: int = 30) -> str:
    if not s:
        return ""
    return s if len(s) <= maxlen else s[: maxlen - 1] + "…"


def _load_project_names(config_path: str = "~/.tech-radar.json") -> list[str]:
    """Load project names from config file."""
    path = os.path.expanduser(config_path)
    if not os.path.exists(path):
        return []
    try:
        with open(path) as f:
            cfg = json.load(f)
        projects = cfg.get("projects", {})
        if isinstance(projects, dict):
            return list(projects.keys())
        return [p.get("name", p.get("id", "")) for p in projects]
    except (json.JSONDecodeError, KeyError, TypeError):
        return []


# ---------------------------------------------------------------------------
# Annotation Modal
# ---------------------------------------------------------------------------

class AnnotationModal(ModalScreen[dict | None]):
    """Modal dialog for adding notes when marking a repo as tested/rejected."""

    def __init__(self, title: str, repo_name: str, existing_notes: str = "") -> None:
        super().__init__()
        self._title = title
        self._repo_name = repo_name
        self._existing_notes = existing_notes

    def compose(self) -> ComposeResult:
        yield Static(self._title, classes="detail-heading")
        yield Static(self._repo_name)
        yield TextArea(self._existing_notes, id="modal-notes")
        yield Button("Save", variant="primary", id="btn-save")
        yield Button("Cancel", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-save":
            notes = self.query_one("#modal-notes", TextArea).text
            self.dismiss({"notes": notes})
        else:
            self.dismiss(None)


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------

class TechRadarApp(App):
    """Tech Radar interactive TUI dashboard."""

    CSS_PATH = "dashboard.tcss"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("s", "sort", "Sort"),
        Binding("S", "reverse_sort", "Reverse"),
        Binding("tab", "next_tab", "Next Tab", show=False),
        Binding("shift+tab", "prev_tab", "Prev Tab", show=False),
        Binding("w", "watch", "Watch"),
        Binding("t", "tested", "Tested"),
        Binding("r", "reject", "Reject"),
        Binding("a", "adopted", "Adopted"),
        Binding("o", "open_url", "Open URL"),
        Binding("c", "copy_url", "Copy URL"),
        Binding("p", "cycle_project", "Project"),
        Binding("slash", "search", "Search"),
        Binding("question_mark", "help", "Help"),
        Binding("escape", "dismiss_search", "Dismiss", show=False),
    ]

    def __init__(self, db_path: str | None = None) -> None:
        super().__init__()
        self._db_path = db_path
        self._db = None
        self._current_tab = "All"
        self._sort_column = "stars"
        self._sort_direction = "DESC"
        self._project_filter: str | None = None
        self._search_query: str | None = None
        self._project_names: list[str] = []
        self._row_data: dict[str, dict] = {}  # row_key -> full row dict
        self._last_scan_date: str | None = None

    def compose(self) -> ComposeResult:
        yield Static("Tech Radar Dashboard   Project: All   Last scan: …", id="header-bar")
        yield Tabs(
            Tab("All", id="tab-all"),
            Tab("Watching", id="tab-watching"),
            Tab("Tested", id="tab-tested"),
            Tab("Rejected", id="tab-rejected"),
            id="tab-bar",
        )
        yield Input(placeholder="Search repos…", id="search-input")
        yield DataTable(id="main-table")
        yield ScrollableContainer(Static(id="detail-content"), id="detail")
        yield Footer()

    def on_mount(self) -> None:
        self._db = db_module.open_db(self._db_path)
        self._project_names = _load_project_names()

        # Get last scan date
        row = self._db.execute(
            "SELECT scan_date FROM scans ORDER BY id DESC LIMIT 1"
        ).fetchone()
        self._last_scan_date = row[0] if row else None

        # Setup table columns
        table = self.query_one("#main-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Repo", "Stars", "Δ%", "Cat", "Status", "Flags")

        self._update_header()
        self._load_repos()

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------

    def _update_header(self) -> None:
        project_label = self._project_filter or "All"
        stale_label, stale_class = _staleness(self._last_scan_date)
        header = self.query_one("#header-bar", Static)
        header.update(
            f"Tech Radar Dashboard   Project: {project_label}   "
            f"Last scan: [{stale_class}]{stale_label}[/]   "
            f"Sort: {self._sort_column} {self._sort_direction}"
        )

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_repos(self) -> None:
        table = self.query_one("#main-table", DataTable)
        table.clear()
        self._row_data.clear()

        latest_scan_id = db_module.get_latest_scan_id(self._db)
        if latest_scan_id is None:
            self.query_one("#detail-content", Static).update(
                "No data yet. Run 'tech-radar gather' to scan for repos."
            )
            return

        # Build query
        sql = """
            SELECT r.id, r.full_name, r.url, r.description, r.language, r.topics,
                   r.homepage, r.license, r.archived, r.first_seen,
                   ss.stars, ss.stars_delta, ss.stars_delta_pct,
                   ss.category, ss.is_under_radar, ss.is_rising,
                   ss.matched_keywords, ss.matched_projects, ss.hn_context,
                   COALESCE(a.status, 'new') as annotation_status,
                   a.notes as annotation_notes, a.tested_date, a.rejection_reason,
                   v.verdict_text, v.project_relevance
            FROM repos r
            JOIN scan_snapshots ss ON ss.repo_id = r.id
            LEFT JOIN annotations a ON a.repo_id = r.id
            LEFT JOIN verdicts v ON v.repo_id = r.id
                AND v.scan_id = (SELECT MAX(v2.scan_id) FROM verdicts v2 WHERE v2.repo_id = r.id)
            WHERE ss.scan_id = ?
        """
        params: list = [latest_scan_id]

        # Tab filter
        tab_status = {
            "Watching": "watching",
            "Tested": "tested",
            "Rejected": "rejected",
        }.get(self._current_tab)
        if tab_status:
            sql += " AND COALESCE(a.status, 'new') = ?"
            params.append(tab_status)

        # Project filter
        if self._project_filter:
            sql += " AND ss.matched_projects LIKE ?"
            params.append(f"%{self._project_filter}%")

        # Sort
        sort_map = {
            "stars": "ss.stars",
            "delta": "ss.stars_delta_pct",
            "category": "ss.category",
            "name": "r.full_name",
        }
        order_col = sort_map.get(self._sort_column, "ss.stars")
        sql += f" ORDER BY {order_col} {self._sort_direction}"

        rows = self._db.execute(sql, params).fetchall()
        columns = [
            "id", "full_name", "url", "description", "language", "topics",
            "homepage", "license", "archived", "first_seen",
            "stars", "stars_delta", "stars_delta_pct",
            "category", "is_under_radar", "is_rising",
            "matched_keywords", "matched_projects", "hn_context",
            "annotation_status", "annotation_notes", "tested_date",
            "rejection_reason", "verdict_text", "project_relevance",
        ]

        # FTS post-filter
        fts_ids: set | None = None
        if self._search_query:
            try:
                fts_results = db_module.search_fts(self._db, self._search_query, table="repos")
                fts_ids = {r["id"] for r in fts_results}
            except Exception:
                fts_ids = set()

        added = 0
        for row in rows:
            data = dict(zip(columns, row))
            repo_id = data["id"]

            if fts_ids is not None and repo_id not in fts_ids:
                continue

            key = str(repo_id)
            self._row_data[key] = data

            flags = ""
            if data.get("is_under_radar"):
                flags += "🔬"
            if data.get("is_rising"):
                flags += "↑"

            cat_abbrev = CATEGORY_ABBREV.get(data.get("category", ""), data.get("category", "")[:3])
            status_icon = STATUS_EMOJI.get(data.get("annotation_status", "new"), "—")

            table.add_row(
                _truncate(data["full_name"]),
                _format_stars(data.get("stars")),
                _format_delta_pct(data.get("stars_delta_pct")),
                cat_abbrev,
                status_icon,
                flags,
                key=key,
            )
            added += 1

        # Empty states
        if added == 0:
            detail = self.query_one("#detail-content", Static)
            if self._search_query:
                detail.update(f"No results for '{self._search_query}'.")
            elif tab_status:
                detail.update(f"No repos with status '{tab_status}' yet.")
            else:
                detail.update("No repos found.")

    # ------------------------------------------------------------------
    # Detail panel
    # ------------------------------------------------------------------

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is None:
            return
        key = str(event.row_key.value)
        data = self._row_data.get(key)
        if not data:
            return
        self._update_detail(data)

    def _update_detail(self, data: dict) -> None:
        detail = self.query_one("#detail-content", Static)

        stars = data.get("stars", 0) or 0
        delta = data.get("stars_delta")
        pct = data.get("stars_delta_pct")
        delta_str = ""
        if delta is not None:
            sign = "+" if delta >= 0 else ""
            delta_str = f" ({sign}{delta:,}, {_format_delta_pct(pct)})"

        lines = [
            f"[bold]{data['full_name']}[/bold]",
            f"★ {_format_stars(stars)}{delta_str}",
            "",
        ]

        # Metadata
        for label, key in [
            ("Language", "language"),
            ("License", "license"),
            ("Category", "category"),
            ("First seen", "first_seen"),
        ]:
            val = data.get(key)
            if val:
                lines.append(f"[bold]{label}:[/bold] {val}")

        # Sparkline
        repo_id = data["id"]
        spark_rows = self._db.execute(
            "SELECT stars FROM scan_snapshots WHERE repo_id = ? ORDER BY scan_id",
            [repo_id],
        ).fetchall()
        if spark_rows:
            values = [r[0] for r in spark_rows]
            lines.append("")
            lines.append(f"[bold]Trend:[/bold] {_sparkline(values)}  ({len(values)} scans)")

        # Flags
        flags = []
        if data.get("is_under_radar"):
            flags.append("🔬 Under-radar")
        if data.get("is_rising"):
            flags.append("↑ Rising")
        if flags:
            lines.append(f"[bold]Flags:[/bold] {', '.join(flags)}")

        # Matched projects
        mp = data.get("matched_projects")
        if mp:
            try:
                projects = json.loads(mp) if isinstance(mp, str) else mp
                if projects:
                    lines.append(f"[bold]Projects:[/bold] {', '.join(projects)}")
            except (json.JSONDecodeError, TypeError):
                if mp and mp != "[]":
                    lines.append(f"[bold]Projects:[/bold] {mp}")

        # Verdict
        verdict = data.get("verdict_text")
        if verdict:
            lines.append("")
            lines.append("[bold]Verdict:[/bold]")
            lines.append(verdict)
        else:
            lines.append("")
            lines.append("[dim]Pending evaluation[/dim]")

        # Project relevance
        pr = data.get("project_relevance")
        if pr:
            lines.append("")
            lines.append("[bold]Project Relevance:[/bold]")
            lines.append(str(pr))

        # HN Context
        hn = data.get("hn_context")
        if hn:
            lines.append("")
            lines.append("[bold]HN Context:[/bold]")
            lines.append(hn)

        # Annotation
        status = data.get("annotation_status", "new")
        if status != "new":
            lines.append("")
            lines.append(f"[bold]Annotation:[/bold] {status}")
            notes = data.get("annotation_notes")
            if notes:
                lines.append(f"  Notes: {notes}")
            td = data.get("tested_date")
            if td:
                lines.append(f"  Tested: {td}")
            rr = data.get("rejection_reason")
            if rr:
                lines.append(f"  Reason: {rr}")

        # URL
        url = data.get("url", "")
        if url:
            lines.append("")
            lines.append(f"[dim]{url}[/dim]")

        detail.update("\n".join(lines))

    # ------------------------------------------------------------------
    # Tab switching
    # ------------------------------------------------------------------

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        label = str(event.tab.label) if event.tab else "All"
        self._current_tab = label
        self._load_repos()

    # ------------------------------------------------------------------
    # Sort
    # ------------------------------------------------------------------

    def action_sort(self) -> None:
        idx = SORT_COLUMNS.index(self._sort_column)
        self._sort_column = SORT_COLUMNS[(idx + 1) % len(SORT_COLUMNS)]
        self._sort_direction = "DESC"
        self._update_header()
        self._load_repos()

    def action_reverse_sort(self) -> None:
        self._sort_direction = "ASC" if self._sort_direction == "DESC" else "DESC"
        self._update_header()
        self._load_repos()

    # ------------------------------------------------------------------
    # Annotations
    # ------------------------------------------------------------------

    def _get_selected_repo(self) -> dict | None:
        table = self.query_one("#main-table", DataTable)
        if table.row_count == 0:
            return None
        row_key = table.cursor_row
        if row_key is None or row_key < 0:
            return None
        # Get the RowKey for the current cursor row
        try:
            key = str(table.get_row_at(row_key))
            # Actually we need the row_key, not the row data
        except Exception:
            return None
        # Use ordered_rows to get the key
        try:
            rk = list(table.rows.keys())[row_key]
            return self._row_data.get(str(rk.value))
        except (IndexError, AttributeError):
            return None

    def action_watch(self) -> None:
        data = self._get_selected_repo()
        if not data:
            return
        current = data.get("annotation_status", "new")
        new_status = "new" if current == "watching" else "watching"
        db_module.save_annotation(self._db, data["id"], new_status)
        self._load_repos()

    def action_tested(self) -> None:
        data = self._get_selected_repo()
        if not data:
            return

        def on_modal_result(result: dict | None) -> None:
            if result is not None:
                db_module.save_annotation(
                    self._db, data["id"], "tested", notes=result.get("notes")
                )
                self._load_repos()

        self.push_screen(
            AnnotationModal(
                "Mark as Tested",
                data["full_name"],
                data.get("annotation_notes", "") or "",
            ),
            on_modal_result,
        )

    def action_reject(self) -> None:
        data = self._get_selected_repo()
        if not data:
            return

        def on_modal_result(result: dict | None) -> None:
            if result is not None:
                db_module.save_annotation(
                    self._db, data["id"], "rejected",
                    notes=result.get("notes"),
                    reason=result.get("notes"),
                )
                self._load_repos()

        self.push_screen(
            AnnotationModal(
                "Mark as Rejected",
                data["full_name"],
                data.get("annotation_notes", "") or "",
            ),
            on_modal_result,
        )

    def action_adopted(self) -> None:
        data = self._get_selected_repo()
        if not data:
            return
        db_module.save_annotation(self._db, data["id"], "adopted")
        self._load_repos()

    # ------------------------------------------------------------------
    # URL actions
    # ------------------------------------------------------------------

    def action_open_url(self) -> None:
        data = self._get_selected_repo()
        if data and data.get("url"):
            webbrowser.open(data["url"])

    def action_copy_url(self) -> None:
        data = self._get_selected_repo()
        if data and data.get("url"):
            self.copy_to_clipboard(data["url"])
            self.notify("Copied URL to clipboard!")

    # ------------------------------------------------------------------
    # Project filter
    # ------------------------------------------------------------------

    def action_cycle_project(self) -> None:
        if not self._project_names:
            self.notify("No projects in ~/.tech-radar.json")
            return
        if self._project_filter is None:
            self._project_filter = self._project_names[0]
        else:
            try:
                idx = self._project_names.index(self._project_filter)
                next_idx = idx + 1
                if next_idx >= len(self._project_names):
                    self._project_filter = None
                else:
                    self._project_filter = self._project_names[next_idx]
            except ValueError:
                self._project_filter = None
        self._update_header()
        self._load_repos()

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def action_search(self) -> None:
        search = self.query_one("#search-input", Input)
        search.add_class("visible")
        search.focus()

    def action_dismiss_search(self) -> None:
        search = self.query_one("#search-input", Input)
        search.remove_class("visible")
        search.value = ""
        if self._search_query is not None:
            self._search_query = None
            self._load_repos()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search-input":
            query = event.value.strip()
            self._search_query = query if query else None
            self._load_repos()

    # ------------------------------------------------------------------
    # Help
    # ------------------------------------------------------------------

    def action_help(self) -> None:
        self.notify(
            "Keys: s=sort S=reverse w=watch t=tested r=reject a=adopted "
            "o=open c=copy p=project /=search q=quit",
            timeout=8,
        )
