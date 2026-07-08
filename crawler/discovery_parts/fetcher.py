"""Async HTML fetcher with strict pre-download content and language gates."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from html import escape
from secrets import SystemRandom
from urllib.parse import parse_qs, urlparse

import aiohttp
from aiohttp import ClientTimeout
from bs4 import BeautifulSoup, Tag
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

BLOCKED_STATUS_CODES = frozenset({401, 403, 407, 429, 451})
ALLOWED_CONTENT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
BLOCKED_CONTENT_TYPE_MARKERS = (
    "application/pdf",
    "application/zip",
    "application/x-zip-compressed",
    "application/x-rar",
    "application/x-7z-compressed",
    "application/x-tar",
    "application/gzip",
    "application/octet-stream",
    "image/",
    "video/",
    "audio/",
    "font/",
)
BLOCKED_FILE_EXTENSIONS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".zip",
    ".rar",
    ".7z",
    ".tar",
    ".gz",
    ".mp4",
    ".webm",
    ".mov",
    ".avi",
    ".mp3",
    ".wav",
    ".css",
    ".js",
    ".mjs",
    ".json",
    ".xml",
    ".rss",
    ".atom",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
)
MEDIA_SOCIAL_HOSTS = frozenset(
    """
    instagram.com tiktok.com facebook.com twitter.com x.com threads.net youtube.com
    youtu.be vimeo.com dailymotion.com twitch.tv snapchat.com pinterest.com reddit.com
    linkedin.com linktr.ee beacons.ai bio.site campsite.bio about.me
    """.split()
)
SOCIAL_PROFILE_PATH_MARKERS = (
    "/@",
    "/user/",
    "/users/",
    "/profile/",
    "/profiles/",
    "/account/",
    "/accounts/",
    "/channel/",
    "/channels/",
    "/c/",
    "/u/",
    "/watch",
    "/shorts/",
    "/reel/",
    "/reels/",
    "/video/",
    "/videos/",
    "/pin/",
    "/pins/",
    "/board/",
    "/boards/",
    "/status/",
    "/posts/",
    "/post/",
    "/photos/",
    "/photo/",
    "/stories/",
    "/story/",
)
JS_REQUIRED_PATTERNS = (
    "enable javascript",
    "javascript is required",
    "please enable js",
    "requires javascript",
    "you need to enable javascript",
    "this app works best with javascript",
)
LANGUAGE_QUERY_KEYS = frozenset({"hl", "lang", "language", "locale"})
ENGLISH_LANGUAGE_VALUES = frozenset(
    """
    en en-us en-gb en-au en-ca en-ie en-in en-my en-nz en-ph en-sg en-uk en-za
    en_us en_gb en_au en_ca en_ie en_in en_my en_nz en_ph en_sg en_uk en_za english
    """.split()
)
ISO_3166_REGION_CODES = frozenset(
    """
    ad ae af ag ai al am ao aq ar as at au aw ax az ba bb bd be bf bg bh bi bj bl
    bm bn bo bq br bs bt bv bw by bz ca cc cd cf cg ch ci ck cl cm cn co cr cu cv
    cw cx cy cz de dj dk dm do dz ec ee eg eh er es et fi fj fk fm fo fr ga gb gd
    ge gf gg gh gi gl gm gn gp gq gr gs gt gu gw gy hk hm hn hr ht hu id ie il im
    in io iq ir is it je jm jo jp ke kg kh ki km kn kp kr kw ky kz la lb lc li lk
    lr ls lt lu lv ly ma mc md me mf mg mh mk ml mm mn mo mp mq mr ms mt mu mv mw
    mx my mz na nc ne nf ng ni nl no np nr nu nz om pa pe pf pg ph pk pl pm pn pr
    ps pt pw py qa re ro rs ru rw sa sb sc sd se sg sh si sj sk sl sm sn so sr ss
    st sv sx sy sz tc td tf tg th tj tk tl tm tn to tr tt tv tw tz ua ug um us uy
    uz va vc ve vg vi vn vu wf ws ye yt za zm zw
    """.split()
)
EXTRA_REGION_ALIASES = frozenset(
    {"uk", "usa", "u-s", "u-s-a", "america", "united-states", "united-kingdom"}
)
REGION_GATEKEEPER_SAFE_HOST_PREFIXES = frozenset(
    {
        "www",
        "docs",
        "doc",
        "developer",
        "developers",
        "help",
        "support",
        "learn",
        "blog",
        "api",
    }
)
ENGLISH_STOPWORDS = frozenset(
    """
    the and you your for with from this that are can how what when where learn create
    account help support settings manage use using page content policy privacy terms search
    make get set new more about not all or if to in on of is it as be by a an at we
    our they their will may should before after overview guide documentation reference
    example examples install configure build run delete edit update
    """.split()
)
NON_ENGLISH_STOPWORDS = frozenset(
    """
    ve veya bir bu şu için ile nasıl nedir olan olarak daha değil giriş hesap ayarlar
    kullan kullanım hakkında yardım destek und oder der die das ein eine für mit nicht ist
    sind wie was konto einstellungen hilfe unterstützung et ou le la les des un une pour
    avec pas est sont comment quoi compte paramètres aide assistance y o el los las una
    para con no es son cómo qué cuenta configuración ayuda soporte não como que conta
    configurações ajuda suporte het een voor met niet zijn hoe wat instellingen hulp ondersteuning
    """.split()
)
NON_ENGLISH_CHARACTER_MARKERS = frozenset(
    {"ç", "ğ", "ı", "İ", "ö", "ş", "ü", "ß", "ñ", "¿", "¡", "ã", "õ"}
)

PREFLIGHT_SAMPLE_BYTES = 98_304
PREFLIGHT_MIN_WORDS = 20
PREFLIGHT_MIN_ENGLISH_RATIO = 0.035
PREFLIGHT_MAX_NON_ENGLISH_RATIO = 0.035
PREFLIGHT_MAX_NON_ENGLISH_MARKER_RATIO = 0.025
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


def is_html(content_type: str) -> bool:
    """Return True when a response content type can be converted to markdown."""

    normalized = content_type.lower().strip()
    return not normalized or any(
        marker in normalized for marker in ALLOWED_CONTENT_TYPES
    )


def is_blocked_content_type(content_type: str) -> bool:
    """Return True when a response content type is binary/media/archive."""

    normalized = content_type.lower().strip()
    return any(marker in normalized for marker in BLOCKED_CONTENT_TYPE_MARKERS)


def is_english(value: str) -> bool:
    """Return True for English language tags."""

    normalized = value.strip().lower().replace("_", "-")
    allowed = {item.replace("_", "-") for item in ENGLISH_LANGUAGE_VALUES}
    return normalized in allowed or normalized.startswith("en-")


def segment_declares_region(value: str) -> bool:
    """Return True when a segment is an ISO region or configured alias."""

    normalized = value.strip().lower().replace("_", "-")
    if not normalized:
        return False

    parts = [part for part in normalized.split("-") if part]
    direct_match = (
        normalized in EXTRA_REGION_ALIASES or normalized in ISO_3166_REGION_CODES
    )
    prefix_match = bool(parts) and parts[0] in EXTRA_REGION_ALIASES.union(
        ISO_3166_REGION_CODES
    )
    suffix_match = 2 <= len(parts) and parts[-1] in ISO_3166_REGION_CODES
    return direct_match or prefix_match or suffix_match


def host_declares_non_english_region(host: str) -> bool:
    """Return True when first host label is a regional language marker."""

    labels = [label for label in host.split(".") if label]
    if not labels:
        return False

    first_label = labels[0].lower().replace("_", "-")
    safe_prefix = first_label in REGION_GATEKEEPER_SAFE_HOST_PREFIXES
    return (
        not safe_prefix
        and not is_english(first_label)
        and segment_declares_region(first_label)
    )


def first_region_or_language_path_segment(path: str) -> str | None:
    """Return first path segment that looks like a language or region marker."""

    for part in path.strip("/").split("/"):
        normalized = part.strip().lower().replace("_", "-")
        if not normalized:
            continue

        if is_english(normalized) or segment_declares_region(normalized):
            return normalized

        if re.fullmatch(r"[a-z]{2}(?:-[a-z]{2})?", normalized):
            return normalized

    return None


def query_declares_non_english_region(query_string: str) -> bool:
    """Return True when language query params explicitly request non-English."""

    query = parse_qs(query_string)
    language_values = [
        value
        for key, values in query.items()
        if key.lower().strip() in LANGUAGE_QUERY_KEYS
        for value in values
        if value.strip()
    ]
    return any(not is_english(value) for value in language_values)


def url_has_definite_non_english_region(url: str) -> bool:
    """Return True when URL host/path/query explicitly points to a non-English region."""

    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.lower()
    normalized_path = f"/{path.strip('/')}/"

    if host_declares_non_english_region(host):
        return True

    region_segment = first_region_or_language_path_segment(path)
    if region_segment and not is_english(region_segment):
        return True

    intl_match = re.search(r"/intl/([^/]+)/", normalized_path)
    if intl_match is not None:
        return not is_english(intl_match.group(1))

    return query_declares_non_english_region(parsed.query)


def is_blocked_url_before_network(url: str, *, require_english: bool) -> bool:
    """Return True when URL can be rejected before any network request."""

    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    path_lower = parsed.path.lower()

    blocked_host = any(
        host == item or host.endswith(f".{item}") for item in MEDIA_SOCIAL_HOSTS
    )
    blocked_social_path = any(
        marker in path_lower for marker in SOCIAL_PROFILE_PATH_MARKERS
    )
    blocked_region = require_english and url_has_definite_non_english_region(url)
    blocked_extension = path_lower.endswith(BLOCKED_FILE_EXTENSIONS)

    return blocked_host or blocked_social_path or blocked_region or blocked_extension


def should_download(
    *,
    url: str,
    content_type: str = "",
    require_english: bool = True,
) -> tuple[bool, str | None]:
    """Return a cheap URL/content-type download decision."""

    if is_blocked_url_before_network(url, require_english=require_english):
        return False, "blocked_url"

    if is_blocked_content_type(content_type):
        return False, "blocked_content_type"

    if content_type and not is_html(content_type):
        return False, "non_html_content_type"

    return True, None


def html_language_decision(soup: BeautifulSoup) -> bool | None:
    """Return HTML language decision from lang/locale metadata."""

    html_tag = soup.find("html")
    if isinstance(html_tag, Tag):
        lang = str(html_tag.get("lang", "")).strip().lower().replace("_", "-")
        if lang:
            return is_english(lang)

    selectors = (
        'meta[property="og:locale"]',
        'meta[name="locale"]',
        'meta[http-equiv="content-language"]',
        'meta[name="language"]',
    )
    for selector in selectors:
        tag = soup.select_one(selector)
        if tag is None:
            continue

        content = str(tag.get("content", "")).strip().lower().replace("_", "-")
        if content:
            return is_english(content)

    return None


def sample_declares_non_english(
    html_or_text: str, *, url: str, content_type: str
) -> bool:
    """Return True when metadata or sampled words confidently identify non-English."""

    if url_has_definite_non_english_region(url):
        return True

    if "text/plain" in content_type:
        return text_sample_is_confidently_non_english(html_or_text)

    soup = BeautifulSoup(html_or_text, "html.parser")
    decision = html_language_decision(soup)
    if decision is not None:
        return not decision

    text = " ".join(soup.get_text(" ", strip=True).split())
    return bool(text) and text_sample_is_confidently_non_english(text)


def text_sample_is_confidently_non_english(text: str) -> bool:
    """Return True only for confident non-English text samples."""

    clean_text = " ".join(text.split())
    if not clean_text:
        return False

    words = re.findall(r"[a-zA-ZÀ-ÿ]{2,}", clean_text.lower())
    if len(words) < PREFLIGHT_MIN_WORDS:
        return False

    english_hits = sum(1 for word in words if word in ENGLISH_STOPWORDS)
    non_english_hits = sum(1 for word in words if word in NON_ENGLISH_STOPWORDS)
    if english_hits == 0 and non_english_hits >= 3:
        return True

    english_ratio = english_hits / len(words)
    non_english_ratio = non_english_hits / len(words)
    marker_ratio = non_english_marker_ratio(clean_text)
    marker_blocked = marker_ratio > PREFLIGHT_MAX_NON_ENGLISH_MARKER_RATIO
    stopword_blocked = non_english_ratio > PREFLIGHT_MAX_NON_ENGLISH_RATIO

    if english_ratio >= PREFLIGHT_MIN_ENGLISH_RATIO:
        return False

    return (marker_blocked or stopword_blocked) and non_english_hits >= english_hits


def non_english_marker_ratio(text: str) -> float:
    """Return ratio of region-specific letters in alphabetic text."""

    letters = [char for char in text if char.isalpha()]
    if not letters:
        return 0.0

    marker_count = sum(1 for char in letters if char in NON_ENGLISH_CHARACTER_MARKERS)
    return marker_count / len(letters)


def plain_text_to_html(text: str, url: str) -> str:
    """Wrap allowed plain text in minimal English HTML."""

    return (
        "<!doctype html>"
        '<html lang="en">'
        "<head>"
        f"<title>{escape(url)}</title>"
        "</head>"
        "<body>"
        f"<main><pre>{escape(text)}</pre></main>"
        "</body>"
        "</html>"
    )


def html_needs_playwright(html: str) -> bool:
    """Return True when static HTML looks like a JavaScript shell."""

    lowered = html.lower()
    if any(pattern in lowered for pattern in JS_REQUIRED_PATTERNS):
        return True

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    script_count = len(soup.find_all("script"))
    link_count = len(soup.find_all("a"))

    return len(text) < 160 and script_count >= 3 and not link_count > 3


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
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
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
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
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
