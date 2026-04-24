"""CLI entrypoint for swarm_do.roles.

Subcommands (python3 -m swarm_do.roles <subcommand>):
  gen           Generate role files from role-specs/.
                  --write   write generated content to agents/ and roles/*/shared.md.
                  --check   diff-check only; exit 1 if any file has drifted.
                  --force   overwrite even non-stamped files (bootstrap migration only).
  gen readme-section  (Phase 6 — not yet implemented; raises NotImplementedError)
  list          Print all role-spec names (one per line).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .render import to_agents_md, to_shared_md
from .spec import load

# The role-specs directory is relative to the repo root.  We locate it by
# walking up from this file's location until we find swarm-do/role-specs/.
def _find_role_specs_dir() -> Path:
    here = Path(__file__).resolve()
    # Walk up: .../swarm-do/py/swarm_do/roles/cli.py → walk to repo root
    for parent in here.parents:
        candidate = parent / "swarm-do" / "role-specs"
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(
        "Could not locate swarm-do/role-specs/ directory. "
        "Run from within the mstefanko-plugins repo."
    )


def _find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "swarm-do" / "role-specs").is_dir():
            return parent
    raise FileNotFoundError("Could not locate repo root.")


_STAMP_PREFIX = "<!-- generated from role-specs/"


def _target_paths(repo_root: Path, spec_path: Path) -> list[tuple[Path, str]]:
    """Return list of (target_path, rendered_content) for a spec file."""
    from .spec import load as spec_load

    spec = spec_load(spec_path)
    results: list[tuple[Path, str]] = []

    if "agents" in spec.consumers:
        target = repo_root / "swarm-do" / "agents" / f"{spec.name}.md"
        results.append((target, to_agents_md(spec)))

    if "roles-shared" in spec.consumers:
        role_dir = repo_root / "swarm-do" / "roles" / spec.name
        target = role_dir / "shared.md"
        results.append((target, to_shared_md(spec)))

    return results


def _cmd_list(args: argparse.Namespace) -> int:
    role_specs_dir = _find_role_specs_dir()
    specs = sorted(role_specs_dir.glob("agent-*.md"))
    for s in specs:
        print(s.stem)
    return 0


def _cmd_gen(args: argparse.Namespace) -> int:
    readme_section = getattr(args, "readme_section", None)
    if readme_section == "readme-section":
        raise NotImplementedError("gen readme-section — Phase 6")

    role_specs_dir = _find_role_specs_dir()
    repo_root = _find_repo_root()
    spec_files = sorted(role_specs_dir.glob("agent-*.md"))

    if not spec_files:
        print("No role-spec files found.", file=sys.stderr)
        return 1

    write_mode = getattr(args, "write", False)
    check_mode = getattr(args, "check", False)
    force_mode = getattr(args, "force", False)

    drift_found = False
    errors: list[str] = []

    for spec_path in spec_files:
        try:
            pairs = _target_paths(repo_root, spec_path)
        except Exception as exc:
            errors.append(f"Error loading {spec_path.name}: {exc}")
            continue

        for target, content in pairs:
            if write_mode:
                # Safety guard: if target exists and lacks the stamp, refuse to
                # overwrite (it's hand-authored content), unless --force is set.
                if target.exists() and not force_mode:
                    existing = target.read_text(encoding="utf-8")
                    if not existing.startswith(_STAMP_PREFIX):
                        errors.append(
                            f"ABORT: {target} exists but has no generated stamp. "
                            "This file appears to be hand-authored. "
                            "Remove it manually or use --force for bootstrap migration."
                        )
                        continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                print(f"  wrote {target.relative_to(repo_root)}")
            else:
                # check mode (default)
                if not target.exists():
                    drift_found = True
                    print(f"  MISSING: {target.relative_to(repo_root)}")
                    continue
                existing = target.read_text(encoding="utf-8")
                if existing != content:
                    drift_found = True
                    # Show a minimal diff
                    import difflib
                    diff = list(
                        difflib.unified_diff(
                            existing.splitlines(keepends=True),
                            content.splitlines(keepends=True),
                            fromfile=str(target.relative_to(repo_root)),
                            tofile=f"role-specs/{spec_path.name} (generated)",
                        )
                    )
                    print(f"  DRIFT: {target.relative_to(repo_root)}")
                    print("".join(diff[:40]))  # first 40 lines of diff

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if check_mode or not write_mode:
        if drift_found:
            print(
                "\nDrift detected. Run `python3 -m swarm_do.roles gen --write` to fix.",
                file=sys.stderr,
            )
            return 1
        else:
            print("OK — all generated files match role-specs.")

    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m swarm_do.roles",
        description="Role-spec generator for swarm-do.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # gen subcommand
    gen_parser = sub.add_parser("gen", help="Generate role files from role-specs.")
    gen_group = gen_parser.add_mutually_exclusive_group(required=False)
    gen_group.add_argument(
        "--write",
        action="store_true",
        help="Write generated files to disk.",
    )
    gen_group.add_argument(
        "--check",
        action="store_true",
        help="Check generated files match disk; exit 1 if drift detected.",
    )
    gen_parser.add_argument(
        "--force",
        action="store_true",
        help="Skip safety guard — overwrite even non-stamped files (bootstrap migration only).",
    )
    gen_parser.add_argument(
        "readme_section",
        nargs="?",
        help="If 'readme-section', generate README section (Phase 6).",
    )

    # list subcommand
    sub.add_parser("list", help="List all role-spec names.")

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "list":
        return _cmd_list(args)

    if args.command == "gen":
        return _cmd_gen(args)

    print(f"Unknown command: {args.command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
