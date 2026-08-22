"""Discovery-only site inventory for docsync."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit

from crawlee.crawlers import (
    BasicCrawlingContext,
    BeautifulSoupCrawler,
    BeautifulSoupCrawlingContext,
)
from crawlee.errors import (
    HttpStatusCodeError,
    RequestHandlerError,
    UserHandlerTimeoutError,
)

from docsync.crawler import (
    DEFAULT_MAX_REQUEST_RETRIES,
    build_scope_pattern,
    extract_in_scope_links,
)
from docsync.crawler_runtime import build_crawlee_runtime
from docsync.language import EnglishPageDetector
from docsync.language_strategy import LanguageStrategy
from docsync.sitemap import discover_sitemap_urls
from docsync.url_security import (
    normalize_url,
    validated_http_url,
)

INVENTORY_REPORT_FILENAME = "site-inventory.json"


def _normalize_inventory_url(url: str) -> str:
    """Normalize a URL while preserving a meaningful directory slash."""

    validated_url = validated_http_url(url)
    parsed_validated = urlsplit(validated_url)

    normalized_url: str = str(normalize_url(validated_url))
    parsed_normalized = urlsplit(normalized_url)

    if (
        parsed_validated.path.endswith("/")
        and parsed_validated.path != "/"
        and not parsed_normalized.path.endswith("/")
    ):
        normalized_url = f"{normalized_url}/"

    return normalized_url


@dataclass(slots=True)
class SiteInventory:
    """Final discovery-only site inventory."""

    seed_url: str
    sitemap_urls: int = 0
    discovered_urls: int = 0
    english_urls: int = 0
    non_english_urls: int = 0
    robots_blocked: int = 0
    duplicate_urls: int = 0
    redirects: int = 0
    reachable_pages: int = 0
    not_found_pages: int = 0
    timeouts: int = 0
    failed_pages: int = 0
    processed_urls: int = 0
    remaining_urls: int = 0
    discovery_complete: bool = False
    sitemap_files_checked: int = 0
    sitemap_files_found: int = 0
    sitemap_errors: int = 0

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-compatible inventory payload."""

        return asdict(self)

    def render(self) -> str:
        """Render the final terminal report."""

        complete = "YES" if self.discovery_complete else "NO"

        return "\n".join(
            (
                "====================================================",
                "SITE INVENTORY",
                "====================================================",
                "",
                "Seed URL:",
                self.seed_url,
                "",
                f"Sitemap URLs:        {self.sitemap_urls}",
                f"Discovered URLs:     {self.discovered_urls}",
                f"English URLs:        {self.english_urls}",
                f"Non-English URLs:    {self.non_english_urls}",
                f"Robots blocked:      {self.robots_blocked}",
                f"Duplicate URLs:      {self.duplicate_urls}",
                f"Redirects:           {self.redirects}",
                f"Reachable pages:     {self.reachable_pages}",
                f"404 pages:           {self.not_found_pages}",
                f"Timeouts:            {self.timeouts}",
                f"Other failures:      {self.failed_pages}",
                f"Processed URLs:      {self.processed_urls}",
                f"Remaining URLs:      {self.remaining_urls}",
                "",
                f"Discovery complete:  {complete}",
            )
        )


def _inventory_progress_text(
    *,
    report: SiteInventory,
    discovered_count: int,
    queued_count: int,
) -> str:
    """Build one live inventory progress line."""

    classified_count = report.english_urls + report.non_english_urls

    problem_count = (
        report.robots_blocked
        + report.not_found_pages
        + report.timeouts
        + report.failed_pages
    )

    return (
        "Inventory progress | "
        f"processed={report.processed_urls}/{discovered_count} | "
        f"queued={queued_count} | "
        f"reachable={report.reachable_pages} | "
        f"classified={classified_count} | "
        f"english={report.english_urls} | "
        f"non_english={report.non_english_urls} | "
        f"blocked={report.robots_blocked} | "
        f"404={report.not_found_pages} | "
        f"timeouts={report.timeouts} | "
        f"failed={report.failed_pages} | "
        f"problems={problem_count}"
    )


