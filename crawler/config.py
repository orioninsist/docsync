"""Crawler runtime configuration and validation defaults."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import ClassVar


def _positive_int(value: int, fallback: int) -> int:
    """Return fallback when an integer setting is not positive."""
    return value if value > 0 else fallback


def _minimum_int(value: int, minimum: int) -> int:
    """Return at least the configured integer minimum."""
    return max(value, minimum)


def _non_negative_int(value: int) -> int:
    """Return zero when an integer setting is negative."""
    return max(value, 0)


def _non_negative_float(value: float, fallback: float) -> float:
    """Return fallback for negative or non-finite floating-point values."""
    return value if isfinite(value) and value >= 0 else fallback


def _normalized_path_prefix(value: str) -> str:
    """Return a normalized absolute URL path prefix."""
    stripped = value.strip()

    if not stripped:
        return "/"

    return stripped if stripped.startswith("/") else f"/{stripped}"


@dataclass(frozen=True, slots=True)
class CrawlerConfig:  # pylint: disable=too-many-instance-attributes
    """Immutable crawler configuration with safe normalized defaults."""

    DEFAULT_MAX_PAGES: ClassVar[int] = 300
    DEFAULT_MAX_QUEUE_SIZE: ClassVar[int] = 10000
    DEFAULT_MAX_DEPTH: ClassVar[int] = 5

    DEFAULT_MIN_DELAY: ClassVar[float] = 1.5
    DEFAULT_MAX_DELAY: ClassVar[float] = 5.0

    MIN_CONCURRENT_REQUESTS: ClassVar[int] = 1
    MIN_MAX_RETRIES: ClassVar[int] = 1
    MIN_REQUEST_TIMEOUT_SECONDS: ClassVar[int] = 5
    MIN_PLAYWRIGHT_TIMEOUT_MS: ClassVar[int] = 5000
    MIN_SITEMAP_TIMEOUT_SECONDS: ClassVar[int] = 1

    start_url: str
    output_dir: Path = Path("output")
    db_path: Path = Path("state.db")
    logs_dir: Path = Path("logs")

    user_agent: str = (
        "DocsMarkdownCrawler/1.0 (compatible; respectful documentation crawler)"
    )

    min_delay: float = DEFAULT_MIN_DELAY
    max_delay: float = DEFAULT_MAX_DELAY
    max_retries: int = 3

    request_timeout: int = 30
    concurrent_requests: int = 1

    playwright_timeout_ms: int = 30000
    playwright_extra_wait_ms: int = 1500
    playwright_scroll_steps: int = 3
    playwright_content_selectors: tuple[str, ...] = (
        "main",
        "article",
        "[role='main']",
        ".content",
        ".documentation",
        ".docs-content",
        ".doc-content",
        ".markdown-body",
        ".article-content",
        ".post-content",
        ".entry-content",
        "h1",
    )

    allowed_path_prefix: str = "/"
    require_english: bool = True

    proceed_delay_seconds: int = 5

    recursive_discovery: bool = True
    use_sitemap_discovery: bool = True

    allow_official_cross_host_discovery: bool = True
    max_official_cross_host_links_per_page: int = 25
    sitemap_discovery_timeout_seconds: int = 10
    max_pages: int = DEFAULT_MAX_PAGES
    max_queue_size: int = DEFAULT_MAX_QUEUE_SIZE
    max_depth: int = DEFAULT_MAX_DEPTH

    auto_continue_until_complete: bool = True
    max_auto_batches: int = 0
    batch_pause_seconds: int = 10

    def __post_init__(self) -> None:
        """Validate required values and normalize unsafe configuration."""
        self._normalize_start_url()
        self._normalize_limit_settings()
        self._normalize_request_settings()
        self._normalize_playwright_settings()
        self._normalize_discovery_settings()
        self._normalize_queue_settings()

    def _normalize_start_url(self) -> None:
        """Strip surrounding whitespace from the required seed URL."""
        normalized_url = self.start_url.strip()

        if not normalized_url:
            raise ValueError("start_url must not be empty.")

        object.__setattr__(self, "start_url", normalized_url)

    def _normalize_limit_settings(self) -> None:
        """Normalize crawler page, queue, and depth limits."""
        object.__setattr__(
            self,
            "max_pages",
            _positive_int(self.max_pages, self.DEFAULT_MAX_PAGES),
        )
        object.__setattr__(
            self,
            "max_queue_size",
            _positive_int(self.max_queue_size, self.DEFAULT_MAX_QUEUE_SIZE),
        )
        object.__setattr__(
            self,
            "max_depth",
            _positive_int(self.max_depth, self.DEFAULT_MAX_DEPTH),
        )

    def _normalize_request_settings(self) -> None:
        """Normalize lightweight HTTP request settings."""
        object.__setattr__(
            self,
            "concurrent_requests",
            _minimum_int(
                self.concurrent_requests,
                self.MIN_CONCURRENT_REQUESTS,
            ),
        )
        object.__setattr__(
            self,
            "min_delay",
            _non_negative_float(
                self.min_delay,
                self.DEFAULT_MIN_DELAY,
            ),
        )
        object.__setattr__(
            self,
            "max_delay",
            _non_negative_float(
                self.max_delay,
                self.DEFAULT_MAX_DELAY,
            ),
        )
        object.__setattr__(
            self,
            "max_retries",
            _minimum_int(
                self.max_retries,
                self.MIN_MAX_RETRIES,
            ),
        )
        object.__setattr__(
            self,
            "request_timeout",
            _minimum_int(
                self.request_timeout,
                self.MIN_REQUEST_TIMEOUT_SECONDS,
            ),
        )
        self._normalize_delay_range()

    def _normalize_delay_range(self) -> None:
        """Ensure maximum request delay is not lower than minimum delay."""
        if self.max_delay < self.min_delay:
            object.__setattr__(self, "max_delay", self.min_delay)

    def _normalize_playwright_settings(self) -> None:
        """Normalize browser-rendering timeout and scroll settings."""
        object.__setattr__(
            self,
            "playwright_timeout_ms",
            _minimum_int(
                self.playwright_timeout_ms,
                self.MIN_PLAYWRIGHT_TIMEOUT_MS,
            ),
        )
        object.__setattr__(
            self,
            "playwright_extra_wait_ms",
            _non_negative_int(self.playwright_extra_wait_ms),
        )
        object.__setattr__(
            self,
            "playwright_scroll_steps",
            _non_negative_int(self.playwright_scroll_steps),
        )

    def _normalize_discovery_settings(self) -> None:
        """Normalize discovery timeout and allowed path prefix settings."""
        object.__setattr__(
            self,
            "sitemap_discovery_timeout_seconds",
            _minimum_int(
                self.sitemap_discovery_timeout_seconds,
                self.MIN_SITEMAP_TIMEOUT_SECONDS,
            ),
        )
        object.__setattr__(
            self,
            "max_official_cross_host_links_per_page",
            _non_negative_int(self.max_official_cross_host_links_per_page),
        )
        object.__setattr__(
            self,
            "allowed_path_prefix",
            _normalized_path_prefix(self.allowed_path_prefix),
        )

    def _normalize_queue_settings(self) -> None:
        """Normalize queue approval and batch continuation settings."""
        object.__setattr__(
            self,
            "proceed_delay_seconds",
            _non_negative_int(self.proceed_delay_seconds),
        )
        object.__setattr__(
            self,
            "max_auto_batches",
            _non_negative_int(self.max_auto_batches),
        )
        object.__setattr__(
            self,
            "batch_pause_seconds",
            _non_negative_int(self.batch_pause_seconds),
        )
