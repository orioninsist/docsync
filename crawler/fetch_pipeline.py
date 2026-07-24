"""Fetch, validation, parsing, deduplication, and persistence pipeline."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from crawler.config import CrawlerConfig
from crawler.database import DatabaseManager
from crawler.dedup import DeduplicationEngine, DedupResult
from crawler.fetcher import AsyncFetcher, FetchResult
from crawler.language import LanguageDetector
from crawler.markdown_writer import MarkdownWriter
from crawler.observability import CrawlerObservability
from crawler.page_quality import PageQualityAnalyzer
from crawler.parser import ContentParser, ParsedPage
from crawler.policy_engine import PolicyDecision, SmartScopePolicy
from crawler.progress import RichDashboard
from crawler.shared.url_normalizer import normalize_url
from crawler.terminal_ui import TerminalUIHandle


DashboardStepUpdater = Callable[..., None]
QueueItemFinisher = Callable[..., None]
UrlFinisher = Callable[..., None]


@dataclass(frozen=True, slots=True)
class EmptyRefetchStatusUpdate:
    """Status payload for an empty forced refetch after HTTP 304."""

    url: str
    url_hash: str
    final_url: str
    final_url_hash: str
    redirect_target_hash: str
    status_code: int
    fallback_status: str
    etag: str | None
    last_modified: str | None


@dataclass(frozen=True, slots=True)
class SkippedPageStatusUpdate:
    """Persistence payload for a skipped page outcome."""

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


class FetchPipeline:
    """Execute the content-ingestion stages for one crawler URL."""

    def __init__(
        self,
        *,
        config: CrawlerConfig,
        database: DatabaseManager,
        fetcher: AsyncFetcher,
        parser: ContentParser,
        language: LanguageDetector,
        dedup: DeduplicationEngine,
        writer: MarkdownWriter,
        policy: SmartScopePolicy,
        page_quality: PageQualityAnalyzer,
        observability: CrawlerObservability,
        update_dashboard_step: DashboardStepUpdater,
        finish_queue_item: QueueItemFinisher,
        finish_url: UrlFinisher,
        logger: logging.Logger,
    ) -> None:
        self._config = config
        self._database = database
        self._fetcher = fetcher
        self._parser = parser
        self._language = language
        self._dedup = dedup
        self._writer = writer
        self._policy = policy
        self._page_quality = page_quality
        self._observability = observability
        self._update_dashboard_step = update_dashboard_step
        self._finish_queue_item = finish_queue_item
        self._finish_url = finish_url
        self._logger = logger

    def finish_non_english_or_invalid_before_fetch_skip(
        self,
        *,
        url: str,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
    ) -> None:
        """Persist and close a URL rejected before fetching."""

        self._logger.info(
            "Skipped non-English or invalid URL before fetch: url=%s",
            url,
        )
        self._observability.record_official_rejected(
            url=url,
            reason="non_english_or_invalid_url_before_fetch",
        )

        normalized_url = normalize_url(url)

        if normalized_url is None:
            normalized_url = url

        fallback_hash = self._dedup.url_hash(normalized_url)

        self._database.mark_status(
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

    async def fetch_page(
        self,
        *,
        url: str,
        url_hash: str,
        cache_headers: dict[str, str],
        dashboard: RichDashboard,
        live: TerminalUIHandle,
    ) -> tuple[FetchResult, str, str | None] | None:
        """Fetch a page and handle HTTP 304 lifecycle behavior."""

        self._update_dashboard_step(
            dashboard=dashboard,
            live=live,
            step_current=7,
            step_name="Fetching page",
            url=url,
        )

        result = await self._fetcher.fetch(
            url,
            cache_headers=cache_headers,
        )
        final_url_hash, redirect_target_hash = (
            self._build_fetch_identity(
                original_url=url,
                result=result,
            )
        )

        if not result.not_modified:
            return (
                result,
                final_url_hash,
                redirect_target_hash,
            )

        if self._writer.exists(url=result.final_url):
            self._finish_not_modified_skip(
                url=url,
                url_hash=url_hash,
                result=result,
                final_url_hash=final_url_hash,
                redirect_target_hash=redirect_target_hash,
                dashboard=dashboard,
                live=live,
            )
            return None

        return await self._refetch_missing_markdown(
            url=url,
            url_hash=url_hash,
            dashboard=dashboard,
            live=live,
        )

    def _build_fetch_identity(
        self,
        *,
        original_url: str,
        result: FetchResult,
    ) -> tuple[str, str | None]:
        final_url_hash = self._dedup.final_url_hash(
            result.final_url
        )
        redirect_target_hash = (
            self._dedup.redirect_target_hash(
                original_url=original_url,
                final_url=result.final_url,
            )
        )
        return final_url_hash, redirect_target_hash

    async def _refetch_missing_markdown(
        self,
        *,
        url: str,
        url_hash: str,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
    ) -> tuple[FetchResult, str, str | None] | None:
        self._logger.info(
            (
                "HTTP 304 received but local Markdown is missing, "
                "refetching without cache headers: %s"
            ),
            url,
        )

        result = await self._fetcher.fetch(
            url,
            cache_headers={},
        )
        final_url_hash, redirect_target_hash = (
            self._build_fetch_identity(
                original_url=url,
                result=result,
            )
        )

        if result.html:
            return (
                result,
                final_url_hash,
                redirect_target_hash,
            )

        fallback_status = (
            self._page_quality.status_for_empty_fetch(
                result.status_code
            )
        )

        self._finish_empty_refetch_after_not_modified(
            status_update=EmptyRefetchStatusUpdate(
                url=url,
                url_hash=url_hash,
                final_url=result.final_url,
                final_url_hash=final_url_hash,
                redirect_target_hash=(
                    redirect_target_hash or ""
                ),
                status_code=result.status_code or 0,
                fallback_status=fallback_status,
                etag=result.etag,
                last_modified=result.last_modified,
            ),
            dashboard=dashboard,
            live=live,
        )
        return None

    def _finish_not_modified_skip(
        self,
        *,
        url: str,
        url_hash: str,
        result: FetchResult,
        final_url_hash: str,
        redirect_target_hash: str | None,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
    ) -> None:
        self._database.mark_status(
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

    def validate_fetch_response(
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
        """Validate transport and raw HTML quality."""

        self._update_dashboard_step(
            dashboard=dashboard,
            live=live,
            step_current=8,
            step_name="Validating fetch response",
            url=url,
        )

        transport_status = (
            self._page_quality.detect_transport_quality_issue(
                result.status_code
            )
        )

        if not result.html:
            self._finish_empty_fetch_response(
                url=url,
                url_hash=url_hash,
                result=result,
                final_url_hash=final_url_hash,
                redirect_target_hash=redirect_target_hash,
                status=transport_status or "error",
                dashboard=dashboard,
                live=live,
            )
            return True

        html_quality_status = (
            self._page_quality.detect_html_quality_issue(
                html=result.html,
                status_code=result.status_code,
            )
        )

        if html_quality_status is None:
            return False

        self._finish_html_quality_skip(
            url=url,
            url_hash=url_hash,
            result=result,
            final_url_hash=final_url_hash,
            redirect_target_hash=redirect_target_hash,
            status=html_quality_status,
            dashboard=dashboard,
            live=live,
        )
        return True

    def _finish_empty_fetch_response(
        self,
        *,
        url: str,
        url_hash: str,
        result: FetchResult,
        final_url_hash: str,
        redirect_target_hash: str | None,
        status: str,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
    ) -> None:
        self._logger.warning(
            (
                "Fetch returned no HTML: "
                "url=%s final_url=%s status=%s "
                "mapped_status=%s"
            ),
            url,
            result.final_url,
            result.status_code,
            status,
        )

        self._database.mark_status(
            url=url,
            url_hash=url_hash,
            status=status,
            final_url=result.final_url,
            final_url_hash=final_url_hash,
            redirect_target_hash=redirect_target_hash,
            etag=result.etag,
            last_modified=result.last_modified,
        )

        queue_status = (
            "done"
            if status != "error"
            else "error"
        )
        dashboard_status = (
            "skipped"
            if status != "error"
            else "error"
        )

        self._database.mark_queue_status(
            url_hash,
            queue_status,
        )
        self._finish_url(
            dashboard,
            live,
            dashboard_status,
            url,
        )

    def _finish_html_quality_skip(
        self,
        *,
        url: str,
        url_hash: str,
        result: FetchResult,
        final_url_hash: str,
        redirect_target_hash: str | None,
        status: str,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
    ) -> None:
        self._logger.warning(
            (
                "Skipped low quality, protected, or login page "
                "before parsing: url=%s final_url=%s "
                "http_status=%s reason=%s"
            ),
            url,
            result.final_url,
            result.status_code,
            status,
        )

        self._finish_skipped_page_status(
            status_update=SkippedPageStatusUpdate(
                url=url,
                url_hash=url_hash,
                status=status,
                final_url=result.final_url,
                final_url_hash=final_url_hash,
                redirect_target_hash=redirect_target_hash,
                etag=result.etag,
                last_modified=result.last_modified,
            ),
            dashboard=dashboard,
            live=live,
        )

    def parse_validated_content(
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
        """Parse validated HTML and reject unsuitable content."""

        self._update_dashboard_step(
            dashboard=dashboard,
            live=live,
            step_current=9,
            step_name="Parsing HTML",
            url=url,
        )

        html = result.html

        if html is None:
            raise RuntimeError(
                "Validated fetch result unexpectedly "
                "contains no HTML"
            )

        if self._should_skip_non_english(
            html=html,
            final_url=result.final_url,
        ):
            self._finish_non_english_page(
                url=url,
                url_hash=url_hash,
                result=result,
                final_url_hash=final_url_hash,
                redirect_target_hash=redirect_target_hash,
                dashboard=dashboard,
                live=live,
            )
            return None

        parsed = self._parser.parse(
            html,
            result.final_url,
        )

        parsed_quality_status = (
            self._page_quality.detect_parsed_quality_issue(
                markdown=parsed.markdown,
                text_content=parsed.text_content,
            )
        )

        if parsed_quality_status is None:
            return parsed

        self._finish_parsed_quality_skip(
            url=url,
            url_hash=url_hash,
            result=result,
            parsed=parsed,
            final_url_hash=final_url_hash,
            redirect_target_hash=redirect_target_hash,
            status=parsed_quality_status,
            dashboard=dashboard,
            live=live,
        )
        return None

    def _should_skip_non_english(
        self,
        *,
        html: str,
        final_url: str,
    ) -> bool:
        return (
            self._config.require_english
            and not self._language.is_english(
                html,
                final_url,
            )
        )

    def _finish_non_english_page(
        self,
        *,
        url: str,
        url_hash: str,
        result: FetchResult,
        final_url_hash: str,
        redirect_target_hash: str | None,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
    ) -> None:
        self._logger.info(
            "Skipped non-English page: "
            "url=%s final_url=%s",
            url,
            result.final_url,
        )

        self._finish_skipped_page_status(
            status_update=SkippedPageStatusUpdate(
                url=url,
                url_hash=url_hash,
                status="non_english",
                final_url=result.final_url,
                final_url_hash=final_url_hash,
                redirect_target_hash=redirect_target_hash,
                etag=result.etag,
                last_modified=result.last_modified,
            ),
            dashboard=dashboard,
            live=live,
        )

    def _finish_parsed_quality_skip(
        self,
        *,
        url: str,
        url_hash: str,
        result: FetchResult,
        parsed: ParsedPage,
        final_url_hash: str,
        redirect_target_hash: str | None,
        status: str,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
    ) -> None:
        self._logger.warning(
            (
                "Skipped low quality parsed page: "
                "url=%s final_url=%s reason=%s title=%s"
            ),
            url,
            result.final_url,
            status,
            parsed.title,
        )

        self._finish_skipped_page_status(
            status_update=SkippedPageStatusUpdate(
                url=url,
                url_hash=url_hash,
                status=status,
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

    def handle_content_policy(
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
        """Evaluate parsed content against the smart scope policy."""

        self._update_dashboard_step(
            dashboard=dashboard,
            live=live,
            step_current=10,
            step_name="Evaluating content policy",
            url=url,
        )

        content_policy = self._policy.evaluate_content(
            url=result.final_url,
            title=parsed.title,
            text=parsed.text_content,
        )

        if content_policy.decision in {
            PolicyDecision.SKIP,
            PolicyDecision.BLOCK,
        }:
            self._logger.info(
                (
                    "Skipped by smart content policy: "
                    "url=%s decision=%s reason=%s title=%s"
                ),
                result.final_url,
                content_policy.decision.value,
                content_policy.reason,
                parsed.title,
            )

            self._finish_skipped_page_status(
                status_update=SkippedPageStatusUpdate(
                    url=url,
                    url_hash=url_hash,
                    status=(
                        f"policy_{content_policy.decision.value}"
                    ),
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
            self._logger.info(
                (
                    "Smart content policy marked page for review "
                    "but allowed it: url=%s reason=%s title=%s"
                ),
                result.final_url,
                content_policy.reason,
                parsed.title,
            )

        return False

    def handle_dedup_result(
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
        """Handle duplicate and unchanged page outcomes."""

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
            self._logger.info(
                (
                    "Skipped duplicate page: "
                    "url=%s final_url=%s duplicate_reason=%s"
                ),
                url,
                result.final_url,
                dedup_result.status,
            )

            self._database.mark_status(
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

        if not self._writer.exists(url=result.final_url):
            self._writer.write(
                url=result.final_url,
                title=parsed.title,
                markdown=parsed.markdown,
            )
            status = "restored"
        else:
            status = "skipped"

        self._database.mark_status(
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

    def persist_processed_page(
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
        """Write and persist a successfully processed page."""

        self._update_dashboard_step(
            dashboard=dashboard,
            live=live,
            step_current=12,
            step_name="Writing Markdown",
            url=url,
        )

        self._writer.write(
            url=result.final_url,
            title=parsed.title,
            markdown=parsed.markdown,
        )

        status = (
            "updated"
            if dedup_result.status == "same_url_changed"
            else "downloaded"
        )

        self._database.upsert_page(
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

        self._logger.info(
            (
                "URL processed successfully: "
                "url=%s final_url=%s status=%s"
            ),
            url,
            result.final_url,
            status,
        )

    def _finish_empty_refetch_after_not_modified(
        self,
        *,
        status_update: EmptyRefetchStatusUpdate,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
    ) -> None:
        self._logger.warning(
            (
                "Refetch after 304 returned no HTML: "
                "url=%s final_url=%s status=%s mapped_status=%s"
            ),
            status_update.url,
            status_update.final_url,
            status_update.status_code,
            status_update.fallback_status,
        )

        self._database.mark_status(
            url=status_update.url,
            url_hash=status_update.url_hash,
            status=status_update.fallback_status,
            final_url=status_update.final_url,
            final_url_hash=status_update.final_url_hash,
            redirect_target_hash=status_update.redirect_target_hash,
            etag=status_update.etag,
            last_modified=status_update.last_modified,
        )
        self._database.mark_queue_status(
            status_update.url_hash,
            (
                "done"
                if status_update.fallback_status != "error"
                else "error"
            ),
        )
        self._finish_url(
            dashboard,
            live,
            (
                "skipped"
                if status_update.fallback_status != "error"
                else "error"
            ),
            status_update.url,
        )

    def _finish_skipped_page_status(
        self,
        *,
        status_update: SkippedPageStatusUpdate,
        dashboard: RichDashboard,
        live: TerminalUIHandle,
    ) -> None:
        self._database.mark_status(
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
