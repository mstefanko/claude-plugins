from __future__ import annotations

import ast
import unittest
from pathlib import Path

from swarm_do.pipeline.paths import REPO_ROOT


MODULES = [
    REPO_ROOT / "py" / "swarm_do" / "pipeline" / "run_trace.py",
    REPO_ROOT / "py" / "swarm_do" / "pipeline" / "run_eval.py",
]
WRITE_MODES = {"w", "a", "x", "w+", "a+", "x+", "wb", "ab", "xb", "wb+", "ab+", "xb+"}


class _ReadOnlyVisitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.violations: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == "subprocess":
                self._record(node, "imports subprocess")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == "subprocess":
            self._record(node, "imports subprocess")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node.func)
        if isinstance(node.func, ast.Attribute):
            if node.func.attr in {"write_text", "write_bytes"}:
                self._record(node, f"Path.{node.func.attr}")
            if node.func.attr == "open" and _has_write_mode(node):
                self._record(node, "Path.open write mode")
            if node.func.attr == "dump" and _root_name(node.func.value) == "json":
                self._record(node, "json.dump")
            if node.func.attr in {"makedirs", "mkdir", "system"} and _root_name(node.func.value) == "os":
                self._record(node, f"os.{node.func.attr}")
            if node.func.attr.startswith("copy") and _root_name(node.func.value) == "shutil":
                self._record(node, f"shutil.{node.func.attr}")
            if node.func.attr == "move" and _root_name(node.func.value) == "shutil":
                self._record(node, "shutil.move")
        elif name == "open" and _has_write_mode(node):
            self._record(node, "open write mode")
        self.generic_visit(node)

    def _record(self, node: ast.AST, reason: str) -> None:
        self.violations.append(f"{self.path.name}:{getattr(node, 'lineno', '?')}: {reason}")


def _call_name(node: ast.AST) -> str | None:
    return node.id if isinstance(node, ast.Name) else None


def _root_name(node: ast.AST) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _has_write_mode(node: ast.Call) -> bool:
    mode = None
    if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
        mode = node.args[1].value
    for keyword in node.keywords:
        if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
            mode = keyword.value.value
    return isinstance(mode, str) and mode in WRITE_MODES


class RunTraceReadOnlyTests(unittest.TestCase):
    def test_trace_and_eval_modules_do_not_write(self) -> None:
        violations: list[str] = []
        for path in MODULES:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            visitor = _ReadOnlyVisitor(path)
            visitor.visit(tree)
            violations.extend(visitor.violations)

        self.assertEqual([], violations)


if __name__ == "__main__":
    unittest.main()
