"""Core Crawlee crawler implementation for docsync."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from re import Pattern
from typing import Any, Final, cast
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from crawlee import HttpHeaders, RequestOptions
from crawlee.crawlers import (
    AdaptivePlaywrightCrawlingContext,
    BasicCrawlingContext,
    BeautifulSoupCrawlingContext,
    PlaywrightCrawlingContext,
)
from crawlee.errors import ContextPipelineInterruptedError
from crawlee.http_clients import ImpitHttpClient

from docsync.config import Settings
from docsync.crawl_engine import build_crawler
from docsync.crawler_runtime import build_crawlee_runtime
from docsync.incremental import (
    conditional_request_headers,
    content_is_unchanged,
    filter_incremental_urls,
    load_url_state,
    record_incremental_skip,
    record_incremental_success,
    response_validators,
    save_url_state,
)
from docsync.language import EnglishPageDetector, LanguagePolicy
from docsync.markdown import MarkdownDocument, MarkdownExporter
from docsync.metrics import CrawlStats, write_crawl_report
from docsync.progress_events import CrawlEvent, CrawlEventSink
from docsync.sitemap import build_sitemap_request_loader
from docsync.url_security import (
    normalize_url,
    validated_http_url,
)


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
        expression = rf"^{re.escape(origin)}/"
    elif path.endswith("/"):
        expression = rf"^{re.escape(origin)}{re.escape(path)}"
    else:
        expression = (
            rf"^{re.escape(origin)}"
            rf"{re.escape(path)}"
            rf"(?:/|$)"
        )

    return re.compile(expression, re.IGNORECASE)


def filter_discovered_urls(
    *,
    urls: list[str],
    base_url: str,
    scope_pattern: Pattern[str],
    should_skip_url: Any,
) -> list[str]:
    """Apply DocsSync URL policy consistently to discovered links."""

    normalized_base_url = normalize_url(validated_http_url(base_url))
    discovered_urls: list[str] = []
    seen_urls: set[str] = set()

    for url in urls:
        try:
            candidate_url = normalize_url(validated_http_url(url))
        except (TypeError, ValueError):
            continue

        if candidate_url == normalized_base_url:
            continue
        if scope_pattern.search(candidate_url) is None:
            continue
        if any(pattern.search(candidate_url) for pattern in EXCLUDED_URL_PATTERNS):
            continue
        if should_skip_url(candidate_url):
            continue
        if candidate_url in seen_urls:
            continue

        seen_urls.add(candidate_url)
        discovered_urls.append(candidate_url)

    return discovered_urls


async def discover_and_enqueue_in_scope_links(
    *,
    context: Any,
    base_url: str,
    scope_pattern: Pattern[str],
    should_skip_url: Any,
) -> list[str]:
    """Use Crawlee to extract and enqueue links while DocsSync owns URL policy."""

    extracted_requests = await context.extract_links(
        selector="a",
        attribute="href",
        base_url=base_url,
        strategy="all",
    )
    discovered_urls = filter_discovered_urls(
        urls=[request.url for request in extracted_requests],
        base_url=base_url,
        scope_pattern=scope_pattern,
        should_skip_url=should_skip_url,
    )

    if discovered_urls:
        await context.enqueue_links(
            requests=discovered_urls,
            strategy="all",
        )

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
                incremental_skipped=stats.incremental_skipped,
                rejected_urls=stats.rejected_urls,
                empty_pages=stats.empty_pages,
                non_english=stats.non_english,
                failed=stats.failed,
                queued=queued,
                discovered=discovered,
                active_requests=active_requests,
                sitemap_urls=stats.sitemap_urls,
                site_title=site_title,
            )
        )

    normalized_start_url = normalize_start_url(start_url)
    start_hostname = urlsplit(normalized_start_url).hostname

    if not start_hostname:
        raise ValueError(
            f"Unable to determine hostname from start URL: {normalized_start_url}"
        )

    emit_event(
        phase="Loading state",
        active_requests=0,
    )

    url_state = load_url_state(
        resolved_state_dir,
        start_hostname,
    )

    markdown_exporter = MarkdownExporter(resolved_output_dir)
    language_detector = EnglishPageDetector()
    language_strategy = LanguagePolicy(resolved_language)

    if language_strategy.should_skip_url(normalized_start_url):
        raise ValueError("The start URL language does not match requested language.")
    scope_pattern = build_scope_pattern(normalized_start_url)

    runtime = await build_crawlee_runtime(
        hostname=start_hostname,
        storage_dir=resolved_state_dir / "crawlee" / "crawl" / start_hostname,
        max_concurrency=resolved_max_concurrency,
        requests_per_minute=settings.requests_per_minute,
        request_timeout_seconds=settings.request_timeout_seconds,
    )

    def transform_sitemap_request(options: RequestOptions) -> RequestOptions | str:
        url = normalize_url(validated_http_url(options["url"]))
        if (
            scope_pattern.search(url) is None
            or language_strategy.should_skip_url(url)
            or any(pattern.search(url) for pattern in EXCLUDED_URL_PATTERNS)
        ):
            return "skip"

        if not filter_incremental_urls(
            [url],
            refresh_hours=resolved_refresh_hours,
            force_refresh=resolved_force_refresh,
            stats=stats,
            url_state=url_state,
        ):
            return "skip"

        options["url"] = url
        return options

    sitemap_http_client = ImpitHttpClient()
    sitemap_loader = build_sitemap_request_loader(
        start_url=normalized_start_url,
        http_client=sitemap_http_client,
        transform_request_function=transform_sitemap_request,
    )

    _silence_crawlee_runtime_logs()

    crawler = build_crawler(
        mode=resolved_mode,
        runtime=runtime,
        max_requests=resolved_max_requests,
        respect_robots_txt=settings.respect_robots_txt,
        headless=resolved_headless,
        browser_type=resolved_browser_type,
        request_timeout_seconds=settings.request_timeout_seconds,
    )

    pending_http_validators: dict[str, tuple[str, str]] = {}

    if resolved_mode == "http":

        async def add_incremental_validators(context: BasicCrawlingContext) -> None:
            headers = conditional_request_headers(
                url=context.request.url,
                url_state=url_state,
                force_refresh=resolved_force_refresh,
            )
            if not headers:
                return

            existing_headers = context.request.headers or HttpHeaders()
            context.request.headers = HttpHeaders(
                {
                    **dict(existing_headers),
                    **headers,
                }
            )

        async def handle_incremental_response(context: Any) -> None:
            normalized_url = normalize_url(context.request.url)
            status_code = context.http_response.status_code

            if status_code == 304:
                record_incremental_skip(normalized_url, stats)
                raise ContextPipelineInterruptedError(f"Not modified: {normalized_url}")

            pending_http_validators[normalized_url] = response_validators(
                context.http_response.headers
            )

        crawler.pre_navigation_hook(add_incremental_validators)
        crawler.post_navigation_hook(handle_incremental_response)

    active_requests = 0

    @crawler.router.default_handler
    async def request_handler(
        context: (
            AdaptivePlaywrightCrawlingContext
            | BeautifulSoupCrawlingContext
            | PlaywrightCrawlingContext
        ),
    ) -> None:
        nonlocal active_requests

        try:
            active_requests += 1
            emit_event(
                phase="Downloading",
                current_url=context.request.url,
                active_requests=active_requests,
            )

            if resolved_mode == "playwright":
                playwright_context = cast(Any, context)
                html = await playwright_context.page.content()
                soup = BeautifulSoup(html, "lxml")
                effective_url = str(playwright_context.page.url)
            else:
                adaptive_context = cast(Any, context)
                soup = await adaptive_context.parse_with_static_parser()
                html = str(soup)
                effective_url = str(
                    getattr(context.request, "loaded_url", None)
                    or context.request.url
                )

            try:
                normalized_effective_url = normalize_url(
                    validated_http_url(effective_url)
                )
            except (TypeError, ValueError):
                return

            if scope_pattern.search(normalized_effective_url) is None:
                context.log.warning(
                    "Redirected outside crawl scope; skipping content: %s",
                    effective_url,
                )
                return

            emit_event(
                phase="Extracting",
                current_url=context.request.url,
                active_requests=active_requests,
            )
            discovered_urls = await discover_and_enqueue_in_scope_links(
                context=cast(Any, context),
                base_url=effective_url,
                scope_pattern=scope_pattern,
                should_skip_url=language_strategy.should_skip_url,
            )
            discovered_link_count = len(discovered_urls)

            content_language = None
            if resolved_mode == "http":
                content_language = cast(Any, context).http_response.headers.get(
                    "content-language"
                )

            language_decision = language_detector.detect_from_html(
                url=effective_url,
                html=html,
                content_language=content_language,
            )
            if not language_strategy.accepts(
                language_decision
            ) and language_decision.source not in {
                "insufficient-text",
                "language-detector-no-result",
            }:
                context.log.info(
                    "Non-English page skipped after discovery: %s",
                    effective_url,
                )
                await context.push_data(
                    {
                        "outcome": "non_english",
                        "url": context.request.url,
                        "discovered_link_count": discovered_link_count,
                    }
                )
                return

            title_element = soup.title
            title = (
                title_element.get_text(" ", strip=True)
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
            except ValueError as error:
                if str(error).startswith("No meaningful Markdown content found:"):
                    # The adaptive result checker rejects this marker for static
                    # rendering, which makes Crawlee retry with Playwright. The
                    # browser result is committed normally if it is still empty.
                    await context.push_data(
                        {
                            "outcome": "empty",
                            "url": context.request.url,
                            "discovered_link_count": discovered_link_count,
                        }
                    )
                    return
                raise

            await context.push_data(
                {
                    "outcome": "document",
                    "url": document.url,
                    "title": document.title,
                    "language": document.language,
                    "output_path": str(document.output_path),
                    "content_hash": document.content_hash,
                    "markdown": document.markdown,
                }
            )
        finally:
            active_requests = max(0, active_requests - 1)
            emit_event(
                phase="Crawling",
                current_url=context.request.url,
                active_requests=active_requests,
            )

    emit_event(
        phase="Discovering sitemaps",
        active_requests=0,
    )

    known_in_scope_urls = [
        url
        for url in url_state
        if scope_pattern.search(url) is not None
        and not language_strategy.should_skip_url(url)
        and not any(pattern.search(url) for pattern in EXCLUDED_URL_PATTERNS)
    ]

    initial_urls = list(
        dict.fromkeys(
            [
                normalized_start_url,
                *known_in_scope_urls,
            ]
        )
    )

    emit_event(
        phase="Preparing queue",
        discovered=len(initial_urls),
        queued=len(initial_urls),
        active_requests=0,
    )

    incremental_urls = filter_incremental_urls(
        initial_urls,
        refresh_hours=resolved_refresh_hours,
        force_refresh=resolved_force_refresh,
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
        "request_storage_dir": resolved_state_dir / "crawlee" / "crawl" / start_hostname,
        "throttled_domains": [start_hostname],
    }

    async def flush_committed_results() -> None:
        """Apply only the handler results committed by Crawlee's selected renderer."""

        dataset = await crawler.get_dataset()
        page = await dataset.get_data()

        for item in page.items:
            outcome = str(item.get("outcome", "document"))
            if outcome == "non_english":
                record_non_english_page()
                continue
            if outcome == "empty":
                stats.empty_pages += 1
                stats.processed += 1
                continue

            document = MarkdownDocument(
                url=str(item["url"]),
                title=str(item["title"]),
                language=str(item["language"]),
                markdown=str(item["markdown"]),
                output_path=Path(str(item["output_path"])),
                content_hash=str(item["content_hash"]),
            )
            unchanged = content_is_unchanged(
                url=document.url,
                digest=document.content_hash,
                url_state=url_state,
            )
            if not unchanged:
                markdown_exporter.write(document)
                stats.saved += 1

            validator_url = normalize_url(document.url)
            etag, last_modified = pending_http_validators.pop(
                validator_url,
                ("", ""),
            )
            record_incremental_success(
                url=document.url,
                output_path=document.output_path,
                digest=document.content_hash,
                url_state=url_state,
                etag=etag,
                last_modified=last_modified,
            )
            stats.processed += 1

        await dataset.drop()

    def persist_incremental_state() -> None:
        save_url_state(
            url_state,
            resolved_state_dir,
            start_hostname,
        )

    def finalize_crawl() -> None:
        persist_incremental_state()
        write_crawl_report(
            output_dir=resolved_output_dir,
            stats=stats,
            configuration=report_configuration,
        )

    crawl_succeeded = False
    request_storage_complete = False
    try:
        while not await sitemap_loader.is_finished():
            sitemap_request = await sitemap_loader.fetch_next_request()
            if sitemap_request is None:
                continue
            await runtime.request_manager.add_request(sitemap_request)
            await sitemap_loader.mark_request_as_handled(sitemap_request)

        if not incremental_urls and await runtime.request_manager.is_finished():
            emit_event(
                phase="Nothing to crawl",
                queued=0,
                discovered=len(initial_urls),
                active_requests=0,
            )
            finalize_crawl()
            crawl_succeeded = True
            request_storage_complete = True
            return stats

        if not incremental_urls:
            emit_event(
                phase="Resuming queue",
                queued=0,
                discovered=len(initial_urls),
                active_requests=0,
            )

        @crawler.failed_request_handler
        async def failed_handler(
            context: BeautifulSoupCrawlingContext | BasicCrawlingContext,
            error: Exception,
        ) -> None:
            nonlocal active_requests
            stats.failed += 1
            active_requests = max(0, active_requests - 1)
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

        try:
            final_statistics = await crawler.run(incremental_urls)
        except BaseException:
            await flush_committed_results()
            persist_incremental_state()
            raise

        await flush_committed_results()
        request_storage_complete = await runtime.request_manager.is_finished()
        if (
            not request_storage_complete
            and final_statistics.requests_total < resolved_max_requests
        ):
            persist_incremental_state()
            raise RuntimeError(
                "Crawl stopped before the persistent request queue finished; "
                "request storage was preserved for resume."
            )

        stats.sitemap_urls = await sitemap_loader.get_total_count()

        emit_event(
            phase="Finalizing",
            queued=0,
            discovered=len(initial_urls),
            active_requests=0,
        )
        finalize_crawl()
        crawl_succeeded = True
        return stats
    finally:
        await sitemap_loader.close()
        await sitemap_http_client.cleanup()
        if crawl_succeeded and request_storage_complete:
            await runtime.drop_request_storage()

