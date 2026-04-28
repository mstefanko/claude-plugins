"""Interactive TUI dashboard for Tech Radar, built with Textual."""

import json
import os
import webbrowser
from datetime import datetime, timezone

from rich.markup import escape
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer
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

from . import db as db_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SPARKLINE_CHARS = "▁▂▃▄▅▆▇█"

CATEGORY_ABBREV = {
    "stack-match": "stk",
    "interest-match": "int",
    "plugin": "plg",
    "general": "gen",
    "frontend": "fe",
    "selfhosted": "sh",
    "mcp": "mcp",
}

STATUS_BADGES = {
    "new": ("NEW", "black on #7aa2f7"),
    "watching": ("WATCH", "black on #e0af68"),
    "tested": ("TESTED", "black on #9ece6a"),
    "adopted": ("ADOPT", "black on #7dcfff"),
    "rejected": ("REJECT", "white on #f7768e"),
    "archived": ("ARCH", "black on #565f89"),
}

STATUS_NAME_STYLE = {
    "new": "bold",
    "watching": "bold #9ece6a",
    "tested": "dim",
    "adopted": "bold #7dcfff",
    "rejected": "dim",
    "archived": "dim",
}

STATUS_HINTS = {
    "new": "triage",
    "watching": "watchlist",
    "tested": "tested",
    "adopted": "in stack",
    "rejected": "dismissed",
    "archived": "archived",
}

CATEGORY_BADGE_STYLES = {
    "stack-match": "white on #3d59a1",
    "interest-match": "black on #bb9af7",
    "plugin": "black on #7dcfff",
    "general": "black on #565f89",
    "frontend": "black on #9ece6a",
    "selfhosted": "black on #e0af68",
    "mcp": "black on #f7768e",
}

SORT_COLUMNS = ["stars", "delta", "category", "name"]
TAB_STATUS = {
    "Watching": "watching",
    "Tested": "tested",
    "Adopted": "adopted",
    "Rejected": "rejected",
}
TAB_IDS = {
    "tab-all": "All",
    "tab-watching": "Watching",
    "tab-tested": "Tested",
    "tab-adopted": "Adopted",
    "tab-rejected": "Rejected",
}

VERTICAL_CYCLE = [None, "frontend", "selfhosted", "mcp"]
VERTICAL_LABELS = {None: "All", "frontend": "Frontend", "selfhosted": "Self-Hosted", "mcp": "MCP"}
VERTICAL_CATEGORIES = {
    "frontend": ("frontend",),
    "selfhosted": ("selfhosted",),
    "mcp": ("mcp", "plugin"),
}


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


def _format_delta_pct_markup(pct: float | None) -> str:
    label = _format_delta_pct(pct)
    if pct is None:
        return f"[dim]{label}[/]"
    if pct > 0:
        return f"[#9ece6a]{label}[/]"
    if pct < 0:
        return f"[#f7768e]{label}[/]"
    return f"[dim]{label}[/]"


def _badge(label: str, style: str) -> str:
    return f"[{style}] {escape(label)} [/]"


def _status_badge(status: str | None) -> str:
    label, style = STATUS_BADGES.get(status or "new", STATUS_BADGES["new"])
    return _badge(label, style)


def _category_badge(category: str | None) -> str:
    if not category:
        return ""
    label = CATEGORY_ABBREV.get(category, category[:3]).upper()
    style = CATEGORY_BADGE_STYLES.get(category, CATEGORY_BADGE_STYLES["general"])
    return _badge(label, style)


def _json_list(value: object) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [value] if value and value != "[]" else []
        if isinstance(parsed, list):
            return [str(item) for item in parsed if item]
    return []


def _format_date(value: str | None) -> str:
    if not value:
        return ""
    return value[:10]


def _join_metadata(parts: list[str]) -> str:
    return " | ".join(escape(part) for part in parts if part)


def _format_project_relevance(value: object) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return value
    else:
        parsed = value
    if isinstance(parsed, dict):
        return "\n".join(f"{key}: {val}" for key, val in parsed.items())
    if isinstance(parsed, list):
        return "\n".join(str(item) for item in parsed)
    return str(parsed)


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


