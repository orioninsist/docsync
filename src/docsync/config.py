"""Application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, cast

from docsync.url_security import validated_http_url

type CrawlerMode = Literal["http", "playwright"]
type BrowserType = Literal["chromium", "firefox", "webkit"]

DEFAULT_CRAWLER_MODE: Final[CrawlerMode] = "http"
DEFAULT_BROWSER_TYPE: Final[BrowserType] = "chromium"

VALID_CRAWLER_MODES: Final[frozenset[str]] = frozenset(
    {
        "http",
        "playwright",
    }
)

VALID_BROWSER_TYPES: Final[frozenset[str]] = frozenset(
    {
        "chromium",
        "firefox",
        "webkit",
    }
)

DEFAULT_REFRESH_HOURS = 0
MIN_REFRESH_HOURS = 0
MAX_REFRESH_HOURS = 8760

DEFAULT_REQUESTS_PER_MINUTE = 6
MIN_REQUESTS_PER_MINUTE = 1
MAX_REQUESTS_PER_MINUTE = 60

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings for the documentation crawler."""

    start_url: str
    output_dir: Path
    state_dir: Path
    log_dir: Path
    max_concurrency: int
    max_requests: int
    requests_per_minute: int
    request_timeout_seconds: int
    respect_robots_txt: bool
    language: str
    refresh_hours: int
    force_refresh: bool
    mode: CrawlerMode
    headless: bool
    browser_type: BrowserType

    @classmethod
    def from_environment(cls) -> Settings:
        """Build settings from environment variables."""

        settings = cls(
            start_url=os.getenv(
                "DOCSYNC_START_URL",
                "https://www.etsy.com/seller-handbook",
            ).strip(),
            output_dir=PROJECT_ROOT / os.getenv("DOCSYNC_OUTPUT_DIR", "data/markdown"),
            state_dir=PROJECT_ROOT / os.getenv("DOCSYNC_STATE_DIR", "data/state"),
            log_dir=PROJECT_ROOT / os.getenv("DOCSYNC_LOG_DIR", "logs"),
            max_concurrency=_read_positive_int(
                "DOCSYNC_MAX_CONCURRENCY",
                default=5,
            ),
            max_requests=_read_positive_int(
                "DOCSYNC_MAX_REQUESTS",
                default=10_000,
            ),
            request_timeout_seconds=_read_positive_int(
                "DOCSYNC_REQUEST_TIMEOUT_SECONDS",
                default=60,
            ),
            respect_robots_txt=_read_bool(
                "DOCSYNC_RESPECT_ROBOTS_TXT",
                default=True,
            ),
            language=os.getenv("DOCSYNC_LANGUAGE", "en").strip().lower(),
            requests_per_minute=_read_bounded_int(
                "DOCSYNC_REQUESTS_PER_MINUTE",
                DEFAULT_REQUESTS_PER_MINUTE,
                minimum=MIN_REQUESTS_PER_MINUTE,
                maximum=MAX_REQUESTS_PER_MINUTE,
            ),
            refresh_hours=int(
                os.environ.get(
                    "DOCSYNC_REFRESH_HOURS",
                    str(DEFAULT_REFRESH_HOURS),
                )
            ),
            force_refresh=os.environ.get("DOCSYNC_FORCE_REFRESH", "").strip().lower()
            in {"1", "true", "yes", "on"},
            mode=_normalize_crawler_mode(
                os.environ.get(
                    "DOCSYNC_MODE",
                    DEFAULT_CRAWLER_MODE,
                )
            ),
            headless=_read_bool(
                "DOCSYNC_HEADLESS",
                default=True,
            ),
            browser_type=_normalize_browser_type(
                os.environ.get(
                    "DOCSYNC_BROWSER_TYPE",
                    DEFAULT_BROWSER_TYPE,
                )
            ),
        )

        settings.validate()
        settings.create_runtime_directories()
        return settings

    def validate(self) -> None:
        if not MIN_REFRESH_HOURS <= self.refresh_hours <= MAX_REFRESH_HOURS:
            raise ValueError(
                "refresh_hours must be between "
                f"{MIN_REFRESH_HOURS} and {MAX_REFRESH_HOURS}."
            )

        """Validate configuration before starting the crawler."""

        if not (
            MIN_REQUESTS_PER_MINUTE
            <= self.requests_per_minute
            <= MAX_REQUESTS_PER_MINUTE
        ):
            raise ValueError(
                "requests_per_minute must be between "
                f"{MIN_REQUESTS_PER_MINUTE} and "
                f"{MAX_REQUESTS_PER_MINUTE}"
            )

        try:
            validated_http_url(self.start_url)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Invalid DOCSYNC_START_URL: {error}") from error

        if self.language not in {"en", "tr"}:
            raise ValueError("DOCSYNC_LANGUAGE must be 'en' or 'tr'.")

        if self.mode not in VALID_CRAWLER_MODES:
            raise ValueError("DOCSYNC_MODE must be 'http' or 'playwright'.")

        if self.browser_type not in VALID_BROWSER_TYPES:
            raise ValueError(
                "DOCSYNC_BROWSER_TYPE must be chromium, firefox, or webkit."
            )

    def create_runtime_directories(self) -> None:
        """Create directories required during execution."""

        for directory in (
            self.output_dir,
            self.state_dir,
            self.log_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def _read_positive_int(name: str, *, default: int) -> int:
    raw_value = os.getenv(name)

    if raw_value is None:
        return default

    try:
        value = int(raw_value)
    except ValueError as error:
        raise ValueError(
            f"{name} must be a positive integer, received {raw_value!r}."
        ) from error

    if value <= 0:
        raise ValueError(f"{name} must be greater than zero, received {value}.")

    return value


def _read_bounded_int(
    variable_name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    """Read an integer constrained to an inclusive range."""

    raw_value = os.environ.get(
        variable_name,
        str(default),
    ).strip()

    try:
        parsed_value = int(raw_value)
    except ValueError as error:
        raise ValueError(
            f"{variable_name} must be an integer between {minimum} and {maximum}"
        ) from error

    if not minimum <= parsed_value <= maximum:
        raise ValueError(f"{variable_name} must be between {minimum} and {maximum}")

    return parsed_value


def _read_bool(name: str, *, default: bool) -> bool:
    raw_value = os.getenv(name)

    if raw_value is None:
        return default

    normalized_value = raw_value.strip().lower()

    if normalized_value in {"1", "true", "yes", "on"}:
        return True

    if normalized_value in {"0", "false", "no", "off"}:
        return False

    raise ValueError(f"{name} must be true or false, received {raw_value!r}.")


def _normalize_crawler_mode(value: str) -> CrawlerMode:
    """Normalize and validate one crawler mode."""

    normalized = value.strip().lower()

    aliases = {
        "browser": "playwright",
        "javascript": "playwright",
        "js": "playwright",
    }
    normalized = aliases.get(
        normalized,
        normalized,
    )

    if normalized not in VALID_CRAWLER_MODES:
        raise ValueError("crawler mode must be 'http' or 'playwright'")

    return cast(
        CrawlerMode,
        normalized,
    )


def _normalize_browser_type(value: str) -> BrowserType:
    """Normalize and validate one Playwright browser engine."""

    normalized = value.strip().lower()

    if normalized not in VALID_BROWSER_TYPES:
        raise ValueError("browser type must be chromium, firefox, or webkit")

    return cast(
        BrowserType,
        normalized,
    )
