"""Crawler engine status and terminal output helpers.

This module owns small presentation/status utilities that do not require
crawler orchestration state. Keeping them here prevents `crawler_engine.py`
from becoming the owner of unrelated formatting and dashboard merge logic.
"""

from __future__ import annotations

from crawler.progress import RichDashboard


def merge_dashboard(target: RichDashboard, source: RichDashboard) -> None:
    """Merge counters from one dashboard into another dashboard."""

    target.downloaded += source.downloaded
    target.updated += source.updated
    target.skipped += source.skipped
    target.duplicates += source.duplicates
    target.errors += source.errors
    target.total_pages = max(target.total_pages, target.processed)


def format_unlimited(value: int) -> str:
    """Format non-positive limits as an unlimited value."""

    if value <= 0:
        return "unlimited"

    return str(value)


def print_batch_banner(
    *,
    batch_number: int,
    pending_before_batch: int,
    batch_page_limit: int,
    estimated_total_batches: int,
) -> None:
    """Print a terminal banner for an automatic crawl batch."""

    print()
    print(f"Auto Batch {batch_number}")
    print("----------------")
    print(f"Pending before batch: {pending_before_batch}")
    print(f"Batch page limit: {batch_page_limit}")
    print(f"Estimated batches remaining now: {estimated_total_batches}")
    print()
