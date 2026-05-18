#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pathlib
import sys
import time


def csv_env(name: str) -> set[str]:
    value = os.environ.get(name, "")
    return {part.strip() for part in value.split(",") if part.strip()}


def bool_env(name: str) -> bool:
    return os.environ.get(name, "").lower() in {"1", "true", "yes", "on"}


def provider_name() -> str:
    return os.environ.get("BAKEOFF_FAKE_PROVIDER_NAME", pathlib.Path(sys.argv[0]).name)


def print_help(name: str) -> None:
    if os.environ.get("BAKEOFF_FAKE_SCOPE_HELP_MODE") == "none":
        print(f"fake {name} help without scope controls")
        return
    if name == "claude":
        print("fake claude help")
        print("  --allowedTools")
        print("  --disallowedTools")
        print("  --tools")
        print("  --permission-mode")
        return
    print("fake codex exec help")
    print("  --sandbox <read-only|workspace-write>")
    print("  --disable")
    print("  --profile")
    print("  --config")
    print("  --output-last-message")


def emit(obj: dict) -> None:
    print("<scratchpad>ok</scratchpad>")
    print("<final_json>" + json.dumps(obj, separators=(",", ":")) + "</final_json>")


def worker_payload(name: str, prompt: str) -> dict:
    if all(marker in prompt for marker in ("files_touched", "tests_added_or_changed", "manual_checks")):
        pathlib.Path("bakeoff-build-output.txt").write_text(
            f"build output from {name}\n", encoding="utf-8"
        )
        pathlib.Path(f"{name}-build.txt").write_text(
            f"provider-specific build output from {name}\n", encoding="utf-8"
        )
        return {
            "status": "complete",
            "summary": f"{name} wrote build output",
            "files_touched": ["bakeoff-build-output.txt", f"{name}-build.txt"],
            "tests_added_or_changed": [],
            "risks": [],
            "manual_checks": [],
        }
    payload = {
        "status": "complete",
        "claims": [
            {
                "id": "R-001",
                "claim": f"{name} claim",
                "evidence": ["fake:1"],
                "confidence": "high",
            }
        ],
        "conflicts": [],
        "unknowns": [],
        "recommended_next_checks": [],
    }
    if "comparison question" in prompt:
        payload["position"] = f"{name} position"
    return payload


