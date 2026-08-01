"""Canonical crawl metrics, final summaries, and durable JSON reporting."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

CRAWL_REPORT_FILENAME: Final[str] = "crawl-report.json"


@dataclass(slots=True)
class CrawlStats:
    """Mutable metrics collected during one crawler execution."""

    mode: str
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    processed: int = 0
    saved: int = 0
    duplicate_content: int = 0
    rejected_urls: int = 0
    empty_pages: int = 0
    non_english: int = 0
    failed: int = 0
    sitemap_urls: int = 0
    sitemap_files_checked: int = 0
    sitemap_files_found: int = 0
    sitemap_errors: int = 0
    incremental_skipped: int = 0
    incremental_skipped_urls: set[str] = field(default_factory=set)

    def record_incremental_skip(self, url: str) -> bool:
        """Record one unique incremental skip.

        Returns ``True`` only when the URL was newly added.
        """

        normalized = url.strip()
        if not normalized or normalized in self.incremental_skipped_urls:
            return False

        self.incremental_skipped_urls.add(normalized)
        self.incremental_skipped = len(self.incremental_skipped_urls)
        return True

    def as_dict(self, *, finished_at: datetime | None = None) -> dict[str, Any]:
        """Return the stable JSON-compatible crawl metrics payload."""

        resolved_finished_at = finished_at or datetime.now(UTC)

        return {
            "started_at": self.started_at.astimezone(UTC).isoformat(),
            "finished_at": resolved_finished_at.astimezone(UTC).isoformat(),
            "mode": self.mode,
            "processed": self.processed,
            "saved": self.saved,
            "duplicate_content": self.duplicate_content,
            "rejected_urls": self.rejected_urls,
            "empty_pages": self.empty_pages,
            "non_english": self.non_english,
            "failed": self.failed,
            "sitemap_urls": self.sitemap_urls,
            "sitemap_files_checked": self.sitemap_files_checked,
            "sitemap_files_found": self.sitemap_files_found,
            "sitemap_errors": self.sitemap_errors,
            "incremental_skipped": self.incremental_skipped,
            "incremental_skipped_urls": sorted(self.incremental_skipped_urls),
        }

    def finished_summary(self) -> str:
        """Return the canonical machine-parseable final summary."""

        return (
            "Finished: "
            f"processed={self.processed} "
            f"saved={self.saved} "
            f"duplicate={self.duplicate_content} "
            f"incremental_skipped={self.incremental_skipped} "
            f"non_english={self.non_english} "
            f"failed={self.failed}"
        )

    @property
    def exit_code(self) -> int:
        """Return a process exit code derived from permanent failures."""

        return 0 if self.failed == 0 else 1


def build_crawl_report(
    *,
    stats: CrawlStats,
    configuration: Mapping[str, Any] | None = None,
    finished_at: datetime | None = None,
) -> dict[str, Any]:
    """Build the canonical crawl-report payload."""

    report: dict[str, Any] = {}

    if configuration is not None:
        report["configuration"] = {
            str(key): _json_compatible(value)
            for key, value in sorted(
                configuration.items(),
                key=lambda item: str(item[0]),
            )
        }

    report.update(stats.as_dict(finished_at=finished_at))
    return report


def write_crawl_report(
    *,
    output_dir: Path,
    stats: CrawlStats,
    configuration: Mapping[str, Any] | None = None,
    filename: str = CRAWL_REPORT_FILENAME,
    finished_at: datetime | None = None,
) -> Path:
    """Atomically write the canonical crawl report and return its path."""

    if not filename.strip():
        raise ValueError("filename must not be empty")

    resolved_output_dir = output_dir.expanduser().resolve()
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    report_path = resolved_output_dir / filename
    temporary_path = report_path.with_suffix(f"{report_path.suffix}.tmp")

    payload = build_crawl_report(
        stats=stats,
        configuration=configuration,
        finished_at=finished_at,
    )

    try:
        temporary_path.write_text(
            json.dumps(
                payload,
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


def _json_compatible(value: Any) -> Any:
    """Convert common configuration values into JSON-compatible values."""

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()

    if isinstance(value, Mapping):
        return {
            str(key): _json_compatible(item)
            for key, item in sorted(
                value.items(),
                key=lambda pair: str(pair[0]),
            )
        }

    if isinstance(value, (list, tuple)):
        return [_json_compatible(item) for item in value]

    if isinstance(value, (set, frozenset)):
        return sorted(_json_compatible(item) for item in value)

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    return str(value)
