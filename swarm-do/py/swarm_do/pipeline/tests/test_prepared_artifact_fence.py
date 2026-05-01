from __future__ import annotations

import ast
import unittest
from pathlib import Path


PIPELINE_ROOT = Path(__file__).resolve().parents[1]
WRITER_PATH = PIPELINE_ROOT / "prepared_artifact_writer.py"


class _GitBaseWriteVisitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.function_stack: list[str] = []
        self.violations: list[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._check_store_target(target, node)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._check_store_target(node.target, node)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._check_store_target(node.target, node)
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        current_function = self.function_stack[-1] if self.function_stack else ""
        if current_function == "prepare_plan_run":
            for key in node.keys:
                if isinstance(key, ast.Constant) and key.value == "git_base_sha":
                    self._record(node, "prepare_plan_run git_base_sha dict literal")
        self.generic_visit(node)

    def _check_store_target(self, target: ast.AST, node: ast.AST) -> None:
        if isinstance(target, ast.Subscript) and _slice_value(target.slice) == "git_base_sha":
            self._record(node, "git_base_sha subscript write")
        for child in ast.iter_child_nodes(target):
            self._check_store_target(child, node)

    def _record(self, node: ast.AST, reason: str) -> None:
        rel = self.path.relative_to(PIPELINE_ROOT)
        self.violations.append(f"{rel}:{getattr(node, 'lineno', '?')}: {reason}")


def _slice_value(node: ast.AST) -> object:
    if isinstance(node, ast.Constant):
        return node.value
    return None


class PreparedArtifactFenceTests(unittest.TestCase):
    def test_prepared_artifact_writer_owns_git_base_sha_writes(self) -> None:
        violations: list[str] = []
        for path in sorted(PIPELINE_ROOT.rglob("*.py")):
            if path == WRITER_PATH or "tests" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            visitor = _GitBaseWriteVisitor(path)
            visitor.visit(tree)
            violations.extend(visitor.violations)

        self.assertEqual([], violations)


if __name__ == "__main__":
    unittest.main()
