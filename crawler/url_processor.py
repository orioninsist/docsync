"""Single-URL processing orchestration for the crawler.

This module coordinates the lifecycle of one URL while delegating fetching,
validation, parsing, policy evaluation, deduplication, persistence, discovery,
queue updates, and dashboard updates to the crawler engine's existing
collaborators.

No crawler-wide run lifecycle or queue-batch logic belongs in this module.
"""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from crawler.crawler_context import CrawlerRuntimeContext
from crawler.crawler_discovery import CrawlerDiscoveryService
from crawler.crawler_engine_url_rules import is_hard_blacklisted_url
from crawler.database import DatabaseManager
from crawler.dedup import DeduplicationEngine, DedupResult
from crawler.fetch_pipeline import FetchPipeline
from crawler.fetcher import FetchResult
from crawler.observability import CrawlerObservability
from crawler.parser import ParsedPage
from crawler.policy_engine import SmartScopePolicy

if TYPE_CHECKING:
    from crawler.progress import RichDashboard
    from crawler.sitemap import SitemapManager
    from crawler.terminal_ui import TerminalUIHandle


FetchLifecycle = tuple[FetchResult, str, str | None]
DedupLifecycle = tuple[str, DedupResult]


class UrlProcessorHost(Protocol):
    """Operations and collaborators required to process one URL."""

    logger: logging.Logger
    database: DatabaseManager
    dedup: DeduplicationEngine
    runtime_context: CrawlerRuntimeContext
    observability: CrawlerObservability
    policy: SmartScopePolicy
    discovery: CrawlerDiscoveryService
    fetch_pipeline: FetchPipeline

    def _normalize_english_candidate_url(self, url: str) -> str | None:
        """Normalize a URL or reject it when invalid for this crawl."""
        ...

    def _finish_queue_item(
        self,
        *,
        url_hash: str,
        queue_status: str,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
        dashboard_status: str,
        url: str,
    ) -> None:
        """Finish a queue item and update runtime progress."""
        ...

    def _start_url(
        self,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
        url: str,
        depth: int,
    ) -> None:
        """Record that processing has started for a URL."""
        ...


