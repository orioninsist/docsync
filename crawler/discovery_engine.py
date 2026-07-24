"""Recursive discovery engine for building crawler queue candidates."""

from __future__ import annotations

import sqlite3
import time
from collections import deque
from dataclasses import dataclass, field
from typing import NamedTuple
from urllib.parse import urljoin, urlparse

import aiohttp

from crawler.discovery_links import extract_real_urls_from_html as extract_html_urls
from crawler.discovery_result import DiscoveryResult
from crawler.discovery_state import (
    discovery_db_key,
    discovery_mark_seen,
    discovery_update_seen_status,
    open_discovery_db,
)
from crawler.discovery_url_rules import normalize_candidate_url
from crawler.policy_engine import SmartScopePolicy

DISCOVERY_MAX_ACCEPTED_MULTIPLIER = 10
DISCOVERY_MAX_DEFAULT_DEPTH = 3
DISCOVERY_MAX_DEFAULT_PAGES = 30
DISCOVERY_MAX_LINKS_PER_PAGE = 250
DISCOVERY_REQUEST_TIMEOUT_SECONDS = 20
DISCOVERY_MAX_NO_NEW_GOOD = 40
DISCOVERY_MIN_GOOD_SCORE = 2
DISCOVERY_QUALITY_EXTRA_SCAN_PAGES = 80
DISCOVERY_MIN_BRANCH_LINKS = 2
DISCOVERY_SCOPE_WIDENING_CONFIRMATIONS = 2
HTTP_ERROR_STATUS = 400

GOOD_PATH_HINTS = (
    "about",
    "blog",
    "case",
    "company",
    "contact",
    "customer",
    "docs",
    "features",
    "guide",
    "help",
    "learn",
    "news",
    "platform",
    "product",
    "resource",
    "solution",
    "support",
)


class DiscoveryQueueItem(NamedTuple):
    """Queued URL plus traversal metadata."""

    url: str
    depth: int
    discovered_from: str | None


class DiscoveryScore(NamedTuple):
    """Simple quality score for a discovered URL."""

    score: int


def normalized_host(url: str) -> str:
    """Return a lowercase host without a leading www label."""

    return urlparse(url).netloc.lower().removeprefix("www.")


def normalized_path(url: str) -> str:
    """Return a normalized absolute URL path."""

    path = urlparse(url).path or "/"

    if path != "/":
        path = path.rstrip("/")

    return path or "/"


def path_segments(path: str) -> tuple[str, ...]:
    """Return non-empty path segments."""

    return tuple(part for part in path.split("/") if part)


def path_from_segments(segments: tuple[str, ...]) -> str:
    """Build an absolute path from normalized segments."""

    if not segments:
        return "/"

    return "/" + "/".join(segments)


def path_is_inside_prefix(path: str, prefix: str) -> bool:
    """Return whether a path is equal to or below a prefix boundary."""

    normalized_candidate = path.rstrip("/") or "/"
    normalized_prefix = prefix.rstrip("/") or "/"

    if normalized_prefix == "/":
        return True

    return (
        normalized_candidate == normalized_prefix
        or normalized_candidate.startswith(normalized_prefix + "/")
        or normalized_candidate.startswith(normalized_prefix + ".")
    )


def common_path_prefix(paths: list[str]) -> str | None:
    """Return the longest non-root path shared by supplied paths."""

    unique_segments = {
        path_segments(path)
        for path in paths
        if path and path != "/"
    }

    if len(unique_segments) < 2:
        return None

    ordered = sorted(unique_segments)
    first = ordered[0]
    last = ordered[-1]
    shared: list[str] = []

    for left, right in zip(first, last, strict=False):
        if left != right:
            break

        shared.append(left)

    if not shared:
        return None

    return path_from_segments(tuple(shared))


def source_branch_candidates(source_url: str) -> list[str]:
    """Return source-ancestor branches ordered deepest first.

    For a document-like source URL, the final path component is excluded.
    For a directory URL ending in a slash, the directory itself is included.
    """

    parsed = urlparse(source_url)
    source_path = normalized_path(source_url)
    segments = path_segments(source_path)

    if not segments:
        return []

    if parsed.path.endswith("/"):
        deepest_size = len(segments)
    else:
        deepest_size = len(segments) - 1

    if deepest_size <= 0:
        return []

    return [
        path_from_segments(segments[:size])
        for size in range(deepest_size, 0, -1)
    ]


