from __future__ import annotations

import ast
import unittest
from pathlib import Path


PIPELINE_ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST_PATH = Path(__file__).with_name("state_store_fence_allowlist.txt")
STREAMING_CONSUMERS = {
    PIPELINE_ROOT / "claude_stream.py",
    PIPELINE_ROOT / "phase_pump.py",
    PIPELINE_ROOT / "stage_controller.py",
}

PROTECTED_FILENAMES = {
    "active-run.json",
    "evidence.json",
    "manifest.json",
    "operator_decisions.v1.json",
    "phase_sessions.v1.json",
    "prepared_plan.v1.json",
    "run_events.jsonl",
    "shared_decisions.v1.json",
    "stage_sessions.v1.json",
}
WRITE_METHODS = {"dump", "write", "write_bytes", "write_text"}
WRITE_FUNCTIONS = {"_atomic_json_write", "atomic_write_text"}
WRITE_MODES = {"a", "ab", "a+", "w", "w+", "wb", "wb+"}


class _CoreStateWriteVisitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.scopes: list[set[str]] = [set()]
        self.violations: list[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scopes.append(set())
        self.generic_visit(node)
        self.scopes.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.scopes.append(set())
        self.generic_visit(node)
        self.scopes.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        protected = self._protected_filename(node.value)
        for target in node.targets:
            if isinstance(target, ast.Name):
                if protected is None:
                    self.scopes[-1].discard(target.id)
                else:
                    self.scopes[-1].add(target.id)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name) and node.value is not None:
            protected = self._protected_filename(node.value)
            if protected is None:
                self.scopes[-1].discard(node.target.id)
            else:
                self.scopes[-1].add(node.target.id)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute):
            if node.func.attr in WRITE_METHODS:
                filename = self._protected_filename(node.func.value)
                if filename is not None:
                    self._record(node, f"{node.func.attr} to {filename}")
            if node.func.attr == "open":
                filename = self._protected_filename(node.func.value)
                if filename is not None and _call_has_write_mode(node):
                    self._record(node, f"open write to {filename}")
        elif isinstance(node.func, ast.Name):
            if node.func.id == "open" and node.args:
                filename = self._protected_filename(node.args[0])
                if filename is not None and _call_has_write_mode(node):
                    self._record(node, f"open write to {filename}")
            elif node.func.id in WRITE_FUNCTIONS and node.args:
                filename = self._protected_filename(node.args[0])
                if filename is not None:
                    self._record(node, f"{node.func.id} to {filename}")
        self.generic_visit(node)

    def _protected_filename(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name) and any(node.id in scope for scope in reversed(self.scopes)):
            return "<tracked protected path>"
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return _protected_name_from_string(node.value)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            return self._protected_filename(node.right) or self._protected_filename(node.left)
        if isinstance(node, ast.Call):
            if _call_name(node.func) == "Path" and node.args:
                return self._protected_filename(node.args[0])
            if isinstance(node.func, ast.Attribute) and node.func.attr == "with_name" and node.args:
                return self._protected_filename(node.args[0])
        return None

    def _record(self, node: ast.AST, reason: str) -> None:
        rel = self.path.relative_to(PIPELINE_ROOT)
        self.violations.append(f"{rel}:{getattr(node, 'lineno', '?')}: {reason}")


def _protected_name_from_string(value: str) -> str | None:
    name = Path(value).name
    return name if name in PROTECTED_FILENAMES else None


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _call_has_write_mode(node: ast.Call) -> bool:
    mode = None
    if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
        mode = node.args[1].value
    for keyword in node.keywords:
        if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
            mode = keyword.value.value
    return isinstance(mode, str) and mode in WRITE_MODES


def _allowlisted_paths() -> set[Path]:
    paths: set[Path] = set()
    for raw in ALLOWLIST_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        path_text, _sep, _rest = line.partition("|")
        paths.add((PIPELINE_ROOT.parents[2] / path_text.strip()).resolve(strict=False))
    return paths


def _violations_for(paths: list[Path], *, allowlisted_paths: set[Path]) -> list[str]:
    violations: list[str] = []
    for path in paths:
        if path.resolve(strict=False) in allowlisted_paths or "tests" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = _CoreStateWriteVisitor(path)
        visitor.visit(tree)
        violations.extend(visitor.violations)
    return violations


class StateStoreWriteFenceTests(unittest.TestCase):
    def test_core_state_writes_stay_in_owner_modules(self) -> None:
        paths = sorted(PIPELINE_ROOT.rglob("*.py"))
        violations = _violations_for(paths, allowlisted_paths=_allowlisted_paths())

        self.assertEqual([], violations)

    def test_phase_zero_streaming_modules_stay_consumers(self) -> None:
        violations = _violations_for(
            sorted(STREAMING_CONSUMERS),
            allowlisted_paths=set(),
        )

        self.assertEqual([], violations)

    def test_allowlist_entries_have_review_justifications(self) -> None:
        for raw in ALLOWLIST_PATH.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = [part.strip() for part in line.split("|")]
            self.assertEqual(3, len(parts), line)
            self.assertTrue(parts[0].startswith("py/swarm_do/pipeline/"), line)
            self.assertTrue(parts[1], line)
            self.assertGreaterEqual(len(parts[2].split()), 4, line)


if __name__ == "__main__":
    unittest.main()
