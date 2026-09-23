"""Crawlee-native crawler construction for DocsSync."""

from __future__ import annotations

from typing import Any, cast

from crawlee.browsers import BrowserType
from crawlee.crawlers import AdaptivePlaywrightCrawler, PlaywrightCrawler

from docsync.crawler_runtime import CrawleeRuntime

DEFAULT_MAX_REQUEST_RETRIES = 2


def adaptive_result_is_meaningful(result: Any) -> bool:
    """Accept terminal static results while forcing empty content to Playwright."""

    for call in result.push_data_calls:
        data = call["data"]
        values = data if isinstance(data, list) else [data]
        for value in values:
            if isinstance(value, dict) and value.get("outcome") != "empty":
                return True
    return False


def _common_crawler_options(
    *,
    runtime: CrawleeRuntime,
    max_requests: int,
    respect_robots_txt: bool,
) -> dict[str, Any]:
    """Return shared Crawlee options for every crawler implementation."""

    return {
        "request_manager": runtime.request_manager,
        "storage_client": runtime.storage_client,
        "configuration": runtime.configuration,
        "event_manager": runtime.event_manager,
        "concurrency_settings": runtime.concurrency_settings,
        "max_request_retries": DEFAULT_MAX_REQUEST_RETRIES,
        "max_requests_per_crawl": max_requests,
        "request_handler_timeout": runtime.request_handler_timeout,
        "respect_robots_txt_file": respect_robots_txt,
    }


def build_adaptive_crawler(
    *,
    runtime: CrawleeRuntime,
    max_requests: int,
    respect_robots_txt: bool,
    headless: bool,
    browser_type: BrowserType,
) -> AdaptivePlaywrightCrawler:
    """Build Crawlee's native adaptive HTTP/Playwright crawler."""

    return AdaptivePlaywrightCrawler.with_beautifulsoup_static_parser(
        **_common_crawler_options(
            runtime=runtime,
            max_requests=max_requests,
            respect_robots_txt=respect_robots_txt,
        ),
        result_checker=adaptive_result_is_meaningful,
        playwright_crawler_specific_kwargs={
            "navigation_timeout": runtime.request_handler_timeout,
            "headless": headless,
            "browser_type": browser_type,
        },
    )


def build_playwright_crawler(
    *,
    runtime: CrawleeRuntime,
    max_requests: int,
    respect_robots_txt: bool,
    headless: bool,
    browser_type: BrowserType,
) -> PlaywrightCrawler:
    """Build Crawlee's native browser crawler."""

    return PlaywrightCrawler(
        **_common_crawler_options(
            runtime=runtime,
            max_requests=max_requests,
            respect_robots_txt=respect_robots_txt,
        ),
        navigation_timeout=runtime.request_handler_timeout,
        headless=headless,
        browser_type=browser_type,
    )


def build_crawler(
    *,
    mode: str,
    runtime: CrawleeRuntime,
    max_requests: int,
    respect_robots_txt: bool,
    headless: bool,
    browser_type: str,
) -> AdaptivePlaywrightCrawler | PlaywrightCrawler:
    """Build the canonical Crawlee crawler for the requested DocsSync mode."""

    resolved_browser_type = cast(BrowserType, browser_type)

    if mode == "http":
        return build_adaptive_crawler(
            runtime=runtime,
            max_requests=max_requests,
            respect_robots_txt=respect_robots_txt,
            headless=headless,
            browser_type=resolved_browser_type,
        )

    if mode == "playwright":
        return build_playwright_crawler(
            runtime=runtime,
            max_requests=max_requests,
            respect_robots_txt=respect_robots_txt,
            headless=headless,
            browser_type=resolved_browser_type,
        )

    raise ValueError("mode must be 'http' or 'playwright'.")
