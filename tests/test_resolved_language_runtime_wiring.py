"""Regression coverage for resolved language runtime wiring."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRAWLER_PATH = ROOT / "src" / "docsync" / "crawler.py"


def _run_crawler() -> ast.AsyncFunctionDef:
    tree = ast.parse(
        CRAWLER_PATH.read_text(encoding="utf-8"),
        filename=str(CRAWLER_PATH),
    )

    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_crawler":
            return node

    raise AssertionError("run_crawler() was not found")


def test_language_strategy_uses_resolved_language_override() -> None:
    run_crawler = _run_crawler()

    assignments = [
        node
        for node in ast.walk(run_crawler)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "language_strategy"
            for target in node.targets
        )
    ]

    assert len(assignments) == 1

    value = assignments[0].value
    assert isinstance(value, ast.Call)
    assert isinstance(value.func, ast.Name)
    assert value.func.id == "LanguageStrategy"
    assert len(value.args) == 1
    assert isinstance(value.args[0], ast.Name)
    assert value.args[0].id == "resolved_language"
