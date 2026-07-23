"""Single-URL processing orchestration for the crawler.

This module coordinates the lifecycle of one URL while delegating fetching,
validation, parsing, policy evaluation, deduplication, persistence, discovery,
queue updates, and dashboard updates to the crawler engine's existing
collaborators.

No crawler-wide run lifecycle or queue-batch logic belongs in this module.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

from crawler.crawler_engine_url_rules import is_hard_blacklisted_url

if TYPE_CHECKING:
    from rich.live import Live

    from crawler.progress import RichDashboard
    from crawler.sitemap import SitemapManager


class UrlProcessorHost(Protocol):
    """Operations and collaborators required to process one URL."""

    logger: logging.Logger
    config: Any
    database: Any
    dedup: Any
    runtime_context: Any
    observability: Any
    policy: Any
    discovery: Any

    def _normalize_english_candidate_url(self, url: str) -> str | None:
        """Normalize a URL or reject it when invalid for this crawl."""
        ...

    def _finish_non_english_or_invalid_before_fetch_skip(
        self,
        *,
        url: str,
        dashboard: RichDashboard,
        live: Live,
    ) -> None:
        """Persist and finish a URL rejected before fetching."""
        ...

    def _finish_queue_item(
        self,
        *,
        url_hash: str,
        queue_status: str,
        dashboard: RichDashboard,
        live: Live,
        dashboard_status: str,
        url: str,
    ) -> None:
        """Finish a queue item and update runtime progress."""
        ...

    def _start_url(
        self,
        dashboard: RichDashboard,
        live: Live,
        url: str,
        depth: int,
    ) -> None:
        """Record that processing has started for a URL."""
        ...

    async def _fetch_page(
        self,
        *,
        url: str,
        url_hash: str,
        cache_headers: dict[str, str],
        dashboard: RichDashboard,
        live: Live,
    ) -> tuple[Any, str, str | None] | None:
        """Fetch a URL and return its response lifecycle values."""
        ...

    def _validate_fetch_response(
        self,
        *,
        url: str,
        url_hash: str,
        result: Any,
        final_url_hash: str,
        redirect_target_hash: str | None,
        dashboard: RichDashboard,
        live: Live,
    ) -> bool:
        """Validate a fetched response and finish rejected responses."""
        ...

    def _parse_validated_content(
        self,
        *,
        url: str,
        url_hash: str,
        result: Any,
        final_url_hash: str,
        redirect_target_hash: str | None,
        dashboard: RichDashboard,
        live: Live,
    ) -> Any | None:
        """Parse a validated response or finish a rejected page."""
        ...

    def _handle_content_policy(
        self,
        *,
        url: str,
        url_hash: str,
        result: Any,
        parsed: Any,
        final_url_hash: str,
        redirect_target_hash: str | None,
        dashboard: RichDashboard,
        live: Live,
    ) -> bool:
        """Evaluate parsed content and finish policy rejections."""
        ...

    def _handle_dedup_result(
        self,
        *,
        url: str,
        url_hash: str,
        result: Any,
        parsed: Any,
        final_url_hash: str,
        redirect_target_hash: str | None,
        content_hash: str,
        dedup_result: Any,
        dashboard: RichDashboard,
        live: Live,
    ) -> bool:
        """Handle duplicate or unchanged content outcomes."""
        ...

    def _persist_processed_page(
        self,
        *,
        url: str,
        url_hash: str,
        result: Any,
        parsed: Any,
        final_url_hash: str,
        redirect_target_hash: str | None,
        content_hash: str,
        dedup_result: Any,
        dashboard: RichDashboard,
        live: Live,
    ) -> None:
        """Persist a successfully processed page."""
        ...


class UrlProcessor:
    """Orchestrate the complete lifecycle of one crawl URL."""

    def __init__(self, host: UrlProcessorHost) -> None:
        self._host = host

    async def process(
        self,
        *,
        url: str,
        depth: int,
        dashboard: RichDashboard,
        live: Live,
        sitemap: SitemapManager,
        use_recursive_discovery: bool,
    ) -> None:
        """Process one URL without managing crawler-wide lifecycle state."""

        host = self._host
        normalized_url = host._normalize_english_candidate_url(url)

        if normalized_url is None:
            host._finish_non_english_or_invalid_before_fetch_skip(
                url=url,
                dashboard=dashboard,
                live=live,
            )
            return

        url = normalized_url
        url_hash = host.dedup.url_hash(url)
        cache_headers = host.runtime_context.database.get_cache_headers_by_url_hash(
            url_hash
        )

        if is_hard_blacklisted_url(url):
            self._finish_hard_blacklist_skip(
                url=url,
                url_hash=url_hash,
                dashboard=dashboard,
                live=live,
            )
            return

        if self._url_policy_blocks(url):
            self._finish_url_policy_skip(
                url=url,
                url_hash=url_hash,
                dashboard=dashboard,
                live=live,
            )
            return

        try:
            host.logger.info("Processing URL: %s", url)
            host._start_url(dashboard, live, url, depth)

            fetch_lifecycle = await host._fetch_page(
                url=url,
                url_hash=url_hash,
                cache_headers=cache_headers,
                dashboard=dashboard,
                live=live,
            )
            if fetch_lifecycle is None:
                return

            result, final_url_hash, redirect_target_hash = fetch_lifecycle

            if host._validate_fetch_response(
                url=url,
                url_hash=url_hash,
                result=result,
                final_url_hash=final_url_hash,
                redirect_target_hash=redirect_target_hash,
                dashboard=dashboard,
                live=live,
            ):
                return

            if use_recursive_discovery:
                await host.discovery.discover_and_enqueue_links(
                    html=result.html,
                    final_url=result.final_url,
                    depth=depth,
                    sitemap=sitemap,
                )

            parsed = host._parse_validated_content(
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

            if host._handle_content_policy(
                url=url,
                url_hash=url_hash,
                result=result,
                parsed=parsed,
                final_url_hash=final_url_hash,
                redirect_target_hash=redirect_target_hash,
                dashboard=dashboard,
                live=live,
            ):
                return

            content_hash = host.dedup.content_hash(parsed.text_content)
            dedup_result = host.dedup.check(
                url_hash=url_hash,
                final_url_hash=final_url_hash,
                redirect_target_hash=redirect_target_hash,
                canonical_url=parsed.canonical_url,
                content_hash=content_hash,
            )

            if host._handle_dedup_result(
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

            host._persist_processed_page(
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

        except OSError, RuntimeError, ValueError:
            self._finish_processing_error(
                url=url,
                url_hash=url_hash,
                depth=depth,
                dashboard=dashboard,
                live=live,
            )

    def _finish_hard_blacklist_skip(
        self,
        *,
        url: str,
        url_hash: str,
        dashboard: RichDashboard,
        live: Live,
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
        live: Live,
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
        live: Live,
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
