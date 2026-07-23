"""Crawler engine status helpers.

This module owns status utilities that do not require crawler orchestration
state. Terminal rendering belongs exclusively to ``TerminalUI`` so automatic
crawl batches cannot create additional output below the persistent Rich Live
dashboard.
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
    """Preserve the legacy call boundary without emitting terminal output.

    Runtime presentation is owned exclusively by ``TerminalUI`` and the
    persistent Rich Live dashboard. Printing a separate banner for every
    automatic batch would force the terminal to scroll and create multiple
    visual progress sections.

    The parameters remain explicit so existing crawler orchestration calls
    stay backward compatible until the legacy boundary is removed separately.
    """

    del (
        batch_number,
        pending_before_batch,
        batch_page_limit,
        estimated_total_batches,
    )
