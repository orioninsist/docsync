"""Verify that pipeline command-line entrypoints are explicit and intentional."""

from __future__ import annotations

import ast
from pathlib import Path

PIPELINE_DIRECTORY = Path("pipeline")

EXPECTED_CLI_ENTRYPOINTS = frozenset(
    {
        Path("pipeline/discover_sites.py"),
        Path("pipeline/docs_pipeline_runner.py"),
        Path("pipeline/flatten_docs.py"),
        Path("pipeline/incremental_update.py"),
        Path("pipeline/merge_service.py"),
        Path("pipeline/release_validate.py"),
        Path("pipeline/run_pipeline.py"),
    }
)


def is_name_main_comparison(expression: ast.expr) -> bool:
    """Return whether an expression is exactly __name__ == '__main__'."""
    if not isinstance(expression, ast.Compare):
        return False

    if len(expression.ops) != 1 or not isinstance(expression.ops[0], ast.Eq):
        return False

    if len(expression.comparators) != 1:
        return False

    left_expression = expression.left
    right_expression = expression.comparators[0]

    return (
        isinstance(left_expression, ast.Name)
        and left_expression.id == "__name__"
        and isinstance(right_expression, ast.Constant)
        and right_expression.value == "__main__"
    ) or (
        isinstance(right_expression, ast.Name)
        and right_expression.id == "__name__"
        and isinstance(left_expression, ast.Constant)
        and left_expression.value == "__main__"
    )


def has_explicit_cli_entrypoint(module_path: Path) -> bool:
    """Return whether a Python module contains an explicit CLI guard."""
    syntax_tree = ast.parse(module_path.read_text(encoding="utf-8"))

    return any(
        isinstance(node, ast.If) and is_name_main_comparison(node.test)
        for node in ast.walk(syntax_tree)
    )


def discover_cli_entrypoints() -> frozenset[Path]:
    """Discover pipeline modules containing an explicit CLI guard."""
    return frozenset(
        module_path
        for module_path in PIPELINE_DIRECTORY.rglob("*.py")
        if has_explicit_cli_entrypoint(module_path)
    )


def test_pipeline_cli_entrypoints_are_intentional() -> None:
    """Ensure only approved pipeline modules expose a command-line interface."""
    discovered_entrypoints = discover_cli_entrypoints()

    assert discovered_entrypoints == EXPECTED_CLI_ENTRYPOINTS, (
        "Pipeline CLI entrypoints differ from the intentional architecture.\n"
        f"Expected: {sorted(map(str, EXPECTED_CLI_ENTRYPOINTS))}\n"
        f"Actual:   {sorted(map(str, discovered_entrypoints))}"
    )
