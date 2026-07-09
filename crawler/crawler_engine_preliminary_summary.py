"""Preliminary crawler run summary rendering helpers."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Mapping


@dataclass(frozen=True, slots=True)
class PreliminarySummaryCounts:
    """Queue and recovery counters shown before crawl execution starts."""

    sitemap_pages_found: int
    seed_pages_queued: int
    total_queued_urls: int
    queue_status_counts: Mapping[str, int]
    interrupted_items_restored: int
    missing_markdown_outputs_restored: int


@dataclass(frozen=True, slots=True)
class PreliminarySummaryConfig:
    """Crawler configuration values shown in the preliminary run summary."""

    recursive_discovery: bool
    max_pages: int
    auto_continue_until_complete: bool


def calculate_estimated_batches(pending_count: int, max_pages: int) -> int:
    """Return the estimated number of crawl batches for pending URLs."""

    safe_max_pages = max(max_pages, 1)
    return ceil(pending_count / safe_max_pages)


def print_preliminary_summary(
    counts: PreliminarySummaryCounts,
    config: PreliminarySummaryConfig,
) -> None:
    """Print the preliminary crawler run summary."""

    pending_count = counts.queue_status_counts.get("pending", 0)
    estimated_batches = calculate_estimated_batches(
        pending_count=pending_count,
        max_pages=config.max_pages,
    )

    print()
    print("Preliminary Summary")
    print("-------------------")
    print(f"Sitemap pages found: {counts.sitemap_pages_found}")
    print(f"Seed pages queued: {counts.seed_pages_queued}")
    print(f"Total queued URLs: {counts.total_queued_urls}")
    print(f"Queue pending: {pending_count}")
    print(f"Queue done: {counts.queue_status_counts.get('done', 0)}")
    print(f"Queue error: {counts.queue_status_counts.get('error', 0)}")
    print(f"Interrupted items restored to pending: {counts.interrupted_items_restored}")
    print(
        "Missing Markdown outputs restored to pending: "
        f"{counts.missing_markdown_outputs_restored}"
    )
    print(f"Recursive discovery: {config.recursive_discovery}")
    print(f"Max pages per batch: {config.max_pages}")
    print(f"Auto continue until complete: {config.auto_continue_until_complete}")
    print(f"Estimated batches: {estimated_batches}")
