"""Mutable runtime state for recursive discovery runs."""

from __future__ import annotations

import sqlite3
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from crawler.discovery_result import DiscoveryResult
from crawler.discovery_scope import (
    build_discovery_policy,
    infer_scope_prefix_from_real_links,
    merge_scope_prefixes,
)
from crawler.discovery_state import (
    discovery_db_key,
    discovery_mark_seen,
    discovery_update_seen_status,
)
from crawler.discovery_types import DiscoveryQueueItem
from crawler.discovery_url_rules import normalize_candidate_url
from crawler.policy_engine import SmartScopePolicy

DISCOVERY_MAX_ACCEPTED_MULTIPLIER = 10
DISCOVERY_MAX_DEFAULT_PAGES = 30
DISCOVERY_MAX_NO_NEW_GOOD = 40
DISCOVERY_MIN_GOOD_SCORE = 2
DISCOVERY_QUALITY_EXTRA_SCAN_PAGES = 80
DISCOVERY_SCOPE_WIDENING_CONFIRMATIONS = 2


class DiscoveryScoreResult(Protocol):
    """Structural contract required from discovery URL scorers."""

    @property
    def score(self) -> int: ...


DiscoveryUrlScorer = Callable[[str, str], DiscoveryScoreResult]


def log(message: str) -> None:
    """Write a discovery runtime progress message."""

    print(message, flush=True)


def strict_normalize_discovery_url(
    raw_url: str,
    *,
    base_url: str | None = None,
) -> str | None:
    """Resolve and normalize one discovery URL."""

    from urllib.parse import urljoin

    candidate = raw_url.strip()

    if not candidate:
        return None

    if base_url:
        candidate = urljoin(base_url, candidate)

    return normalize_candidate_url(candidate)


