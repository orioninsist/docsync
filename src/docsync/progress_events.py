"""Typed crawl lifecycle events shared by crawler and terminal UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class CrawlEvent:
    """One immutable crawler lifecycle event."""

    phase: str | None = None
    current_url: str | None = None
    current_title: str | None = None
    processed: int | None = None
    saved: int | None = None
    duplicate_content: int | None = None
    incremental_skipped: int | None = None
    rejected_urls: int | None = None
    empty_pages: int | None = None
    non_english: int | None = None
    failed: int | None = None
    queued: int | None = None
    discovered: int | None = None
    active_requests: int | None = None
    sitemap_urls: int | None = None
    sitemap_files_checked: int | None = None
    sitemap_files_found: int | None = None
    sitemap_errors: int | None = None
    site_title: str | None = None


class CrawlEventSink(Protocol):
    """Callable receiving crawler lifecycle events."""

    def __call__(
        self,
        event: CrawlEvent,
    ) -> None:
        """Receive one crawler lifecycle event."""