def _print_inventory_progress(
    *,
    report: SiteInventory,
    discovered_count: int,
    queued_count: int,
) -> None:
    """Print live progress immediately after a completed URL."""

    print(
        _inventory_progress_text(
            report=report,
            discovered_count=discovered_count,
            queued_count=queued_count,
        ),
        flush=True,
    )


def write_inventory_report(
    *,
    report: SiteInventory,
    state_dir: Path,
) -> Path:
    """Atomically write the durable site inventory report."""

    resolved_state_dir = state_dir.expanduser().resolve()

    resolved_state_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    report_path = resolved_state_dir / INVENTORY_REPORT_FILENAME

    temporary_path = report_path.with_suffix(".json.tmp")

    try:
        temporary_path.write_text(
            json.dumps(
                report.as_dict(),
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        temporary_path.replace(report_path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise

    return report_path


async def run_inventory(
    *,
    start_url: str,
    state_dir: str | Path,
    max_requests: int,
    max_concurrency: int,
    requests_per_minute: int,
    request_timeout_seconds: int,
    language: str = "en",
    respect_robots_txt: bool = True,
) -> SiteInventory:
    """Discover and classify pages without writing Markdown."""

    if max_requests <= 0:
        raise ValueError("max_requests must be greater than zero")

    if max_concurrency <= 0:
        raise ValueError("max_concurrency must be greater than zero")

    if request_timeout_seconds <= 0:
        raise ValueError("request_timeout_seconds must be greater than zero")

    normalized_seed_url = _normalize_inventory_url(start_url)
    scope_pattern = build_scope_pattern(normalized_seed_url)

    parsed_seed_url = urlsplit(normalized_seed_url)
    hostname = parsed_seed_url.hostname

    if hostname is None:
        raise ValueError(
            f"Unable to determine hostname from start URL: {normalized_seed_url}"
        )

    report = SiteInventory(seed_url=normalized_seed_url)
    detector = EnglishPageDetector()
    language_strategy = LanguageStrategy(language)

    discovered_urls: set[str] = set()
    processed_urls: set[str] = set()

    def register_discovered_url(url: str) -> str | None:
        try:
            normalized_url = _normalize_inventory_url(url)
        except (TypeError, ValueError):
            return None

        if scope_pattern.search(normalized_url) is None:
            return None

        if language_strategy.should_skip_url(normalized_url):
            return None

        if normalized_url in discovered_urls:
            report.duplicate_urls += 1
            return None

        discovered_urls.add(normalized_url)
        return normalized_url

    def record_processed_url(url: str) -> None:
        if url in processed_urls:
            return

        processed_urls.add(url)
        report.processed_urls = len(processed_urls)

    def print_progress() -> None:
        _print_inventory_progress(
            report=report,
            discovered_count=len(discovered_urls),
            queued_count=max(0, len(discovered_urls) - len(processed_urls)),
        )

    initial_urls: list[str] = []

    seed_url = register_discovered_url(normalized_seed_url)

    if seed_url is not None:
        initial_urls.append(seed_url)

    sitemap_result = await discover_sitemap_urls(
        start_url=normalized_seed_url,
        timeout_seconds=request_timeout_seconds,
        max_urls=max_requests,
    )

    report.sitemap_urls = len(sitemap_result.urls)
    report.sitemap_files_checked = sitemap_result.sitemap_files_checked
    report.sitemap_files_found = sitemap_result.sitemap_files_found
    report.sitemap_errors = len(sitemap_result.errors)

    for sitemap_url in sitemap_result.urls:
        registered_url = register_discovered_url(sitemap_url)

        if registered_url is not None:
            initial_urls.append(registered_url)

    print(
        "Inventory discovery started | "
        f"seed={normalized_seed_url} | "
        f"sitemap_urls={report.sitemap_urls} | "
        f"initial_discovered={len(discovered_urls)} | "
        f"max_requests={max_requests}",
        flush=True,
    )

    runtime = await build_crawlee_runtime(
        hostname=hostname,
        max_concurrency=max_concurrency,
        requests_per_minute=requests_per_minute,
        request_timeout_seconds=request_timeout_seconds,
    )

    crawler = BeautifulSoupCrawler(
        request_manager=runtime.request_manager,
        storage_client=runtime.storage_client,
        concurrency_settings=runtime.concurrency_settings,
        max_request_retries=DEFAULT_MAX_REQUEST_RETRIES,
        max_requests_per_crawl=max_requests,
        request_handler_timeout=runtime.request_handler_timeout,
        respect_robots_txt_file=respect_robots_txt,
    )

    @crawler.router.default_handler
    async def request_handler(context: BeautifulSoupCrawlingContext) -> None:
        requested_url = _normalize_inventory_url(context.request.url)
        loaded_url = context.request.loaded_url or context.request.url

        try:
            effective_url = _normalize_inventory_url(loaded_url)
        except (TypeError, ValueError):
            effective_url = requested_url

        record_processed_url(requested_url)

        if effective_url != requested_url:
            report.redirects += 1

        content_type = context.http_response.headers.get(
            "content-type",
            "",
        ).lower()

        if (
            "text/html" not in content_type
            and "application/xhtml+xml" not in content_type
        ):
            report.failed_pages += 1
            print_progress()
            return

        report.reachable_pages += 1

        discovered_links = extract_in_scope_links(
            soup=context.soup,
            base_url=effective_url,
            scope_pattern=scope_pattern,
        )

        queued_urls: list[str] = []

        for discovered_link in discovered_links:
            registered_url = register_discovered_url(discovered_link)

            if registered_url is not None:
                queued_urls.append(registered_url)

        if queued_urls:
            await context.add_requests(queued_urls)

        if language_strategy.should_skip_url(effective_url):
            report.non_english_urls += 1
            print_progress()
            return

        html = str(context.soup)

        language_decision = detector.detect_from_html(
            url=effective_url,
            html=html,
            content_language=context.http_response.headers.get("content-language"),
        )

        if language_strategy.accepts(language_decision):
            report.english_urls += 1
        else:
            report.non_english_urls += 1

        print_progress()

    @crawler.on_skipped_request
    async def skipped_handler(url: str, reason: str) -> None:
        if reason == "robots_txt":
            report.robots_blocked += 1

        try:
            normalized_url = _normalize_inventory_url(url)
        except (TypeError, ValueError):
            normalized_url = url

        record_processed_url(normalized_url)
        print_progress()

    @crawler.failed_request_handler
    async def failed_handler(
        context: BeautifulSoupCrawlingContext | BasicCrawlingContext,
        error: Exception,
    ) -> None:
        current_error = error

        while isinstance(current_error, RequestHandlerError):
            current_error = current_error.wrapped_exception

        if isinstance(current_error, HttpStatusCodeError):
            if current_error.status_code == 404:
                report.not_found_pages += 1
            else:
                report.failed_pages += 1
        elif isinstance(
            current_error,
            (asyncio.TimeoutError, UserHandlerTimeoutError),
        ):
            report.timeouts += 1
        else:
            report.failed_pages += 1

        try:
            normalized_url = _normalize_inventory_url(context.request.url)
        except (TypeError, ValueError):
            normalized_url = context.request.url

        record_processed_url(normalized_url)
        print_progress()

    await crawler.run(initial_urls)

    report.discovered_urls = len(discovered_urls)
    report.remaining_urls = max(
        0,
        len(discovered_urls) - len(processed_urls),
    )
    report.discovery_complete = (
        report.remaining_urls == 0 and report.processed_urls < max_requests
    )

    _print_inventory_progress(
        report=report,
        discovered_count=report.discovered_urls,
        queued_count=report.remaining_urls,
    )

    write_inventory_report(
        report=report,
        state_dir=Path(state_dir),
    )

    return report
