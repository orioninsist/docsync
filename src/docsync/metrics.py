"""Minimal crawl outcome counters returned by DocsSync."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class CrawlStats:
    """Mutable product-level outcomes collected during one crawl."""

    mode: str
    processed: int = 0
    saved: int = 0
    rejected_urls: int = 0
    empty_pages: int = 0
    non_english: int = 0
    failed: int = 0
    sitemap_urls: int = 0
    incremental_skipped: int = 0
    incremental_skipped_urls: set[str] = field(default_factory=set)

    def finished_summary(self) -> str:
        """Return the concise CLI completion summary."""

        return (
            "Finished: "
            f"processed={self.processed} "
            f"saved={self.saved} "
            f"incremental_skipped={self.incremental_skipped} "
            f"non_english={self.non_english} "
            f"failed={self.failed}"
        )

    @property
    def exit_code(self) -> int:
        """Return non-zero when requests permanently failed."""

        return 0 if self.failed == 0 else 1
