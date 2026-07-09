"""Terminal reporting helpers for crawler final run summaries."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class RunSummaryDashboard(Protocol):
    """Minimal dashboard shape required for final run summary output."""

    @property
    def processed(self) -> int:
        """Number of URLs processed by the current command."""

    @property
    def downloaded(self) -> int:
        """Number of URLs downloaded, updated, or restored by the current command."""

    @property
    def skipped(self) -> int:
        """Number of URLs skipped by the current command."""

    @property
    def duplicates(self) -> int:
        """Number of duplicate URLs found by the current command."""

    @property
    def errors(self) -> int:
        """Number of errors seen by the current command."""


@dataclass(frozen=True, slots=True)
class RunSummaryQueueCounts:
    """Queue status counters used by final run summary rendering."""

    pending: int
    done: int
    processing: int
    errors: int
    queued: int


@dataclass(frozen=True, slots=True)
class RunSummaryPaths:
    """Filesystem paths displayed in final run summary output."""

    output_dir: Path
    db_path: Path
    log_file: Path


def build_run_summary_queue_counts(
    *,
    raw_queue_counts: dict[str, int],
    queued: int,
) -> RunSummaryQueueCounts:
    """Normalize database queue counters for summary rendering."""
    return RunSummaryQueueCounts(
        pending=raw_queue_counts.get("pending", 0),
        done=raw_queue_counts.get("done", 0),
        processing=raw_queue_counts.get("processing", 0),
        errors=raw_queue_counts.get("error", 0),
        queued=queued,
    )


def print_final_run_summary(
    *,
    dashboard: RunSummaryDashboard,
    queue_counts: RunSummaryQueueCounts,
    paths: RunSummaryPaths,
    max_pages: int,
) -> None:
    """Print final crawler run summary without owning crawler orchestration."""
    print()
    print("Run Summary")
    print("-----------")
    print(f"This command processed: {dashboard.processed}")
    print(f"This command downloaded/updated/restored: {dashboard.downloaded}")
    print(f"This command skipped: {dashboard.skipped}")
    print(f"This command duplicates: {dashboard.duplicates}")
    print(f"This command errors: {dashboard.errors}")
    print(f"Database queued total: {queue_counts.queued}")
    print(f"Database queue done: {queue_counts.done}")
    print(f"Database queue pending: {queue_counts.pending}")
    print(f"Database queue processing: {queue_counts.processing}")
    print(f"Database queue error: {queue_counts.errors}")
    print(f"Output directory: {paths.output_dir}")
    print(f"Database file: {paths.db_path}")
    print(f"Log file: {paths.log_file}")

    if queue_counts.pending > 0:
        remaining_runs = math.ceil(queue_counts.pending / max(max_pages, 1))

        print()
        print("STATUS: INCOMPLETE - QUEUE STILL HAS PENDING URLS")
        print(f"Approximate additional batch count: {remaining_runs}")
        print(
            "If auto_continue_until_complete is true and this message still appears, "
            "the stop reason is usually max_auto_batches, max_queue_size, a crash, "
            "or no processable pending item. Re-running the same Podman/just command "
            "continues from the database without duplicating existing Markdown."
        )
        return

    if queue_counts.errors > 0:
        print()
        print("STATUS: FINISHED WITH ERRORS")
        print(
            "No pending URL remains, but some URLs failed. Check the crawler.log "
            "file for details. Re-running will not duplicate existing Markdown."
        )
        return

    print()
    print("STATUS: COMPLETE")
    print(
        "No pending URL remains. The current crawl queue is complete. "
        "Weekly or later re-runs will only update changed pages, restore missing "
        "Markdown files, and skip duplicates by URL, final URL, canonical URL, "
        "redirect target, and content hash."
    )
