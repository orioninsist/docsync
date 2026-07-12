"""Recursive link discovery and queue-enrollment service.

This module isolates discovered-link extraction, normalization, policy checks,
official cross-host evaluation, ownership checks, and queue enrollment from the
main crawler orchestration engine.
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from crawler.config import CrawlerConfig
from crawler.crawler_engine_url_rules import is_hard_blacklisted_url
from crawler.database import DatabaseManager
from crawler.dedup import DeduplicationEngine
from crawler.intent_analyzer import IntentAnalyzer
from crawler.observability import CrawlerObservability
from crawler.official_graph import OfficialHostGraph
from crawler.policy_engine import SmartScopePolicy
from crawler.robots import RobotsManager
from crawler.shared.url_normalizer import (
    normalize_joined_url,
    normalize_url,
)
from crawler.sitemap import SitemapManager
from pipeline.global_url_registry import GlobalUrlRegistry


class CrawlerDiscoveryService:
    """Discover, validate, and enqueue crawlable links from fetched pages."""

    def __init__(
        self,
        *,
        config: CrawlerConfig,
        database: DatabaseManager,
        robots: RobotsManager,
        dedup: DeduplicationEngine,
        intent_analyzer: IntentAnalyzer,
        policy: SmartScopePolicy,
        official_graph: OfficialHostGraph,
        observability: CrawlerObservability,
        global_url_registry: GlobalUrlRegistry,
        owner_project: str,
        logger: logging.Logger,
    ) -> None:
        self.config = config
        self.database = database
        self.robots = robots
        self.dedup = dedup
        self.intent_analyzer = intent_analyzer
        self.policy = policy
        self.official_graph = official_graph
        self.observability = observability
        self.global_url_registry = global_url_registry
        self.owner_project = owner_project
        self.logger = logger

    async def discover_and_enqueue_links(
        self,
        *,
        html: str,
        final_url: str,
        depth: int,
        sitemap: SitemapManager,
    ) -> None:
        """Extract eligible links from a fetched page and enqueue new URLs."""

        if self._max_depth_reached(depth):
            self.logger.info(
                (
                    "Max crawl depth reached, skipping link discovery: "
                    "url=%s depth=%s max_depth=%s"
                ),
                final_url,
                depth,
                self.config.max_depth,
            )
            return

        if self.database.queued_count() >= self.config.max_queue_size:
            self.logger.warning(
                (
                    "Max queue size already reached, skipping link discovery: "
                    "url=%s max_queue_size=%s"
                ),
                final_url,
                self.config.max_queue_size,
            )
            return

        discovered_links = sitemap.extract_links(
            html=html,
            base_url=final_url,
        )

        if self.config.allow_official_cross_host_discovery:
            discovered_links.extend(
                self.extract_official_cross_host_links(
                    html=html,
                    base_url=final_url,
                    depth=depth,
                )
            )

        next_depth = depth + 1

        for raw_link in sorted(dict.fromkeys(discovered_links)):
            if self.database.queued_count() >= self.config.max_queue_size:
                self.logger.warning(
                    (
                        "Max queue size reached during recursive discovery: "
                        "max_queue_size=%s"
                    ),
                    self.config.max_queue_size,
                )
                break

            await self._evaluate_and_enqueue_link(
                raw_link=raw_link,
                parent_url=final_url,
                depth=next_depth,
            )

    async def _evaluate_and_enqueue_link(
        self,
        *,
        raw_link: str,
        parent_url: str,
        depth: int,
    ) -> None:
        """Validate one discovered URL and enqueue it when all checks pass."""

        link = await self.resolve_phase2_redirect_final_link(
            raw_link=raw_link,
            parent_url=parent_url,
            depth=depth,
        )

        if link is None:
            self.observability.record_official_rejected(
                url=raw_link,
                reason="non_english_or_invalid_discovered_url_before_enqueue",
            )
            return

        if is_hard_blacklisted_url(link):
            self.observability.record_official_rejected(
                url=link,
                reason="hard_blacklist_before_enqueue",
            )
            return

        intent = self.intent_analyzer.evaluate_url(
            link,
            source_url=parent_url,
        )

        if not intent.allowed:
            self.logger.info(
                ("Smart Router skipped discovered URL before queue: url=%s reason=%s"),
                link,
                intent.reason,
            )
            self.observability.record_official_rejected(
                url=link,
                reason=f"smart_router:{intent.reason}",
            )
            return

        if not self.robots.can_fetch(link):
            return

        if not self._claim_url_ownership(link):
            return

        self.database.enqueue_url(
            url=link,
            url_hash=self.dedup.url_hash(link),
            depth=depth,
            discovered_from=parent_url,
            priority=intent.priority,
        )

    async def resolve_phase2_redirect_final_link(
        self,
        *,
        raw_link: str,
        parent_url: str,
        depth: int,
    ) -> str | None:
        """Normalize and scope-check a discovered link before queue enrollment."""

        link = self._normalize_joined_candidate_url(
            base_url=parent_url,
            candidate_url=raw_link,
        )

        if link is None:
            return None

        url_policy = self.policy.evaluate_url(link)

        if url_policy.allowed:
            return link

        if self.is_allowed_official_cross_host(
            link,
            parent_url=parent_url,
            depth=depth,
        ):
            return link

        self.observability.record_official_rejected(
            url=link,
            reason=f"smart_url_policy:{url_policy.reason}",
        )
        self.logger.info(
            (
                "Smart URL policy rejected discovered URL before enqueue: "
                "url=%s decision=%s reason=%s"
            ),
            link,
            url_policy.decision.value,
            url_policy.reason,
        )
        return None

    def extract_official_cross_host_links(
        self,
        *,
        html: str,
        base_url: str,
        depth: int = 0,
    ) -> list[str]:
        """Extract official cross-host links accepted by the official host graph."""

        soup = BeautifulSoup(html, "html.parser")
        accepted_links: list[str] = []
        seen: set[str] = set()

        for tag in soup.select("a[href], link[href]"):
            href = str(tag.get("href", "")).strip()

            if not href or href.startswith(
                (
                    "#",
                    "mailto:",
                    "tel:",
                    "javascript:",
                    "data:",
                    "blob:",
                )
            ):
                continue

            candidate = self._normalize_joined_candidate_url(
                base_url=base_url,
                candidate_url=href,
            )

            if candidate is None:
                self.observability.record_official_rejected(
                    url=urljoin(base_url, href),
                    reason="non_english_or_invalid_cross_host_url_before_graph",
                )
                continue

            if candidate in seen:
                continue

            if is_hard_blacklisted_url(candidate):
                self.observability.record_official_rejected(
                    url=candidate,
                    reason="hard_blacklist_before_official_graph",
                )
                continue

            if not self.is_allowed_official_cross_host(
                candidate,
                parent_url=base_url,
                depth=depth + 1,
            ):
                continue

            seen.add(candidate)
            accepted_links.append(candidate)

            if (
                len(accepted_links)
                >= self.config.max_official_cross_host_links_per_page
            ):
                break

        if accepted_links:
            self.logger.info(
                "Official host graph discovered links: base_url=%s count=%s",
                base_url,
                len(accepted_links),
            )

        return accepted_links

    def is_allowed_official_cross_host(
        self,
        url: str,
        *,
        parent_url: str | None = None,
        depth: int = 0,
    ) -> bool:
        """Return whether the official host graph permits a cross-host URL."""

        if not self.config.allow_official_cross_host_discovery:
            return False

        decision = self.official_graph.evaluate_url(
            url=url,
            parent_url=parent_url,
            depth=depth,
        )

        if decision.allowed:
            self.observability.record_official_allowed(
                url=url,
                reason=decision.reason,
            )
            self.logger.info(
                (
                    "Official host graph allowed URL: "
                    "url=%s host=%s confidence=%s reason=%s"
                ),
                url,
                decision.host,
                decision.confidence,
                decision.reason,
            )
            return True

        self.observability.record_official_rejected(
            url=url,
            reason=decision.reason,
        )
        return False

    def _claim_url_ownership(self, url: str) -> bool:
        result = self.global_url_registry.claim_or_check(
            raw_url=url,
            owner_project=self.owner_project,
            owner_project_dir=self.config.output_dir,
        )

        if result.allowed:
            return True

        self.logger.warning(
            (
                "Blocked URL owned by another project: "
                "url=%s normalized_url=%s owner_project=%s status=%s"
            ),
            url,
            result.normalized_url,
            result.owner_project,
            result.status,
        )
        print(result.message, flush=True)
        return False

    def _normalize_joined_candidate_url(
        self,
        *,
        base_url: str,
        candidate_url: str,
    ) -> str | None:
        try:
            if self.config.require_english:
                return normalize_joined_url(base_url, candidate_url)

            return normalize_url(urljoin(base_url, candidate_url))
        except ValueError:
            return None

    def _max_depth_reached(self, depth: int) -> bool:
        return depth >= self.config.max_depth
