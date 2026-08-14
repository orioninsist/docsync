"""Canonical crawler incremental-filter wiring contracts."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRAWLER_PATH = ROOT / "src/docsync/crawler.py"


def _tree() -> ast.Module:
    return ast.parse(
        CRAWLER_PATH.read_text(encoding="utf-8"),
        filename=str(CRAWLER_PATH),
    )


def _run_crawler() -> ast.AsyncFunctionDef:
    for node in _tree().body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_crawler":
            return node

    raise AssertionError("async run_crawler() was not found")


def _qualified_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id

    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value)
        if parent:
            return f"{parent}.{node.attr}"
        return node.attr

    return None


def _calls(name: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(_run_crawler())
        if isinstance(node, ast.Call) and _qualified_name(node.func) == name
    ]


def test_crawler_imports_incremental_filtering() -> None:
    imports = {
        alias.name
        for node in _tree().body
        if isinstance(node, ast.ImportFrom) and node.module == "docsync.incremental"
        for alias in node.names
    }

    assert "filter_incremental_urls" in imports
    assert "load_url_state" in imports


def test_crawler_declares_incremental_runtime_contracts() -> None:
    tree = ast.parse(
        CRAWLER_PATH.read_text(encoding="utf-8"),
        filename=str(CRAWLER_PATH),
    )

    class_names = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    metric_imports = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "docsync.metrics"
        for alias in node.names
    }

    assert "_IncrementalRuntimeConfig" in class_names
    assert "_IncrementalRuntimeStats" not in class_names
    assert "CrawlStats" in metric_imports


def test_crawler_loads_persistent_url_state() -> None:
    calls = _calls("load_url_state")

    assert len(calls) == 1
    assert calls[0].args
    assert isinstance(calls[0].args[0], ast.Name)
    assert calls[0].args[0].id == "resolved_state_dir"


def test_crawler_filters_initial_urls() -> None:
    calls = _calls("filter_incremental_urls")

    assert len(calls) == 1

    keyword_names = {
        keyword.arg for keyword in calls[0].keywords if keyword.arg is not None
    }

    assert "config" in keyword_names
    assert {"url_state", "state"} & keyword_names or any(
        isinstance(argument, ast.Name) and argument.id == "url_state"
        for argument in calls[0].args
    )


def test_crawlee_run_uses_filtered_urls() -> None:
    calls = [
        node
        for node in ast.walk(_run_crawler())
        if isinstance(node, ast.Call)
        and (_qualified_name(node.func) or "").endswith(".run")
    ]

    assert len(calls) == 1
    assert calls[0].args
    assert isinstance(calls[0].args[0], ast.Name)
    assert calls[0].args[0].id == "incremental_urls"


def test_empty_incremental_selection_finalizes_and_returns_stats() -> None:
    run_crawler = _run_crawler()
    guards = [
        node
        for node in ast.walk(run_crawler)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.UnaryOp)
        and isinstance(node.test.op, ast.Not)
        and isinstance(node.test.operand, ast.Name)
        and node.test.operand.id == "incremental_urls"
    ]

    assert len(guards) == 1
    assert any(
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Name)
        and statement.value.func.id == "finalize_crawl"
        for statement in guards[0].body
    )
    assert any(
        isinstance(statement, ast.Return)
        and isinstance(statement.value, ast.Name)
        and statement.value.id == "stats"
        for statement in guards[0].body
    )


def test_resolved_controls_reach_runtime_config() -> None:
    constructors = _calls("_IncrementalRuntimeConfig")

    assert len(constructors) == 1

    keyword_values = {
        keyword.arg: keyword.value
        for keyword in constructors[0].keywords
        if keyword.arg is not None
    }

    refresh_value = keyword_values["refresh_hours"]
    force_value = keyword_values["force_refresh"]

    assert isinstance(refresh_value, ast.Name)
    assert refresh_value.id == "resolved_refresh_hours"
    assert isinstance(force_value, ast.Name)
    assert force_value.id == "resolved_force_refresh"
