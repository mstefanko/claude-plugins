from __future__ import annotations

from typing import Any


def render_report(
    work_order: dict[str, Any],
    decision: dict[str, Any],
    worker_results: dict[str, dict[str, Any]],
    *,
    judge_results: dict[str, dict[str, Any]] | None = None,
) -> str:
    mode = decision["mode"]
    lines = [
        f"# Bakeoff Report: {work_order['id']}",
        "",
        f"Mode: `{mode}`",
        f"Decision: `{decision['decision_kind']}`",
        "",
    ]
    lines.extend(_decision_audit(decision))
    if mode == "gather":
        lines.extend(_render_gather(decision, worker_results, judge_results or {}))
    elif mode == "compare":
        lines.extend(_render_compare(decision, worker_results))
    elif mode == "analyze":
        lines.extend(_render_analyze(decision, worker_results))
    else:
        lines.append("Unsupported mode.")
    lines.extend(_caveats(decision))
    return "\n".join(lines).rstrip() + "\n"


def _decision_audit(decision: dict[str, Any]) -> list[str]:
    lines = ["## Decision Audit", "", f"- Judge ran: `{str(decision.get('judge_ran', False)).lower()}`"]
    if decision.get("canonical_winner"):
        lines.append(f"- Canonical winner: `{decision['canonical_winner']}`")
    if decision.get("spine_tiebreak"):
        lines.append(f"- Spine tiebreak: `{decision['spine_tiebreak']}`")
    if decision.get("order_maps"):
        for name, mapping in decision["order_maps"].items():
            lines.append(f"- {name}: A=`{mapping.get('A')}`, B=`{mapping.get('B')}`")
    if decision.get("judge_rationale"):
        lines.append("- Judge rationale:")
        for item in _as_list(decision["judge_rationale"]):
            lines.append(f"  - {item}")
    lines.extend(["", "## Provider Status", ""])
    for provider_id, status in decision.get("provider_statuses", {}).items():
        detail = f"{status.get('wall_seconds', 0)}s, {status.get('output_bytes', 0)} bytes"
        stderr_path = status.get("stderr_path")
        suffix = f", stderr: `{stderr_path}`" if stderr_path else ""
        lines.append(f"- `{provider_id}`: `{status.get('status')}` ({detail}{suffix})")
    lines.append("")
    return lines


def _render_gather(
    decision: dict[str, Any],
    worker_results: dict[str, dict[str, Any]],
    judge_results: dict[str, dict[str, Any]],
) -> list[str]:
    if decision["decision_kind"] == "both_failed":
        return ["## Findings", "", "No provider completed successfully.", ""]
    if decision["decision_kind"] == "single_provider_only":
        provider_id = decision.get("canonical_winner")
        worker = worker_results.get(provider_id or "", {}).get("final_json") or {}
        return ["## Findings", ""] + _claim_lines(worker.get("claims", []), source=provider_id) + _unknowns(worker)

    judge = judge_results.get("pass1") or judge_results.get("gather") or {}
    merged = judge.get("merged_claims", [])
    order_map = decision.get("order_maps", {}).get("pass1", {})
    grouped: dict[str, list[dict[str, Any]]] = {}
    for claim in merged:
        sources = [order_map.get(source, source) for source in claim.get("sources", [])]
        key = "+".join(sorted(sources)) if sources else "unknown"
        grouped.setdefault(key, []).append(claim)

    lines = ["## Findings", ""]
    for key in sorted(grouped):
        lines.append(f"### {key}")
        lines.extend(_claim_lines(grouped[key]))
        lines.append("")
    lines.extend(["## Conflicts", ""])
    lines.extend(_conflict_lines(judge.get("conflicts", [])))
    lines.extend(["", "## Unknowns", ""])
    for item in judge.get("unknowns_union", []):
        lines.append(f"- {item}")
    if not judge.get("unknowns_union"):
        lines.append("- None reported.")
    lines.append("")
    return lines


