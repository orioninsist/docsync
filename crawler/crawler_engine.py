"""Crawler orchestration engine for fetching, parsing, deduplicating, and writing pages.

from typing import Any
This module coordinates crawl lifecycle operations while delegating network access,
content parsing, deduplication, and persistence to specialized collaborators.
"""

# pylint: disable=too-many-lines
from __future__ import annotations

from crawler.url_processor import UrlProcessor
from crawler.crawler_engine_run_summary import (
    RunSummaryPaths,
    build_run_summary_queue_counts,
)
import asyncio
import logging
import math
from dataclasses import dataclass
from typing import TypedDict
from pathlib import Path
from urllib.parse import urlparse

from crawler.terminal_ui import (
    TerminalUI,
    TerminalUIHandle,
)

from crawler.config import CrawlerConfig
from crawler.crawler_discovery import CrawlerDiscoveryService
from crawler.crawler_context import CrawlerRuntimeContext
from crawler.database import DatabaseManager
from crawler.dedup import DeduplicationEngine, DedupResult
from crawler.engine_status import format_unlimited, merge_dashboard, print_batch_banner
from crawler.fetcher import AsyncFetcher, FetchResult
from crawler.intent_analyzer import IntentAnalyzer
from crawler.language import LanguageDetector
from crawler.markdown_writer import MarkdownWriter
from crawler.observability import CrawlerObservability
from crawler.official_graph import OfficialHostGraph
from crawler.page_quality import PageQualityAnalyzer
from crawler.parser import ContentParser, ParsedPage
from crawler.policy_engine import PolicyDecision, SmartScopePolicy
from crawler.progress import RichDashboard
from crawler.robots import RobotsManager
from crawler.shared.url_normalizer import (
    normalize_optional_url,
    normalize_url,
)
from crawler.shared.url_ownership import claim_url_ownership
from crawler.sitemap import SitemapManager
from crawler.global_url_registry import GlobalUrlRegistry


@dataclass(frozen=True, slots=True)
class EmptyRefetchStatusUpdate:  # pylint: disable=too-many-instance-attributes
    """Status payload for an empty forced refetch after an HTTP 304 response."""

    url: str
    url_hash: str
    final_url: str
    final_url_hash: str
    redirect_target_hash: str
    status_code: int
    fallback_status: str
    etag: str | None
    last_modified: str | None


@dataclass(frozen=True)
class SkippedPageStatusUpdate:  # pylint: disable=too-many-instance-attributes,too-few-public-methods
    """Database and queue update payload for skipped page outcomes."""

    url: str
    url_hash: str
    status: str
    final_url: str
    final_url_hash: str
    redirect_target_hash: str | None
    canonical_url: str | None = None
    content_hash: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    queue_status: str = "done"
    dashboard_status: str = "skipped"


class CrawlerRunRuntime(TypedDict):
    """Strongly typed values prepared before crawl execution."""

    interrupted_count: int
    repaired_missing_outputs: int
    sitemap: SitemapManager
    sitemap_urls: list[str]
    seed_urls: list[str]


