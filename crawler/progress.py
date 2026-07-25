"""Crawler dashboard state and Rich rendering."""

from __future__ import annotations

from datetime import datetime, timedelta

from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.table import Table


class RichDashboard:
    """Store crawler progress state and render it as a Rich panel."""

    def __init__(self, total_pages: int) -> None:
        self.total_pages: int = max(total_pages, 1)
        self.start_time: datetime = datetime.now()
        self.current_url: str = ""

        self.downloaded: int = 0
        self.updated: int = 0
        self.skipped: int = 0
        self.duplicates: int = 0
        self.errors: int = 0

        self.pending: int = 0
        self.queued: int = 0
        self.remaining_batches: int = 0

        self.step_current: int = 0
        self.step_total: int = 14
        self.step_name: str = "Crawler running"
        self.batch_current: int = 0
        self.batch_total: int = 0

    def set_pipeline_context(
        self,
        *,
        step_current: int,
        step_total: int,
        step_name: str,
        batch_current: int = 0,
        batch_total: int = 0,
    ) -> None:
        self.step_current = step_current
        self.step_total = step_total
        self.step_name = step_name
        self.batch_current = batch_current
        self.batch_total = batch_total

    def set_current_url(self, url: str) -> None:
        self.current_url = url

    def update_queue_context(
        self,
        *,
        pending: int,
        queued: int,
    ) -> None:
        self.pending = max(pending, 0)
        self.queued = max(queued, 0)
        self.remaining_batches = (
            (self.pending + self.total_pages - 1) // self.total_pages
            if self.total_pages > 0
            else 0
        )

    def increment(self, status: str) -> None:
        if status in {"downloaded", "updated", "restored"}:
            self.downloaded += 1
        elif status == "duplicate":
            self.duplicates += 1
        elif status == "error":
            self.errors += 1
        else:
            self.skipped += 1

    @property
    def processed(self) -> int:
        return self.downloaded + self.skipped + self.duplicates + self.errors

    def _stats(self) -> tuple[float, int, float, datetime]:
        elapsed = max(
            (datetime.now() - self.start_time).total_seconds(),
            1,
        )
        speed = self.processed / elapsed
        remaining = max(self.total_pages - self.processed, 0)
        eta_seconds = int(remaining / speed) if speed > 0 else 0
        percent = min(
            (self.processed / self.total_pages) * 100,
            100.0,
        )
        estimated_end = datetime.now() + timedelta(seconds=eta_seconds)

        return speed, eta_seconds, percent, estimated_end

    def terminal_line(
        self,
        *,
        status: str,
        url: str,
        pending: int,
        queued: int,
    ) -> str:
        """Build a file-log progress record without printing it."""

        self.update_queue_context(
            pending=pending,
            queued=queued,
        )
        speed, eta_seconds, percent, _ = self._stats()

        batch_text = ""

        if self.batch_current:
            if self.batch_total:
                batch_text = f" batch={self.batch_current}/{self.batch_total}"
            else:
                batch_text = f" batch={self.batch_current}"

        return (
            f"[PROGRESS]"
            f" step={self.step_current}/{self.step_total}"
            f"{batch_text}"
            f" status={status}"
            f" processed_batch={self.processed}/{self.total_pages}"
            f" percent_batch={percent:.2f}%"
            f" pending={self.pending}"
            f" queued={self.queued}"
            f" remaining_batches≈{self.remaining_batches}"
            f" downloaded={self.downloaded}"
            f" skipped={self.skipped}"
            f" duplicates={self.duplicates}"
            f" errors={self.errors}"
            f" speed={speed:.2f}/s"
            f" eta_batch={timedelta(seconds=eta_seconds)}"
            f" url={url}"
        )

    def render(self) -> Panel:
        """Render the complete dashboard without writing to the console."""

        speed, eta_seconds, percent, estimated_end = self._stats()

        table = Table(title="Docs Markdown Crawler Progress")
        table.add_column("Metric")
        table.add_column("Value")

        table.add_row(
            "Step",
            f"{self.step_current}/{self.step_total} - {self.step_name}",
        )

        if self.batch_current:
            if self.batch_total:
                table.add_row(
                    "Batch",
                    f"{self.batch_current}/{self.batch_total}",
                )
            else:
                table.add_row(
                    "Batch",
                    str(self.batch_current),
                )

        table.add_row(
            "Batch Progress",
            f"{self.processed} / {self.total_pages}",
        )
        table.add_row(
            "Batch Bar",
            ProgressBar(
                total=100,
                completed=percent,
            ),
        )
        table.add_row(
            "Batch Percentage",
            f"{percent:.2f}%",
        )

        table.add_row(
            "Database Queued Total",
            str(self.queued),
        )
        table.add_row(
            "Database Pending",
            str(self.pending),
        )
        table.add_row(
            "Estimated Remaining Batches",
            f"≈{self.remaining_batches}",
        )

        table.add_row(
            "Downloaded / Updated",
            str(self.downloaded),
        )
        table.add_row(
            "Skipped",
            str(self.skipped),
        )
        table.add_row(
            "Duplicates",
            str(self.duplicates),
        )
        table.add_row(
            "Errors",
            str(self.errors),
        )

        table.add_row(
            "Speed",
            f"{speed:.2f} pages/sec",
        )
        table.add_row(
            "Batch ETA",
            str(timedelta(seconds=eta_seconds)),
        )
        table.add_row(
            "Estimated Batch End",
            estimated_end.strftime("%Y-%m-%d %H:%M:%S"),
        )
        table.add_row(
            "Current URL",
            self.current_url or "-",
        )

        return Panel(table)


__all__ = ["RichDashboard"]