def same_host_real_paths(
    *,
    base_url: str,
    links: list[str],
) -> list[str]:
    """Return unique same-host paths from real extracted links."""

    base_host = normalized_host(base_url)
    paths: list[str] = []
    seen: set[str] = set()

    for link in links:
        if normalized_host(link) != base_host:
            continue

        path = normalized_path(link)

        if path in seen:
            continue

        seen.add(path)
        paths.append(path)

    return paths


def branch_support_count(
    branch_prefix: str,
    real_paths: list[str],
) -> int:
    """Count unique real paths contained by one candidate branch."""

    return sum(
        1
        for path in real_paths
        if path_is_inside_prefix(path, branch_prefix)
    )


def infer_scope_prefix_from_real_links(
    *,
    base_url: str,
    source_url: str,
    links: list[str],
) -> str | None:
    """Infer the deepest source branch supported by real HTML links.

    Scope evidence is restricted to links from the same host. Candidate
    branches are ancestors of the fetched source page, ordered deepest first.
    The first branch containing multiple real links becomes the proposal.
    """

    if normalized_host(source_url) != normalized_host(base_url):
        return None

    real_paths = same_host_real_paths(
        base_url=base_url,
        links=links,
    )

    if len(real_paths) < DISCOVERY_MIN_BRANCH_LINKS:
        return None

    for branch_prefix in source_branch_candidates(source_url):
        support = branch_support_count(
            branch_prefix,
            real_paths,
        )

        if support >= DISCOVERY_MIN_BRANCH_LINKS:
            return branch_prefix

    return None


def merge_scope_prefixes(
    current_prefix: str | None,
    proposed_prefix: str,
) -> str | None:
    """Return a safe relationship-based scope merge result.

    A narrower proposal does not narrow an established scope. A broader
    ancestor proposal may widen it. Unrelated branches are rejected.
    """

    if current_prefix is None:
        return proposed_prefix

    if path_is_inside_prefix(proposed_prefix, current_prefix):
        return current_prefix

    if path_is_inside_prefix(current_prefix, proposed_prefix):
        return proposed_prefix

    return None


def discovery_path_prefix(base_url: str) -> str:
    """Return the host-safe bootstrap path before scope learning."""

    del base_url
    return "/"


