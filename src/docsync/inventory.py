"""Discovery-only site inventory for docsync."""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from docsync.crawler import (
    build_scope_pattern,
    extract_in_scope_links,
)
from docsync.language import EnglishPageDetector
from docsync.sitemap import discover_sitemap_urls
from docsync.url_security import (
    normalize_url,
    validated_http_url,
)

INVENTORY_REPORT_FILENAME = "site-inventory.json"
INVENTORY_USER_AGENT = "docsync-inventory/1.0"


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


class RequestPacer:
    """Apply one process-wide requests-per-minute limit."""

    def __init__(
        self,
        requests_per_minute: int,
    ) -> None:
        if requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be greater than zero")

        self._interval_seconds = 60.0 / requests_per_minute
        self._lock = asyncio.Lock()
        self._next_request_at = 0.0

    async def wait(self) -> None:
        """Wait until the next globally permitted request time."""

        async with self._lock:
            now = time.monotonic()
            delay = self._next_request_at - now

            if delay > 0:
                await asyncio.sleep(delay)

            current = time.monotonic()

            self._next_request_at = (
                max(
                    current,
                    self._next_request_at,
                )
                + self._interval_seconds
            )


async def load_robots_parser(
    *,
    client: httpx.AsyncClient,
    seed_url: str,
    timeout_seconds: int,
) -> RobotFileParser:
    """Download and parse the site's root robots.txt file."""

    parsed = urlsplit(seed_url)

    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    parser = RobotFileParser()
    parser.set_url(robots_url)

    try:
        response = await client.get(
            robots_url,
            timeout=timeout_seconds,
        )

        if response.status_code < 400:
            parser.parse(response.text.splitlines())
        else:
            parser.parse([])
    except httpx.HTTPError:
        parser.parse([])

    return parser


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

    report = SiteInventory(
        seed_url=normalized_seed_url,
    )

    detector = EnglishPageDetector()
    pacer = RequestPacer(requests_per_minute)

    pending_urls: deque[str] = deque()
    discovered_urls: set[str] = set()
    processed_urls: set[str] = set()
    queue_lock = asyncio.Lock()

    def add_discovered_url(
        url: str,
    ) -> bool:
        try:
            normalized_url = _normalize_inventory_url(url)
        except (TypeError, ValueError):
            return False

        if scope_pattern.search(normalized_url) is None:
            return False

        if normalized_url in discovered_urls:
            report.duplicate_urls += 1
            return False

        discovered_urls.add(normalized_url)
        pending_urls.append(normalized_url)

        return True

    add_discovered_url(normalized_seed_url)

    sitemap_result = await discover_sitemap_urls(
        start_url=normalized_seed_url,
        timeout_seconds=(request_timeout_seconds),
        max_urls=max_requests,
    )

    report.sitemap_urls = len(sitemap_result.urls)
    report.sitemap_files_checked = sitemap_result.sitemap_files_checked
    report.sitemap_files_found = sitemap_result.sitemap_files_found
    report.sitemap_errors = len(sitemap_result.errors)

    for sitemap_url in sitemap_result.urls:
        add_discovered_url(sitemap_url)

    print(
        "Inventory discovery started | "
        f"seed={normalized_seed_url} | "
        f"sitemap_urls={report.sitemap_urls} | "
        f"initial_discovered={len(discovered_urls)} | "
        f"max_requests={max_requests}",
        flush=True,
    )

    limits = httpx.Limits(
        max_connections=max_concurrency,
        max_keepalive_connections=(max_concurrency),
    )

    headers = {
        "User-Agent": INVENTORY_USER_AGENT,
        "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.1"),
    }

    async with httpx.AsyncClient(
        follow_redirects=True,
        limits=limits,
        headers=headers,
    ) as client:
        robots_parser = await load_robots_parser(
            client=client,
            seed_url=(normalized_seed_url),
            timeout_seconds=(request_timeout_seconds),
        )

        async def process_one_url(
            url: str,
        ) -> None:
            if respect_robots_txt and not robots_parser.can_fetch(
                INVENTORY_USER_AGENT,
                url,
            ):
                report.robots_blocked += 1
                return

            await pacer.wait()

            try:
                response = await client.get(
                    url,
                    timeout=(request_timeout_seconds),
                )
            except httpx.TimeoutException:
                report.timeouts += 1
                return
            except httpx.HTTPError:
                report.failed_pages += 1
                return

            try:
                final_url = _normalize_inventory_url(str(response.url))
            except (TypeError, ValueError):
                final_url = url

            if final_url != url:
                report.redirects += 1

            if response.status_code == 404:
                report.not_found_pages += 1
                return

            if response.status_code >= 400:
                report.failed_pages += 1
                return

            content_type = response.headers.get(
                "content-type",
                "",
            ).lower()

            if (
                "text/html" not in content_type
                and "application/xhtml+xml" not in content_type
            ):
                report.failed_pages += 1
                return

            report.reachable_pages += 1

            html = response.text

            language_decision = detector.detect_from_html(
                url=final_url,
                html=html,
                content_language=(response.headers.get("content-language")),
            )

            if language_decision.is_english:
                report.english_urls += 1
            else:
                report.non_english_urls += 1

            soup = BeautifulSoup(
                html,
                "lxml",
            )

            discovered_links = extract_in_scope_links(
                soup=soup,
                base_url=str(response.url),
                scope_pattern=(scope_pattern),
            )

            async with queue_lock:
                for discovered_link in discovered_links:
                    add_discovered_url(discovered_link)

        async def worker() -> None:
            while True:
                async with queue_lock:
                    if report.processed_urls >= max_requests:
                        return

                    if not pending_urls:
                        return

                    current_url = pending_urls.popleft()

                    if current_url in processed_urls:
                        report.duplicate_urls += 1
                        continue

                    processed_urls.add(current_url)

                    report.processed_urls += 1

                await process_one_url(current_url)

                async with queue_lock:
                    discovered_count = len(discovered_urls)
                    queued_count = len(pending_urls)

                _print_inventory_progress(
                    report=report,
                    discovered_count=(discovered_count),
                    queued_count=(queued_count),
                )

        while pending_urls and report.processed_urls < max_requests:
            processed_before_batch = report.processed_urls

            workers = [asyncio.create_task(worker()) for _ in range(max_concurrency)]

            await asyncio.gather(*workers)

            if report.processed_urls == processed_before_batch:
                break

    report.discovered_urls = len(discovered_urls)

    report.remaining_urls = max(
        0,
        len(discovered_urls) - len(processed_urls),
    )

    report.discovery_complete = (
        not pending_urls
        and report.remaining_urls == 0
        and report.processed_urls < max_requests
    )

    _print_inventory_progress(
        report=report,
        discovered_count=(report.discovered_urls),
        queued_count=(report.remaining_urls),
    )

    write_inventory_report(
        report=report,
        state_dir=Path(state_dir),
    )

    return report
