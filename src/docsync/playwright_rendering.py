"""Canonical Playwright rendering and browser resource controls."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Protocol

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
