"""Async HTML fetcher with strict pre-download content and language gates."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from secrets import SystemRandom

import aiohttp
from aiohttp import ClientTimeout
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from crawler.config import CrawlerConfig
from crawler.discovery_url_rules import (
    EXTRA_REGION_ALIASES,
    ISO_3166_REGION_CODES,
    MEDIA_SOCIAL_HOSTS,
    PREFLIGHT_SAMPLE_BYTES,
    html_needs_playwright,
    is_blocked_url_before_network,
    is_html,
    plain_text_to_html,
    sample_declares_non_english,
    should_download,
)

__all__ = [
    "AsyncFetcher",
    "FetchResult",
    "ProbeResult",
    "EXTRA_REGION_ALIASES",
    "ISO_3166_REGION_CODES",
    "MEDIA_SOCIAL_HOSTS",
]

BLOCKED_STATUS_CODES = frozenset({401, 403, 407, 429, 451})
READ_CHUNK_SIZE = 8_192
EARLY_LANGUAGE_CHECK_BYTES = 16_384
_JITTER = SystemRandom()


@dataclass(frozen=True, slots=True)
class FetchResult:
    """Final fetch result returned to the queue executor."""

    html: str | None
    final_url: str
    status_code: int | None
    etag: str | None
    last_modified: str | None
    not_modified: bool


@dataclass(frozen=True, slots=True)
class ResponseMetadata:
    """Small immutable HTTP metadata object."""

    final_url: str
    status_code: int
    content_type: str
    etag: str | None
    last_modified: str | None


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Lightweight pre-download decision."""

    allowed: bool
    final_url: str
    status_code: int | None
    etag: str | None
    last_modified: str | None
    not_modified: bool
    reason: str | None = None


