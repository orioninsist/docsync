"""Runtime wiring contracts for Crawlee throttling."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRAWLER_PATH = ROOT / "src" / "docsync" / "crawler.py"
RUNTIME_PATH = ROOT / "src" / "docsync" / "crawler_runtime.py"
ENGINE_PATH = ROOT / "src" / "docsync" / "crawl_engine.py"


def _source() -> str:
    return CRAWLER_PATH.read_text(encoding="utf-8")

def _tree() -> ast.Module:
    return ast.parse(
        _source(),
        filename=str(CRAWLER_PATH),
    )

def _run_crawler() -> ast.AsyncFunctionDef:
    for node in _tree().body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_crawler":
            return node

    raise AssertionError("run_crawler() was not found")

def _call_name(call: ast.Call) -> str:
    if isinstance(call.func, ast.Name):
        return call.func.id

    if isinstance(call.func, ast.Attribute):
        return call.func.attr

    return ""




def test_official_throttling_manager_is_imported() -> None:
    source = RUNTIME_PATH.read_text(encoding="utf-8")

    assert "from crawlee.request_loaders import ThrottlingRequestManager" in source
    assert "from crawlee.storages import RequestQueue" in source

def test_request_queue_is_opened_inside_runtime_builder() -> None:
    runtime_tree = ast.parse(
        RUNTIME_PATH.read_text(encoding="utf-8"),
        filename=str(RUNTIME_PATH),
    )
    calls = [node for node in ast.walk(runtime_tree) if isinstance(node, ast.Call)]

    assert any(
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "RequestQueue"
        and call.func.attr == "open"
        for call in calls
    )

def test_throttling_manager_wraps_request_queue() -> None:
    runtime_source = RUNTIME_PATH.read_text(encoding="utf-8")
    crawler_source = _source()

    assert "request_manager = ThrottlingRequestManager(" in runtime_source
    assert "inner=request_queue" in runtime_source
    assert "domains=[hostname]" in runtime_source
    assert "async def open_run_request_queue(" in runtime_source
    assert "request_manager_opener=open_run_request_queue" in runtime_source
    assert 'alias="docsync-main"' in runtime_source
    assert "MemoryStorageClient" in runtime_source
    assert "storage_client=storage_client" in runtime_source
    assert "request_manager_opener=RequestQueue.open" not in runtime_source
    assert "runtime = await build_crawlee_runtime(" in crawler_source

def test_http_and_playwright_share_throttling_manager() -> None:
    source = ENGINE_PATH.read_text(encoding="utf-8")
    assert '"request_manager": runtime.request_manager' in source
    assert "request_manager=runtime.request_manager" in source

def test_legacy_handler_wait_is_removed() -> None:
    source = _source()

    assert "await crawl_delay_throttle.wait()" not in source

def test_runtime_report_identifies_request_manager() -> None:
    source = _source()

    assert '"request_manager": "ThrottlingRequestManager"' in source
    assert '"throttled_domains": [start_hostname]' in source
