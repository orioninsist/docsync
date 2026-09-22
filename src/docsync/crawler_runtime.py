"""Shared Crawlee runtime construction for DocsSync."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from crawlee import ConcurrencySettings, service_locator
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
    event_manager = LocalEventManager.from_config(configuration)

    # Crawlee's public global service locator is also consulted by components
    # such as ThrottlingRequestManager. Register the same runtime services
    # before those components are constructed.
    service_locator.set_configuration(configuration)
    service_locator.set_storage_client(storage_client)
    service_locator.set_event_manager(event_manager)
    request_queue = await RequestQueue.open(
        name="docsync-main",
        storage_client=storage_client,
        configuration=configuration,
    )

    async def open_throttled_queue(**kwargs: object) -> RequestQueue:
        """Open Crawlee's aliased throttle queue on this runtime's storage."""

        alias = kwargs.get("alias")
        if not isinstance(alias, str):
            raise TypeError("Throttled request queue alias must be a string.")

        return await RequestQueue.open(
            alias=alias,
            storage_client=storage_client,
            configuration=configuration,
        )

    request_manager = ThrottlingRequestManager(
        inner=request_queue,
        domains=[hostname],
        request_manager_opener=open_throttled_queue,
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
