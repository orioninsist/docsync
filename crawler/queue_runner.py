"""Run the persistent recursive crawler database queue."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable

from crawler.config import CrawlerConfig
from crawler.database import DatabaseManager
from crawler.progress import RichDashboard
from crawler.sitemap import SitemapManager
from crawler.terminal_ui import TerminalUI, TerminalUIHandle


DatabaseQueueBatchRunner = Callable[
    [
        SitemapManager,
        int,
        RichDashboard,
        TerminalUIHandle,
    ],
    Awaitable[RichDashboard],
]


class QueueRunner:
    """Coordinate recursive queue batches inside one terminal display."""

    def __init__(
        self,
        *,
        config: CrawlerConfig,
        database: DatabaseManager,
        terminal_ui: TerminalUI,
        run_database_queue_batch: DatabaseQueueBatchRunner,
        logger: logging.Logger,
    ) -> None:
        self._config: CrawlerConfig = config
        self._database: DatabaseManager = database
        self._terminal_ui: TerminalUI = terminal_ui
        self._run_database_queue_batch: DatabaseQueueBatchRunner = (
            run_database_queue_batch
        )
        self._logger: logging.Logger = logger

    async def run(
        self,
        sitemap: SitemapManager,
    ) -> RichDashboard:
        """Process queued URLs until completion or configured stop."""

        initial_pending = self._database.pending_queue_count()
        dashboard = self._create_dashboard(initial_pending)
        batch_number = 0

        with self._terminal_ui.open(
            dashboard,
            refresh_per_second=4,
        ) as live:
            while True:
                pending_before_batch = self._database.pending_queue_count()

                self._refresh_queue_dashboard(
                    dashboard=dashboard,
                    live=live,
                    pending=pending_before_batch,
                )

                if pending_before_batch <= 0:
                    break

                if self._maximum_batch_count_reached(
                    batch_number=batch_number,
                    pending=pending_before_batch,
                ):
                    break

                batch_number += 1
                estimated_total_batches = self._estimate_total_batches(
                    batch_number=batch_number,
                    pending=pending_before_batch,
                )

                self._show_batch_started(
                    dashboard=dashboard,
                    live=live,
                    batch_number=batch_number,
                    estimated_total_batches=estimated_total_batches,
                )

                processed_before_batch = dashboard.processed

                dashboard = await self._run_database_queue_batch(
                    sitemap,
                    batch_number,
                    dashboard,
                    live,
                )

                pending_after_batch = self._database.pending_queue_count()
                processed_in_batch = dashboard.processed - processed_before_batch

                self._refresh_queue_dashboard(
                    dashboard=dashboard,
                    live=live,
                    pending=pending_after_batch,
                )

                if pending_after_batch <= 0:
                    break

                if not self._config.auto_continue_until_complete:
                    break

                self._ensure_batch_made_progress(
                    batch_number=batch_number,
                    processed_in_batch=processed_in_batch,
                    pending_before=pending_before_batch,
                    pending_after=pending_after_batch,
                )

                await self._pause_before_next_batch(
                    dashboard=dashboard,
                    live=live,
                    batch_number=batch_number,
                    estimated_total_batches=estimated_total_batches,
                )

            self._show_final_state(
                dashboard=dashboard,
                live=live,
                batch_number=batch_number,
            )

        return dashboard

    def _create_dashboard(
        self,
        initial_pending: int,
    ) -> RichDashboard:
        dashboard = RichDashboard(total_pages=max(initial_pending, 1))
        dashboard.set_pipeline_context(
            step_current=6,
            step_total=14,
            step_name="Preparing crawl queue",
            batch_current=0,
            batch_total=0,
        )
        dashboard.update_queue_context(
            pending=initial_pending,
            queued=self._database.queued_count(),
        )
        return dashboard

    def _refresh_queue_dashboard(
        self,
        *,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
        pending: int,
    ) -> None:
        dashboard.total_pages = max(
            dashboard.total_pages,
            dashboard.processed + pending,
            1,
        )
        dashboard.update_queue_context(
            pending=pending,
            queued=self._database.queued_count(),
        )
        live.update(dashboard.render(), refresh=True)

    def _maximum_batch_count_reached(
        self,
        *,
        batch_number: int,
        pending: int,
    ) -> bool:
        max_auto_batches = self._config.max_auto_batches

        if max_auto_batches <= 0:
            return False

        if batch_number < max_auto_batches:
            return False

        self._logger.warning(
            (
                "Max auto batches reached, stopping command: "
                "batches=%s pending=%s max_auto_batches=%s"
            ),
            batch_number,
            pending,
            max_auto_batches,
        )
        return True

    def _estimate_total_batches(
        self,
        *,
        batch_number: int,
        pending: int,
    ) -> int:
        remaining_batches = max(
            math.ceil(pending / max(self._config.max_pages, 1)) - 1,
            0,
        )
        return batch_number + remaining_batches

    @staticmethod
    def _show_batch_started(
        *,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
        batch_number: int,
        estimated_total_batches: int,
    ) -> None:
        dashboard.set_pipeline_context(
            step_current=6,
            step_total=14,
            step_name="Crawling queued URLs",
            batch_current=batch_number,
            batch_total=estimated_total_batches,
        )
        live.update(dashboard.render(), refresh=True)

    def _ensure_batch_made_progress(
        self,
        *,
        batch_number: int,
        processed_in_batch: int,
        pending_before: int,
        pending_after: int,
    ) -> None:
        if processed_in_batch > 0:
            return

        message = (
            "Crawler queue stalled while pending URLs remain: "
            f"batch={batch_number} "
            f"processed={processed_in_batch} "
            f"pending_before={pending_before} "
            f"pending_after={pending_after}"
        )
        self._logger.critical(message)
        raise RuntimeError(message)

    async def _pause_before_next_batch(
        self,
        *,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
        batch_number: int,
        estimated_total_batches: int,
    ) -> None:
        pause_seconds = self._config.batch_pause_seconds

        if pause_seconds <= 0:
            return

        dashboard.set_pipeline_context(
            step_current=6,
            step_total=14,
            step_name=(f"Waiting before next automatic batch ({pause_seconds}s)"),
            batch_current=batch_number,
            batch_total=estimated_total_batches,
        )
        live.update(dashboard.render(), refresh=True)
        await asyncio.sleep(pause_seconds)

    def _show_final_state(
        self,
        *,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
        batch_number: int,
    ) -> None:
        final_pending = self._database.pending_queue_count()
        final_step_name = (
            "Finished" if final_pending <= 0 else "Stopped with pending queue items"
        )

        dashboard.total_pages = max(
            dashboard.total_pages,
            dashboard.processed,
            1,
        )
        dashboard.update_queue_context(
            pending=final_pending,
            queued=self._database.queued_count(),
        )
        dashboard.set_pipeline_context(
            step_current=14,
            step_total=14,
            step_name=final_step_name,
            batch_current=batch_number,
            batch_total=max(batch_number, 1),
        )
        live.update(dashboard.render(), refresh=True)
