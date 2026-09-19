"""Canonical Playwright rendering and browser resource controls."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Final, Protocol, cast

BLOCKED_RESOURCE_TYPES: Final[frozenset[str]] = frozenset(
    {
        "font",
        "image",
        "media",
        "websocket",
    }
)

DEFAULT_NETWORK_IDLE_TIMEOUT_MILLISECONDS: Final[int] = 10_000

DEFAULT_BROWSER_ARGUMENTS: Final[tuple[str, ...]] = (
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-extensions",
    "--disable-sync",
    "--no-first-run",
)

type RouteHandler = Callable[["RouteLike"], Awaitable[None]]


class RequestLike(Protocol):
    """Minimal Playwright request contract required for routing."""

    @property
    def resource_type(self) -> str:
        """Return the Playwright resource type."""


class RouteLike(Protocol):
    """Minimal Playwright route contract required for resource blocking."""

    @property
    def request(self) -> RequestLike:
        """Return the routed request."""

    async def abort(self) -> None:
        """Abort the routed request."""

    async def continue_(self) -> None:
        """Continue the routed request."""


class PageLike(Protocol):
    """Minimal Playwright page contract required by docsync."""

    async def route(
        self,
        url: str,
        handler: RouteHandler,
    ) -> None:
        """Register a route handler."""

    async def wait_for_load_state(
        self,
        state: str,
        *,
        timeout: float | None = None,
    ) -> None:
        """Wait for a browser load state."""

    async def content(self) -> str:
        """Return the rendered HTML document."""


class LoggerLike(Protocol):
    """Minimal logger contract used for non-fatal render diagnostics."""

    def debug(
        self,
        message: str,
        *args: object,
    ) -> None:
        """Log a debug message."""


@dataclass(frozen=True, slots=True)
class PlaywrightRenderingConfig:
    """Validated browser rendering configuration."""

    headless: bool = True
    browser_type: str = "chromium"
    request_timeout_seconds: int = 60
    network_idle_timeout_milliseconds: int = DEFAULT_NETWORK_IDLE_TIMEOUT_MILLISECONDS
    blocked_resource_types: frozenset[str] = BLOCKED_RESOURCE_TYPES
    browser_arguments: tuple[str, ...] = DEFAULT_BROWSER_ARGUMENTS

    def __post_init__(self) -> None:
        normalized_browser_type = self.browser_type.strip().lower()

        if normalized_browser_type not in {
            "chromium",
            "firefox",
            "webkit",
        }:
            raise ValueError("browser_type must be chromium, firefox, or webkit")

        if self.request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be greater than zero")

        if self.network_idle_timeout_milliseconds <= 0:
            raise ValueError(
                "network_idle_timeout_milliseconds must be greater than zero"
            )

        normalized_resource_types = frozenset(
            resource_type.strip().lower()
            for resource_type in self.blocked_resource_types
            if resource_type.strip()
        )

        normalized_arguments = tuple(
            argument.strip() for argument in self.browser_arguments if argument.strip()
        )

        object.__setattr__(
            self,
            "browser_type",
            normalized_browser_type,
        )
        object.__setattr__(
            self,
            "blocked_resource_types",
            normalized_resource_types,
        )
        object.__setattr__(
            self,
            "browser_arguments",
            normalized_arguments,
        )

    @property
    def browser_launch_options(self) -> dict[str, list[str]]:
        """Return Crawlee-compatible browser launch options."""

        return {
            "args": list(self.browser_arguments),
        }

    def crawler_options(self) -> dict[str, Any]:
        """Return the browser-specific PlaywrightCrawler options."""

        return {
            "headless": self.headless,
            "browser_type": self.browser_type,
            "browser_launch_options": self.browser_launch_options,
        }

    def report_configuration(self) -> dict[str, Any]:
        """Return stable JSON-compatible browser configuration."""

        return {
            "headless": self.headless,
            "browser_type": self.browser_type,
            "request_timeout_seconds": self.request_timeout_seconds,
            "network_idle_timeout_milliseconds": (
                self.network_idle_timeout_milliseconds
            ),
            "blocked_resource_types": sorted(self.blocked_resource_types),
            "browser_arguments": list(self.browser_arguments),
        }


def should_block_resource(
    resource_type: str,
    *,
    blocked_resource_types: frozenset[str] = BLOCKED_RESOURCE_TYPES,
) -> bool:
    """Return whether one Playwright resource type should be blocked."""

    normalized = resource_type.strip().lower()

    return bool(normalized) and normalized in blocked_resource_types


async def handle_route(
    route: RouteLike,
    *,
    blocked_resource_types: frozenset[str] = BLOCKED_RESOURCE_TYPES,
) -> None:
    """Abort blocked browser resources and continue all others."""

    if should_block_resource(
        route.request.resource_type,
        blocked_resource_types=blocked_resource_types,
    ):
        await route.abort()
        return

    await route.continue_()


async def install_resource_blocking(
    page: PageLike,
    *,
    blocked_resource_types: frozenset[str] = BLOCKED_RESOURCE_TYPES,
) -> None:
    """Install the canonical all-request Playwright route handler."""

    async def route_handler(route: RouteLike) -> None:
        await handle_route(
            route,
            blocked_resource_types=blocked_resource_types,
        )

    await page.route(
        "**/*",
        route_handler,
    )


async def render_page_html(
    page: PageLike,
    *,
    url: str,
    logger: LoggerLike,
    request_timeout_seconds: int,
    network_idle_timeout_milliseconds: int = (
        DEFAULT_NETWORK_IDLE_TIMEOUT_MILLISECONDS
    ),
) -> str:
    """Wait for JavaScript rendering and return the final HTML."""

    if request_timeout_seconds <= 0:
        raise ValueError("request_timeout_seconds must be greater than zero")

    if network_idle_timeout_milliseconds <= 0:
        raise ValueError("network_idle_timeout_milliseconds must be greater than zero")

    await page.wait_for_load_state(
        "domcontentloaded",
        timeout=request_timeout_seconds * 1000,
    )

    try:
        await page.wait_for_load_state(
            "networkidle",
            timeout=network_idle_timeout_milliseconds,
        )
    except Exception as error:
        logger.debug(
            "Network did not become idle: url=%s error=%s",
            url,
            error,
        )

    return await page.content()


def merge_playwright_options(
    *,
    base_options: Mapping[str, Any],
    rendering_config: PlaywrightRenderingConfig,
) -> dict[str, Any]:
    """Merge generic crawler options with browser rendering options."""

    merged = dict(base_options)
    merged.update(rendering_config.crawler_options())
    return merged


def normalized_blocked_resource_types(
    values: Sequence[str],
) -> frozenset[str]:
    """Normalize a user-provided resource-blocking sequence."""

    return frozenset(value.strip().lower() for value in values if value.strip())


class PlaywrightFallbackRenderer:
    """Crawl-scoped Playwright fallback renderer with one persistent crawler."""

    def __init__(
        self,
        *,
        headless: bool,
        browser_type: str,
        request_timeout_seconds: int,
        network_idle_timeout_milliseconds: int = (
            DEFAULT_NETWORK_IDLE_TIMEOUT_MILLISECONDS
        ),
        blocked_resource_types: frozenset[str] = BLOCKED_RESOURCE_TYPES,
        browser_arguments: tuple[str, ...] = DEFAULT_BROWSER_ARGUMENTS,
    ) -> None:
        self._config = PlaywrightRenderingConfig(
            headless=headless,
            browser_type=browser_type,
            request_timeout_seconds=request_timeout_seconds,
            network_idle_timeout_milliseconds=network_idle_timeout_milliseconds,
            blocked_resource_types=blocked_resource_types,
            browser_arguments=browser_arguments,
        )
        self._crawler: Any | None = None
        self._crawler_task: asyncio.Task[None] | None = None
        self._pending: dict[str, asyncio.Future[tuple[str, list[str]]]] = {}
        self._request_sequence = 0

    async def _start(self) -> None:
        if self._crawler_task is not None:
            return

        from crawlee.crawlers import (
            PlaywrightCrawler,
            PlaywrightCrawlingContext,
            PlaywrightPreNavCrawlingContext,
        )
        from crawlee.storage_clients import MemoryStorageClient
        from crawlee.storages import RequestQueue

        storage_client = MemoryStorageClient()
        request_queue = await RequestQueue.open(
            alias=None,
            storage_client=storage_client,
        )
        crawler = PlaywrightCrawler(
            request_manager=request_queue,
            storage_client=storage_client,
            keep_alive=True,
            max_request_retries=0,
            request_handler_timeout=timedelta(
                seconds=self._config.request_timeout_seconds
            ),
            navigation_timeout=timedelta(seconds=self._config.request_timeout_seconds),
            **self._config.crawler_options(),
        )

        @crawler.pre_navigation_hook
        async def install_browser_controls(
            context: PlaywrightPreNavCrawlingContext,
        ) -> None:
            await install_resource_blocking(
                cast(PageLike, context.page),
                blocked_resource_types=self._config.blocked_resource_types,
            )

        @crawler.router.default_handler
        async def capture_html(context: PlaywrightCrawlingContext) -> None:
            html = await render_page_html(
                cast(PageLike, context.page),
                url=context.request.url,
                logger=context.log,
                request_timeout_seconds=self._config.request_timeout_seconds,
                network_idle_timeout_milliseconds=(
                    self._config.network_idle_timeout_milliseconds
                ),
            )
            extracted_requests = await context.extract_links(
                selector="a",
                attribute="href",
                base_url=str(context.page.url),
                strategy="all",
            )
            future = self._pending.get(context.request.unique_key)
            if future is not None and not future.done():
                future.set_result(
                    (html, [request.url for request in extracted_requests])
                )

        @crawler.failed_request_handler
        async def capture_failure(
            context: PlaywrightCrawlingContext,
            error: Exception,
        ) -> None:
            future = self._pending.get(context.request.unique_key)
            if future is not None and not future.done():
                future.set_exception(error)

        self._crawler = crawler
        self._crawler_task = asyncio.create_task(crawler.run())
        await asyncio.sleep(0)

    async def render(self, url: str) -> tuple[str, list[str]]:
        """Render one URL through the crawl-scoped persistent crawler."""

        from crawlee import Request

        await self._start()
        assert self._crawler is not None

        self._request_sequence += 1
        unique_key = (
            f"{url}#docsync-fallback-{id(self)}-{self._request_sequence}"
        )
        future = asyncio.get_running_loop().create_future()
        self._pending[unique_key] = future
        request = Request.from_url(url, unique_key=unique_key)

        try:
            await self._crawler.add_requests([request])
            return await future
        finally:
            self._pending.pop(unique_key, None)

    async def close(self) -> None:
        """Stop the persistent crawler and close its BrowserPool."""

        if self._crawler_task is None:
            return

        assert self._crawler is not None
        self._crawler.stop("DocsSync fallback renderer lifecycle completed.")
        await self._crawler_task
        self._crawler_task = None
        self._crawler = None

    async def __aenter__(self) -> PlaywrightFallbackRenderer:
        await self._start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object | None,
    ) -> None:
        await self.close()


async def render_url_with_crawlee(
    url: str,
    *,
    headless: bool,
    browser_type: str,
    request_timeout_seconds: int,
    network_idle_timeout_milliseconds: int = (
        DEFAULT_NETWORK_IDLE_TIMEOUT_MILLISECONDS
    ),
    blocked_resource_types: frozenset[str] = BLOCKED_RESOURCE_TYPES,
    browser_arguments: tuple[str, ...] = DEFAULT_BROWSER_ARGUMENTS,
) -> tuple[str, list[str]]:
    """Render one URL through the reusable fallback renderer API."""

    renderer = PlaywrightFallbackRenderer(
        headless=headless,
        browser_type=browser_type,
        request_timeout_seconds=request_timeout_seconds,
        network_idle_timeout_milliseconds=network_idle_timeout_milliseconds,
        blocked_resource_types=blocked_resource_types,
        browser_arguments=browser_arguments,
    )
    try:
        return await renderer.render(url)
    finally:
        await renderer.close()