class HelpModal(ModalScreen[None]):
    """Keyboard help overlay."""

    BINDINGS = [
        Binding("escape", "close", "Close", show=False),
        Binding("q", "close", "Close", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Static("[bold]Tech Radar Keys[/bold]", classes="detail-heading")
        yield Static(
            "\n".join(
                [
                    "[bold]Navigate[/bold]",
                    "  j/k or arrows     Move between rows",
                    "  tab / shift+tab   Switch status tabs",
                    "  ctrl+d / ctrl+u   Scroll preview",
                    "",
                    "[bold]View[/bold]",
                    "  p                 Toggle preview pane",
                    "  s / S             Cycle sort / reverse sort",
                    "  / / escape        Search / clear search",
                    "  P                 Cycle project filter",
                    "  v                 Cycle vertical filter",
                    "",
                    "[bold]Act[/bold]",
                    "  w                 Toggle watch",
                    "  t                 Mark tested",
                    "  a                 Mark adopted",
                    "  r                 Reject with note",
                    "  o / c             Open URL / copy URL",
                    "",
                    "[bold]System[/bold]",
                    "  ?                 Show this help",
                    "  q                 Quit",
                ]
            ),
            id="help-content",
        )
        yield Button("Close", variant="primary", id="btn-close-help")

    def action_close(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-close-help":
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
        Binding("p", "toggle_preview", "Preview"),
        Binding("P", "cycle_project", "Project"),
        Binding("v", "cycle_vertical", "Vertical"),
        Binding("ctrl+d", "preview_page_down", "Preview Down", show=False),
        Binding("ctrl+u", "preview_page_up", "Preview Up", show=False),
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
        self._vertical_filter: str | None = None
        self._search_query: str | None = None
        self._project_names: list[str] = []
        self._row_data: dict[str, dict] = {}  # row_key -> full row dict
        self._last_scan_date: str | None = None
        self._preview_visible = True

    def compose(self) -> ComposeResult:
        yield Static("Tech Radar   project: All   scan: …", id="header-bar")
        yield Tabs(
            Tab("All 0", id="tab-all"),
            Tab("Watching 0", id="tab-watching"),
            Tab("Tested 0", id="tab-tested"),
            Tab("Adopted 0", id="tab-adopted"),
            Tab("Rejected 0", id="tab-rejected"),
            id="tab-bar",
        )
        yield Input(placeholder="Search repos…", id="search-input")
        with Horizontal(id="content-area"):
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
        table.zebra_stripes = True
        table.add_column("Repository", key="repo", width=58)
        table.add_column("Stars", key="stars", width=10)
        table.add_column("Growth", key="growth", width=9)
        table.add_column("Status", key="status", width=11)

        if self.size.width < 110:
            self._preview_visible = False
            self._sync_preview_visibility(notify=False)
        self._update_header()
        self._load_repos()

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------

    def _update_header(self) -> None:
        project_label = self._project_filter or "All"
        vertical_label = VERTICAL_LABELS.get(self._vertical_filter, "All")
        stale_label, stale_class = _staleness(self._last_scan_date)
        sort_arrow = "▼" if self._sort_direction == "DESC" else "▲"
        search_indicator = (
            f"   [dim]search:[/] {escape(self._search_query)}"
            if self._search_query else ""
        )
        vertical_indicator = (
            f"   [dim]vertical:[/] {escape(vertical_label)}"
            if self._vertical_filter else ""
        )
        preview_label = "on" if self._preview_visible else "off"
        header = self.query_one("#header-bar", Static)
        header.update(
            f"[bold]Tech Radar[/]   [dim]project:[/] {escape(project_label)}"
            f"{vertical_indicator}   [dim]scan:[/] [{stale_class}]{stale_label}[/]   "
            f"[dim]sort:[/] {escape(self._sort_column)} {sort_arrow}   "
            f"[dim]preview:[/] {preview_label}{search_indicator}"
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
            "Adopted": "adopted",
            "Rejected": "rejected",
        }.get(self._current_tab)
        if tab_status:
            sql += " AND COALESCE(a.status, 'new') = ?"
            params.append(tab_status)
        elif self._current_tab == "All":
            # Hide rejected repos from All tab — they have their own tab
            sql += " AND COALESCE(a.status, 'new') != 'rejected'"

        # Project filter
        if self._project_filter:
            sql += " AND ss.matched_projects LIKE ?"
            params.append(f"%{self._project_filter}%")

        # Vertical filter
        if self._vertical_filter:
            cats = VERTICAL_CATEGORIES.get(self._vertical_filter, (self._vertical_filter,))
            cat_placeholders = ",".join("?" * len(cats))
            sql += f" AND ss.category IN ({cat_placeholders})"
            params.extend(cats)

        # Sort
        sort_map = {
            "stars": "ss.stars",
            "delta": "ss.stars_delta_pct",
            "category": "ss.category",
            "name": "r.full_name",
        }
        order_col = sort_map.get(self._sort_column, "ss.stars")
        promotion_sort = ""
        if self._current_tab == "All":
            # Boost watching/adopted to top, everything else below
            promotion_sort = (
                "CASE COALESCE(a.status, 'new') "
                "WHEN 'watching' THEN 0 "
                "WHEN 'adopted' THEN 0 "
                "ELSE 1 END, "
            )
        sql += f" ORDER BY {promotion_sort}{order_col} {self._sort_direction}"

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

            # Build composite repo cell: {status} {name} {lang} {cat} {flags}
            ann_status = data.get("annotation_status", "new")
            status_icon = STATUS_EMOJI.get(ann_status, "·")
            cat_abbrev = CATEGORY_ABBREV.get(data.get("category", ""), data.get("category", "")[:3])
            lang = data.get("language", "")
            lang_suffix = f" [dim]{lang[:4]}[/]" if lang else ""
            cat_suffix = f" [dim]{cat_abbrev}[/]"
            flag_suffix = ""
            if data.get("is_under_radar"):
                flag_suffix += " 🔬"
            if data.get("is_rising"):
                flag_suffix += " ↑"

            # Color-code by annotation status:
            #   new = bold (untriaged work queue, needs attention)
            #   watching = green (actively interesting)
            #   tested = dim (handled, de-prioritized)
            #   adopted = cyan (settled, in your stack)
            #   rejected = dim (only visible on Rejected tab)
            name_text = _truncate(data['full_name'], 38)
            if ann_status == "new":
                name_text = f"[bold]{name_text}[/]"
            elif ann_status == "watching":
                name_text = f"[green]{name_text}[/]"
            elif ann_status == "tested":
                name_text = f"[dim]{name_text}[/]"
            elif ann_status == "adopted":
                name_text = f"[cyan]{name_text}[/]"
            elif ann_status == "rejected":
                name_text = f"[dim]{name_text}[/]"

            repo_cell = f"{status_icon} {name_text}{lang_suffix}{cat_suffix}{flag_suffix}"

            table.add_row(
                repo_cell,
                _format_stars(data.get("stars")),
                _format_delta_pct(data.get("stars_delta_pct")),
                _truncate(data.get("description", ""), 45),
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

        # 1. Name
        lines = [
            f"[bold]{data['full_name']}[/bold]",
        ]

        # 2. Description
        desc = data.get("description", "")
        if desc:
            lines.append(f"[italic]{desc}[/italic]")

        lines.append("")

        # 3. Verdict (prominent)
        verdict = data.get("verdict_text")
        if verdict:
            lines.append("[bold reverse] Verdict [/bold reverse]")
            lines.append(verdict)
        else:
            lines.append("[dim]Pending evaluation[/dim]")

        # 4. Project relevance
        pr = data.get("project_relevance")
        if pr:
            lines.append("")
            lines.append("[bold]Project Relevance:[/bold]")
            lines.append(str(pr))

        # 5. Stars + delta
        lines.append("")
        lines.append(f"★ {_format_stars(stars)}{delta_str}")

        # 6. Sparkline
        repo_id = data["id"]
        spark_rows = self._db.execute(
            "SELECT stars FROM scan_snapshots WHERE repo_id = ? ORDER BY scan_id",
            [repo_id],
        ).fetchall()
        if spark_rows:
            values = [r[0] for r in spark_rows]
            lines.append(f"[bold]Trend:[/bold] {_sparkline(values)}  ({len(values)} scans)")

        # 7. Matched projects
        mp = data.get("matched_projects")
        if mp:
            try:
                projects = json.loads(mp) if isinstance(mp, str) else mp
                if projects:
                    lines.append(f"[bold]Projects:[/bold] {', '.join(projects)}")
            except (json.JSONDecodeError, TypeError):
                if mp and mp != "[]":
                    lines.append(f"[bold]Projects:[/bold] {mp}")

        # Flags
        flags = []
        if data.get("is_under_radar"):
            flags.append("🔬 Under-radar")
        if data.get("is_rising"):
            flags.append("↑ Rising")
        if flags:
            lines.append(f"[bold]Flags:[/bold] {', '.join(flags)}")

        # 8. Metadata
        lines.append("")
        for label, key in [
            ("Language", "language"),
            ("License", "license"),
            ("Category", "category"),
            ("First seen", "first_seen"),
        ]:
            val = data.get(key)
            if val:
                lines.append(f"[bold]{label}:[/bold] {val}")

        # 9. HN Context
        hn = data.get("hn_context")
        if hn:
            lines.append("")
            lines.append("[bold]HN Context:[/bold]")
            lines.append(hn)

        # 10. Annotation
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

        # 11. URL
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
        # Show notification with count and next project hint
        count = len(self._row_data)
        label = self._project_filter or "All"
        if self._project_filter is None:
            next_name = self._project_names[0] if self._project_names else "All"
        else:
            try:
                idx = self._project_names.index(self._project_filter)
                next_name = self._project_names[idx + 1] if idx + 1 < len(self._project_names) else "All"
            except ValueError:
                next_name = "All"
        self.notify(f"Project: {label} ({count} repos)  next: {next_name}")

    # ------------------------------------------------------------------
    # Vertical filter
    # ------------------------------------------------------------------

    def action_cycle_vertical(self) -> None:
        try:
            idx = VERTICAL_CYCLE.index(self._vertical_filter)
            self._vertical_filter = VERTICAL_CYCLE[(idx + 1) % len(VERTICAL_CYCLE)]
        except ValueError:
            self._vertical_filter = None
        self._update_header()
        self._load_repos()
        label = VERTICAL_LABELS.get(self._vertical_filter, "All")
        count = len(self._row_data)
        self.notify(f"Vertical: {label} ({count} repos)")

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
            self._update_header()
            self._load_repos()

    # ------------------------------------------------------------------
    # Help
    # ------------------------------------------------------------------

    def action_help(self) -> None:
        self.notify(
            "Keys: s=sort S=reverse w=watch t=tested r=reject a=adopted "
            "o=open c=copy p=project v=vertical /=search q=quit",
            timeout=0,
        )
