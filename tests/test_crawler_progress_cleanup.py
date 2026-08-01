"""Exception-safe crawler progress cleanup contracts."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRAWLER_PATH = ROOT / "src" / "docsync" / "crawler.py"


def _request_handler() -> ast.AsyncFunctionDef:
    source = CRAWLER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(
        source,
        filename=str(CRAWLER_PATH),
    )

    run_crawler = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_crawler"
    )

    return next(
        node
        for node in ast.walk(run_crawler)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "request_handler"
    )


def test_request_handler_keeps_delay_as_first_operation() -> None:
    handler = _request_handler()
    first_statement = handler.body[0]

    assert isinstance(first_statement, ast.Expr)
    assert isinstance(first_statement.value, ast.Await)
    assert isinstance(first_statement.value.value, ast.Call)
    assert isinstance(
        first_statement.value.value.func,
        ast.Attribute,
    )
    assert first_statement.value.value.func.attr == "wait"


def test_request_handler_uses_exception_safe_cleanup() -> None:
    handler = _request_handler()

    try_statement = next(
        statement for statement in handler.body if isinstance(statement, ast.Try)
    )

    assert try_statement.finalbody

    final_source_nodes = list(
        ast.walk(
            ast.Module(
                body=try_statement.finalbody,
                type_ignores=[],
            )
        )
    )

    assert any(
        isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "active_requests"
            for target in node.targets
        )
        for node in final_source_nodes
    )

    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "emit_event"
        for node in final_source_nodes
    )


def test_active_request_increment_occurs_inside_try() -> None:
    handler = _request_handler()

    try_statement = next(
        statement for statement in handler.body if isinstance(statement, ast.Try)
    )

    assert any(
        isinstance(node, ast.AugAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "active_requests"
        for node in ast.walk(try_statement)
    )


def test_success_only_cleanup_was_removed() -> None:
    handler = _request_handler()

    top_level_assignments = [
        statement for statement in handler.body if isinstance(statement, ast.Assign)
    ]

    assert not any(
        any(
            isinstance(target, ast.Name) and target.id == "active_requests"
            for target in statement.targets
        )
        for statement in top_level_assignments
    )
