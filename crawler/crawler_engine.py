"""Crawler orchestration engine.

This module coordinates crawl lifecycle operations while delegating network
access, content parsing, deduplication, persistence, discovery, and queue
execution to specialized collaborators.
"""

# pylint: disable=too-many-lines
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from urllib.parse import urlparse

from crawler.batch_executor import BatchExecutor
from crawler.config import CrawlerConfig
from crawler.crawler_context import CrawlerRuntimeContext
from crawler.crawler_discovery import CrawlerDiscoveryService
from crawler.crawler_engine_run_summary import (
    RunSummaryPaths,
    build_run_summary_queue_counts,
)
from crawler.crawler_runtime_builder import (
    CrawlerRunRuntime,
    CrawlerRuntimeBuilder,
)
from crawler.database import DatabaseManager
from crawler.dedup import DeduplicationEngine
from crawler.discovery_parts.fetcher import AsyncFetcher
from crawler.engine_status import (
    format_unlimited,
    merge_dashboard,
    print_batch_banner,
)
from crawler.fetch_pipeline import FetchPipeline
from crawler.global_url_registry import GlobalUrlRegistry
from crawler.intent_analyzer import IntentAnalyzer
from crawler.language import LanguageDetector
from crawler.markdown_writer import MarkdownWriter
from crawler.observability import CrawlerObservability
from crawler.official_graph import OfficialHostGraph
from crawler.parser import ContentParser
from crawler.policy_engine import SmartScopePolicy
from crawler.progress import RichDashboard
from crawler.queue_runner import QueueRunner
from crawler.robots import RobotsManager
from crawler.shared.url_normalizer import (
    normalize_optional_url,
    normalize_url,
)
from crawler.shared.url_ownership import claim_url_ownership
from crawler.sitemap import SitemapManager
from crawler.terminal_ui import TerminalUI, TerminalUIHandle
from crawler.url_processor import UrlProcessor