@dataclass
class DiscoveryRunState:  # pylint: disable=too-many-instance-attributes
    """Mutable state for one recursive discovery run."""

    base_url: str
    limit: int
    connection: sqlite3.Connection
    started: float = field(default_factory=time.time)
    policy: SmartScopePolicy = field(init=False)
    learned_path_prefix: str | None = None
    widening_evidence: dict[str, set[str]] = field(default_factory=dict)
    queue: deque[DiscoveryQueueItem] = field(default_factory=deque)
    queued_urls: set[str] = field(default_factory=set)
    discovered: list[str] = field(default_factory=list)
    blocked_results: list[DiscoveryResult] = field(default_factory=list)
    processed: int = 0
    accepted_good: int = 0
    no_new_good: int = 0

    def __post_init__(self) -> None:
        """Build a host-safe bootstrap policy for the seed request."""

        self.policy = build_discovery_policy(self.base_url)

    @property
    def seed_key(self) -> str:
        """Return the normalized persistence key for the seed URL."""

        return discovery_db_key(self.base_url)

    @property
    def max_pages(self) -> int:
        """Return the maximum number of pages processed during discovery."""

        return max(
            DISCOVERY_MAX_DEFAULT_PAGES,
            self.limit * DISCOVERY_MAX_ACCEPTED_MULTIPLIER,
        )

    @property
    def scope_learned(self) -> bool:
        """Return whether HTML evidence established a path scope."""

        return self.learned_path_prefix is not None

    def install_scope(
        self,
        *,
        prefix: str,
        source_url: str,
        action: str,
    ) -> None:
        """Install a learned scope and rebuild the shared policy."""

        previous_prefix = self.learned_path_prefix
        self.learned_path_prefix = prefix
        self.policy = build_discovery_policy(
            self.base_url,
            allowed_path_prefix=prefix,
        )

        message = "".join(
            (
                f"       SCOPE {action} ",
                f"previous={previous_prefix or '<none>'} ",
                f"current={prefix} ",
                f"source={source_url}",
            )
        )
        log(message)

    def record_widening_evidence(
        self,
        *,
        proposed_prefix: str,
        source_url: str,
    ) -> int:
        """Record one fetched page supporting a broader scope."""

        sources = self.widening_evidence.setdefault(
            proposed_prefix,
            set(),
        )
        sources.add(source_url)
        return len(sources)

    def learn_scope_from_real_links(
        self,
        *,
        source_url: str,
        links: list[str],
    ) -> None:
        """Learn or cautiously widen scope using real HTML links only."""

        proposed_prefix = infer_scope_prefix_from_real_links(
            base_url=self.base_url,
            source_url=source_url,
            links=links,
        )

        if proposed_prefix is None:
            message = "".join(
                (
                    "       SCOPE unchanged ",
                    "reason=insufficient_same_branch_evidence ",
                    f"source={source_url}",
                )
            )
            log(message)
            return

        if self.learned_path_prefix is None:
            self.install_scope(
                prefix=proposed_prefix,
                source_url=source_url,
                action="LEARNED",
            )
            return

        merged_prefix = merge_scope_prefixes(
            self.learned_path_prefix,
            proposed_prefix,
        )

        if merged_prefix is None:
            message = "".join(
                (
                    "       SCOPE unchanged ",
                    "reason=unrelated_branch_proposal ",
                    f"current={self.learned_path_prefix} ",
                    f"proposed={proposed_prefix} ",
                    f"source={source_url}",
                )
            )
            log(message)
            return

        if merged_prefix == self.learned_path_prefix:
            return

        confirmation_count = self.record_widening_evidence(
            proposed_prefix=merged_prefix,
            source_url=source_url,
        )

        message = "".join(
            (
                "       SCOPE WIDENING EVIDENCE ",
                f"current={self.learned_path_prefix} ",
                f"proposed={merged_prefix} ",
                f"confirmations={confirmation_count}/",
                f"{DISCOVERY_SCOPE_WIDENING_CONFIRMATIONS} ",
                f"source={source_url}",
            )
        )
        log(message)

        if confirmation_count < DISCOVERY_SCOPE_WIDENING_CONFIRMATIONS:
            return

        self.install_scope(
            prefix=merged_prefix,
            source_url=source_url,
            action="WIDENED",
        )

    def add_blocked(self, url: str, reason: str) -> None:
        """Record a blocked URL in the result list."""

        self.blocked_results.append(
            DiscoveryResult(
                url=url.rstrip("/") + "/",
                source="engine_blocked",
                score=0,
                reason=reason,
            )
        )

    def mark_status(self, url: str, status: str, reason: str) -> bool:
        """Update status without terminating discovery on DB failure."""

        try:
            discovery_update_seen_status(
                self.connection,
                seed_key=self.seed_key,
                url=url,
                status=status,
                reason=reason,
            )
            return True
        except sqlite3.Error as exc:
            message = "".join(
                (
                    "       DISCOVERY STATE WRITE ERROR ",
                    f"type={type(exc).__name__} ",
                    f"status={status} ",
                    f"url={url} ",
                    f"detail={exc}",
                )
            )
            log(message)
            return False

    def record_discovered(self, url: str) -> None:
        """Record one successfully fetched discovery URL."""

        if url not in self.discovered:
            self.discovered.append(url)

    def candidate_may_use_scope(
        self,
        *,
        reason: str,
    ) -> tuple[bool, str]:
        """Protect bootstrap traversal from external discovery sources."""

        if reason == "seed":
            return True, "seed"

        if self.scope_learned and reason == "html_recursive_link":
            return True, "dynamic_scope_learned"

        if reason == "html_recursive_link":
            return False, "dynamic_scope_not_learned"

        return False, "scope_requires_real_html_link_evidence"

    def enqueue(
        self,
        raw_url: str,
        *,
        depth: int,
        discovered_from: str | None,
        reason: str,
    ) -> None:
        """Normalize, filter, persist, and enqueue one candidate URL."""

        clean = strict_normalize_discovery_url(
            raw_url,
            base_url=discovered_from,
        )

        if clean is None:
            if raw_url:
                self.blocked_results.append(
                    DiscoveryResult(
                        url=str(raw_url).strip(),
                        source="engine_blocked",
                        score=0,
                        reason="invalid_or_unsafe_url",
                    )
                )
            return

        may_use_scope, scope_reason = self.candidate_may_use_scope(
            reason=reason,
        )

        if not may_use_scope:
            self.add_blocked(clean, scope_reason)
            _ = self._persist_seen(
                url=clean,
                depth=depth,
                status="blocked",
                discovered_from=discovered_from,
                reason=scope_reason,
            )
            return

        policy_result = self.policy.evaluate_url(clean)

        if not policy_result.allowed:
            self.add_blocked(clean, policy_result.reason)
            _ = self._persist_seen(
                url=clean,
                depth=depth,
                status="blocked",
                discovered_from=discovered_from,
                reason=policy_result.reason,
            )
            return

        if clean in self.queued_urls:
            return

        if not self._persist_seen(
            url=clean,
            depth=depth,
            status="pending",
            discovered_from=discovered_from,
            reason=reason,
        ):
            return

        self.queued_urls.add(clean)
        self.queue.append(
            DiscoveryQueueItem(
                clean,
                depth,
                discovered_from,
            )
        )

    def _persist_seen(
        self,
        *,
        url: str,
        depth: int,
        status: str,
        discovered_from: str | None,
        reason: str,
    ) -> bool:
        """Persist queue state without allowing DB errors to crash the run."""

        try:
            _ = discovery_mark_seen(
                self.connection,
                seed_key=self.seed_key,
                url=url,
                depth=depth,
                status=status,
                discovered_from=discovered_from,
                reason=reason,
            )
            return True
        except sqlite3.Error as exc:
            message = "".join(
                (
                    "       DISCOVERY STATE WRITE ERROR ",
                    f"type={type(exc).__name__} ",
                    f"status={status} ",
                    f"url={url} ",
                    f"detail={exc}",
                )
            )
            log(message)
            return False

    def log_progress(self, current_url: str, depth: int) -> None:
        """Log progress for the active traversal."""

        elapsed = max(time.time() - self.started, 1.0)
        speed = self.processed / elapsed

        message = "".join(
            (
                f"       PROGRESS processed={self.processed}/{self.max_pages} ",
                f"queued={len(self.queue)} ",
                f"discovered={len(self.discovered)} ",
                f"good_pages={self.accepted_good} ",
                f"no_new_good={self.no_new_good} ",
                f"blocked={len(self.blocked_results)} ",
                f"depth={depth} ",
                f"scope={self.learned_path_prefix or '<unlearned>'} ",
                f"speed={speed:.2f}/s",
            )
        )
        log(message)
        log(f"       current={current_url}")

    def record_page_quality(
        self,
        links: list[str],
        *,
        scorer: DiscoveryUrlScorer,
    ) -> None:
        """Track whether a processed page produced high-value links."""

        found_good = any(
            scorer(self.base_url, candidate).score >= DISCOVERY_MIN_GOOD_SCORE
            for candidate in links
        )

        if found_good:
            self.accepted_good += 1
            self.no_new_good = 0
            return

        self.no_new_good += 1

    def saturated(self) -> bool:
        """Return True when discovery quality has saturated."""

        quality_floor = self.limit * 30

        return (
            self.accepted_good >= self.limit
            and self.processed >= quality_floor
            and self.no_new_good >= DISCOVERY_MAX_NO_NEW_GOOD
            and self.processed >= quality_floor + DISCOVERY_QUALITY_EXTRA_SCAN_PAGES
        )
