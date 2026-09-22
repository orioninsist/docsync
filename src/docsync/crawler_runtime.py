"""Shared Crawlee runtime construction for DocsSync."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from crawlee import ConcurrencySettings
from crawlee._service_locator import ServiceLocator
from crawlee.configuration import Configuration
from crawlee.events import EventManager, LocalEventManager
from crawlee.request_loaders import RequestManager, ThrottlingRequestManager
from crawlee.storage_clients import FileSystemStorageClient, StorageClient
from crawlee.storages import RequestQueue


@dataclass(slots=True)
class CrawleeRuntime:
    """Public Crawlee components shared by DocsSync crawl workflows."""

    storage_client: StorageClient
    configuration: Configuration
    event_manager: EventManager
    request_manager: RequestManager
    concurrency_settings: ConcurrencySettings
    request_handler_timeout: timedelta


    async def drop_request_storage(self) -> None:
        """Drop all request-manager storage owned by this runtime."""

        await self.request_manager.drop()


async def build_crawlee_runtime(
    *,
    hostname: str,
    storage_dir: str | Path,
    max_concurrency: int,
    requests_per_minute: int,
    request_timeout_seconds: int,
) -> CrawleeRuntime:
    """Build one persistent Crawlee runtime using only public components."""

    resolved_storage_dir = Path(storage_dir).expanduser().resolve()
    resolved_storage_dir.mkdir(parents=True, exist_ok=True)

    configuration = Configuration(
        storage_dir=str(resolved_storage_dir),
        purge_on_start=False,
    )
    storage_client = FileSystemStorageClient()
    event_manager = LocalEventManager().from_config(config=configuration)
    service_locator = ServiceLocator(
        configuration=configuration,
        storage_client=storage_client,
        event_manager=event_manager,
    )

    request_queue = await RequestQueue.open(
        name="docsync-main",
        storage_client=storage_client,
        configuration=configuration,
    )

    request_manager = ThrottlingRequestManager(
        inner=request_queue,
        domains=[hostname],
        request_manager_opener=RequestQueue.open,
        service_locator=service_locator,
    )

    concurrency_settings = ConcurrencySettings(
        min_concurrency=1,
        max_concurrency=max_concurrency,
        desired_concurrency=max_concurrency,
        max_tasks_per_minute=requests_per_minute,
    )

    return CrawleeRuntime(
        storage_client=storage_client,
        configuration=configuration,
        event_manager=event_manager,
        request_manager=request_manager,
        concurrency_settings=concurrency_settings,
        request_handler_timeout=timedelta(seconds=request_timeout_seconds),
    )
