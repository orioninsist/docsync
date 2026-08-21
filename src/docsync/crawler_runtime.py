"""Shared Crawlee runtime construction for docsync."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import uuid4

from crawlee import ConcurrencySettings, service_locator
from crawlee.request_loaders import ThrottlingRequestManager
from crawlee.storage_clients import MemoryStorageClient, StorageClient
from crawlee.storages import RequestQueue


@dataclass(slots=True)
class CrawleeRuntime:
    """Runtime components shared by docsync Crawlee consumers."""

    storage_client: StorageClient
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

    service_locator.storage_instance_manager.clear_cache()

    storage_client = MemoryStorageClient()
    runtime_storage_client = storage_client

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
        queue_storage_client = storage_client or runtime_storage_client

        return await RequestQueue.open(
            alias=alias or f"docsync-domain-{runtime_id}-{uuid4().hex}",
            storage_client=queue_storage_client,
        )

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
