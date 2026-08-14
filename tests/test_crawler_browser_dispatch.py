from __future__ import annotations

import ast
from pathlib import Path

CRAWLER_PATH = Path("src/docsync/crawler.py")


def _load_tree() -> ast.Module:
    return ast.parse(
        CRAWLER_PATH.read_text(encoding="utf-8"),
        filename=str(CRAWLER_PATH),
    )


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _run_crawler_function(tree: ast.Module) -> ast.AsyncFunctionDef | ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name in {
            "run_crawler",
            "_run_crawler",
        }:
            return node
    raise AssertionError("Canonical run_crawler function was not found.")


def test_canonical_crawler_preserves_both_dispatch_targets() -> None:
    function = _run_crawler_function(_load_tree())
    constructors = {
        _call_name(node) for node in ast.walk(function) if isinstance(node, ast.Call)
    }

    assert "BeautifulSoupCrawler" in constructors
    assert "PlaywrightCrawler" in constructors


def test_canonical_crawler_dispatch_is_conditional() -> None:
    function = _run_crawler_function(_load_tree())

    conditional_nodes = [
        node for node in ast.walk(function) if isinstance(node, (ast.If, ast.IfExp))
    ]
    assert conditional_nodes, "Crawler construction must use browser-mode dispatch."

    def constructors(node: ast.AST) -> set[str | None]:
        return {
            _call_name(child) for child in ast.walk(node) if isinstance(child, ast.Call)
        }

    assert any(
        (
            "PlaywrightCrawler" in constructors(node)
            and "BeautifulSoupCrawler" in constructors(node)
        )
        for node in conditional_nodes
    ), "The same conditional must preserve browser and HTTP crawler paths."


def test_playwright_crawler_is_imported() -> None:
    tree = _load_tree()
    imported = {
        alias.asname or alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "PlaywrightCrawler" in imported
