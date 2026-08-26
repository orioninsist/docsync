"""Core Crawlee crawler implementation for docsync."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from re import Pattern
from typing import Any, Final, cast
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from crawlee.crawlers import (
    BasicCrawlingContext,
    BeautifulSoupCrawler,
    BeautifulSoupCrawlingContext,
    PlaywrightCrawler,
    PlaywrightCrawlingContext,
)

from docsync.config import Settings
from docsync.crawler_runtime import build_crawlee_runtime
from docsync.incremental import (
    content_is_unchanged,
    filter_incremental_urls,
    load_content_hashes,
    load_url_state,
    record_incremental_success,
    save_content_hashes,
    save_url_state,
)
from docsync.language import EnglishPageDetector
from docsync.language_strategy import LanguageStrategy
from docsync.markdown import MarkdownExporter
from docsync.metrics import CrawlStats, write_crawl_report
from docsync.playwright_rendering import (
    PlaywrightRenderingConfig,
    install_resource_blocking,
    render_page_html,
    render_url_html,
)
from docsync.progress_events import CrawlEvent, CrawlEventSink
from docsync.sitemap import discover_sitemap_urls
from docsync.url_security import (
    normalize_url,
    validated_http_url,
)


class _IncrementalRuntimeConfig:
    """Resolved incremental controls for one crawl execution."""

    def __init__(
        self,
        *,
        refresh_hours: int,
        force_refresh: bool,
    ) -> None:
        self.refresh_hours = refresh_hours
        self.force_refresh = force_refresh


def _silence_crawlee_runtime_logs() -> None:
    """Disable Crawlee internal terminal logging."""

    for logger_name in (
        "crawlee",
        "crawlee._autoscaling",
        "BeautifulSoupCrawler",
        "PlaywrightCrawler",
    ):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.setLevel(logging.WARNING)
        logger.propagate = False


DEFAULT_MAX_REQUEST_RETRIES: Final[int] = 2
DEFAULT_REQUEST_TIMEOUT_SECONDS: Final[int] = 60
DEFAULT_MAX_REQUESTS_PER_CRAWL: Final[int] = 100

EXCLUDED_URL_PATTERNS: Final[tuple[Pattern[str], ...]] = (
    re.compile(
        r"\.(?:"
        r"7z|avi|css|csv|doc|docx|gif|gz|ico|jpe?g|json|m4a|mov|"
        r"mp3|mp4|mpeg|mpg|pdf|png|ppt|pptx|rar|rss|svg|tar|tgz|"
        r"txt|wav|webm|webp|woff2?|xls|xlsx|xml|zip"
        r")(?:[?#].*)?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"/(?:login|signin|signup|cart|checkout)(?:/|$|[?#])",
        re.IGNORECASE,
    ),
)


def normalize_start_url(start_url: str) -> str:
    """Normalize and validate the starting URL."""

    validated: str = validated_http_url(start_url)
    normalized: str = normalize_url(validated)
    return normalized


def build_scope_pattern(start_url: str) -> Pattern[str]:
    """Build a regex restricted to the start URL origin and path tree."""
    parsed_url = urlsplit(normalize_start_url(start_url))
    origin = f"{parsed_url.scheme}://{parsed_url.netloc}"
    path = parsed_url.path

    if path == "/":
        scope_path = "/"
    elif path.endswith("/"):
        scope_path = path
    else:
        scope_path = path.rsplit("/", 1)[0] + "/"

    expression = rf"^{re.escape(origin)}{re.escape(scope_path)}"
    return re.compile(expression, re.IGNORECASE)


def extract_in_scope_links(
    *,
    soup: BeautifulSoup,
    base_url: str,
    scope_pattern: Pattern[str],
) -> list[str]:
    """Extract normalized, unique, crawlable links from one parsed DOM."""

    validated_base_url = validated_http_url(base_url)
    normalized_base_url = normalize_url(validated_base_url)
    discovered_urls: list[str] = []
    seen_urls: set[str] = set()

    for anchor in soup.select("a[href]"):
        href = anchor.get("href")

        if not isinstance(href, str) or not href.strip():
            continue

        try:
            candidate_url = normalize_url(
                urljoin(
                    validated_base_url,
                    href.strip(),
                )
            )
        except (TypeError, ValueError):
            continue

        if candidate_url == normalized_base_url:
            continue

        if scope_pattern.search(candidate_url) is None:
            continue

        if any(pattern.search(candidate_url) for pattern in EXCLUDED_URL_PATTERNS):
            continue

        if candidate_url in seen_urls:
            continue

        seen_urls.add(candidate_url)
        discovered_urls.append(candidate_url)

    return discovered_urls


async def run_crawler(
    start_url: str,
    output_dir: str | Path | None = None,
    state_dir: str | Path | None = None,
    max_concurrency: int | None = None,
    max_requests: int | None = None,
    language: str | None = None,
    refresh_hours: int | None = None,
    force_refresh: bool | None = None,
    mode: str | None = None,
    headless: bool | None = None,
    browser_type: str | None = None,
    event_sink: CrawlEventSink | None = None,
) -> CrawlStats:
    """Crawl HTML pages and synchronize Markdown output."""
    settings = Settings.from_environment()

    resolved_refresh_hours = (
        refresh_hours if refresh_hours is not None else settings.refresh_hours
    )
    resolved_force_refresh = (
        force_refresh if force_refresh is not None else settings.force_refresh
    )
    resolved_mode = mode.strip().lower() if mode is not None else settings.mode
    resolved_headless = headless if headless is not None else settings.headless
    resolved_browser_type = (
        browser_type.strip().lower()
        if browser_type is not None
        else settings.browser_type
    )

    if not 0 <= resolved_refresh_hours <= 8760:
        raise ValueError("refresh_hours must be between 0 and 8760.")

    mode_aliases = {
        "browser": "playwright",
        "javascript": "playwright",
        "js": "playwright",
    }
    resolved_mode = mode_aliases.get(
        resolved_mode,
        resolved_mode,
    )

    if resolved_mode not in {
        "http",
        "playwright",
    }:
        raise ValueError("mode must be 'http' or 'playwright'.")

    if resolved_browser_type not in {
        "chromium",
        "firefox",
        "webkit",
    }:
        raise ValueError("browser_type must be chromium, firefox, or webkit.")

    _ = resolved_force_refresh

    resolved_output_dir = (
        Path(output_dir).expanduser().resolve()
        if output_dir is not None
        else settings.output_dir.resolve()
    )
    resolved_state_dir = (
        Path(state_dir).expanduser().resolve()
        if state_dir is not None
        else settings.state_dir.resolve()
    )
    resolved_max_concurrency = (
        max_concurrency if max_concurrency is not None else settings.max_concurrency
    )
    resolved_max_requests = (
        max_requests if max_requests is not None else settings.max_requests
    )
    resolved_language = (
        language.strip().lower() if language is not None else settings.language
    )

    if resolved_max_concurrency <= 0:
        raise ValueError("max_concurrency must be greater than zero")

    if resolved_max_requests <= 0:
        raise ValueError("max_requests must be greater than zero")

    if resolved_language not in {"en", "tr"}:
        raise ValueError("language must be 'en' or 'tr'.")

    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    resolved_state_dir.mkdir(parents=True, exist_ok=True)

    stats = CrawlStats(mode=resolved_mode)

    def record_non_english_page() -> None:
        """Record one successfully handled non-English page."""

        stats.non_english = stats.non_english + 1
        stats.processed = stats.processed + 1

    def emit_event(
        *,
        phase: str | None = None,
        current_url: str | None = None,
        current_title: str | None = None,
        queued: int | None = None,
        discovered: int | None = None,
        active_requests: int | None = None,
        site_title: str | None = None,
    ) -> None:
        if event_sink is None:
            return

        event_sink(
            CrawlEvent(
                phase=phase,
                current_url=current_url,
                current_title=current_title,
                processed=stats.processed,
                saved=stats.saved,
                duplicate_content=stats.duplicate_content,
                incremental_skipped=stats.incremental_skipped,
                rejected_urls=stats.rejected_urls,
                empty_pages=stats.empty_pages,
                non_english=stats.non_english,
                failed=stats.failed,
                queued=queued,
                discovered=discovered,
                active_requests=active_requests,
                sitemap_urls=stats.sitemap_urls,
                sitemap_files_checked=stats.sitemap_files_checked,
                sitemap_files_found=stats.sitemap_files_found,
                sitemap_errors=stats.sitemap_errors,
                site_title=site_title,
            )
        )

    emit_event(
        phase="Loading state",
        active_requests=0,
    )

    content_hashes = load_content_hashes(resolved_state_dir)
    url_state = load_url_state(resolved_state_dir)

    markdown_exporter = MarkdownExporter(resolved_output_dir)
    language_detector = EnglishPageDetector()
    language_strategy = LanguageStrategy(settings.language)

    normalized_start_url = normalize_start_url(start_url)

    if language_strategy.should_skip_url(normalized_start_url):
        raise ValueError("The start URL language does not match requested language.")
    scope_pattern = build_scope_pattern(normalized_start_url)

    start_hostname = urlsplit(normalized_start_url).hostname

    if not start_hostname:
        raise ValueError(
            f"Unable to determine hostname from start URL: {normalized_start_url}"
        )

    runtime = await build_crawlee_runtime(
        hostname=start_hostname,
        max_concurrency=resolved_max_concurrency,
        requests_per_minute=settings.requests_per_minute,
        request_timeout_seconds=settings.request_timeout_seconds,
    )

    crawler_storage_client = runtime.storage_client
    request_manager = runtime.request_manager
    concurrency_settings = runtime.concurrency_settings
    request_handler_timeout = runtime.request_handler_timeout

    _silence_crawlee_runtime_logs()

    rendering_config: PlaywrightRenderingConfig | None = None
    crawler: Any

    if resolved_mode == "playwright":
        rendering_config = PlaywrightRenderingConfig(
            headless=resolved_headless,
            browser_type=resolved_browser_type,
            request_timeout_seconds=settings.request_timeout_seconds,
        )
        crawler = PlaywrightCrawler(
            request_manager=request_manager,
            storage_client=crawler_storage_client,
            concurrency_settings=concurrency_settings,
            max_request_retries=DEFAULT_MAX_REQUEST_RETRIES,
            max_requests_per_crawl=resolved_max_requests,
            request_handler_timeout=request_handler_timeout,
            navigation_timeout=request_handler_timeout,
            respect_robots_txt_file=settings.respect_robots_txt,
            **rendering_config.crawler_options(),
        )

        async def install_browser_controls(
            context: Any,
        ) -> None:
            await install_resource_blocking(
                context.page,
                blocked_resource_types=rendering_config.blocked_resource_types,
            )

        crawler.pre_navigation_hook(install_browser_controls)
    else:
        crawler = BeautifulSoupCrawler(
            request_manager=request_manager,
            storage_client=crawler_storage_client,
            concurrency_settings=concurrency_settings,
            max_request_retries=DEFAULT_MAX_REQUEST_RETRIES,
            max_requests_per_crawl=resolved_max_requests,
            request_handler_timeout=request_handler_timeout,
            respect_robots_txt_file=settings.respect_robots_txt,
        )

    active_requests = 0

    @crawler.router.default_handler
    async def request_handler(
        context: BeautifulSoupCrawlingContext | PlaywrightCrawlingContext,
    ) -> None:
        nonlocal active_requests

        try:
            active_requests += 1
            emit_event(
                phase="Downloading",
                current_url=context.request.url,
                active_requests=active_requests,
            )

            used_browser_fallback = False

            if resolved_mode == "playwright":
                playwright_context = cast(Any, context)
                html = await render_page_html(
                    playwright_context.page,
                    url=playwright_context.request.url,
                    logger=playwright_context.log,
                    request_timeout_seconds=settings.request_timeout_seconds,
                    network_idle_timeout_milliseconds=(
                        rendering_config.network_idle_timeout_milliseconds
                        if rendering_config is not None
                        else 10_000
                    ),
                )
                soup = BeautifulSoup(
                    html,
                    "lxml",
                )
                effective_url = str(playwright_context.page.url)
            else:
                http_context = cast(Any, context)
                soup = http_context.soup
                html = str(soup)
                effective_url = str(
                    getattr(
                        context.request,
                        "loaded_url",
                        None,
                    )
                    or context.request.url
                )

            discovered_urls = extract_in_scope_links(
                soup=soup,
                base_url=effective_url,
                scope_pattern=scope_pattern,
            )

            discovered_urls = [
                url
                for url in discovered_urls
                if not language_strategy.should_skip_url(url)
            ]

            if discovered_urls:
                queue_context = cast(
                    Any,
                    context,
                )
                await queue_context.add_requests(
                    discovered_urls,
                )

            discovered_link_count = len(discovered_urls)

            language_decision = language_detector.detect_from_html(
                url=effective_url,
                html=html,
            )

            if not language_strategy.accepts(
                language_decision
            ) and language_decision.source not in {
                "insufficient-text",
                "language-detector-no-result",
            }:
                record_non_english_page()
                context.log.info(
                    "Non-English page skipped after discovery: "
                    "url=%s source=%s language=%s discovered_links=%s",
                    effective_url,
                    language_decision.source,
                    language_decision.language_code or "unknown",
                    discovered_link_count,
                )
                return

            title_element = soup.title
            title = (
                title_element.get_text(
                    " ",
                    strip=True,
                )
                if title_element is not None
                else ""
            )

            emit_event(
                phase="Extracting",
                current_url=context.request.url,
                current_title=title,
                active_requests=active_requests,
                site_title=(title if stats.processed == 0 and title else None),
            )

            try:
                document = markdown_exporter.export(
                    url=context.request.url,
                    soup=soup,
                    title=title,
                    language=resolved_language,
                    write=False,
                )
            except ValueError as error:
                empty_markdown_error = str(error).startswith(
                    "No meaningful Markdown content found:"
                )

                if (
                    empty_markdown_error
                    and discovered_link_count > 0
                    and resolved_mode == "playwright"
                ):
                    stats.empty_pages += 1
                    stats.processed += 1

                    context.log.info(
                        "Discovery-only page processed: "
                        "url=%s discovered_links=%s renderer=playwright",
                        context.request.url,
                        discovered_link_count,
                    )
                    return

                if resolved_mode != "http" or not empty_markdown_error:
                    raise

                context.log.warning(
                    "HTTP extraction returned no meaningful content; "
                    "retrying with Playwright: %s",
                    context.request.url,
                )

                fallback_config = PlaywrightRenderingConfig(
                    headless=resolved_headless,
                    browser_type=resolved_browser_type,
                    request_timeout_seconds=settings.request_timeout_seconds,
                )

                fallback_html = await render_url_html(
                    context.request.url,
                    headless=fallback_config.headless,
                    browser_type=fallback_config.browser_type,
                    request_timeout_seconds=(fallback_config.request_timeout_seconds),
                    network_idle_timeout_milliseconds=(
                        fallback_config.network_idle_timeout_milliseconds
                    ),
                    blocked_resource_types=(fallback_config.blocked_resource_types),
                    browser_arguments=(fallback_config.browser_arguments),
                )

                soup = BeautifulSoup(
                    fallback_html,
                    "lxml",
                )
                used_browser_fallback = True

                fallback_urls = extract_in_scope_links(
                    soup=soup,
                    base_url=effective_url,
                    scope_pattern=scope_pattern,
                )

                fallback_urls = [
                    url
                    for url in fallback_urls
                    if not language_strategy.should_skip_url(url)
                ]

                if fallback_urls:
                    fallback_context = cast(
                        Any,
                        context,
                    )
                    await fallback_context.add_requests(
                        fallback_urls,
                    )

                discovered_link_count = len(fallback_urls)

                fallback_language_decision = language_detector.detect_from_html(
                    url=context.request.url,
                    html=fallback_html,
                )

                if not language_strategy.accepts(
                    fallback_language_decision
                ) and fallback_language_decision.source not in {
                    "insufficient-text",
                    "language-detector-no-result",
                }:
                    record_non_english_page()
                    context.log.info(
                        "Non-English fallback page skipped after discovery: "
                        "url=%s source=%s language=%s discovered_links=%s",
                        context.request.url,
                        fallback_language_decision.source,
                        fallback_language_decision.language_code or "unknown",
                        discovered_link_count,
                    )
                    return

                title_element = soup.title
                title = (
                    title_element.get_text(
                        " ",
                        strip=True,
                    )
                    if title_element is not None
                    else ""
                )

                try:
                    document = markdown_exporter.export(
                        url=context.request.url,
                        soup=soup,
                        title=title,
                        language=resolved_language,
                        write=False,
                    )
                except ValueError as fallback_error:
                    fallback_empty_error = str(fallback_error).startswith(
                        "No meaningful Markdown content found:"
                    )

                    if fallback_empty_error and discovered_link_count > 0:
                        stats.empty_pages += 1
                        stats.processed += 1

                        context.log.info(
                            "Discovery-only page processed: "
                            "url=%s discovered_links=%s "
                            "renderer=playwright-fallback",
                            context.request.url,
                            discovered_link_count,
                        )
                        return

                    raise

            unchanged = content_is_unchanged(
                url=document.url,
                digest=document.content_hash,
                url_state=url_state,
            )

            if not unchanged:
                markdown_exporter.write(document)
                stats.saved += 1

            context.log.info(
                "Page synchronized: url=%s title=%s output=%s",
                document.url,
                document.title or "<no title>",
                document.output_path,
            )

            await context.push_data(
                {
                    "url": document.url,
                    "title": document.title,
                    "language": document.language,
                    "output_path": str(document.output_path),
                    "content_hash": document.content_hash,
                    "browser_fallback": used_browser_fallback,
                }
            )

            record_incremental_success(
                url=document.url,
                output_path=document.output_path,
                digest=document.content_hash,
                hashes=content_hashes,
                url_state=url_state,
            )

            stats.processed += 1
        finally:
            active_requests = max(
                0,
                active_requests - 1,
            )
            emit_event(
                phase="Crawling",
                current_url=context.request.url,
                active_requests=active_requests,
            )

    emit_event(
        phase="Discovering sitemaps",
        active_requests=0,
    )

    sitemap_result = await discover_sitemap_urls(
        start_url=normalized_start_url,
        timeout_seconds=settings.request_timeout_seconds,
        max_urls=resolved_max_requests,
    )

    initial_urls = list(
        dict.fromkeys(
            url
            for url in [
                normalized_start_url,
                *sitemap_result.urls,
            ]
            if not language_strategy.should_skip_url(url)
        )
    )

    stats.sitemap_urls = len(sitemap_result.urls)
    stats.sitemap_files_checked = sitemap_result.sitemap_files_checked
    stats.sitemap_files_found = sitemap_result.sitemap_files_found
    stats.sitemap_errors = len(sitemap_result.errors)

    emit_event(
        phase="Preparing queue",
        discovered=len(initial_urls),
        queued=len(initial_urls),
        active_requests=0,
    )

    if sitemap_result.errors:
        for sitemap_error in sitemap_result.errors:
            crawler.log.debug(
                "Sitemap discovery error: %s",
                sitemap_error,
            )

    incremental_config = _IncrementalRuntimeConfig(
        refresh_hours=resolved_refresh_hours,
        force_refresh=resolved_force_refresh,
    )
    incremental_urls = filter_incremental_urls(
        initial_urls,
        config=incremental_config,
        stats=stats,
        url_state=url_state,
    )

    emit_event(
        phase="Ready",
        discovered=len(initial_urls),
        queued=len(incremental_urls),
        active_requests=0,
    )

    report_configuration = {
        "start_url": normalized_start_url,
        "output_dir": resolved_output_dir,
        "state_dir": resolved_state_dir,
        "max_concurrency": resolved_max_concurrency,
        "max_requests": resolved_max_requests,
        "language": resolved_language,
        "refresh_hours": resolved_refresh_hours,
        "force_refresh": resolved_force_refresh,
        "requests_per_minute": settings.requests_per_minute,
        "request_timeout_seconds": settings.request_timeout_seconds,
        "mode": resolved_mode,
        "headless": resolved_headless,
        "browser_type": resolved_browser_type,
        "request_manager": "ThrottlingRequestManager",
        "request_storage": "MemoryStorageClient",
        "throttled_domains": [start_hostname],
    }

    def finalize_crawl() -> None:
        save_content_hashes(
            content_hashes,
            resolved_state_dir,
        )
        save_url_state(
            url_state,
            resolved_state_dir,
        )
        write_crawl_report(
            output_dir=resolved_output_dir,
            stats=stats,
            configuration=report_configuration,
        )

    if not incremental_urls:
        emit_event(
            phase="Nothing to crawl",
            queued=0,
            discovered=len(initial_urls),
            active_requests=0,
        )
        finalize_crawl()
        return stats

    @crawler.failed_request_handler
    async def failed_handler(
        context: BeautifulSoupCrawlingContext | BasicCrawlingContext,
        error: Exception,
    ) -> None:
        nonlocal active_requests

        stats.failed += 1
        active_requests = max(
            0,
            active_requests - 1,
        )

        emit_event(
            phase="Request failed",
            current_url=context.request.url,
            active_requests=active_requests,
        )

        context.log.error(
            "Request permanently failed: url=%s error=%s",
            context.request.url,
            error,
        )

    emit_event(
        phase="Crawling",
        queued=len(incremental_urls),
        discovered=len(initial_urls),
        active_requests=0,
    )

    await crawler.run(incremental_urls)

    emit_event(
        phase="Finalizing",
        queued=0,
        discovered=len(initial_urls),
        active_requests=0,
    )

    finalize_crawl()
    return stats
