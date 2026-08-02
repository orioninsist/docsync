"""Regression contracts for process-local Crawlee request storage."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRAWLER_PATH = ROOT / "src" / "docsync" / "crawler.py"


def _source() -> str:
    return CRAWLER_PATH.read_text(encoding="utf-8")


def _tree() -> ast.Module:
    return ast.parse(
        _source(),
        filename=str(CRAWLER_PATH),
    )


def _run_crawler() -> ast.AsyncFunctionDef:
    matches = [
        node
        for node in ast.walk(_tree())
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_crawler"
    ]

    assert len(matches) == 1
    return matches[0]


def test_memory_storage_client_is_created_per_crawl() -> None:
    function = _run_crawler()

    assignments = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "crawler_storage_client"
            for target in node.targets
        )
    ]

    assert len(assignments) == 1

    value = assignments[0].value

    assert isinstance(value, ast.Call)
    assert isinstance(value.func, ast.Name)
    assert value.func.id == "MemoryStorageClient"


def test_main_request_queue_uses_memory_storage() -> None:
    source = _source()

    assert 'alias="docsync-main"' in source
    assert "storage_client=crawler_storage_client" in source


def test_throttled_subqueues_use_process_local_storage() -> None:
    source = _source()

    assert "async def open_run_request_queue(" in source
    assert "request_manager_opener=open_run_request_queue" in source
    assert "else crawler_storage_client" in source


def test_both_crawlers_use_the_same_memory_storage_client() -> None:
    source = _source()

    assert source.count("storage_client=crawler_storage_client") >= 3

    assert "PlaywrightCrawler(" in source
    assert "BeautifulSoupCrawler(" in source


def test_persistent_uuid_queue_aliases_are_removed() -> None:
    source = _source()

    assert "uuid4" not in source
    assert "request_queue_namespace" not in source


def test_memory_storage_backend_is_reported() -> None:
    source = _source()

    assert '"request_storage": "MemoryStorageClient"' in source