class CrawlerEngine:  # pylint: disable=too-many-instance-attributes,too-few-public-methods
    """Coordinate crawling workflow, persistence, parsing, and runtime services."""

    # Dependency wiring constructor for crawler orchestration.
    # pylint: disable=too-many-statements
    def __init__(self, config: CrawlerConfig) -> None:
        self.config = config
        self.logger = self._build_logger()
        self.terminal_ui = TerminalUI()

        self.database = DatabaseManager(config.db_path)
        self.robots = RobotsManager(config)
        self.fetcher = AsyncFetcher(config, logger=self.logger)
        self.intent_analyzer = IntentAnalyzer()
        self.parser = ContentParser()
        self.language = LanguageDetector()
        self.dedup = DeduplicationEngine(self.database)
        self.writer = MarkdownWriter(config.output_dir)
        self.policy = SmartScopePolicy(
            start_url=config.start_url,
            allowed_path_prefix=config.allowed_path_prefix,
        )

        self.start_netloc = urlparse(config.start_url).netloc.lower()
        self.owner_project = self._owner_project_name()
        self.global_url_registry = GlobalUrlRegistry()
        self.official_graph = OfficialHostGraph(
            seed_url=config.start_url,
            owner_project=self.owner_project,
        )
        self.observability = CrawlerObservability(
            logs_dir=config.logs_dir,
            start_url=config.start_url,
        )
        self.runtime_context = CrawlerRuntimeContext(
            output_dir=config.output_dir,
            database=self.database,
            logger=self.logger,
            config=self.config,
        )
        self.page_quality = PageQualityAnalyzer()
        self.discovery = CrawlerDiscoveryService(
            config=self.config,
            database=self.database,
            robots=self.robots,
            dedup=self.dedup,
            intent_analyzer=self.intent_analyzer,
            policy=self.policy,
            official_graph=self.official_graph,
            observability=self.observability,
            global_url_registry=self.global_url_registry,
            owner_project=self.owner_project,
            logger=self.logger,
        )
        self.url_processor = UrlProcessor(self)

    def _owner_project_name(self) -> str:
        output_root = Path("output")

        try:
            return self.config.output_dir.relative_to(output_root).as_posix()
        except ValueError:
            return self.config.output_dir.name

    def _build_logger(self) -> logging.Logger:
        self.config.logs_dir.mkdir(parents=True, exist_ok=True)

        logger_name = f"crawler.{self.config.logs_dir.as_posix()}"
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.INFO)
        logger.propagate = False

        if logger.handlers:
            return logger

        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        file_handler = logging.FileHandler(
            self.config.logs_dir / "crawler.log",
            encoding="utf-8",
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)

        logger.addHandler(file_handler)

        return logger

    async def run(self) -> None:
        """Run the crawler until configured crawl limits or queue exhaustion."""
        try:
            self.logger.info("Crawler started: %s", self.config.start_url)

            runtime = await self._prepare_run_runtime()
            self._print_preliminary_run_summary(runtime)

            has_crawl_work = (
                self.database.pending_queue_count() > 0
                if self.config.recursive_discovery
                else bool(runtime["seed_urls"])
            )

            if has_crawl_work:
                if self.config.proceed_delay_seconds > 0:
                    await asyncio.sleep(self.config.proceed_delay_seconds)

                self._print_terminal_banner()
            else:
                message = (
                    "Crawl queue is empty. Skipping startup delay and "
                    "runtime progress display."
                )
                print(message, flush=True)
                self.logger.info(message)

            dashboard = await self._execute_crawl(
                runtime["sitemap"], runtime["seed_urls"]
            )
            self._finalize_successful_run(dashboard)

            self.logger.info("Crawler finished: %s", self.config.start_url)

        except Exception:
            self.logger.exception(
                "Crawler crashed before normal completion: %s",
                self.config.start_url,
            )
            raise

        finally:
            await self.fetcher.close()
            self.official_graph.close()
            self.global_url_registry.close()
            self.database.close()

    async def _prepare_run_runtime(self) -> CrawlerRunRuntime:
        interrupted_count = self.database.reset_interrupted_processing()
        repaired_missing_outputs = self._repair_missing_markdown_outputs()

        await self.robots.load()
        self._apply_robots_delay()

        sitemap = SitemapManager(self.config, self.robots)
        sitemap_urls = await self._discover_sitemap_urls(sitemap)
        seed_urls = self._prepare_seed_urls(sitemap, sitemap_urls)

        return {
            "interrupted_count": interrupted_count,
            "repaired_missing_outputs": repaired_missing_outputs,
            "sitemap": sitemap,
            "sitemap_urls": sitemap_urls,
            "seed_urls": seed_urls,
        }

    async def _discover_sitemap_urls(
        self,
        sitemap: SitemapManager,
    ) -> list[str]:
        sitemap_urls: list[str] = []

        if not self.config.use_sitemap_discovery:
            return sitemap_urls

        self.logger.info(
            "Starting sitemap discovery with timeout=%ss",
            self.config.sitemap_discovery_timeout_seconds,
        )
        print(
            (
                "Sitemap discovery started. Timeout: "
                f"{self.config.sitemap_discovery_timeout_seconds}s"
            ),
            flush=True,
        )

        try:
            sitemap_urls = await asyncio.wait_for(
                sitemap.discover_urls(),
                timeout=self.config.sitemap_discovery_timeout_seconds,
            )
            self.logger.info(
                "Sitemap discovery finished. URLs=%s",
                len(sitemap_urls),
            )
            print(
                f"Sitemap discovery finished. URLs found: {len(sitemap_urls)}",
                flush=True,
            )

        except asyncio.TimeoutError:
            self.logger.warning(
                "Sitemap discovery timed out after %ss. Falling back to exact start URL.",
                self.config.sitemap_discovery_timeout_seconds,
            )
            print(
                "Sitemap discovery timed out. Falling back to exact start URL.",
                flush=True,
            )

        return sitemap_urls

    def _prepare_seed_urls(
        self,
        sitemap: SitemapManager,
        sitemap_urls: list[str],
    ) -> list[str]:
        seed_urls = list(sitemap_urls)

        start_url = sitemap.normalize_url(self.config.start_url)

        if start_url is None:
            return seed_urls

        if start_url not in seed_urls:
            seed_urls.insert(0, start_url)

        robots_allowed_seed_urls: list[str] = []

        for seed_url in seed_urls:
            if self.robots.can_fetch(seed_url):
                robots_allowed_seed_urls.append(seed_url)
                continue

            message = (
                "Seed URL blocked by robots.txt; it will not be queued: "
                f"url={seed_url}"
            )
            print(message, flush=True)
            self.logger.warning(message)

        seed_urls = robots_allowed_seed_urls

        if not seed_urls:
            message = (
                "No crawlable seed URLs remain after robots.txt filtering. "
                "The crawler will finish without downloading pages."
            )
            print(message, flush=True)
            self.logger.warning(message)
        seed_urls = self._limit_seed_urls(seed_urls)
        self._enqueue_seed_urls(seed_urls)

        return seed_urls

    def _print_preliminary_run_summary(
        self,
        runtime: CrawlerRunRuntime,
    ) -> None:
        queue_counts = self.database.queue_status_counts()

        sitemap_pages_found = len(runtime["sitemap_urls"])
        seed_pages_queued = len(runtime["seed_urls"])
        total_queued_urls = sum(queue_counts.values())

        has_crawl_work = (
            self.database.pending_queue_count() > 0
            if self.config.recursive_discovery
            else bool(runtime["seed_urls"])
        )

        if has_crawl_work and self.config.proceed_delay_seconds > 0:
            proceed_message = (
                f"Proceeding in {self.config.proceed_delay_seconds} seconds..."
            )
        elif has_crawl_work:
            proceed_message = "Proceeding immediately..."
        else:
            proceed_message = (
                "Queue is empty. Startup delay will be skipped."
            )

        self.terminal_ui.show_preliminary_summary(
            sitemap_pages_found=sitemap_pages_found,
            seed_pages_queued=seed_pages_queued,
            total_queued_urls=total_queued_urls,
            queue_status_counts=queue_counts,
            interrupted_items_restored=runtime["interrupted_count"],
            missing_markdown_outputs_restored=runtime[
                "repaired_missing_outputs"
            ],
            recursive_discovery=self.config.recursive_discovery,
            max_pages=self.config.max_pages,
            auto_continue_until_complete=(
                self.config.auto_continue_until_complete
            ),
            max_auto_batches=self._format_unlimited(
                self.config.max_auto_batches
            ),
            batch_pause_seconds=self.config.batch_pause_seconds,
            max_queue_size=self.config.max_queue_size,
            max_depth=self.config.max_depth,
            allowed_path_prefix=self.config.allowed_path_prefix,
            min_delay=self.config.min_delay,
            max_delay=self.config.max_delay,
            robots_crawl_delay=self.robots.crawl_delay,
            proceed_message=proceed_message,
        )

    async def _execute_crawl(
        self,
        sitemap: SitemapManager,
        seed_urls: list[str],
    ) -> RichDashboard:
        if self.config.recursive_discovery:
            return await self._run_database_queue_until_complete(sitemap)

        return await self._run_static(seed_urls, sitemap)

    def _finalize_successful_run(
        self,
        dashboard: RichDashboard,
    ) -> None:
        self._print_final_run_summary(dashboard)
        self._write_observability_report()

    def _repair_missing_markdown_outputs(self) -> int:
        existing_hashes: set[str] = set()

        if self.config.output_dir.exists():
            for path in self.config.output_dir.glob("*.md"):
                if not path.is_file():
                    continue

                stem = path.stem
                if "__" not in stem:
                    continue

                short_hash = stem.rsplit("__", 1)[-1].strip()
                if short_hash:
                    existing_hashes.add(short_hash)

        full_hashes = {
            url_hash
            for url_hash in self.database.all_queue_url_hashes()
            if url_hash[:12] in existing_hashes
        }

        repaired = self.database.repair_missing_markdown_outputs(full_hashes)

        if repaired:
            self.logger.info(
                "Repaired missing Markdown outputs by requeueing URLs: count=%s output_dir=%s",
                repaired,
                self.config.output_dir,
            )

        return repaired

    def _apply_robots_delay(self) -> None:
        effective_min = self.robots.effective_min_delay()
        effective_max = self.robots.effective_max_delay()

        object.__setattr__(self.config, "min_delay", effective_min)
        object.__setattr__(self.config, "max_delay", effective_max)

    def _limit_seed_urls(self, urls: list[str]) -> list[str]:
        hard_limit = self.config.max_queue_size

        if len(urls) <= hard_limit:
            return urls

        self.logger.warning(
            "Seed URL list was capped by max_queue_size: original=%s capped=%s max_queue_size=%s",
            len(urls),
            hard_limit,
            self.config.max_queue_size,
        )

        return urls[:hard_limit]

    def _claim_url_ownership(self, url: str) -> bool:
        return claim_url_ownership(
            url=url,
            registry=self.global_url_registry,
            owner_project=self.owner_project,
            owner_project_dir=self.config.output_dir,
            logger=self.logger,
        )

    def _normalize_english_candidate_url(self, url: str) -> str | None:
        try:
            if self.config.require_english:
                return normalize_optional_url(url)

            return normalize_url(url)
        except ValueError:
            return None

    def _enqueue_seed_urls(self, urls: list[str]) -> None:
        for raw_url in urls:
            url = self._normalize_english_candidate_url(raw_url)

            if url is None:
                self.observability.record_official_rejected(
                    url=raw_url,
                    reason="non_english_or_invalid_seed_url_before_enqueue",
                )
                continue
            if self.database.queued_count() >= self.config.max_queue_size:
                self.logger.warning(
                    "Max queue size reached while enqueueing seed URLs: max_queue_size=%s",
                    self.config.max_queue_size,
                )
                break

            if not self._claim_url_ownership(url):
                continue

            url_hash = self.dedup.url_hash(url)

            queued = self.database.enqueue_url(
                url=url,
                url_hash=url_hash,
                depth=0,
                discovered_from=None,
            )

            if not queued:
                self.database.requeue_url(
                    url=url,
                    url_hash=url_hash,
                    depth=0,
                    discovered_from=None,
                )

    async def _run_static(
        self,
        urls: list[str],
        sitemap: SitemapManager,
    ) -> RichDashboard:
        dashboard = RichDashboard(total_pages=len(urls))
        dashboard.set_pipeline_context(
            step_current=6,
            step_total=14,
            step_name="Crawling static URLs",
            batch_current=1,
            batch_total=1,
        )
        dashboard.update_queue_context(
            pending=len(urls),
            queued=len(urls),
                    )

        with self.terminal_ui.open(
            dashboard,
            refresh_per_second=2,
        ) as live:
            tasks = [
                self._process_url(
                    url=url,
                    depth=0,
                    dashboard=dashboard,
                    live=live,
                    sitemap=sitemap,
                    use_recursive_discovery=False,
                )
                for url in urls
            ]

            await asyncio.gather(*tasks)

        return dashboard

    async def _run_database_queue_until_complete(
        self,
        sitemap: SitemapManager,
    ) -> RichDashboard:
        """Process the complete database queue inside one persistent Live display."""

        initial_pending = self.database.pending_queue_count()
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
            queued=self.database.queued_count(),
                    )

        batch_number = 0

        with self.terminal_ui.open(
            dashboard,
            refresh_per_second=4,
        ) as live:
            while True:
                pending_before_batch = self.database.pending_queue_count()

                dashboard.total_pages = max(
                    dashboard.total_pages,
                    dashboard.processed + pending_before_batch,
                    1,
                )
                dashboard.update_queue_context(
                    pending=pending_before_batch,
                    queued=self.database.queued_count(),
                                    )
                live.update(dashboard.render(), refresh=True)

                if pending_before_batch <= 0:
                    break

                if (
                    self.config.max_auto_batches > 0
                    and batch_number >= self.config.max_auto_batches
                ):
                    self.logger.warning(
                        (
                            "Max auto batches reached, stopping command: "
                            "batches=%s pending=%s max_auto_batches=%s"
                        ),
                        batch_number,
                        pending_before_batch,
                        self.config.max_auto_batches,
                    )
                    break

                batch_number += 1
                estimated_total_batches = batch_number + max(
                    math.ceil(
                        pending_before_batch
                        / max(self.config.max_pages, 1)
                    )
                    - 1,
                    0,
                )

                dashboard.set_pipeline_context(
                    step_current=6,
                    step_total=14,
                    step_name="Crawling queued URLs",
                    batch_current=batch_number,
                    batch_total=estimated_total_batches,
                )
                live.update(dashboard.render(), refresh=True)

                processed_before_batch = dashboard.processed

                await self._run_database_queue_batch(
                    sitemap=sitemap,
                    batch_number=batch_number,
                    dashboard=dashboard,
                    live=live,
                )

                pending_after_batch = self.database.pending_queue_count()
                processed_in_batch = (
                    dashboard.processed - processed_before_batch
                )

                dashboard.total_pages = max(
                    dashboard.total_pages,
                    dashboard.processed + pending_after_batch,
                    1,
                )
                dashboard.update_queue_context(
                    pending=pending_after_batch,
                    queued=self.database.queued_count(),
                                    )
                live.update(dashboard.render(), refresh=True)

                if pending_after_batch <= 0:
                    break

                if not self.config.auto_continue_until_complete:
                    break

                if processed_in_batch <= 0:
                    message = (
                        "Crawler queue stalled while pending URLs remain: "
                        f"batch={batch_number} "
                        f"processed={processed_in_batch} "
                        f"pending_before={pending_before_batch} "
                        f"pending_after={pending_after_batch}"
                    )
                    self.logger.critical(message)
                    raise RuntimeError(message)

                if self.config.batch_pause_seconds > 0:
                    dashboard.set_pipeline_context(
                        step_current=6,
                        step_total=14,
                        step_name=(
                            "Waiting before next automatic batch "
                            f"({self.config.batch_pause_seconds}s)"
                        ),
                        batch_current=batch_number,
                        batch_total=estimated_total_batches,
                    )
                    live.update(dashboard.render(), refresh=True)
                    await asyncio.sleep(self.config.batch_pause_seconds)

            final_pending = self.database.pending_queue_count()
            final_step_name = (
                "Finished"
                if final_pending <= 0
                else "Stopped with pending queue items"
            )

            dashboard.total_pages = max(
                dashboard.total_pages,
                dashboard.processed,
                1,
            )
            dashboard.update_queue_context(
                pending=final_pending,
                queued=self.database.queued_count(),
                            )
            dashboard.set_pipeline_context(
                step_current=14,
                step_total=14,
                step_name=final_step_name,
                batch_current=batch_number,
                batch_total=max(batch_number, 1),
            )
            live.update(dashboard.render(), refresh=True)

        return dashboard


    async def _run_database_queue_batch(
        self,
        sitemap: SitemapManager,
        batch_number: int,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
    ) -> RichDashboard:
        """Process one queue batch using the caller-owned Live display."""

        pending_count = self.database.pending_queue_count()

        if pending_count <= 0:
            self.logger.info(
                "Skipped empty crawl batch: batch=%s",
                batch_number,
            )
            return dashboard

        processed_at_batch_start = dashboard.processed
        batch_page_limit = max(self.config.max_pages, 1)

        while True:
            processed_in_batch = (
                dashboard.processed - processed_at_batch_start
            )

            if processed_in_batch >= batch_page_limit:
                self.logger.info(
                    (
                        "Max pages per batch reached: "
                        "batch=%s processed=%s max_pages=%s "
                        "pending=%s queued=%s"
                    ),
                    batch_number,
                    processed_in_batch,
                    self.config.max_pages,
                    self.database.pending_queue_count(),
                    self.database.queued_count(),
                )
                break

            pending_rows = self.database.fetch_pending_urls(
                limit=self.config.concurrent_requests
            )

            if not pending_rows:
                break

            remaining_page_budget = (
                batch_page_limit - processed_in_batch
            )

            if remaining_page_budget <= 0:
                break

            pending_rows = pending_rows[:remaining_page_budget]

            current_pending = self.database.pending_queue_count()
            dashboard.total_pages = max(
                dashboard.total_pages,
                dashboard.processed + current_pending,
                dashboard.processed + len(pending_rows),
                1,
            )
            dashboard.update_queue_context(
                pending=current_pending,
                queued=self.database.queued_count(),
                            )
            live.update(dashboard.render(), refresh=True)

            tasks = []

            for row in pending_rows:
                url = str(row["url"])
                url_hash = str(row["url_hash"])
                depth = int(row["depth"])

                self.database.mark_queue_status(
                    url_hash=url_hash,
                    status="processing",
                )

                tasks.append(
                    self._process_url(
                        url=url,
                        depth=depth,
                        dashboard=dashboard,
                        live=live,
                        sitemap=sitemap,
                        use_recursive_discovery=True,
                    )
                )

            results = await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )

            fatal_errors: list[BaseException] = []

            for result in results:
                if not isinstance(result, BaseException):
                    continue

                self.logger.exception(
                    "Isolated URL task failed inside batch %s",
                    batch_number,
                    exc_info=(
                        type(result),
                        result,
                        result.__traceback__,
                    ),
                )
                fatal_errors.append(result)

            live.update(dashboard.render(), refresh=True)

            if fatal_errors and len(fatal_errors) == len(results):
                raise RuntimeError(
                    "Every URL task failed in the current batch"
                ) from fatal_errors[0]

        return dashboard


    def _merge_dashboard(
        self,
        target: RichDashboard,
        source: RichDashboard,
    ) -> None:
        merge_dashboard(target, source)

    def _print_batch_banner(
        self,
        *,
        batch_number: int,
        pending_before_batch: int,
        estimated_total_batches: int,
    ) -> None:
        print_batch_banner(
            batch_number=batch_number,
            pending_before_batch=pending_before_batch,
            batch_page_limit=self.config.max_pages,
            estimated_total_batches=estimated_total_batches,
        )

    def _format_unlimited(self, value: int) -> str:
        return format_unlimited(value)

    def _finish_empty_refetch_after_not_modified(
        self,
        *,
        status_update: EmptyRefetchStatusUpdate,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
    ) -> None:
        self.logger.warning(
            "Refetch after 304 returned no HTML: url=%s final_url=%s "
            "status=%s mapped_status=%s",
            status_update.url,
            status_update.final_url,
            status_update.status_code,
            status_update.fallback_status,
        )

        self.database.mark_status(
            url=status_update.url,
            url_hash=status_update.url_hash,
            status=status_update.fallback_status,
            final_url=status_update.final_url,
            final_url_hash=status_update.final_url_hash,
            redirect_target_hash=status_update.redirect_target_hash,
            etag=status_update.etag,
            last_modified=status_update.last_modified,
        )

        self.database.mark_queue_status(
            status_update.url_hash,
            "done" if status_update.fallback_status != "error" else "error",
        )
        self._finish_url(
            dashboard,
            live,
            "skipped" if status_update.fallback_status != "error" else "error",
            status_update.url,
        )

    def _finish_skipped_page_status(
        self,
        *,
        status_update: SkippedPageStatusUpdate,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
    ) -> None:
        """Persist a skipped page outcome and close the crawl queue item."""

        self.database.mark_status(
            url=status_update.url,
            url_hash=status_update.url_hash,
            status=status_update.status,
            final_url=status_update.final_url,
            final_url_hash=status_update.final_url_hash,
            redirect_target_hash=status_update.redirect_target_hash,
            canonical_url=status_update.canonical_url,
            content_hash=status_update.content_hash,
            etag=status_update.etag,
            last_modified=status_update.last_modified,
        )

        self._finish_queue_item(
            url_hash=status_update.url_hash,
            queue_status=status_update.queue_status,
            dashboard=dashboard,
            live=live,
            dashboard_status=status_update.dashboard_status,
            url=status_update.url,
        )

    def _finish_non_english_or_invalid_before_fetch_skip(
        self,
        *,
        url: str,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
    ) -> None:
        """Persist and close a URL skipped before fetch due to language or validity."""

        self.logger.info(
            "Skipped non-English or invalid URL before fetch: url=%s",
            url,
        )
        self.observability.record_official_rejected(
            url=url,
            reason="non_english_or_invalid_url_before_fetch",
        )
        normalized_url = normalize_url(url)

        if normalized_url is None:
            normalized_url = url

        fallback_hash = self.dedup.url_hash(normalized_url)
        self.database.mark_status(
            url=url,
            url_hash=fallback_hash,
            status="non_english_or_invalid_before_fetch",
        )
        self._finish_queue_item(
            url_hash=fallback_hash,
            queue_status="done",
            dashboard=dashboard,
            live=live,
            dashboard_status="skipped",
            url=url,
        )

    async def _fetch_page(
        self,
        *,
        url: str,
        url_hash: str,
        cache_headers: dict[str, str],
        dashboard: RichDashboard,
        live: TerminalUIHandle,
    ) -> tuple[FetchResult, str, str | None] | None:
        self._update_dashboard_step(
            dashboard=dashboard,
            live=live,
            step_current=7,
            step_name="Fetching page",
            url=url,
        )
        result = await self.fetcher.fetch(
            url,
            cache_headers=cache_headers,
        )

        final_url_hash = self.dedup.final_url_hash(result.final_url)
        redirect_target_hash = self.dedup.redirect_target_hash(
            original_url=url,
            final_url=result.final_url,
        )

        if not result.not_modified:
            return result, final_url_hash, redirect_target_hash

        if not self.writer.exists(url=result.final_url):
            self.logger.info(
                (
                    "HTTP 304 received but local Markdown is missing, "
                    "refetching without cache headers: %s"
                ),
                url,
            )

            result = await self.fetcher.fetch(
                url,
                cache_headers={},
            )

            final_url_hash = self.dedup.final_url_hash(result.final_url)
            redirect_target_hash = self.dedup.redirect_target_hash(
                original_url=url,
                final_url=result.final_url,
            )

            if not result.html:
                fallback_status = self._status_for_empty_fetch(result.status_code)
                safe_redirect_target_hash = (
                    "" if redirect_target_hash is None else redirect_target_hash
                )
                safe_status_code = (
                    0 if result.status_code is None else result.status_code
                )

                self._finish_empty_refetch_after_not_modified(
                    status_update=EmptyRefetchStatusUpdate(
                        url=url,
                        url_hash=url_hash,
                        final_url=result.final_url,
                        final_url_hash=final_url_hash,
                        redirect_target_hash=safe_redirect_target_hash,
                        status_code=safe_status_code,
                        fallback_status=fallback_status,
                        etag=result.etag,
                        last_modified=result.last_modified,
                    ),
                    dashboard=dashboard,
                    live=live,
                )
                return None

            return result, final_url_hash, redirect_target_hash

        self.database.mark_status(
            url=url,
            url_hash=url_hash,
            status="skipped",
            final_url=result.final_url,
            final_url_hash=final_url_hash,
            redirect_target_hash=redirect_target_hash,
            etag=result.etag,
            last_modified=result.last_modified,
        )

        self._finish_queue_item(
            url_hash=url_hash,
            queue_status="done",
            dashboard=dashboard,
            live=live,
            dashboard_status="skipped",
            url=url,
        )
        return None

    # pylint: disable=too-many-arguments,too-many-locals,too-many-return-statements,too-many-branches,too-many-statements
    def _validate_fetch_response(
        self,
        *,
        url: str,
        url_hash: str,
        result: FetchResult,
        final_url_hash: str,
        redirect_target_hash: str | None,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
    ) -> bool:
        self._update_dashboard_step(
            dashboard=dashboard,
            live=live,
            step_current=8,
            step_name="Validating fetch response",
            url=url,
        )
        transport_quality_status = self._detect_transport_quality_issue(
            result.status_code
        )

        if not result.html:
            status = transport_quality_status or "error"

            self.logger.warning(
                "Fetch returned no HTML: url=%s final_url=%s status=%s mapped_status=%s",
                url,
                result.final_url,
                result.status_code,
                status,
            )

            self.database.mark_status(
                url=url,
                url_hash=url_hash,
                status=status,
                final_url=result.final_url,
                final_url_hash=final_url_hash,
                redirect_target_hash=redirect_target_hash,
                etag=result.etag,
                last_modified=result.last_modified,
            )

            self.database.mark_queue_status(
                url_hash,
                "done" if status != "error" else "error",
            )
            self._finish_url(
                dashboard,
                live,
                "skipped" if status != "error" else "error",
                url,
            )
            return True

        html_quality_status = self._detect_html_quality_issue(
            html=result.html,
            status_code=result.status_code,
        )

        if html_quality_status is not None:
            self.logger.warning(
                (
                    "Skipped low quality, protected, or login page before parsing: "
                    "url=%s final_url=%s http_status=%s reason=%s"
                ),
                url,
                result.final_url,
                result.status_code,
                html_quality_status,
            )

            self._finish_skipped_page_status(
                status_update=SkippedPageStatusUpdate(
                    url=url,
                    url_hash=url_hash,
                    status=html_quality_status,
                    final_url=result.final_url,
                    final_url_hash=final_url_hash,
                    redirect_target_hash=redirect_target_hash,
                    etag=result.etag,
                    last_modified=result.last_modified,
                ),
                dashboard=dashboard,
                live=live,
            )
            return True

        return False

    def _parse_validated_content(
        self,
        *,
        url: str,
        url_hash: str,
        result: FetchResult,
        final_url_hash: str,
        redirect_target_hash: str | None,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
    ) -> ParsedPage | None:
        self._update_dashboard_step(
            dashboard=dashboard,
            live=live,
            step_current=9,
            step_name="Parsing HTML",
            url=url,
        )
        html = result.html

        if html is None:
            raise RuntimeError("Validated fetch result unexpectedly contains no HTML")

        if self.config.require_english and not self.language.is_english(
            html,
            result.final_url,
        ):
            self.logger.info(
                "Skipped non-English page: url=%s final_url=%s",
                url,
                result.final_url,
            )

            self.database.mark_status(
                url=url,
                url_hash=url_hash,
                status="non_english",
                final_url=result.final_url,
                final_url_hash=final_url_hash,
                redirect_target_hash=redirect_target_hash,
                etag=result.etag,
                last_modified=result.last_modified,
            )

            self._finish_queue_item(
                url_hash=url_hash,
                queue_status="done",
                dashboard=dashboard,
                live=live,
                dashboard_status="skipped",
                url=url,
            )
            return None

        parsed = self.parser.parse(html, result.final_url)

        parsed_quality_status = self._detect_parsed_quality_issue(
            markdown=parsed.markdown,
            text_content=parsed.text_content,
        )

        if parsed_quality_status is not None:
            self.logger.warning(
                "Skipped low quality parsed page: url=%s final_url=%s reason=%s title=%s",
                url,
                result.final_url,
                parsed_quality_status,
                parsed.title,
            )

            self.database.mark_status(
                url=url,
                url_hash=url_hash,
                status=parsed_quality_status,
                final_url=result.final_url,
                final_url_hash=final_url_hash,
                redirect_target_hash=redirect_target_hash,
                canonical_url=parsed.canonical_url,
                etag=result.etag,
                last_modified=result.last_modified,
            )

            self._finish_queue_item(
                url_hash=url_hash,
                queue_status="done",
                dashboard=dashboard,
                live=live,
                dashboard_status="skipped",
                url=url,
            )
            return None

        return parsed

    def _handle_content_policy(
        self,
        *,
        url: str,
        url_hash: str,
        result: FetchResult,
        parsed: ParsedPage,
        final_url_hash: str,
        redirect_target_hash: str | None,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
    ) -> bool:
        self._update_dashboard_step(
            dashboard=dashboard,
            live=live,
            step_current=10,
            step_name="Evaluating content policy",
            url=url,
        )
        content_policy = self.policy.evaluate_content(
            url=result.final_url,
            title=parsed.title,
            text=parsed.text_content,
        )

        if content_policy.decision in {
            PolicyDecision.SKIP,
            PolicyDecision.BLOCK,
        }:
            self.logger.info(
                "Skipped by smart content policy: "
                "url=%s decision=%s reason=%s title=%s",
                result.final_url,
                content_policy.decision.value,
                content_policy.reason,
                parsed.title,
            )

            self._finish_skipped_page_status(
                status_update=SkippedPageStatusUpdate(
                    url=url,
                    url_hash=url_hash,
                    status=f"policy_{content_policy.decision.value}",
                    final_url=result.final_url,
                    final_url_hash=final_url_hash,
                    redirect_target_hash=redirect_target_hash,
                    canonical_url=parsed.canonical_url,
                    etag=result.etag,
                    last_modified=result.last_modified,
                ),
                dashboard=dashboard,
                live=live,
            )
            return True

        if content_policy.decision == PolicyDecision.REVIEW:
            self.logger.info(
                (
                    "Smart content policy marked page for review but allowed it: "
                    "url=%s reason=%s title=%s"
                ),
                result.final_url,
                content_policy.reason,
                parsed.title,
            )

        return False

    def _handle_dedup_result(
        self,
        *,
        url: str,
        url_hash: str,
        result: FetchResult,
        parsed: ParsedPage,
        final_url_hash: str,
        redirect_target_hash: str | None,
        content_hash: str,
        dedup_result: DedupResult,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
    ) -> bool:
        self._update_dashboard_step(
            dashboard=dashboard,
            live=live,
            step_current=11,
            step_name="Checking duplicates",
            url=url,
        )
        duplicate_statuses = {
            "same_content",
            "same_canonical",
            "same_final_url",
            "same_redirect_target",
        }

        if dedup_result.status in duplicate_statuses:
            self.logger.info(
                "Skipped duplicate page: url=%s final_url=%s duplicate_reason=%s",
                url,
                result.final_url,
                dedup_result.status,
            )

            self.database.mark_status(
                url=url,
                url_hash=url_hash,
                status="duplicate",
                final_url=result.final_url,
                final_url_hash=final_url_hash,
                redirect_target_hash=redirect_target_hash,
                canonical_url=parsed.canonical_url,
                content_hash=content_hash,
                etag=result.etag,
                last_modified=result.last_modified,
            )

            self._finish_queue_item(
                url_hash=url_hash,
                queue_status="done",
                dashboard=dashboard,
                live=live,
                dashboard_status="duplicate",
                url=url,
            )
            return True

        if dedup_result.status != "same_url_unchanged":
            return False

        if not self.writer.exists(url=result.final_url):
            self.writer.write(
                url=result.final_url,
                title=parsed.title,
                markdown=parsed.markdown,
            )
            status = "restored"
        else:
            status = "skipped"

        self.database.mark_status(
            url=url,
            url_hash=url_hash,
            status=status,
            final_url=result.final_url,
            final_url_hash=final_url_hash,
            redirect_target_hash=redirect_target_hash,
            canonical_url=parsed.canonical_url,
            content_hash=content_hash,
            etag=result.etag,
            last_modified=result.last_modified,
        )

        self._finish_queue_item(
            url_hash=url_hash,
            queue_status="done",
            dashboard=dashboard,
            live=live,
            dashboard_status=status,
            url=url,
        )
        return True

    # pylint: disable=too-many-arguments
    def _persist_processed_page(
        self,
        *,
        url: str,
        url_hash: str,
        result: FetchResult,
        parsed: ParsedPage,
        final_url_hash: str,
        redirect_target_hash: str | None,
        content_hash: str,
        dedup_result: DedupResult,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
    ) -> None:
        """Persist a successfully parsed and deduplicated page."""

        self._update_dashboard_step(
            dashboard=dashboard,
            live=live,
            step_current=12,
            step_name="Writing Markdown",
            url=url,
        )

        self.writer.write(
            url=result.final_url,
            title=parsed.title,
            markdown=parsed.markdown,
        )

        status = (
            "updated" if dedup_result.status == "same_url_changed" else "downloaded"
        )

        self.database.upsert_page(
            url=url,
            url_hash=url_hash,
            final_url=result.final_url,
            final_url_hash=final_url_hash,
            redirect_target_hash=redirect_target_hash,
            canonical_url=parsed.canonical_url,
            content_hash=content_hash,
            etag=result.etag,
            last_modified=result.last_modified,
            status=status,
            content_changed=dedup_result.content_changed,
        )

        self._finish_queue_item(
            url_hash=url_hash,
            queue_status="done",
            dashboard=dashboard,
            live=live,
            dashboard_status=status,
            url=url,
        )

        self.logger.info(
            "URL processed successfully: url=%s final_url=%s status=%s",
            url,
            result.final_url,
            status,
        )

    async def _process_url(
        self,
        *,
        url: str,
        depth: int,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
        sitemap: SitemapManager,
        use_recursive_discovery: bool,
    ) -> None:
        """Delegate single-URL lifecycle orchestration to UrlProcessor."""

        await self.url_processor.process(
            url=url,
            depth=depth,
            dashboard=dashboard,
            live=live,
            sitemap=sitemap,
            use_recursive_discovery=use_recursive_discovery,
        )

    def _print_terminal_banner(self) -> None:
        self.terminal_ui.show_runtime_banner()

    def _print_final_run_summary(
        self,
        dashboard: RichDashboard,
    ) -> None:
        queue_counts = build_run_summary_queue_counts(
            raw_queue_counts=self.database.queue_status_counts(),
            queued=self.database.queued_count(),
        )
        paths = RunSummaryPaths(
            output_dir=self.config.output_dir,
            db_path=self.config.db_path,
            log_file=self.config.logs_dir / "crawler.log",
        )

        self.terminal_ui.show_final_run_summary(
            dashboard=dashboard,
            queue_counts=queue_counts,
            paths=paths,
            max_pages=self.config.max_pages,
        )

    def _update_dashboard_step(
        self,
        *,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
        step_current: int,
        step_name: str,
        url: str | None = None,
    ) -> None:
        """Update the existing Live dashboard without emitting extra lines."""

        dashboard.set_pipeline_context(
            step_current=step_current,
            step_total=14,
            step_name=step_name,
            batch_current=dashboard.batch_current,
            batch_total=dashboard.batch_total,
        )

        if url is not None:
            dashboard.set_current_url(url)

        live.update(dashboard.render(), refresh=True)

    def _start_url(
        self,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
        url: str,
        depth: int,
    ) -> None:
        self._update_dashboard_step(
            dashboard=dashboard,
            live=live,
            step_current=6,
            step_name="Starting URL processing",
            url=url,
        )

        start_line = (
            f"START    [{dashboard.processed + 1}/{dashboard.total_pages}] "
            f"depth={depth} {url}"
        )
        self.logger.info(start_line)

    def _finish_queue_item(  # pylint: disable=too-many-arguments
        self,
        *,
        url_hash: str,
        queue_status: str,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
        dashboard_status: str,
        url: str,
    ) -> None:
        self._update_dashboard_step(
            dashboard=dashboard,
            live=live,
            step_current=13,
            step_name="Updating crawl queue",
            url=url,
        )
        self.database.mark_queue_status(url_hash, queue_status)
        self._finish_url(dashboard, live, dashboard_status, url)

    def _finish_url(
        self,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
        status: str,
        url: str,
    ) -> None:
        self.observability.record_url_status(url=url, status=status)
        dashboard.increment(status)

        pending = self.database.pending_queue_count()
        queued = self.database.queued_count()

        dashboard.update_queue_context(
            pending=pending,
            queued=queued,
        )

        if dashboard.processed >= dashboard.total_pages or pending <= 0:
            dashboard.set_pipeline_context(
                step_current=14,
                step_total=14,
                step_name="Finished",
                batch_current=dashboard.batch_current,
                batch_total=dashboard.batch_total,
            )

        live.update(dashboard.render(), refresh=True)

        terminal_line = dashboard.terminal_line(
            status=status,
            url=url,
            pending=pending,
            queued=queued,
        )
        self.logger.info(terminal_line)

    def _write_observability_report(self) -> None:
        report_path = self.observability.write_report()

        self.terminal_ui.show_observability_report(
            report_path=report_path,
        )
        self.logger.info(
            "Observability report written: %s",
            report_path,
        )

    def _detect_transport_quality_issue(self, status_code: int | None) -> str | None:
        return self.page_quality.detect_transport_quality_issue(status_code)

    def _status_for_empty_fetch(self, status_code: int | None) -> str:
        return self.page_quality.status_for_empty_fetch(status_code)

    def _detect_html_quality_issue(
        self,
        *,
        html: str,
        status_code: int | None,
    ) -> str | None:
        return self.page_quality.detect_html_quality_issue(
            html=html,
            status_code=status_code,
        )

    def _detect_parsed_quality_issue(
        self,
        *,
        markdown: str,
        text_content: str,
    ) -> str | None:
        return self.page_quality.detect_parsed_quality_issue(
            markdown=markdown,
            text_content=text_content,
        )
