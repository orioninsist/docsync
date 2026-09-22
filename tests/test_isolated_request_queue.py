"""Regression contracts for persistent Crawlee request storage."""

from __future__ import annotations

import asyncio
from pathlib import Path

from crawlee.request_loaders import ThrottlingRequestManager
from crawlee.storage_clients import FileSystemStorageClient
from crawlee.storages import RequestQueue

from docsync.crawler_runtime import build_crawlee_runtime


def build_runtime(storage_dir: Path):
    return asyncio.run(
        build_crawlee_runtime(
            hostname="example.com",
            storage_dir=storage_dir,
            max_concurrency=2,
            requests_per_minute=20,
            request_timeout_seconds=60,
        )
    )


def test_filesystem_storage_client_is_used(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path / "crawlee")

    assert isinstance(runtime.storage_client, FileSystemStorageClient)
    assert runtime.configuration.purge_on_start is False
    assert Path(runtime.configuration.storage_dir) == (tmp_path / "crawlee").resolve()


def test_main_request_queue_uses_persistent_storage(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path / "crawlee")

    assert isinstance(runtime.request_manager, ThrottlingRequestManager)
    assert isinstance(runtime.request_manager._inner, RequestQueue)
    assert runtime.request_manager._inner.name == "docsync-main"


def test_throttled_runtime_contains_requested_domain(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path / "crawlee")

    assert "example.com" in runtime.request_manager._domain_states


def test_runtime_uses_native_request_queue_opener(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path / "crawlee")

    assert runtime.request_manager._request_manager_opener == RequestQueue.open
