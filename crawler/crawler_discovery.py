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
from crawler.global_url_registry import GlobalUrlRegistry
from crawler.intent_analyzer import IntentAnalyzer
from crawler.observability import CrawlerObservability
from crawler.official_graph import OfficialHostGraph
from crawler.policy_engine import PolicyResult, SmartScopePolicy
from crawler.robots import RobotsManager
from crawler.shared.url_ownership import claim_url_ownership
from crawler.shared.url_normalizer import (
    normalize_joined_url,
    normalize_url,
)
from crawler.sitemap import SitemapManager


class CrawlerDiscoveryService:
    """Discover, validate, and enqueue crawlable links from fetched pages."""

    config: CrawlerConfig
    database: DatabaseManager
    robots: RobotsManager
    dedup: DeduplicationEngine
    intent_analyzer: IntentAnalyzer
    policy: SmartScopePolicy
    official_graph: OfficialHostGraph
    observability: CrawlerObservability
    global_url_registry: GlobalUrlRegistry
    owner_project: str
    logger: logging.Logger

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

            try:
                await self._evaluate_and_enqueue_link(
                    raw_link=raw_link,
                    parent_url=final_url,
                    depth=next_depth,
                )
            except Exception:
                self.logger.exception(
                    (
                        "Unexpected discovered-link evaluation failure; "
                        "continuing crawl: raw_link=%s parent_url=%s depth=%s"
                    ),
                    raw_link,
                    final_url,
                    next_depth,
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
                "Smart Router skipped discovered URL before queue: url=%s reason=%s",
                link,
                intent.reason,
            )
            self.observability.record_official_rejected(
                url=link,
                reason=f"smart_router:{intent.reason}",
            )
            return

        try:
            robots_allowed = self.robots.can_fetch(link)
        except Exception:
            self.logger.exception(
                (
                    "Robots.txt evaluation failed; discovered URL will not be "
                    "enqueued: url=%s parent_url=%s"
                ),
                link,
                parent_url,
            )
            self.observability.record_official_rejected(
                url=link,
                reason="robots_txt_evaluation_error_before_enqueue",
            )
            return

        if not robots_allowed:
            self.logger.warning(
                (
                    "Robots.txt blocked discovered URL before enqueue: "
                    "url=%s parent_url=%s depth=%s"
                ),
                link,
                parent_url,
                depth,
            )
            self.observability.record_official_rejected(
                url=link,
                reason="robots_txt_blocked_before_enqueue",
            )
            return

        if not self._claim_url_ownership(link):
            return

        _ = self.database.enqueue_url(
            url=link,
            url_hash=self.dedup.url_hash(link),
            depth=depth,
            discovered_from=parent_url,
            priority=intent.priority,
        )

        self.logger.debug(
            ("Discovered URL enqueued: url=%s parent_url=%s depth=%s priority=%s"),
            link,
            parent_url,
            depth,
            intent.priority,
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

        decision = self.policy.evaluate_discovered_url(
            link,
            parent_url=parent_url,
            depth=depth,
            known_hosts=self.official_graph.known_hosts(),
            allow_official_cross_host=(self.config.allow_official_cross_host_discovery),
        )

        if not decision.allowed:
            self._record_scope_rejection(
                url=link,
                decision=decision,
            )
            return None

        if not self.policy.same_scope(link):
            self._record_official_scope_allow(
                url=link,
                parent_url=parent_url,
                depth=depth,
                decision=decision,
            )

        return link

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
        """Return whether the canonical scope policy permits an official URL."""

        if not self.config.allow_official_cross_host_discovery:
            return False

        decision = self.policy.evaluate_official_url(
            url,
            parent_url=parent_url,
            depth=depth,
            known_hosts=self.official_graph.known_hosts(),
        )

        if not decision.allowed:
            self.observability.record_official_rejected(
                url=url,
                reason=decision.reason,
            )
            return False

        self._record_official_scope_allow(
            url=url,
            parent_url=parent_url,
            depth=depth,
            decision=decision,
        )
        return True

    def _record_scope_rejection(
        self,
        *,
        url: str,
        decision: PolicyResult,
    ) -> None:
        self.observability.record_official_rejected(
            url=url,
            reason=f"smart_url_policy:{decision.reason}",
        )
        self.logger.info(
            (
                "Smart URL policy rejected discovered URL before enqueue: "
                "url=%s decision=%s reason=%s"
            ),
            url,
            decision.decision.value,
            decision.reason,
        )

    def _record_official_scope_allow(
        self,
        *,
        url: str,
        parent_url: str | None,
        depth: int,
        decision: PolicyResult,
    ) -> None:
        self.official_graph.learn_host(
            url=url,
            parent_url=parent_url,
            confidence=75,
            reason=decision.reason,
            depth=depth,
        )
        self.observability.record_official_allowed(
            url=url,
            reason=decision.reason,
        )
        self.logger.info(
            "Canonical scope policy allowed official URL: url=%s reason=%s",
            url,
            decision.reason,
        )

    def _claim_url_ownership(self, url: str) -> bool:
        return claim_url_ownership(
            url=url,
            registry=self.global_url_registry,
            owner_project=self.owner_project,
            owner_project_dir=self.config.output_dir,
            logger=self.logger,
        )

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