class UrlProcessor:
    """Orchestrate the complete lifecycle of one crawl URL."""

    def __init__(self, host: UrlProcessorHost) -> None:
        self._host: UrlProcessorHost = host

    async def process(
        self,
        *,
        url: str,
        depth: int,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
        sitemap: SitemapManager,
        use_recursive_discovery: bool,
    ) -> None:
        """Process one URL without managing crawler-wide lifecycle state."""

        normalized_url = self._normalize_candidate_or_finish(
            url=url,
            dashboard=dashboard,
            live=live,
        )
        if normalized_url is None:
            return

        url = normalized_url
        url_hash, cache_headers = self._prepare_request_context(url)

        if self._run_pre_fetch_checks(
            url=url,
            url_hash=url_hash,
            dashboard=dashboard,
            live=live,
        ):
            return

        try:
            fetch_lifecycle = await self._fetch_and_validate(
                url=url,
                url_hash=url_hash,
                cache_headers=cache_headers,
                depth=depth,
                dashboard=dashboard,
                live=live,
            )
            if fetch_lifecycle is None:
                return

            await self._process_fetched_page(
                url=url,
                url_hash=url_hash,
                depth=depth,
                fetch_lifecycle=fetch_lifecycle,
                dashboard=dashboard,
                live=live,
                sitemap=sitemap,
                use_recursive_discovery=use_recursive_discovery,
            )
        except OSError, RuntimeError, ValueError:
            self._finish_processing_error(
                url=url,
                url_hash=url_hash,
                depth=depth,
                dashboard=dashboard,
                live=live,
            )

    async def _process_fetched_page(
        self,
        *,
        url: str,
        url_hash: str,
        depth: int,
        fetch_lifecycle: FetchLifecycle,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
        sitemap: SitemapManager,
        use_recursive_discovery: bool,
    ) -> None:
        result, final_url_hash, redirect_target_hash = fetch_lifecycle

        await self._run_recursive_discovery(
            result=result,
            depth=depth,
            sitemap=sitemap,
            use_recursive_discovery=use_recursive_discovery,
        )

        parsed = self._parse_and_filter_content(
            url=url,
            url_hash=url_hash,
            result=result,
            final_url_hash=final_url_hash,
            redirect_target_hash=redirect_target_hash,
            dashboard=dashboard,
            live=live,
        )
        if parsed is None:
            return

        content_hash, dedup_result = self._deduplicate_content(
            url_hash=url_hash,
            parsed=parsed,
            final_url_hash=final_url_hash,
            redirect_target_hash=redirect_target_hash,
        )

        if self._finish_duplicate_if_needed(
            url=url,
            url_hash=url_hash,
            result=result,
            parsed=parsed,
            final_url_hash=final_url_hash,
            redirect_target_hash=redirect_target_hash,
            content_hash=content_hash,
            dedup_result=dedup_result,
            dashboard=dashboard,
            live=live,
        ):
            return

        self._persist_page(
            url=url,
            url_hash=url_hash,
            result=result,
            parsed=parsed,
            final_url_hash=final_url_hash,
            redirect_target_hash=redirect_target_hash,
            content_hash=content_hash,
            dedup_result=dedup_result,
            dashboard=dashboard,
            live=live,
        )

    def _normalize_candidate_or_finish(
        self,
        *,
        url: str,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
    ) -> str | None:
        host = self._host
        normalized_url = host._normalize_english_candidate_url(url)

        if normalized_url is not None:
            return normalized_url

        host.fetch_pipeline.finish_non_english_or_invalid_before_fetch_skip(
            url=url,
            dashboard=dashboard,
            live=live,
        )
        return None

    def _prepare_request_context(
        self,
        url: str,
    ) -> tuple[str, dict[str, str]]:
        host = self._host
        url_hash = host.dedup.url_hash(url)
        cache_headers = host.runtime_context.database.get_cache_headers_by_url_hash(
            url_hash
        )
        return url_hash, cache_headers

    def _run_pre_fetch_checks(
        self,
        *,
        url: str,
        url_hash: str,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
    ) -> bool:
        if is_hard_blacklisted_url(url):
            self._finish_hard_blacklist_skip(
                url=url,
                url_hash=url_hash,
                dashboard=dashboard,
                live=live,
            )
            return True

        if self._url_policy_blocks(url):
            self._finish_url_policy_skip(
                url=url,
                url_hash=url_hash,
                dashboard=dashboard,
                live=live,
            )
            return True

        return False

    async def _fetch_and_validate(
        self,
        *,
        url: str,
        url_hash: str,
        cache_headers: dict[str, str],
        depth: int,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
    ) -> FetchLifecycle | None:
        host = self._host

        host.logger.info("Processing URL: %s", url)
        host._start_url(dashboard, live, url, depth)

        fetch_lifecycle = await host.fetch_pipeline.fetch_page(
            url=url,
            url_hash=url_hash,
            cache_headers=cache_headers,
            dashboard=dashboard,
            live=live,
        )
        if fetch_lifecycle is None:
            return None

        result, final_url_hash, redirect_target_hash = fetch_lifecycle

        should_finish = host.fetch_pipeline.validate_fetch_response(
            url=url,
            url_hash=url_hash,
            result=result,
            final_url_hash=final_url_hash,
            redirect_target_hash=redirect_target_hash,
            dashboard=dashboard,
            live=live,
        )
        if should_finish:
            return None

        return result, final_url_hash, redirect_target_hash

    async def _run_recursive_discovery(
        self,
        *,
        result: FetchResult,
        depth: int,
        sitemap: SitemapManager,
        use_recursive_discovery: bool,
    ) -> None:
        if not use_recursive_discovery:
            return

        html = result.html

        if html is None:
            raise RuntimeError("Validated fetch result unexpectedly contains no HTML")

        await self._host.discovery.discover_and_enqueue_links(
            html=html,
            final_url=result.final_url,
            depth=depth,
            sitemap=sitemap,
        )

    def _parse_and_filter_content(
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
        host = self._host

        parsed = host.fetch_pipeline.parse_validated_content(
            url=url,
            url_hash=url_hash,
            result=result,
            final_url_hash=final_url_hash,
            redirect_target_hash=redirect_target_hash,
            dashboard=dashboard,
            live=live,
        )
        if parsed is None:
            return None

        should_finish = host.fetch_pipeline.handle_content_policy(
            url=url,
            url_hash=url_hash,
            result=result,
            parsed=parsed,
            final_url_hash=final_url_hash,
            redirect_target_hash=redirect_target_hash,
            dashboard=dashboard,
            live=live,
        )
        if should_finish:
            return None

        return parsed

    def _deduplicate_content(
        self,
        *,
        url_hash: str,
        parsed: ParsedPage,
        final_url_hash: str,
        redirect_target_hash: str | None,
    ) -> DedupLifecycle:
        host = self._host
        content_hash = host.dedup.content_hash(parsed.text_content)
        dedup_result = host.dedup.check(
            url_hash=url_hash,
            final_url_hash=final_url_hash,
            redirect_target_hash=redirect_target_hash,
            canonical_url=parsed.canonical_url,
            content_hash=content_hash,
        )
        return content_hash, dedup_result

    def _finish_duplicate_if_needed(
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
        return self._host.fetch_pipeline.handle_dedup_result(
            url=url,
            url_hash=url_hash,
            result=result,
            parsed=parsed,
            final_url_hash=final_url_hash,
            redirect_target_hash=redirect_target_hash,
            content_hash=content_hash,
            dedup_result=dedup_result,
            dashboard=dashboard,
            live=live,
        )

    def _persist_page(
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
        self._host.fetch_pipeline.persist_processed_page(
            url=url,
            url_hash=url_hash,
            result=result,
            parsed=parsed,
            final_url_hash=final_url_hash,
            redirect_target_hash=redirect_target_hash,
            content_hash=content_hash,
            dedup_result=dedup_result,
            dashboard=dashboard,
            live=live,
        )

    def _finish_hard_blacklist_skip(
        self,
        *,
        url: str,
        url_hash: str,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
    ) -> None:
        host = self._host

        host.logger.info(
            "Skipped by hard blacklist before fetch: url=%s",
            url,
        )
        host.observability.record_official_rejected(
            url=url,
            reason="hard_blacklist_before_fetch",
        )
        host.database.mark_status(
            url=url,
            url_hash=url_hash,
            status="hard_blacklist",
        )
        host._finish_queue_item(
            url_hash=url_hash,
            queue_status="done",
            dashboard=dashboard,
            live=live,
            dashboard_status="skipped",
            url=url,
        )

    def _url_policy_blocks(self, url: str) -> bool:
        host = self._host
        url_policy = host.policy.evaluate_url(url)

        return (
            not url_policy.allowed
            and not host.discovery.is_allowed_official_cross_host(url)
        )

    def _finish_url_policy_skip(
        self,
        *,
        url: str,
        url_hash: str,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
    ) -> None:
        host = self._host
        url_policy = host.policy.evaluate_url(url)

        host.logger.info(
            "Skipped by smart URL policy: url=%s decision=%s reason=%s",
            url,
            url_policy.decision.value,
            url_policy.reason,
        )
        host.database.mark_status(
            url=url,
            url_hash=url_hash,
            status=f"policy_{url_policy.decision.value}",
        )
        host._finish_queue_item(
            url_hash=url_hash,
            queue_status="done",
            dashboard=dashboard,
            live=live,
            dashboard_status="skipped",
            url=url,
        )

    def _finish_processing_error(
        self,
        *,
        url: str,
        url_hash: str,
        depth: int,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
    ) -> None:
        host = self._host

        host.logger.exception(
            "URL processing failed: url=%s depth=%s",
            url,
            depth,
        )
        host.database.mark_status(
            url=url,
            url_hash=url_hash,
            status="error",
        )
        host._finish_queue_item(
            url_hash=url_hash,
            queue_status="error",
            dashboard=dashboard,
            live=live,
            dashboard_status="error",
            url=url,
        )
