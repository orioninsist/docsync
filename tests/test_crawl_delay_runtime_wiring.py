"""Runtime wiring contracts for crawl-delay throttling."""

from __future__ import annotations

import ast
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from docsync.crawl_delay import (
    CRAWL_DELAY_ENVIRONMENT_VARIABLE,
    crawl_delay_seconds_from_environment,
)

ROOT = Path(__file__).resolve().parents[1]
CRAWLER_PATH = ROOT / "src" / "docsync" / "crawler.py"


def _crawler_tree() -> ast.Module:
    return ast.parse(CRAWLER_PATH.read_text(encoding="utf-8"))


def _run_crawler_node() -> ast.AsyncFunctionDef:
    for node in ast.walk(_crawler_tree()):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_crawler":
            return node

    raise AssertionError("async run_crawler() was not found")


def _request_handler_node() -> ast.AsyncFunctionDef:
    run_crawler = _run_crawler_node()

    for node in ast.walk(run_crawler):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "request_handler":
            return node

    raise AssertionError("nested async request_handler() was not found")


def test_default_crawl_delay_is_zero() -> None:
    with patch.dict(os.environ, {}, clear=True):
        assert crawl_delay_seconds_from_environment() == 0.0


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("0", 0.0),
        ("0.25", 0.25),
        ("1", 1.0),
        (" 2.5 ", 2.5),
    ],
)
def test_valid_crawl_delay_environment_values(
    raw_value: str,
    expected: float,
) -> None:
    with patch.dict(
        os.environ,
        {CRAWL_DELAY_ENVIRONMENT_VARIABLE: raw_value},
        clear=True,
    ):
        assert crawl_delay_seconds_from_environment() == pytest.approx(expected)


@pytest.mark.parametrize(
    "raw_value",
    [
        "-0.01",
        "invalid",
        "nan",
        "inf",
        "-inf",
        "",
    ],
)
def test_invalid_crawl_delay_environment_values_are_rejected(
    raw_value: str,
) -> None:
    with (
        patch.dict(
            os.environ,
            {CRAWL_DELAY_ENVIRONMENT_VARIABLE: raw_value},
            clear=True,
        ),
        pytest.raises(
            ValueError,
            match="must be a finite non-negative number",
        ),
    ):
        crawl_delay_seconds_from_environment()


def test_run_crawler_constructs_shared_throttle() -> None:
    run_crawler = _run_crawler_node()

    constructors = [
        node
        for node in ast.walk(run_crawler)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "CrawlDelayThrottle"
    ]

    assert len(constructors) == 1

    constructor = constructors[0]
    delay_keywords = [
        keyword for keyword in constructor.keywords if keyword.arg == "delay_seconds"
    ]

    assert len(delay_keywords) == 1
    assert isinstance(delay_keywords[0].value, ast.Call)
    assert isinstance(delay_keywords[0].value.func, ast.Name)
    assert delay_keywords[0].value.func.id == "crawl_delay_seconds_from_environment"


def test_request_handler_waits_before_other_runtime_operations() -> None:
    request_handler = _request_handler_node()

    executable_statements = list(request_handler.body)

    if (
        executable_statements
        and isinstance(executable_statements[0], ast.Expr)
        and isinstance(executable_statements[0].value, ast.Constant)
        and isinstance(executable_statements[0].value.value, str)
    ):
        executable_statements = executable_statements[1:]

    assert executable_statements

    first_statement = executable_statements[0]
    assert isinstance(first_statement, ast.Expr)
    assert isinstance(first_statement.value, ast.Await)

    awaited_call = first_statement.value.value
    assert isinstance(awaited_call, ast.Call)
    assert isinstance(awaited_call.func, ast.Attribute)
    assert awaited_call.func.attr == "wait"
    assert isinstance(awaited_call.func.value, ast.Name)
    assert awaited_call.func.value.id == "crawl_delay_throttle"


def test_throttle_is_scoped_to_single_crawl_execution() -> None:
    tree = _crawler_tree()
    run_crawler = _run_crawler_node()

    module_level_constructors = [
        node
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and any(
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == "CrawlDelayThrottle"
            for child in ast.walk(node)
        )
    ]

    assert module_level_constructors == []

    nested_handlers = [
        node
        for node in ast.walk(run_crawler)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "request_handler"
    ]

    assert len(nested_handlers) == 1