class AsyncFetcher:
    """Network-only fetcher with lightweight pre-download filtering."""

    def __init__(
        self, config: CrawlerConfig, logger: logging.Logger | None = None
    ) -> None:
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self.semaphore = asyncio.Semaphore(config.concurrent_requests)
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._playwright_lock = asyncio.Lock()

    async def fetch(
        self,
        url: str,
        *,
        cache_headers: dict[str, str] | None = None,
    ) -> FetchResult:
        """Fetch HTML after HEAD/content/language preflight checks."""

        async with self.semaphore:
            await self._respect_delay()
            result = await self._fetch_with_aiohttp(
                url, cache_headers=cache_headers or {}
            )

            if result.not_modified:
                return result

            blocked_without_html = (
                result.status_code in BLOCKED_STATUS_CODES and not result.html
            )
            if blocked_without_html:
                self.logger.warning(
                    "HTTP status indicates blocked page; skipping Playwright: url=%s status=%s",
                    url,
                    result.status_code,
                )
                return result

            if result.html and not html_needs_playwright(result.html):
                return result

            playwright_result = await self._fetch_with_playwright(url)
            return playwright_result if playwright_result.html else result

    async def probe_url(self, url: str) -> ProbeResult:
        """Run lightweight URL and HEAD checks without downloading the full body."""

        allowed, reason = should_download(
            url=url, require_english=self.config.require_english
        )
        if not allowed:
            return ProbeResult(False, url, None, None, None, False, reason)

        headers = self._request_headers(cache_headers={})
        async with aiohttp.ClientSession(headers=headers) as session:
            result = await self._preflight_head(session=session, url=url)

        if result is None:
            return ProbeResult(True, url, None, None, None, False)

        result_allowed = result.not_modified or result.status_code is not None
        return ProbeResult(
            allowed=result_allowed,
            final_url=result.final_url,
            status_code=result.status_code,
            etag=result.etag,
            last_modified=result.last_modified,
            not_modified=result.not_modified,
            reason=None if result_allowed else "head_rejected",
        )

    async def close(self) -> None:
        """Close Playwright resources owned by this fetcher."""

        if self._context is not None:
            await self._context.close()
            self._context = None

        if self._browser is not None:
            await self._browser.close()
            self._browser = None

        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    async def _respect_delay(self) -> None:
        """Sleep between requests using configured polite delay."""

        delay = _JITTER.uniform(self.config.min_delay, self.config.max_delay)
        await asyncio.sleep(delay)

    def _request_headers(self, *, cache_headers: dict[str, str]) -> dict[str, str]:
        """Build crawler request headers."""

        return {
            "User-Agent": self.config.user_agent,
            "Accept": "text/html,text/plain;q=0.9,*/*;q=0.1",
            **cache_headers,
        }

    async def _fetch_with_aiohttp(
        self,
        url: str,
        *,
        cache_headers: dict[str, str],
    ) -> FetchResult:
        """Fetch page with aiohttp and streaming language preflight."""

        blocked_result = self._blocked_url_result(url)
        if blocked_result is not None:
            return blocked_result

        headers = self._request_headers(cache_headers=cache_headers)
        last_result = self._empty_result(url)

        async with aiohttp.ClientSession(headers=headers) as session:
            head_result = await self._preflight_head(session=session, url=url)
            if head_result is not None:
                return head_result

            for attempt in range(1, self.config.max_retries + 1):
                last_result = await self._attempt_get(
                    session=session, url=url, attempt=attempt
                )
                if self._is_terminal_fetch_result(last_result):
                    return last_result

        self.logger.error(
            "aiohttp fetch exhausted retries: url=%s retries=%s last_status=%s",
            url,
            self.config.max_retries,
            last_result.status_code,
        )
        return last_result

    async def _attempt_get(
        self,
        *,
        session: aiohttp.ClientSession,
        url: str,
        attempt: int,
    ) -> FetchResult:
        """Perform one GET attempt."""

        try:
            async with session.get(
                url,
                timeout=ClientTimeout(total=self.config.request_timeout),
                allow_redirects=True,
            ) as response:
                return await self._handle_get_response(
                    response=response,
                    source_url=url,
                    attempt=attempt,
                )
        except aiohttp.ClientError, asyncio.TimeoutError, OSError:
            self.logger.exception(
                "aiohttp fetch failed on attempt %s/%s: url=%s",
                attempt,
                self.config.max_retries,
                url,
            )
            await asyncio.sleep(1)
            return self._empty_result(url)

    async def _handle_get_response(
        self,
        *,
        response: aiohttp.ClientResponse,
        source_url: str,
        attempt: int,
    ) -> FetchResult:
        """Convert a GET response into FetchResult."""

        metadata = self._response_metadata(response)
        preflight_result = self._reject_response_metadata(
            source_url=source_url, metadata=metadata
        )
        if preflight_result is not None:
            return preflight_result

        if metadata.status_code == 304:
            return self._not_modified_result(metadata)

        if metadata.status_code in BLOCKED_STATUS_CODES:
            return await self._blocked_status_result(
                response=response, metadata=metadata
            )

        if metadata.status_code >= 400:
            self.logger.warning(
                "aiohttp HTTP error on attempt %s/%s: url=%s status=%s final_url=%s",
                attempt,
                self.config.max_retries,
                source_url,
                metadata.status_code,
                metadata.final_url,
            )
            await asyncio.sleep(1)
            return self._metadata_empty_result(metadata)

        html = await self._read_text_with_language_preflight(
            response=response,
            url=metadata.final_url,
            content_type=metadata.content_type,
        )
        return FetchResult(
            html=html,
            final_url=metadata.final_url,
            status_code=metadata.status_code,
            etag=metadata.etag,
            last_modified=metadata.last_modified,
            not_modified=False,
        )

    async def _blocked_status_result(
        self,
        *,
        response: aiohttp.ClientResponse,
        metadata: ResponseMetadata,
    ) -> FetchResult:
        """Return protected/blocked HTTP status result."""

        html = await response.text() if is_html(metadata.content_type) else None
        self.logger.warning(
            "aiohttp detected blocked/protected HTTP status: status=%s final_url=%s",
            metadata.status_code,
            metadata.final_url,
        )
        return FetchResult(
            html=html,
            final_url=metadata.final_url,
            status_code=metadata.status_code,
            etag=metadata.etag,
            last_modified=metadata.last_modified,
            not_modified=False,
        )

    async def _preflight_head(
        self,
        *,
        session: aiohttp.ClientSession,
        url: str,
    ) -> FetchResult | None:
        """Reject blocked resources using HEAD before body download."""

        try:
            async with session.head(
                url,
                timeout=ClientTimeout(total=self.config.request_timeout),
                allow_redirects=True,
            ) as response:
                metadata = self._response_metadata(response)
                if metadata.status_code == 304:
                    return self._not_modified_result(metadata)

                if metadata.status_code in {405, 501} or metadata.status_code >= 400:
                    return None

                return self._reject_response_metadata(source_url=url, metadata=metadata)
        except aiohttp.ClientError, asyncio.TimeoutError, OSError:
            self.logger.info(
                "HEAD preflight unavailable; continuing with streamed GET: url=%s",
                url,
            )
            return None

    async def _read_text_with_language_preflight(
        self,
        *,
        response: aiohttp.ClientResponse,
        url: str,
        content_type: str,
    ) -> str | None:
        """Stream text and reject non-English pages before full body read when possible."""

        chunks: list[bytes] = []
        sampled_size = 0
        checked_language = False

        async for chunk in response.content.iter_chunked(READ_CHUNK_SIZE):
            if not chunk:
                continue

            chunks.append(chunk)
            sampled_size += len(chunk)
            if checked_language or sampled_size < EARLY_LANGUAGE_CHECK_BYTES:
                continue

            sample_text = self._decode_response_bytes(response, b"".join(chunks))
            if self._sample_is_blocked_by_language(
                sample_text,
                url=url,
                content_type=content_type,
            ):
                self.logger.info(
                    "Stream preflight skipped non-English page: url=%s",
                    url,
                )
                return None

            checked_language = True

        text = self._decode_response_bytes(response, b"".join(chunks))
        sample = text[:PREFLIGHT_SAMPLE_BYTES].strip()
        if self._sample_is_blocked_by_language(
            sample,
            url=url,
            content_type=content_type,
        ):
            self.logger.info(
                "Stream preflight skipped non-English page after confirmation: %s",
                url,
            )
            return None

        if "text/plain" in content_type:
            return plain_text_to_html(text, url)

        return text

    def _sample_is_blocked_by_language(
        self,
        sample: str,
        *,
        url: str,
        content_type: str,
    ) -> bool:
        """Return True when English-only mode rejects sampled content."""

        return self.config.require_english and sample_declares_non_english(
            sample,
            url=url,
            content_type=content_type,
        )

    def _blocked_url_result(self, url: str) -> FetchResult | None:
        """Return empty result when URL is blocked before network."""

        if not is_blocked_url_before_network(
            url, require_english=self.config.require_english
        ):
            return None

        self.logger.info(
            "Preflight skipped blocked URL before network request: url=%s", url
        )
        return self._empty_result(url)

    def _reject_response_metadata(
        self,
        *,
        source_url: str,
        metadata: ResponseMetadata,
    ) -> FetchResult | None:
        """Return FetchResult when response metadata should reject download."""

        allowed, reason = should_download(
            url=metadata.final_url,
            content_type=metadata.content_type,
            require_english=self.config.require_english,
        )
        if allowed:
            return None

        self.logger.info(
            "Preflight skipped response: reason=%s url=%s status=%s final_url=%s",
            reason,
            source_url,
            metadata.status_code,
            metadata.final_url,
        )
        return self._metadata_empty_result(metadata)

    async def _ensure_playwright_context(self) -> BrowserContext:
        """Start and cache one Playwright browser context."""

        async with self._playwright_lock:
            if self._context is not None:
                return self._context

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)
            self._context = await self._browser.new_context(
                user_agent=self.config.user_agent,
                java_script_enabled=True,
                ignore_https_errors=True,
            )
            return self._context

    async def _fetch_with_playwright(self, url: str) -> FetchResult:
        """Fetch JavaScript-rendered HTML only after normal fetch is insufficient."""

        blocked_result = self._blocked_url_result(url)
        if blocked_result is not None:
            return blocked_result

        context = await self._ensure_playwright_context()
        page = await context.new_page()
        result = await self._read_playwright_page(page=page, url=url)
        await page.close()
        return result

    async def _read_playwright_page(self, *, page: Page, url: str) -> FetchResult:
        """Read one Playwright page and convert it to FetchResult."""

        status_code: int | None = None
        try:
            response = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.config.playwright_timeout_ms,
            )
            if response is not None:
                status_code = response.status

            if status_code in BLOCKED_STATUS_CODES:
                return self._playwright_empty_result(page.url, status_code)

            await page.wait_for_timeout(self.config.playwright_extra_wait_ms)
            await self._scroll_page(page=page)

            if is_blocked_url_before_network(
                page.url, require_english=self.config.require_english
            ):
                return self._playwright_empty_result(page.url, status_code)

            html = await page.content()
            if self._sample_is_blocked_by_language(
                html[:PREFLIGHT_SAMPLE_BYTES],
                url=page.url,
                content_type="text/html",
            ):
                return self._playwright_empty_result(page.url, status_code)

            return FetchResult(html, page.url, status_code, None, None, False)
        except PlaywrightTimeoutError:
            self.logger.warning("Playwright timeout: url=%s", url)
            return self._playwright_empty_result(url, status_code)
        except PlaywrightError:
            self.logger.exception("Playwright fetch failed: url=%s", url)
            return self._playwright_empty_result(url, status_code)

    async def _scroll_page(self, *, page: Page) -> None:
        """Scroll page to trigger lazy-rendered content."""

        for _ in range(self.config.playwright_scroll_steps):
            await page.mouse.wheel(0, 1600)
            await page.wait_for_timeout(500)

    @staticmethod
    def _is_terminal_fetch_result(result: FetchResult) -> bool:
        """Return True when retry loop should stop."""

        if result.html is not None or result.not_modified:
            return True

        return result.status_code is not None and result.status_code < 400

    @staticmethod
    def _decode_response_bytes(response: aiohttp.ClientResponse, raw: bytes) -> str:
        """Decode response bytes with server charset fallback."""

        return raw.decode(response.charset or "utf-8", errors="replace")

    @staticmethod
    def _response_metadata(response: aiohttp.ClientResponse) -> ResponseMetadata:
        """Extract immutable response metadata."""

        return ResponseMetadata(
            final_url=str(response.url),
            status_code=response.status,
            content_type=response.headers.get("Content-Type", "").lower(),
            etag=response.headers.get("ETag"),
            last_modified=response.headers.get("Last-Modified"),
        )

    @staticmethod
    def _empty_result(url: str) -> FetchResult:
        """Return empty fetch result."""

        return FetchResult(None, url, None, None, None, False)

    @staticmethod
    def _metadata_empty_result(metadata: ResponseMetadata) -> FetchResult:
        """Return empty fetch result with response metadata."""

        return FetchResult(
            None,
            metadata.final_url,
            metadata.status_code,
            metadata.etag,
            metadata.last_modified,
            False,
        )

    @staticmethod
    def _not_modified_result(metadata: ResponseMetadata) -> FetchResult:
        """Return 304 fetch result."""

        return FetchResult(
            None,
            metadata.final_url,
            metadata.status_code,
            metadata.etag,
            metadata.last_modified,
            True,
        )

    @staticmethod
    def _playwright_empty_result(url: str, status_code: int | None) -> FetchResult:
        """Return empty Playwright result."""

        return FetchResult(None, url, status_code, None, None, False)
