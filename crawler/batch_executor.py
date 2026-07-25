"""Execution service for processing one persistent crawler queue batch."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import Awaitable, Callable
from typing import cast

from crawler.config import CrawlerConfig
from crawler.database import DatabaseManager
from crawler.progress import RichDashboard
from crawler.sitemap import SitemapManager
from crawler.terminal_ui import TerminalUIHandle

UrlProcessor = Callable[
    [
        str,
        int,
        RichDashboard,
        TerminalUIHandle,
        SitemapManager,
        bool,
    ],
    Awaitable[None],
]


class BatchExecutor:
    """Process pending database queue rows within one configured batch."""

    def __init__(
        self,
        *,
        config: CrawlerConfig,
        database: DatabaseManager,
        process_url: UrlProcessor,
        logger: logging.Logger,
    ) -> None:
        self._config: CrawlerConfig = config
        self._database: DatabaseManager = database
        self._process_url: UrlProcessor = process_url
        self._logger: logging.Logger = logger

    async def run(
        self,
        sitemap: SitemapManager,
        batch_number: int,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
    ) -> RichDashboard:
        """Process one queue batch using the caller-owned Live display."""

        pending_count = self._database.pending_queue_count()

        if pending_count <= 0:
            self._logger.info(
                "Skipped empty crawl batch: batch=%s",
                batch_number,
            )
            return dashboard

        processed_at_batch_start = dashboard.processed
        batch_page_limit = max(self._config.max_pages, 1)

        while self._batch_has_capacity(
            dashboard=dashboard,
            processed_at_batch_start=processed_at_batch_start,
            batch_page_limit=batch_page_limit,
            batch_number=batch_number,
        ):
            pending_rows = self._load_pending_rows(
                dashboard=dashboard,
                processed_at_batch_start=processed_at_batch_start,
                batch_page_limit=batch_page_limit,
            )

            if not pending_rows:
                break

            self._refresh_dashboard(
                dashboard=dashboard,
                live=live,
                pending_rows=pending_rows,
            )

            tasks = self._build_tasks(
                pending_rows=pending_rows,
                dashboard=dashboard,
                live=live,
                sitemap=sitemap,
            )

            results = await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )

            self._handle_task_results(
                results=results,
                batch_number=batch_number,
            )

            live.update(dashboard.render(), refresh=True)

        return dashboard

    def _batch_has_capacity(
        self,
        *,
        dashboard: RichDashboard,
        processed_at_batch_start: int,
        batch_page_limit: int,
        batch_number: int,
    ) -> bool:
        processed_in_batch = dashboard.processed - processed_at_batch_start

        if processed_in_batch < batch_page_limit:
            return True

        self._logger.info(
            (
                "Max pages per batch reached: "
                "batch=%s processed=%s max_pages=%s "
                "pending=%s queued=%s"
            ),
            batch_number,
            processed_in_batch,
            self._config.max_pages,
            self._database.pending_queue_count(),
            self._database.queued_count(),
        )
        return False

    def _load_pending_rows(
        self,
        *,
        dashboard: RichDashboard,
        processed_at_batch_start: int,
        batch_page_limit: int,
    ) -> list[sqlite3.Row]:
        processed_in_batch = dashboard.processed - processed_at_batch_start
        remaining_page_budget = batch_page_limit - processed_in_batch

        if remaining_page_budget <= 0:
            return []

        pending_rows = self._database.fetch_pending_urls(
            limit=self._config.concurrent_requests
        )

        if not pending_rows:
            return []

        return pending_rows[:remaining_page_budget]

    def _refresh_dashboard(
        self,
        *,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
        pending_rows: list[sqlite3.Row],
    ) -> None:
        current_pending = self._database.pending_queue_count()

        dashboard.total_pages = max(
            dashboard.total_pages,
            dashboard.processed + current_pending,
            dashboard.processed + len(pending_rows),
            1,
        )
        dashboard.update_queue_context(
            pending=current_pending,
            queued=self._database.queued_count(),
        )
        live.update(dashboard.render(), refresh=True)

    def _build_tasks(
        self,
        *,
        pending_rows: list[sqlite3.Row],
        dashboard: RichDashboard,
        live: TerminalUIHandle,
        sitemap: SitemapManager,
    ) -> list[Awaitable[None]]:
        tasks: list[Awaitable[None]] = []

        for row in pending_rows:
            url = cast(str, row["url"])
            url_hash = cast(str, row["url_hash"])
            depth = cast(int, row["depth"])

            self._database.mark_queue_status(
                url_hash=url_hash,
                status="processing",
            )

            tasks.append(
                self._process_url(
                    url,
                    depth,
                    dashboard,
                    live,
                    sitemap,
                    True,
                )
            )

        return tasks

    def _handle_task_results(
        self,
        *,
        results: list[None | BaseException],
        batch_number: int,
    ) -> None:
        fatal_errors: list[BaseException] = []

        for result in results:
            if not isinstance(result, BaseException):
                continue

            self._logger.error(
                "Isolated URL task failed inside batch %s",
                batch_number,
                exc_info=(
                    type(result),
                    result,
                    result.__traceback__,
                ),
            )
            fatal_errors.append(result)

        if fatal_errors and len(fatal_errors) == len(results):
            raise RuntimeError(
                "Every URL task failed in the current batch"
            ) from fatal_errors[0]
