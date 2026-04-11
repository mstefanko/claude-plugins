"""Export scan results to Obsidian markdown."""

import json
import os
from datetime import datetime


def export_scan(db, scan_id=None, config_path="~/.tech-radar.json", output_path=None):
    """Export a scan to markdown. Returns output path or 'stdout'."""
    # Resolve scan_id
    if scan_id is None:
        row = db.execute("SELECT id FROM scans ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            print("No scans found in database.")
            return "stdout"
        scan_id = row[0]

    # Load config
    config_path = os.path.expanduser(config_path)
    config = {}
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            config = json.load(f)

    # Generate the report
    report = _format_report(db, scan_id, config)

    # Determine output destination
    if output_path == "/dev/stdout" or output_path == "-":
        print(report)
        return "stdout"

    if output_path:
        dest = os.path.expanduser(output_path)
    else:
        # Try obsidian config
        obsidian_path = os.path.expanduser("~/.obsidian-notes.json")
        if os.path.exists(obsidian_path):
            with open(obsidian_path, "r") as f:
                obs = json.load(f)
            vault_path = os.path.expanduser(obs.get("vault_path", "~/Notes"))
            notes_dir = obs.get("notes_dir", "")
            scan_row = db.execute("SELECT scan_date FROM scans WHERE id = ?", [scan_id]).fetchone()
            scan_date = scan_row[0] if scan_row else datetime.now().strftime("%Y-%m-%d")
            dest = os.path.join(vault_path, notes_dir, f"{scan_date}-tech-radar.md")
        else:
            print(report)
            return "stdout"

    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    with open(dest, "w") as f:
        f.write(report)
    return dest


def _format_report(db, scan_id, config):
    """Build the full markdown report for a scan."""
    # Get scan metadata
    scan = db.execute("SELECT scan_date, timeframe, repos_new, repos_returning, repos_rising, metadata FROM scans WHERE id = ?", [scan_id]).fetchone()
    if not scan:
        return "# Tech Radar\n\nNo scan data found.\n"

    scan_date, timeframe, repos_new, repos_returning, repos_rising, metadata_str = scan
    dt = datetime.strptime(scan_date[:10], "%Y-%m-%d") if scan_date else datetime.now()
    month_year = dt.strftime("%B %Y")

    # Parse key_takeaways from metadata
    key_takeaways = None
    if metadata_str:
        try:
            meta = json.loads(metadata_str)
            key_takeaways = meta.get("key_takeaways")
        except (json.JSONDecodeError, TypeError):
            pass

    # Fetch all repos for this scan
    rows = db.execute("""
        SELECT r.full_name, r.description, r.url,
               ss.stars, ss.stars_delta, ss.stars_delta_pct,
               ss.category, ss.is_under_radar, ss.is_rising,
               ss.matched_projects, ss.hn_context,
               COALESCE(a.status, 'new') as annotation_status,
               a.notes, a.rejection_reason,
               v.verdict_text, v.project_relevance
        FROM repos r
        JOIN scan_snapshots ss ON ss.repo_id = r.id
        LEFT JOIN annotations a ON a.repo_id = r.id
        LEFT JOIN verdicts v ON v.repo_id = r.id
            AND v.scan_id = (SELECT MAX(v2.scan_id) FROM verdicts v2 WHERE v2.repo_id = r.id)
        WHERE ss.scan_id = ?
        ORDER BY ss.stars DESC
    """, [scan_id]).fetchall()

    columns = ["full_name", "description", "url", "stars", "stars_delta", "stars_delta_pct",
                "category", "is_under_radar", "is_rising", "matched_projects", "hn_context",
                "annotation_status", "notes", "rejection_reason", "verdict_text", "project_relevance"]
    repos = [dict(zip(columns, row)) for row in rows]

    # Sources
    sources = set()
    for r in repos:
        if r["hn_context"]:
            sources.add("Hacker News")
        sources.add("GitHub")
    sources_str = ", ".join(sorted(sources)) if sources else "GitHub"

    # Build report
    lines = []
    lines.append("---")
    lines.append("type: note")
    lines.append("project: tech-radar")
    lines.append(f"date: {scan_date}")
    lines.append(f"tags: [tech-radar, {timeframe}]")
    lines.append("---")
    lines.append("")
    lines.append(f"# Tech Radar — {month_year}")
    lines.append("")
    lines.append(f"Sources: {sources_str}")
    lines.append(f"New this scan: {repos_new or 0} | Returning: {repos_returning or 0} | Rising: {repos_rising or 0}")
    lines.append("")

    # Key Takeaways
    lines.append("## Key Takeaways")
    lines.append("")
    if key_takeaways:
        lines.append(key_takeaways)
    else:
        lines.append("Run `tech-radar evaluate` to generate key takeaways.")
    lines.append("")

    # Per-project sections
    projects = config.get("projects", {})
    if isinstance(projects, dict):
        project_names = list(projects.keys())
    elif isinstance(projects, list):
        project_names = [p.get("name", p) if isinstance(p, dict) else p for p in projects]
    else:
        project_names = []

    for proj_name in project_names:
        proj_repos = []
        for r in repos:
            mp = r.get("matched_projects") or "[]"
            try:
                matched = json.loads(mp) if isinstance(mp, str) else mp
            except (json.JSONDecodeError, TypeError):
                matched = []
            if proj_name in matched:
                proj_repos.append(r)

        if not proj_repos:
            continue

        # Sort: non-rejected first, then rejected at bottom
        proj_repos.sort(key=lambda x: (1 if x["annotation_status"] == "rejected" else 0, -(x["stars"] or 0)))

        lines.append(f"## For {proj_name}")
        lines.append("")
        lines.append("| Project | What | ★ | Δ | Status | Verdict |")
        lines.append("|---------|------|---|---|--------|---------|")
        for r in proj_repos:
            name = f"[{r['full_name']}]({r['url']})" if r["url"] else r["full_name"]
            what = (r["description"] or "")[:60]
            stars = _format_stars(r["stars"])
            delta = _format_delta(r["stars_delta_pct"])
            badge = _status_badge(r["annotation_status"], r["rejection_reason"])
            verdict = (r["verdict_text"] or "")[:80].replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {name} | {what} | {stars} | {delta} | {badge} | {verdict} |")
        lines.append("")

    # Plugins section
    plugin_repos = [r for r in repos if r["category"] == "plugin"]
    if plugin_repos:
        lines.append("## Plugins")
        lines.append("")
        lines.append("| Project | What | ★ | Δ | Status | Verdict |")
        lines.append("|---------|------|---|---|--------|---------|")
        for r in plugin_repos:
            name = f"[{r['full_name']}]({r['url']})" if r["url"] else r["full_name"]
            what = (r["description"] or "")[:60]
            stars = _format_stars(r["stars"])
            delta = _format_delta(r["stars_delta_pct"])
            badge = _status_badge(r["annotation_status"], r["rejection_reason"])
            verdict = (r["verdict_text"] or "")[:80].replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {name} | {what} | {stars} | {delta} | {badge} | {verdict} |")
        lines.append("")

    # Under the Radar
    under_radar = [r for r in repos if r["is_under_radar"]]
    if under_radar:
        lines.append("## Under the Radar")
        lines.append("")
        lines.append("| Project | What | ★ | Δ | Status | Verdict |")
        lines.append("|---------|------|---|---|--------|---------|")
        for r in under_radar:
            name = f"[{r['full_name']}]({r['url']})" if r["url"] else r["full_name"]
            what = (r["description"] or "")[:60]
            stars = _format_stars(r["stars"])
            delta = _format_delta(r["stars_delta_pct"])
            badge = _status_badge(r["annotation_status"], r["rejection_reason"])
            verdict = (r["verdict_text"] or "")[:80].replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {name} | {what} | {stars} | {delta} | {badge} | {verdict} |")
        lines.append("")

    # Rising Stars
    rising = [r for r in repos if r["is_rising"]]
    if rising:
        lines.append("## Rising Stars")
        lines.append("")
        lines.append("| Project | What | ★ | Δ | Status | Verdict |")
        lines.append("|---------|------|---|---|--------|---------|")
        for r in rising:
            name = f"[{r['full_name']}]({r['url']})" if r["url"] else r["full_name"]
            what = (r["description"] or "")[:60]
            stars = _format_stars(r["stars"])
            delta = _format_delta(r["stars_delta_pct"])
            badge = _status_badge(r["annotation_status"], r["rejection_reason"])
            verdict = (r["verdict_text"] or "")[:80].replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {name} | {what} | {stars} | {delta} | {badge} | {verdict} |")
        lines.append("")

    # Wild Cards
    wildcards = [r for r in repos if r["category"] == "interest-match"][:5]
    if wildcards:
        lines.append("## Wild Cards")
        lines.append("")
        lines.append("| Project | What | ★ | Δ | Status | Verdict |")
        lines.append("|---------|------|---|---|--------|---------|")
        for r in wildcards:
            name = f"[{r['full_name']}]({r['url']})" if r["url"] else r["full_name"]
            what = (r["description"] or "")[:60]
            stars = _format_stars(r["stars"])
            delta = _format_delta(r["stars_delta_pct"])
            badge = _status_badge(r["annotation_status"], r["rejection_reason"])
            verdict = (r["verdict_text"] or "")[:80].replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {name} | {what} | {stars} | {delta} | {badge} | {verdict} |")
        lines.append("")

    # HN Highlights
    hn_repos = [r for r in repos if r["hn_context"]]
    if hn_repos:
        lines.append("## HN Highlights")
        lines.append("")
        for r in hn_repos:
            name = f"[{r['full_name']}]({r['url']})" if r["url"] else r["full_name"]
            lines.append(f"### {name}")
            lines.append("")
            lines.append(f"> {r['hn_context']}")
            lines.append("")

    # General Dev Tools
    general = [r for r in repos if r["category"] == "general"]
    if general:
        lines.append("## General Dev Tools")
        lines.append("")
        lines.append("| Project | What | ★ | Δ | Status | Verdict |")
        lines.append("|---------|------|---|---|--------|---------|")
        for r in general:
            name = f"[{r['full_name']}]({r['url']})" if r["url"] else r["full_name"]
            what = (r["description"] or "")[:60]
            stars = _format_stars(r["stars"])
            delta = _format_delta(r["stars_delta_pct"])
            badge = _status_badge(r["annotation_status"], r["rejection_reason"])
            verdict = (r["verdict_text"] or "")[:80].replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {name} | {what} | {stars} | {delta} | {badge} | {verdict} |")
        lines.append("")

    return "\n".join(lines)


def _format_stars(stars):
    """Format star count with commas: 69000 -> '69,000'."""
    if stars is None:
        return "—"
    return f"{stars:,}"


def _format_delta(delta_pct):
    """Format delta percentage: 12.3 -> '+12.3%', None -> '—'."""
    if delta_pct is None:
        return "—"
    sign = "+" if delta_pct >= 0 else ""
    return f"{sign}{delta_pct:.1f}%"


def _status_badge(annotation_status, rejection_reason=None):
    """Return emoji badge for annotation status."""
    if annotation_status == "watching":
        return "👀"
    if annotation_status in ("tested", "adopted"):
        return "✅"
    if annotation_status == "rejected":
        reason = f" ({rejection_reason})" if rejection_reason else ""
        return f"❌{reason}"
    return ""
