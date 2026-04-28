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

    def _search_repo_ids(self) -> set[int] | None:
        if not self._search_query:
            return None
        try:
            fts_results = db_module.search_fts(self._db, self._search_query, table="repos")
            return {int(r["id"]) for r in fts_results}
        except Exception:
            return set()

    def _common_filter_sql(self, params: list, fts_ids: set[int] | None) -> str:
        clauses: list[str] = []
        if self._project_filter:
            clauses.append("ss.matched_projects LIKE ?")
            params.append(f"%{self._project_filter}%")

        if self._vertical_filter:
            cats = VERTICAL_CATEGORIES.get(self._vertical_filter, (self._vertical_filter,))
            cat_placeholders = ",".join("?" * len(cats))
            clauses.append(f"ss.category IN ({cat_placeholders})")
            params.extend(cats)

        if fts_ids is not None:
            if not fts_ids:
                clauses.append("1 = 0")
            else:
                repo_placeholders = ",".join("?" * len(fts_ids))
                clauses.append(f"r.id IN ({repo_placeholders})")
                params.extend(sorted(fts_ids))

        return "".join(f" AND {clause}" for clause in clauses)

    def _status_counts(self, latest_scan_id: int, fts_ids: set[int] | None) -> dict[str, int]:
        params: list = [latest_scan_id]
        sql = """
            SELECT COALESCE(a.status, 'new') as status, COUNT(*)
            FROM repos r
            JOIN scan_snapshots ss ON ss.repo_id = r.id
            LEFT JOIN annotations a ON a.repo_id = r.id
            WHERE ss.scan_id = ?
        """
        sql += self._common_filter_sql(params, fts_ids)
        sql += " GROUP BY COALESCE(a.status, 'new')"

        raw_counts = {row[0]: row[1] for row in self._db.execute(sql, params).fetchall()}
        return {
            "All": sum(count for status, count in raw_counts.items() if status != "rejected"),
            "Watching": raw_counts.get("watching", 0),
            "Tested": raw_counts.get("tested", 0),
            "Adopted": raw_counts.get("adopted", 0),
            "Rejected": raw_counts.get("rejected", 0),
        }

    def _update_tab_counts(self, counts: dict[str, int]) -> None:
        for tab_id, label in TAB_IDS.items():
            tab = self.query_one(f"#{tab_id}", Tab)
            tab.label = f"{label} {counts.get(label, 0)}"

    def _render_repo_cell(self, data: dict) -> str:
        status = data.get("annotation_status", "new")
        name_style = STATUS_NAME_STYLE.get(status, STATUS_NAME_STYLE["new"])
        name = escape(_truncate(data.get("full_name", ""), 44))
        badges = [_category_badge(data.get("category"))]
        if data.get("is_rising"):
            badges.append(_badge("RISING", "black on #9ece6a"))
        if data.get("is_under_radar"):
            badges.append(_badge("RADAR", "black on #bb9af7"))
        if data.get("archived"):
            badges.append(_badge("ARCH", "black on #565f89"))

        title_line = f"[{name_style}]{name}[/] {' '.join(badge for badge in badges if badge)}"

        description = escape(_truncate(data.get("description", "") or "No description", 48))
        metadata: list[str] = []
        if data.get("language"):
            metadata.append(str(data["language"]))
        if data.get("license"):
            metadata.append(str(data["license"]))
        first_seen = _format_date(data.get("first_seen"))
        if first_seen:
            metadata.append(f"seen {first_seen}")
        projects = _json_list(data.get("matched_projects"))
        if projects:
            project_text = ", ".join(projects[:2])
            if len(projects) > 2:
                project_text += f" +{len(projects) - 2}"
            metadata.append(f"projects {project_text}")

        meta_line = _join_metadata(metadata)
        if meta_line:
            return f"{title_line}\n[dim]{description}[/] [dim]{meta_line}[/]"
        return f"{title_line}\n[dim]{description}[/]"

    def _render_stars_cell(self, data: dict) -> str:
        return f"[bold]{_format_stars(data.get('stars'))}[/]\n[dim]stars[/]"

    def _render_growth_cell(self, data: dict) -> str:
        delta = data.get("stars_delta")
        delta_bits = []
        if delta is not None:
            sign = "+" if delta >= 0 else ""
            delta_bits.append(f"{sign}{delta:,}")
        delta_bits.append("growth")
        return f"{_format_delta_pct_markup(data.get('stars_delta_pct'))}\n[dim]{escape(' '.join(delta_bits))}[/]"

    def _render_status_cell(self, data: dict) -> str:
        status = data.get("annotation_status", "new")
        hint = STATUS_HINTS.get(status, status)
        if status == "tested" and data.get("tested_date"):
            hint = _format_date(data.get("tested_date"))
        return f"{_status_badge(status)}\n[dim]{escape(hint)}[/]"

    def _load_repos(self) -> None:
        table = self.query_one("#main-table", DataTable)
        table.clear()
        self._row_data.clear()

        latest_scan_id = db_module.get_latest_scan_id(self._db)
        if latest_scan_id is None:
            self._update_tab_counts({})
            self.query_one("#detail-content", Static).update(
                "No data yet. Run 'tech-radar gather' to scan for repos."
            )
            return

        fts_ids = self._search_repo_ids()
        self._update_tab_counts(self._status_counts(latest_scan_id, fts_ids))

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
        tab_status = TAB_STATUS.get(self._current_tab)
        if tab_status:
            sql += " AND COALESCE(a.status, 'new') = ?"
            params.append(tab_status)
        elif self._current_tab == "All":
            # Hide rejected repos from All tab — they have their own tab
            sql += " AND COALESCE(a.status, 'new') != 'rejected'"

        sql += self._common_filter_sql(params, fts_ids)

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

        added = 0
        for row in rows:
            data = dict(zip(columns, row))
            repo_id = data["id"]

            key = str(repo_id)
            self._row_data[key] = data

            table.add_row(
                self._render_repo_cell(data),
                self._render_stars_cell(data),
                self._render_growth_cell(data),
                self._render_status_cell(data),
                height=2,
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
        else:
            first_key = next(iter(self._row_data))
            self._update_detail(self._row_data[first_key])

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
        delta_str = "[dim]no growth data[/]"
        if delta is not None:
            sign = "+" if delta >= 0 else ""
            delta_str = f"{sign}{delta:,} / {_format_delta_pct_markup(pct)}"

        status = data.get("annotation_status", "new")
        header_badges = [_status_badge(status), _category_badge(data.get("category"))]
        if data.get("is_rising"):
            header_badges.append(_badge("RISING", "black on #9ece6a"))
        if data.get("is_under_radar"):
            header_badges.append(_badge("RADAR", "black on #bb9af7"))

        lines = [f"[bold]{escape(data['full_name'])}[/bold] {' '.join(filter(None, header_badges))}"]

        url = data.get("url", "")
        if url:
            lines.append(f"[dim]{escape(url)}[/dim]")

        desc = data.get("description", "")
        if desc:
            lines.append("")
            lines.append(f"[italic]{escape(desc)}[/italic]")

        lines.append("")

        verdict = data.get("verdict_text")
        if verdict:
            lines.append("[bold reverse] Verdict [/bold reverse]")
            lines.append(escape(verdict))
        else:
            lines.append("[dim]Pending evaluation[/dim]")

        pr = _format_project_relevance(data.get("project_relevance"))
        if pr:
            lines.append("")
            lines.append("[bold]Project Relevance:[/bold]")
            lines.append(escape(pr))

        lines.append("")
        lines.append(f"[bold]Growth:[/bold] {_format_stars(stars)} stars   {delta_str}")

        repo_id = data["id"]
        spark_rows = self._db.execute(
            "SELECT stars FROM scan_snapshots WHERE repo_id = ? ORDER BY scan_id",
            [repo_id],
        ).fetchall()
        if spark_rows:
            values = [r[0] for r in spark_rows]
            lines.append(f"[bold]Trend:[/bold] {_sparkline(values)}  ({len(values)} scans)")

        projects = _json_list(data.get("matched_projects"))
        if projects:
            lines.append(f"[bold]Projects:[/bold] {escape(', '.join(projects))}")

        keywords = _json_list(data.get("matched_keywords"))
        if keywords:
            lines.append(f"[bold]Matched:[/bold] {escape(', '.join(keywords[:8]))}")

        lines.append("")
        lines.append("[bold]Metadata[/bold]")
        for label, key in [
            ("Language", "language"),
            ("License", "license"),
            ("Category", "category"),
            ("First seen", "first_seen"),
        ]:
            val = data.get(key)
            if val:
                lines.append(f"[dim]{label}:[/] {escape(str(val))}")

        hn = data.get("hn_context")
        if hn:
            lines.append("")
            lines.append("[bold]HN Context:[/bold]")
            lines.append(escape(hn))

        lines.append("")
        lines.append(f"[bold]Annotation:[/bold] {_status_badge(status)}")
        notes = data.get("annotation_notes")
        if notes:
            lines.append(f"[dim]Notes:[/] {escape(notes)}")
        td = data.get("tested_date")
        if td:
            lines.append(f"[dim]Tested:[/] {escape(td)}")
        rr = data.get("rejection_reason")
        if rr:
            lines.append(f"[dim]Reason:[/] {escape(rr)}")
        if status == "new":
            lines.append("[dim]No annotation yet. Use w/t/a/r to classify this repo.[/dim]")

        homepage = data.get("homepage")
        if homepage:
            lines.append("")
            lines.append(f"[dim]Homepage:[/] {escape(homepage)}")

        detail.update("\n".join(lines))

    # ------------------------------------------------------------------
    # Tab switching
    # ------------------------------------------------------------------

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        tab_id = event.tab.id if event.tab else "tab-all"
        self._current_tab = TAB_IDS.get(tab_id or "tab-all", "All")
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
        row_index = table.cursor_row
        if row_index is None or row_index < 0:
            return None
        try:
            ordered_row = table.ordered_rows[row_index]
            row_key = getattr(ordered_row, "key", ordered_row)
            value = getattr(row_key, "value", row_key)
            return self._row_data.get(str(value))
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
    # Preview pane
    # ------------------------------------------------------------------

    def _sync_preview_visibility(self, notify: bool = True) -> None:
        detail = self.query_one("#detail", ScrollableContainer)
        if self._preview_visible:
            detail.remove_class("hidden")
        else:
            detail.add_class("hidden")
        self._update_header()
        if notify:
            state = "shown" if self._preview_visible else "hidden"
            self.notify(f"Preview {state}")

    def action_toggle_preview(self) -> None:
        self._preview_visible = not self._preview_visible
        self._sync_preview_visibility()

    def action_preview_page_down(self) -> None:
        if self._preview_visible:
            self.query_one("#detail", ScrollableContainer).scroll_page_down(animate=False)

    def action_preview_page_up(self) -> None:
        if self._preview_visible:
            self.query_one("#detail", ScrollableContainer).scroll_page_up(animate=False)

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
            self._update_header()
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
        self.push_screen(HelpModal())
