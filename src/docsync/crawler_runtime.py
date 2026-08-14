"""Shared Crawlee runtime construction for docsync."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import uuid4

from crawlee import ConcurrencySettings
from crawlee.request_loaders import ThrottlingRequestManager
from crawlee.storage_clients import MemoryStorageClient
from crawlee.storages import RequestQueue


@dataclass(slots=True)
class CrawleeRuntime:
    """Runtime components shared by docsync Crawlee consumers."""

    storage_client: MemoryStorageClient
    request_manager: ThrottlingRequestManager[RequestQueue]
    concurrency_settings: ConcurrencySettings
    request_handler_timeout: timedelta


async def build_crawlee_runtime(
    *,
    hostname: str,
    max_concurrency: int,
    requests_per_minute: int,
    request_timeout_seconds: int,
) -> CrawleeRuntime:
    """Build one process-local Crawlee request runtime."""

    storage_client = MemoryStorageClient()
    runtime_id = uuid4().hex

    request_queue = await RequestQueue.open(
        alias="docsync-main",
        storage_client=storage_client,
    )

    async def open_run_request_queue(
        *,
        alias: str | None = None,
        storage_client: Any = None,
        configuration: Any = None,
    ) -> RequestQueue:
        return await RequestQueue.open(
            alias=f"docsync-domain-{runtime_id}-{uuid4().hex}",
            storage_client=(
                storage_client if storage_client is not None else runtime_storage_client
            ),
            configuration=configuration,
        )

    runtime_storage_client = storage_client

    request_manager = ThrottlingRequestManager(
        inner=request_queue,
        domains=[hostname],
        request_manager_opener=open_run_request_queue,
    )

    concurrency_settings = ConcurrencySettings(
        min_concurrency=1,
        max_concurrency=max_concurrency,
        desired_concurrency=max_concurrency,
        max_tasks_per_minute=requests_per_minute,
    )

    return CrawleeRuntime(
        storage_client=storage_client,
        request_manager=request_manager,
        concurrency_settings=concurrency_settings,
        request_handler_timeout=timedelta(seconds=request_timeout_seconds),
    )