class CrawlerEngine:  # pylint: disable=too-many-instance-attributes,too-few-public-methods
    """Coordinate crawling workflow, persistence, parsing, and runtime services."""

    # Dependency wiring constructor for crawler orchestration.
    # pylint: disable=too-many-statements
    def __init__(self, config: CrawlerConfig) -> None:
        self.config: CrawlerConfig = config
        self.logger: logging.Logger = self._build_logger()
        self.terminal_ui: TerminalUI = TerminalUI()

        self.database: DatabaseManager = DatabaseManager(config.db_path)
        self.robots: RobotsManager = RobotsManager(config)
        self.fetcher: AsyncFetcher = AsyncFetcher(
            config,
            logger=self.logger,
        )
        self.intent_analyzer: IntentAnalyzer = IntentAnalyzer()
        self.parser: ContentParser = ContentParser()
        self.language: LanguageDetector = LanguageDetector()
        self.dedup: DeduplicationEngine = DeduplicationEngine(self.database)
        self.writer: MarkdownWriter = MarkdownWriter(config.output_dir)
        self.policy: SmartScopePolicy = SmartScopePolicy(
            start_url=config.start_url,
            allowed_path_prefix=config.allowed_path_prefix,
        )

        self.start_netloc: str = urlparse(config.start_url).netloc.lower()
        self.owner_project: str = self._owner_project_name()
        self.global_url_registry: GlobalUrlRegistry = GlobalUrlRegistry()
        self.official_graph: OfficialHostGraph = OfficialHostGraph(
            seed_url=config.start_url,
            owner_project=self.owner_project,
        )
        self.observability: CrawlerObservability = CrawlerObservability(
            logs_dir=config.logs_dir,
            start_url=config.start_url,
        )
        self.runtime_context: CrawlerRuntimeContext = CrawlerRuntimeContext(
            output_dir=config.output_dir,
            database=self.database,
            logger=self.logger,
            config=self.config,
        )
        self.fetch_pipeline: FetchPipeline = FetchPipeline(
            config=self.config,
            database=self.database,
            fetcher=self.fetcher,
            parser=self.parser,
            language=self.language,
            dedup=self.dedup,
            writer=self.writer,
            policy=self.policy,
            observability=self.observability,
            update_dashboard_step=self._update_dashboard_step,
            finish_queue_item=self._finish_queue_item,
            finish_url=self._finish_url,
            logger=self.logger,
        )
        self.discovery: CrawlerDiscoveryService = CrawlerDiscoveryService(
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
        self.runtime_builder: CrawlerRuntimeBuilder = CrawlerRuntimeBuilder(
            config=self.config,
            database=self.database,
            robots=self.robots,
            dedup=self.dedup,
            observability=self.observability,
            claim_url_ownership=self._claim_url_ownership,
            normalize_english_candidate_url=(self._normalize_english_candidate_url),
            logger=self.logger,
        )
        self.url_processor: UrlProcessor = UrlProcessor(self)
        self.batch_executor: BatchExecutor = BatchExecutor(
            config=self.config,
            database=self.database,
            process_url=self._process_batch_url,
            logger=self.logger,
        )
        self.queue_runner: QueueRunner = QueueRunner(
            config=self.config,
            database=self.database,
            terminal_ui=self.terminal_ui,
            run_database_queue_batch=self.batch_executor.run,
            logger=self.logger,
        )

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
        """Run until crawl limits or queue exhaustion."""

        try:
            self.logger.info(
                "Crawler started: %s",
                self.config.start_url,
            )

            runtime = await self.runtime_builder.build()
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
                runtime["sitemap"],
                runtime["seed_urls"],
            )
            self._finalize_successful_run(dashboard)

            self.logger.info(
                "Crawler finished: %s",
                self.config.start_url,
            )
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
            proceed_message = "Queue is empty. Startup delay will be skipped."

        self.terminal_ui.show_preliminary_summary(
            sitemap_pages_found=sitemap_pages_found,
            seed_pages_queued=seed_pages_queued,
            total_queued_urls=total_queued_urls,
            queue_status_counts=queue_counts,
            interrupted_items_restored=runtime["interrupted_count"],
            missing_markdown_outputs_restored=runtime["repaired_missing_outputs"],
            recursive_discovery=self.config.recursive_discovery,
            max_pages=self.config.max_pages,
            auto_continue_until_complete=(self.config.auto_continue_until_complete),
            max_auto_batches=self._format_unlimited(self.config.max_auto_batches),
            batch_pause_seconds=self.config.batch_pause_seconds,
            max_queue_size=self.config.max_queue_size,
            max_depth=self.config.max_depth,
            allowed_path_prefix=self.config.allowed_path_prefix,
            min_delay=self.config.min_delay,
            max_delay=self.config.max_delay,
            robots_crawl_delay=self.robots.crawl_delay,
            proceed_message=proceed_message,
        )

    def _claim_url_ownership(self, url: str) -> bool:
        """Claim cross-project ownership for a normalized URL."""

        return claim_url_ownership(
            url=url,
            registry=self.global_url_registry,
            owner_project=self.owner_project,
            owner_project_dir=self.config.output_dir,
            logger=self.logger,
        )

    def _normalize_english_candidate_url(
        self,
        url: str,
    ) -> str | None:
        """Normalize a URL and enforce the configured language policy."""

        try:
            if self.config.require_english:
                return normalize_optional_url(url)

            return normalize_url(url)
        except ValueError:
            return None

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

            _ = await asyncio.gather(*tasks)

        return dashboard

    async def _run_database_queue_until_complete(
        self,
        sitemap: SitemapManager,
    ) -> RichDashboard:
        """Delegate persistent recursive queue execution."""

        return await self.queue_runner.run(sitemap)

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

    async def _process_batch_url(
        self,
        url: str,
        depth: int,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
        sitemap: SitemapManager,
        use_recursive_discovery: bool,
    ) -> None:
        """Adapt BatchExecutor calls to the keyword-only URL processor."""

        await self._process_url(
            url=url,
            depth=depth,
            dashboard=dashboard,
            live=live,
            sitemap=sitemap,
            use_recursive_discovery=use_recursive_discovery,
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
        """Delegate single-URL lifecycle orchestration."""

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
        """Update the existing Live dashboard without extra lines."""

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
            f"START    [{dashboard.processed + 1}/"
            f"{dashboard.total_pages}] depth={depth} {url}"
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
        self._finish_url(
            dashboard,
            live,
            dashboard_status,
            url,
        )

    def _finish_url(
        self,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
        status: str,
        url: str,
    ) -> None:
        self.observability.record_url_status(
            url=url,
            status=status,
        )
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