def main() -> int:
    name = provider_name()
    if "--version" in sys.argv:
        print(f"{name} fake 1.0")
        return 0
    if "--help" in sys.argv:
        print_help(name)
        return 0

    prompt = sys.stdin.read()
    fail_providers = csv_env("BAKEOFF_FAKE_FAIL_PROVIDERS")
    repair_providers = csv_env("BAKEOFF_FAKE_REPAIR_PROVIDERS")
    timeout_providers = csv_env("BAKEOFF_FAKE_TIMEOUT_PROVIDERS")
    output_cap_providers = csv_env("BAKEOFF_FAKE_OUTPUT_CAP_PROVIDERS")
    output_cap_salvage_providers = csv_env("BAKEOFF_FAKE_OUTPUT_CAP_SALVAGE_PROVIDERS")
    stderr_truncation_providers = csv_env("BAKEOFF_FAKE_STDERR_TRUNCATION_PROVIDERS")
    schema_error_providers = csv_env("BAKEOFF_FAKE_SCHEMA_ERROR_PROVIDERS")
    judge_mode = os.environ.get("BAKEOFF_FAKE_JUDGE_MODE", "gather")
    triage_source_id = os.environ.get("BAKEOFF_FAKE_TRIAGE_SOURCE_ID") or None
    is_judge = (
        "deduplication and conflict-flagging judge" in prompt
        or "pairwise judge" in prompt
        or "synthesis judge" in prompt
        or "build judge" in prompt
    )
    is_triage = "evidence-grounded triage of a Bakeoff report" in prompt

    if "BAKEOFF_DOCTOR_BUILD_EDIT_PROBE_V1" in prompt:
        pathlib.Path("bakeoff-doctor-build-probe.txt").write_text(
            f"bakeoff-build-write-ok-{name}\n", encoding="utf-8"
        )
        emit(worker_payload(name, prompt))
        return 0

    if name in timeout_providers and not is_judge and not is_triage:
        time.sleep(float(os.environ.get("BAKEOFF_FAKE_TIMEOUT_SECONDS", "5")))
        return 0
    if name in output_cap_providers and not is_judge and not is_triage:
        sys.stdout.write("x" * int(os.environ.get("BAKEOFF_FAKE_OUTPUT_CAP_BYTES", "5000")))
        sys.stdout.flush()
        return 0
    if name in output_cap_salvage_providers and not is_judge and not is_triage:
        sys.stdout.write("x" * int(os.environ.get("BAKEOFF_FAKE_OUTPUT_CAP_PREFIX_BYTES", "200")))
        sys.stdout.write('<final_json>{"status":"complete","claims":[{"id":"R-001","claim":"late claim","evidence":["fake:1"],"confidence":"high"}],"conflicts":[],"unknowns":[],"recommended_next_checks":[]}</final_json>')
        sys.stdout.flush()
        return 0
    if name in stderr_truncation_providers and not is_judge and not is_triage:
        sys.stderr.write("e" * int(os.environ.get("BAKEOFF_FAKE_STDERR_BYTES", "5000")))
        sys.stderr.flush()
    if name in fail_providers and not is_judge and not is_triage:
        print("provider failed before final json", file=sys.stderr)
        return 9
    if bool_env("BAKEOFF_FAKE_FAIL_JUDGE") and is_judge:
        print("judge failed before final json", file=sys.stderr)
        return 9
    if name in schema_error_providers and not is_judge and not is_triage:
        emit({"status": "complete", "claims": [{"id": "R-001", "finding": f"{name} malformed claim"}], "conflicts": [], "unknowns": [], "recommended_next_checks": []})
        return 0
    if name in repair_providers and "BAKEOFF_FORMAT_RETRY_V1" not in prompt and not is_judge and not is_triage:
        emit({"status": "complete", "claims": [{"id": "R-001", "finding": f"{name} malformed claim"}], "conflicts": [], "unknowns": [], "recommended_next_checks": []})
        return 0
    if is_triage:
        if triage_source_id is None:
            emit({"schema_version": 1, "status": "complete", "summary": "no selected findings", "items": [], "unknowns": []})
        else:
            emit(
                {
                    "schema_version": 1,
                    "status": "complete",
                    "summary": "checked",
                    "items": [
                        {
                            "id": "T-001",
                            "source_finding_id": triage_source_id,
                            "source_finding": "Fake merged claim",
                            "classification": "real_issue",
                            "severity": "medium",
                            "confidence": "high",
                            "supporting_evidence": ["src/fake.py:1"],
                            "counterevidence": [],
                            "citation_check_ids": [],
                            "recommended_action": "fix_now",
                            "rationale": "actionable",
                        }
                    ],
                    "unknowns": [],
                }
            )
        return 0
    if "deduplication and conflict-flagging judge" in prompt:
        emit({"merged_claims": [{"claim": "Fake merged claim", "evidence": ["fake:1"], "sources": ["A", "B"], "confidence": "high"}], "conflicts": [], "unknowns_union": []})
        return 0
    if "pairwise judge" in prompt:
        compare_scores_a = {"evidence": 5, "coherence": 5, "tradeoff_honesty": 5, "rebuttals": 5}
        compare_scores_b = {"evidence": 4, "coherence": 4, "tradeoff_honesty": 4, "rebuttals": 4}
        winner = "B" if judge_mode == "compare_always_b" else "tie" if judge_mode == "compare_tie" else "A"
        emit(
            {
                "relation": "compare",
                "scores_a": compare_scores_a,
                "scores_b": compare_scores_b,
                "winner": winner,
                "rationale": f"position {winner} looked better",
                "kept_from_nonwinner": [{"claim": "useful material from loser"}],
                "consensus_strongest": [],
                "consensus_disagreements": [],
            }
        )
        return 0
    if "synthesis judge" in prompt:
        analyze_scores_a = {"step_atomicity": 5, "citation_grounding": 5, "assumption_transparency": 5, "coherence": 5}
        analyze_scores_b = {"step_atomicity": 4, "citation_grounding": 4, "assumption_transparency": 4, "coherence": 4}
        spine_winner = "B" if judge_mode == "analyze_always_b" else "A"
        emit(
            {
                "scores_a": analyze_scores_a,
                "scores_b": analyze_scores_b,
                "spine_winner": spine_winner,
                "spine_rationale": f"{spine_winner} is clearer",
                "claim_verdicts": [],
                "additions_from_loser": [],
            }
        )
        return 0
    if "build judge" in prompt:
        build_scores_a = {
            "correctness": 5,
            "verifier_evidence": 5,
            "comparative_evidence": 4,
            "scope_control": 5,
            "test_quality": 4,
            "benchmark_quality": 3,
            "maintainability": 5,
        }
        build_scores_b = {
            "correctness": 4,
            "verifier_evidence": 5,
            "comparative_evidence": 3,
            "scope_control": 4,
            "test_quality": 3,
            "benchmark_quality": 3,
            "maintainability": 4,
        }
        worker_a = prompt.split("<worker_a_output>", 1)[1].split("</worker_a_output>", 1)[0]
        worker_b = prompt.split("<worker_b_output>", 1)[1].split("</worker_b_output>", 1)[0]
        if judge_mode == "build_tie":
            winner = "tie"
        elif judge_mode == "build_always_a":
            winner = "A"
        elif judge_mode == "build_always_b":
            winner = "B"
        else:
            # Test fake behavior is provider-targeted so swapped passes can
            # assert canonical resolution without relying on a real judge.
            target = "codex" if judge_mode == "build_pick_codex" else "claude"
            winner = "A" if f'"provider_id": "{target}"' in worker_a else "B"
            if f'"provider_id": "{target}"' not in worker_a and f'"provider_id": "{target}"' not in worker_b:
                winner = "tie"
        emit(
            {
                "relation": "compare",
                "scores_a": build_scores_a,
                "scores_b": build_scores_b,
                "winner": winner,
                "rationale": f"build candidate {winner} has stronger verifier evidence and maintainability",
                "risks": [],
            }
        )
        return 0

    emit(worker_payload(name, prompt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
