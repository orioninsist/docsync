"""Shared Crawlee construction for DocsSync crawl workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from crawlee.crawlers import BeautifulSoupCrawler, PlaywrightCrawler
from crawlee.http_clients import HttpClient

from docsync.crawler_runtime import CrawleeRuntime
from docsync.playwright_rendering import (
    PlaywrightRenderingConfig,
    install_resource_blocking,
)

DEFAULT_MAX_REQUEST_RETRIES = 2


@dataclass(slots=True)
class CrawlerBuildResult:
    """Crawler plus optional Playwright rendering configuration."""

    crawler: Any
    rendering_config: PlaywrightRenderingConfig | None = None


def build_http_crawler(
    *,
    runtime: CrawleeRuntime,
    max_requests: int,
    respect_robots_txt: bool,
    http_client: HttpClient | None = None,
) -> BeautifulSoupCrawler:
    """Build the canonical HTTP crawler from one shared runtime."""

    crawler_options: dict[str, Any] = {
        "request_manager": runtime.request_manager,
        "storage_client": runtime.storage_client,
        "configuration": runtime.configuration,
        "event_manager": runtime.service_locator.get_event_manager(),
        "concurrency_settings": runtime.concurrency_settings,
        "max_request_retries": DEFAULT_MAX_REQUEST_RETRIES,
        "max_requests_per_crawl": max_requests,
        "request_handler_timeout": runtime.request_handler_timeout,
        "respect_robots_txt_file": respect_robots_txt,
    }
    if http_client is not None:
        crawler_options["http_client"] = http_client

    return BeautifulSoupCrawler(**crawler_options)


def build_playwright_crawler(
    *,
    runtime: CrawleeRuntime,
    max_requests: int,
    respect_robots_txt: bool,
    rendering_config: PlaywrightRenderingConfig,
) -> PlaywrightCrawler:
    """Build the canonical browser crawler from one shared runtime."""

    crawler = PlaywrightCrawler(
        request_manager=runtime.request_manager,
        storage_client=runtime.storage_client,
        configuration=runtime.configuration,
        event_manager=runtime.service_locator.get_event_manager(),
        concurrency_settings=runtime.concurrency_settings,
        max_request_retries=DEFAULT_MAX_REQUEST_RETRIES,
        max_requests_per_crawl=max_requests,
        request_handler_timeout=runtime.request_handler_timeout,
        navigation_timeout=runtime.request_handler_timeout,
        respect_robots_txt_file=respect_robots_txt,
        **rendering_config.crawler_options(),
    )

    async def install_browser_controls(context: Any) -> None:
        await install_resource_blocking(
            context.page,
            blocked_resource_types=rendering_config.blocked_resource_types,
        )

    crawler.pre_navigation_hook(install_browser_controls)
    return crawler


def build_crawler(
    *,
    mode: str,
    runtime: CrawleeRuntime,
    max_requests: int,
    respect_robots_txt: bool,
    headless: bool,
    browser_type: str,
    request_timeout_seconds: int,
    http_client: HttpClient | None = None,
) -> CrawlerBuildResult:
    """Build the canonical crawler for an HTTP or Playwright workflow."""

    if mode == "playwright":
        rendering_config = PlaywrightRenderingConfig(
            headless=headless,
            browser_type=browser_type,
            request_timeout_seconds=request_timeout_seconds,
        )
        return CrawlerBuildResult(
            crawler=build_playwright_crawler(
                runtime=runtime,
                max_requests=max_requests,
                respect_robots_txt=respect_robots_txt,
                rendering_config=rendering_config,
            ),
            rendering_config=rendering_config,
        )

    if mode == "http":
        return CrawlerBuildResult(
            crawler=build_http_crawler(
                runtime=runtime,
                max_requests=max_requests,
                respect_robots_txt=respect_robots_txt,
                http_client=http_client,
            )
        )

    raise ValueError("mode must be 'http' or 'playwright'.")
