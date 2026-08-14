"""Exception-safe crawler progress cleanup contracts."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRAWLER_PATH = ROOT / "src" / "docsync" / "crawler.py"
RUNTIME_PATH = ROOT / "src" / "docsync" / "crawler_runtime.py"


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


def test_request_handler_uses_official_request_manager_throttling() -> None:
    handler = _request_handler()
    crawler_source = CRAWLER_PATH.read_text(encoding="utf-8")
    runtime_source = RUNTIME_PATH.read_text(encoding="utf-8")

    executable_statements = list(handler.body)

    if (
        executable_statements
        and isinstance(executable_statements[0], ast.Expr)
        and isinstance(executable_statements[0].value, ast.Constant)
        and isinstance(executable_statements[0].value.value, str)
    ):
        executable_statements = executable_statements[1:]

    assert executable_statements
    assert isinstance(executable_statements[0], ast.Nonlocal)

    assert "runtime = await build_crawlee_runtime(" in crawler_source
    assert "request_manager = runtime.request_manager" in crawler_source
    assert "request_manager = ThrottlingRequestManager(" in runtime_source
    assert "request_manager_opener=open_run_request_queue" in runtime_source
    assert "CrawlDelayThrottle(" not in crawler_source
    assert "await crawl_delay_throttle.wait()" not in crawler_source


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