def _render_compare(decision: dict[str, Any], worker_results: dict[str, dict[str, Any]]) -> list[str]:
    lines = ["## Comparison", ""]
    kind = decision["decision_kind"]
    winner = decision.get("canonical_winner")
    if kind == "pick_winner" and winner:
        final = worker_results[winner].get("final_json") or {}
        lines.append(f"Winner: `{winner}`")
        if final.get("position"):
            lines.append(f"Position: {final['position']}")
        lines.append("")
        lines.extend(_claim_lines(final.get("claims", []), source=winner))
    elif kind == "consensus":
        lines.append("The judge found both providers reached the same position.")
        lines.extend(["", "### Strongest Material", ""])
        lines.extend(_generic_item_lines(decision.get("consensus_strongest", [])))
        lines.extend(["", "### Consensus Disagreements", ""])
        lines.extend(_generic_item_lines(decision.get("consensus_disagreements", [])))
    elif kind == "single_provider_only" and winner:
        final = worker_results[winner].get("final_json") or {}
        lines.append("No comparison possible - surfacing the single completed result.")
        if final.get("position"):
            lines.append(f"Position: {final['position']}")
        lines.append("")
        lines.extend(_claim_lines(final.get("claims", []), source=winner))
    elif kind == "both_failed":
        lines.append("No provider completed successfully.")
    else:
        lines.append("No stable winner after position swap. Human decision required.")

    if decision.get("kept_from_nonwinner"):
        lines.extend(["", "## Kept From Nonwinner", ""])
        lines.extend(_generic_item_lines(decision["kept_from_nonwinner"]))
    lines.append("")
    return lines


def _render_analyze(decision: dict[str, Any], worker_results: dict[str, dict[str, Any]]) -> list[str]:
    lines = ["## Primary Explanation", ""]
    winner = decision.get("canonical_winner")
    if decision["decision_kind"] == "both_failed":
        return lines + ["No provider completed successfully.", ""]
    if not winner:
        lines.append("No stable spine was selected. Human decision required.")
        return lines + [""]

    final = worker_results[winner].get("final_json") or {}
    verdicts = {item.get("claim_id"): item for item in decision.get("claim_verdicts", []) if isinstance(item, dict)}
    for claim in final.get("claims", []):
        verdict = verdicts.get(claim.get("id"), {})
        marker = verdict.get("loser_position")
        note = f" [{marker}: {verdict.get('loser_note')}]" if marker else ""
        evidence = ", ".join(claim.get("evidence", []))
        lines.append(f"- **{claim.get('id', '?')}** {claim.get('claim', '')}{note}")
        if evidence:
            lines.append(f"  Evidence: {evidence}")
    if not final.get("claims"):
        lines.append("No claims were available to render.")
    if decision.get("additions_from_loser"):
        lines.extend(["", "## Additions From Loser", ""])
        lines.extend(_generic_item_lines(decision["additions_from_loser"]))
    lines.append("")
    return lines


def _claim_lines(claims: list[dict[str, Any]], *, source: str | None = None) -> list[str]:
    if not claims:
        return ["- None reported."]
    lines: list[str] = []
    for claim in claims:
        confidence = claim.get("confidence", "unknown")
        source_text = f" source `{source}`," if source else ""
        evidence = ", ".join(claim.get("evidence", []))
        lines.append(f"- {claim.get('claim', '')} ({source_text} confidence `{confidence}`)")
        if evidence:
            lines.append(f"  Evidence: {evidence}")
    return lines


def _conflict_lines(conflicts: list[Any]) -> list[str]:
    if not conflicts:
        return ["- No conflicts found."]
    return _generic_item_lines(conflicts)


def _unknowns(worker: dict[str, Any]) -> list[str]:
    lines = ["", "## Unknowns", ""]
    unknowns = worker.get("unknowns", [])
    if not unknowns:
        lines.append("- None reported.")
    else:
        for item in unknowns:
            lines.append(f"- {item}")
    lines.append("")
    return lines


def _generic_item_lines(items: list[Any]) -> list[str]:
    if not items:
        return ["- None reported."]
    lines: list[str] = []
    for item in items:
        if isinstance(item, str):
            lines.append(f"- {item}")
        elif isinstance(item, dict):
            claim = item.get("claim") or item.get("description") or item.get("loser_note") or str(item)
            lines.append(f"- {claim}")
            if item.get("evidence"):
                lines.append(f"  Evidence: {', '.join(str(piece) for piece in item['evidence'])}")
            if item.get("source_provider"):
                lines.append(f"  Source: `{item['source_provider']}`")
        else:
            lines.append(f"- {item}")
    return lines


def _caveats(decision: dict[str, Any]) -> list[str]:
    caveats = decision.get("caveats") or []
    if not caveats:
        return []
    lines = ["## Caveats", ""]
    for caveat in caveats:
        lines.append(f"- {caveat}")
    lines.append("")
    return lines


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value is None:
        return []
    return [str(value)]