def build_discovery_policy(
    base_url: str,
    *,
    allowed_path_prefix: str | None = None,
) -> SmartScopePolicy:
    """Build crawler policy with an explicit or bootstrap path boundary."""

    return SmartScopePolicy(
        start_url=base_url,
        allowed_path_prefix=(
            allowed_path_prefix
            or discovery_path_prefix(base_url)
        ),
    )


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
        """Return the maximum number of pages to process during discovery."""

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

        log(
            f"       SCOPE {action} "
            f"previous={previous_prefix or '<none>'} "
            f"current={prefix} "
            f"source={source_url}"
        )

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
            log(
                "       SCOPE unchanged "
                "reason=insufficient_same_branch_evidence "
                f"source={source_url}"
            )
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
            log(
                "       SCOPE unchanged "
                "reason=unrelated_branch_proposal "
                f"current={self.learned_path_prefix} "
                f"proposed={proposed_prefix} "
                f"source={source_url}"
            )
            return

        if merged_prefix == self.learned_path_prefix:
            return

        confirmation_count = self.record_widening_evidence(
            proposed_prefix=merged_prefix,
            source_url=source_url,
        )

        log(
            "       SCOPE WIDENING EVIDENCE "
            f"current={self.learned_path_prefix} "
            f"proposed={merged_prefix} "
            f"confirmations={confirmation_count}/"
            f"{DISCOVERY_SCOPE_WIDENING_CONFIRMATIONS} "
            f"source={source_url}"
        )

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
        """Update discovery status without terminating the crawl on DB failure."""

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
            log(
                "       DISCOVERY STATE WRITE ERROR "
                f"type={type(exc).__name__} "
                f"status={status} "
                f"url={url} "
                f"detail={exc}"
            )
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
        """Normalize, filter, persist, and enqueue a candidate URL."""

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
            discovery_mark_seen(
                self.connection,
                seed_key=self.seed_key,
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
            discovery_mark_seen(
                self.connection,
                seed_key=self.seed_key,
                url=clean,
                depth=depth,
                status="blocked",
                discovered_from=discovered_from,
                reason=policy_result.reason,
            )
            return

        if clean in self.queued_urls:
            return

        discovery_mark_seen(
            self.connection,
            seed_key=self.seed_key,
            url=clean,
            depth=depth,
            status="pending",
            discovered_from=discovered_from,
            reason=reason,
        )

        self.queued_urls.add(clean)
        self.queue.append(
            DiscoveryQueueItem(
                clean,
                depth,
                discovered_from,
            )
        )

    def log_progress(self, current_url: str, depth: int) -> None:
        """Log progress for the active traversal."""

        elapsed = max(time.time() - self.started, 1.0)
        speed = self.processed / elapsed

        log(
            f"       PROGRESS processed={self.processed}/{self.max_pages} "
            f"queued={len(self.queue)} "
            f"discovered={len(self.discovered)} "
            f"good_pages={self.accepted_good} "
            f"no_new_good={self.no_new_good} "
            f"blocked={len(self.blocked_results)} "
            f"depth={depth} "
            f"scope={self.learned_path_prefix or '<unlearned>'} "
            f"speed={speed:.2f}/s"
        )
        log(f"       current={current_url}")

    def record_page_quality(self, links: list[str]) -> None:
        """Track whether a processed page produced high-value links."""

        found_good = any(
            score_real_discovered_url(
                self.base_url,
                candidate,
            ).score
            >= DISCOVERY_MIN_GOOD_SCORE
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
            and self.processed
            >= quality_floor + DISCOVERY_QUALITY_EXTRA_SCAN_PAGES
        )


def log(message: str) -> None:
    """Write a crawler discovery progress message."""

    print(message, flush=True)


def strict_normalize_discovery_url(
    raw_url: str,
    *,
    base_url: str | None = None,
) -> str | None:
    """Resolve and normalize one discovery URL."""

    candidate = raw_url.strip()

    if not candidate:
        return None

    if base_url:
        candidate = urljoin(base_url, candidate)

    return normalize_candidate_url(candidate)


def extract_real_urls_from_html(
    html: str,
    base_url: str,
) -> list[str]:
    """Extract normalized URLs from one HTML document."""

    return extract_html_urls(
        html,
        base_url,
        normalize=normalize_candidate_url,
    )


async def fetch_text(
    session: aiohttp.ClientSession,
    url: str,
) -> str | None:
    """Fetch textual HTML content without leaking network failures."""

    timeout = aiohttp.ClientTimeout(
        total=DISCOVERY_REQUEST_TIMEOUT_SECONDS,
        connect=10,
        sock_connect=10,
        sock_read=DISCOVERY_REQUEST_TIMEOUT_SECONDS,
    )

    try:
        async with session.get(
            url,
            allow_redirects=True,
            timeout=timeout,
        ) as response:
            if response.status >= HTTP_ERROR_STATUS:
                log(
                    f"       FETCH SKIP status={response.status} "
                    f"url={url}"
                )
                return None

            return await response.text()
    except TimeoutError:
        log(
            f"       FETCH TIMEOUT after="
            f"{DISCOVERY_REQUEST_TIMEOUT_SECONDS}s "
            f"url={url}"
        )
        return None
    except aiohttp.ClientError as exc:
        log(
            f"       FETCH ERROR type={type(exc).__name__} "
            f"url={url}"
        )
        return None
    except (OSError, UnicodeError) as exc:
        log(
            f"       FETCH ERROR type={type(exc).__name__} "
            f"url={url}"
        )
        return None


async def robots_sitemaps(
    session: aiohttp.ClientSession,
    base_url: str,
) -> list[str]:
    """Return robots sitemap candidates when a provider is configured."""

    del session, base_url
    return []


async def sitemap_candidates(
    session: aiohttp.ClientSession,
    base_url: str,
) -> list[str]:
    """Return sitemap candidates when a provider is configured."""

    del session, base_url
    return []


async def certificate_transparency_subdomain_candidates(
    session: aiohttp.ClientSession,
    base_url: str,
    *,
    max_hosts: int = 0,
) -> list[str]:
    """Return certificate-transparency hosts when configured."""

    del session, base_url, max_hosts
    return []


def host_without_www(url: str) -> str:
    """Return a normalized host without a leading www label."""

    return normalized_host(url)


def discovery_allowed_real_link(
    base_url: str,
    candidate_url: str,
) -> tuple[bool, str]:
    """Evaluate one real candidate using seed-branch evidence."""

    proposed_prefix = infer_scope_prefix_from_real_links(
        base_url=base_url,
        source_url=base_url,
        links=[candidate_url],
    )

    if proposed_prefix is None:
        return False, "insufficient_same_branch_evidence"

    result = build_discovery_policy(
        base_url,
        allowed_path_prefix=proposed_prefix,
    ).evaluate_url(candidate_url)

    return result.allowed, result.reason


def score_real_discovered_url(
    base_url: str,
    candidate_url: str,
) -> DiscoveryScore:
    """Score a candidate URL for discovery quality checks."""

    parsed = urlparse(candidate_url)
    base_host = host_without_www(base_url)
    candidate_host = host_without_www(candidate_url)
    path = parsed.path.strip("/").lower()
    score = 0

    if candidate_host == base_host:
        score += 1

    if (
        candidate_host.endswith(f".{base_host}")
        and candidate_host != base_host
    ):
        score += 1

    if path:
        score += 1

    if any(hint in path for hint in GOOD_PATH_HINTS):
        score += 2

    return DiscoveryScore(score)


def extract_recursive_links_from_html(
    html: str,
    base_url: str,
) -> list[str]:
    """Extract resolved, normalized, de-duplicated recursive links."""

    urls = extract_real_urls_from_html(html, base_url)
    kept: list[str] = []
    seen: set[str] = set()

    for raw_url in urls[:DISCOVERY_MAX_LINKS_PER_PAGE]:
        clean = strict_normalize_discovery_url(
            raw_url,
            base_url=base_url,
        )

        if clean is None or clean in seen:
            continue

        seen.add(clean)
        kept.append(clean)

    return kept


async def enqueue_robots_and_sitemap_candidates(
    session: aiohttp.ClientSession,
    state: DiscoveryRunState,
) -> None:
    """Inspect external candidates without using them as scope evidence."""

    log("  [2/6] inspecting robots/sitemap real candidates")

    robots_candidates = await robots_sitemaps(
        session,
        state.base_url,
    )
    sitemap_urls = await sitemap_candidates(
        session,
        state.base_url,
    )

    candidates = list(
        dict.fromkeys(
            [
                *robots_candidates,
                *sitemap_urls,
            ]
        )
    )

    for candidate in candidates:
        state.enqueue(
            candidate,
            depth=0,
            discovered_from=state.base_url,
            reason="external_discovery_candidate",
        )

    log(
        f"       external candidates={len(candidates)} "
        "scope_evidence=disabled"
    )


async def certificate_transparency_candidates(
    session: aiohttp.ClientSession,
    state: DiscoveryRunState,
) -> list[str]:
    """Return CT candidates without failing discovery."""

    try:
        return await certificate_transparency_subdomain_candidates(
            session,
            state.base_url,
            max_hosts=max(2500, state.limit * 50),
        )
    except (
        aiohttp.ClientError,
        TimeoutError,
        ValueError,
    ) as exc:
        log(
            f"       CT SKIP type={type(exc).__name__} "
            f"seed={state.base_url}"
        )
        return []


async def enqueue_certificate_transparency_candidates(
    session: aiohttp.ClientSession,
    state: DiscoveryRunState,
) -> None:
    """Inspect CT candidates without using them as scope evidence."""

    log("  [3/6] inspecting CT real subdomain candidates")

    ct_candidates = await certificate_transparency_candidates(
        session,
        state,
    )

    for candidate in ct_candidates:
        state.enqueue(
            candidate,
            depth=0,
            discovered_from=state.base_url,
            reason="certificate_transparency",
        )

    log(
        f"       CT candidates={len(ct_candidates)} "
        "scope_evidence=disabled"
    )


async def process_queue_item(
    session: aiohttp.ClientSession,
    state: DiscoveryRunState,
    item: DiscoveryQueueItem,
) -> bool:
    """Process one queued URL and report whether traversal should continue."""

    if item.depth > DISCOVERY_MAX_DEFAULT_DEPTH:
        state.mark_status(
            item.url,
            "depth_limited",
            "max_depth_reached",
        )
        return True

    state.processed += 1
    state.log_progress(item.url, item.depth)
    log(f"       FETCH START url={item.url}")

    try:
        html = await fetch_text(session, item.url)

        if not html:
            state.mark_status(
                item.url,
                "fetch_empty",
                "no_html_or_blocked_fetch",
            )
            return True

        state.record_discovered(item.url)

        links = extract_recursive_links_from_html(
            html,
            item.url,
        )

        state.learn_scope_from_real_links(
            source_url=item.url,
            links=links,
        )

        state.record_page_quality(links)

        if state.saturated():
            log(
                "       Quality saturation reached. "
                "Stopping discovery because no new "
                "high-value URLs were found."
            )
            return False

        state.mark_status(
            item.url,
            "processed",
            f"links_extracted:{len(links)}",
        )

        next_depth = item.depth + 1

        for link in links:
            state.enqueue(
                link,
                depth=next_depth,
                discovered_from=item.url,
                reason="html_recursive_link",
            )

        return True
    except (
        OSError,
        UnicodeError,
        ValueError,
    ) as exc:
        state.mark_status(
            item.url,
            "processing_error",
            type(exc).__name__,
        )
        log(
            f"       PROCESS ERROR type={type(exc).__name__} "
            f"url={item.url}"
        )
        return True


async def walk_recursive_link_graph(
    session: aiohttp.ClientSession,
    state: DiscoveryRunState,
) -> None:
    """Walk the queued recursive link graph until limits are reached."""

    log("  [4/6] walking real link graph recursively")

    while state.queue and state.processed < state.max_pages:
        item = state.queue.popleft()

        try:
            should_continue = await process_queue_item(
                session,
                state,
                item,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            state.mark_status(
                item.url,
                "unexpected_error",
                type(exc).__name__,
            )
            log(
                "       UNEXPECTED PROCESS ERROR "
                f"type={type(exc).__name__} "
                f"url={item.url}"
            )
            should_continue = True

        if not should_continue:
            break


def finish_discovery(
    state: DiscoveryRunState,
) -> tuple[list[str], list[DiscoveryResult]]:
    """Return fetched discovery URLs and blocked results."""

    successful_urls = list(
        dict.fromkeys(state.discovered)
    )

    log(
        f"       BFS finished processed={state.processed} "
        f"verified={len(successful_urls)} "
        f"blocked={len(state.blocked_results)} "
        f"scope={state.learned_path_prefix or '<unlearned>'}"
    )

    return successful_urls, state.blocked_results


async def recursive_bfs_discovery_candidates(
    session: aiohttp.ClientSession,
    *,
    base_url: str,
    limit: int,
) -> tuple[list[str], list[DiscoveryResult]]:
    """Discover real crawler candidates through recursive traversal."""

    connection = open_discovery_db(base_url)
    state = DiscoveryRunState(
        base_url=base_url,
        limit=limit,
        connection=connection,
    )

    try:
        state.enqueue(
            base_url,
            depth=0,
            discovered_from=None,
            reason="seed",
        )

        log("  [1/6] recursive BFS seed prepared")
        log(f"       seed={base_url}")

        await enqueue_robots_and_sitemap_candidates(
            session,
            state,
        )
        await enqueue_certificate_transparency_candidates(
            session,
            state,
        )
        await walk_recursive_link_graph(
            session,
            state,
        )

        return finish_discovery(state)
    finally:
        connection.close()
