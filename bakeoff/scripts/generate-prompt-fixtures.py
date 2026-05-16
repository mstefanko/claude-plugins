#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "tests" / "parity" / "fixtures" / "prompts"
sys.path.insert(0, str(ROOT / "src"))

from bakeoff.providers import build_judge_prompt, build_triage_prompt, build_worker_prompt  # noqa: E402
from bakeoff.work_order import validate_work_order  # noqa: E402


def work_order(mode: str) -> dict[str, Any]:
    data = {
        "schema_version": 1,
        "id": f"{mode}-prompt-fixture",
        "type": mode,
        "goal": "Document the prompt contract.",
        "background": "Stable prompt fixture context.",
        "providers": [
            {"id": "claude", "backend": "claude", "model": "fake-claude", "scope": "codebase"},
            {"id": "codex", "backend": "codex", "model": "fake-codex", "scope": "web" if mode == "gather" else "mixed"},
        ],
        "judge": {"backend": "claude", "model": "fake-judge"},
        "budgets": {"wall_clock_seconds": 3, "max_output_bytes": 20000, "heartbeat_seconds": 0},
        "facet": {
            "id": "code-review",
            "kind": "generic",
            "focus": "Find actionable defects introduced or exposed by the change.",
            "include": ["correctness bugs and edge cases"],
            "exclude": ["style-only preferences"],
        },
    }
    return validate_work_order(data)


def worker_result(label: str) -> dict[str, Any]:
    return {
        "status": "complete",
        "position": f"{label} position",
        "claims": [{"id": "R-001", "claim": f"{label} claim", "evidence": ["fake:1"], "confidence": "high"}],
        "conflicts": [],
        "unknowns": [],
        "recommended_next_checks": [],
    }


def prompt_files() -> dict[str, str]:
    files: dict[str, str] = {}
    for mode in ("gather", "compare", "analyze"):
        wo = work_order(mode)
        for provider in wo["providers"]:
            files[f"worker-{mode}-{provider['id']}.txt"] = build_worker_prompt(wo, provider)
        files[f"judge-{mode}.txt"] = build_judge_prompt(wo, worker_result("A"), worker_result("B"), mode=mode)
    triage_payload = {
        "schema_version": 1,
        "run_id": "prompt-fixture",
        "facet": work_order("gather")["facet"],
        "budgets": {"wall_clock_seconds": 3, "max_output_bytes": 20000, "heartbeat_seconds": 0},
        "source_findings": [
            {
                "source_finding_id": "F-001",
                "source": "report",
                "text": "Fake merged claim",
                "citations": ["src/fake.py:1"],
            }
        ],
        "citation_checks": [],
        "report_md": "# Report\n\nFake merged claim.",
        "artifacts": {},
    }
    files["triage.txt"] = build_triage_prompt(triage_payload, triage_payload["budgets"])
    return files


def write_all(out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": 1, "files": {}}
    for name, text in sorted(prompt_files().items()):
        path = out_dir / name
        path.write_text(text, encoding="utf-8")
        manifest["files"][name] = {
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "size_bytes": len(text.encode("utf-8")),
        }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def check() -> int:
    with tempfile.TemporaryDirectory(prefix="bakeoff-prompt-fixtures-") as tmp:
        write_all(Path(tmp))
        for name in prompt_files():
            actual = (Path(tmp) / name).read_text(encoding="utf-8")
            expected_path = OUT_DIR / name
            if not expected_path.exists():
                print(f"missing prompt fixture: {expected_path}", file=sys.stderr)
                return 1
            expected = expected_path.read_text(encoding="utf-8")
            if actual != expected:
                print(f"prompt fixture drift: {expected_path}", file=sys.stderr)
                return 1
        actual_manifest = (Path(tmp) / "manifest.json").read_text(encoding="utf-8")
        expected_manifest = (OUT_DIR / "manifest.json").read_text(encoding="utf-8")
        if actual_manifest != expected_manifest:
            print(f"prompt fixture manifest drift: {OUT_DIR / 'manifest.json'}", file=sys.stderr)
            return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Python oracle prompt fixtures for Go parity.")
    parser.add_argument("--check", action="store_true", help="verify committed fixtures are current")
    args = parser.parse_args()
    if args.check:
        return check()
    write_all(OUT_DIR)
    print(f"wrote prompt fixtures under {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
