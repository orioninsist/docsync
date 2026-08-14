"""Regression contracts for process-local Crawlee request storage."""

from __future__ import annotations

import asyncio

from crawlee.request_loaders import ThrottlingRequestManager
from crawlee.storage_clients import MemoryStorageClient
from crawlee.storages import RequestQueue

from docsync.crawler_runtime import build_crawlee_runtime


def build_runtime():
    return asyncio.run(
        build_crawlee_runtime(
            hostname="example.com",
            max_concurrency=2,
            requests_per_minute=20,
            request_timeout_seconds=60,
        )
    )


def test_memory_storage_client_is_created_per_runtime() -> None:
    first = build_runtime()
    second = build_runtime()

    assert isinstance(first.storage_client, MemoryStorageClient)
    assert isinstance(second.storage_client, MemoryStorageClient)
    assert first.storage_client is not second.storage_client


def test_main_request_queue_uses_memory_storage() -> None:
    runtime = build_runtime()

    assert isinstance(runtime.request_manager, ThrottlingRequestManager)
    assert isinstance(runtime.request_manager._inner, RequestQueue)


def test_throttled_runtime_contains_requested_domain() -> None:
    runtime = build_runtime()

    assert "example.com" in runtime.request_manager._domain_states


def test_runtime_creates_process_local_storage_client() -> None:
    first = build_runtime()
    second = build_runtime()

    assert isinstance(first.storage_client, MemoryStorageClient)
    assert isinstance(second.storage_client, MemoryStorageClient)
    assert first.storage_client is not second.storage_client
