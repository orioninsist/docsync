"""Recursive breadth-first discovery orchestration for crawler queue building."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol
from urllib.parse import urlparse

from crawler.language_gate import allow_english_html


# pylint: disable=too-few-public-methods
class DiscoveryDatabase(Protocol):
    """Minimal closeable database connection protocol used by discovery state."""

    def close(self) -> None:
        """Close the discovery database connection."""


# pylint: disable=too-few-public-methods
@dataclass(frozen=True)
class RecursiveBFSResult:
    """Result produced by recursive breadth-first discovery."""

    discovered: list[str]
    blocked: list[Any]


# pylint: disable=too-many-instance-attributes
@dataclass(frozen=True)
class RecursiveBFSHooks:
    """External callbacks required by recursive breadth-first discovery."""

    discovery_result_type: type
    normalize_url: Callable[..., str | None]
    final_txt_candidate: Callable[[str, str], tuple[str | None, str | None]]
    sitemap_candidates: Callable[..., Awaitable[list[str]]]
    certificate_transparency_subdomain_candidates: Callable[..., Awaitable[list[str]]]
    fetch_text: Callable[..., Awaitable[str | None]]
    extract_real_urls_from_html: Callable[[str, str], list[str]]
    discovery_db_key: Callable[[str], str]
    open_discovery_db: Callable[[], DiscoveryDatabase]
    mark_seen: Callable[..., bool]
    update_seen: Callable[..., None]
    log: Callable[[str], None]


@dataclass(frozen=True)
class RecursiveBFSLimits:
    """Page, host, and depth limits for recursive breadth-first discovery."""

    limit: int
    max_default_pages: int
    max_accepted_multiplier: int
    max_default_depth: int

    @property
    def max_pages(self) -> int:
        """Return the effective maximum number of pages to process."""
        return max(self.max_default_pages, self.limit * self.max_accepted_multiplier)


# pylint: disable=too-many-instance-attributes
@dataclass
class RecursiveBFSContext:
    """Mutable runtime state for recursive breadth-first discovery."""

    session: Any
    base_url: str
    hooks: RecursiveBFSHooks
    limits: RecursiveBFSLimits
    seed_key: str
    connection: DiscoveryDatabase
    started: float
    queue: list[tuple[str, int, str | None]]
    discovered: list[str]
    blocked: list[Any]


def _add_blocked(context: RecursiveBFSContext, raw_url: str, reason: str) -> None:
    """Record a blocked discovery candidate."""
    if raw_url:
        context.blocked.append(
            context.hooks.discovery_result_type(str(raw_url).strip(), 0, reason)
        )


def _same_seed_host(context: RecursiveBFSContext, candidate_url: str) -> bool:
    """Return True when a candidate belongs to the exact seed host."""
    seed_host = urlparse(context.base_url).netloc.lower()
    candidate_host = urlparse(candidate_url).netloc.lower()
    return bool(seed_host and candidate_host == seed_host)


def _mark_blocked(
    context: RecursiveBFSContext,
    *,
    clean_url: str,
    depth: int,
    discovered_from: str | None,
    reason: str,
) -> None:
    """Persist a blocked candidate in discovery state."""
    _add_blocked(context, clean_url, reason)
    context.hooks.mark_seen(
        context.connection,
        seed_key=context.seed_key,
        url=clean_url,
        depth=depth,
        status="blocked",
        discovered_from=discovered_from,
        reason=reason,
    )


def _enqueue(
    context: RecursiveBFSContext,
    raw_url: str,
    *,
    depth: int,
    discovered_from: str | None,
    reason: str,
) -> None:
    """Normalize, filter, persist, and enqueue one candidate URL."""
    clean = context.hooks.normalize_url(raw_url, base_url=discovered_from)

    if clean is None:
        _add_blocked(context, raw_url, "invalid_or_unsafe_url")
        return

    if reason == "html_recursive_link" and not _same_seed_host(context, clean):
        _mark_blocked(
            context,
            clean_url=clean,
            depth=depth,
            discovered_from=discovered_from,
            reason="blocked_cross_host_bfs_traversal",
        )
        return

    _final_txt_url, block_reason = context.hooks.final_txt_candidate(
        context.base_url,
        clean,
    )

    if block_reason:
        _mark_blocked(
            context,
            clean_url=clean,
            depth=depth,
            discovered_from=discovered_from,
            reason=block_reason,
        )
        return

    inserted = context.hooks.mark_seen(
        context.connection,
        seed_key=context.seed_key,
        url=clean,
        depth=depth,
        status="pending",
        discovered_from=discovered_from,
        reason=reason,
    )

    if inserted or reason == "seed":
        context.queue.append((clean, depth, discovered_from))

        if clean not in context.discovered:
            context.discovered.append(clean)


async def _enqueue_sitemap_candidates(context: RecursiveBFSContext) -> None:
    """Collect sitemap candidates and enqueue accepted URLs."""
    context.hooks.log("  [2/6] adding sitemap real candidates")
    candidates = await context.hooks.sitemap_candidates(
        context.session,
        context.base_url,
    )
    for candidate in candidates:
        _enqueue(
            context,
            candidate,
            depth=0,
            discovered_from=context.base_url,
            reason="sitemap_url",
        )


async def _safe_ct_candidates(context: RecursiveBFSContext) -> list[str]:
    """Return certificate transparency candidates, or an empty list on failure."""
    try:
        return await context.hooks.certificate_transparency_subdomain_candidates(
            context.session,
            context.base_url,
            max_hosts=max(2500, context.limits.limit * 50),
        )
    except (OSError, TimeoutError, ValueError):
        return []


async def _enqueue_ct_candidates(context: RecursiveBFSContext) -> None:
    """Skip CT expansion during bounded same-host BFS discovery."""
    context.hooks.log("  [3/6] skipping CT subdomain candidates for bounded BFS")
    context.hooks.log("       CT candidates=0 skipped=bounded_same_host_discovery")


def _mark_depth_limited(context: RecursiveBFSContext, current_url: str) -> None:
    """Persist that a queued URL exceeded the configured crawl depth."""
    context.hooks.update_seen(
        context.connection,
        seed_key=context.seed_key,
        url=current_url,
        status="depth_limited",
        reason="max_depth_reached",
    )


def _mark_fetch_empty(context: RecursiveBFSContext, current_url: str) -> None:
    """Persist that a queued URL did not return usable HTML."""
    context.hooks.update_seen(
        context.connection,
        seed_key=context.seed_key,
        url=current_url,
        status="fetch_empty",
        reason="no_html_or_blocked_fetch",
    )


def _log_progress(
    context: RecursiveBFSContext,
    *,
    processed: int,
    current_url: str,
    depth: int,
) -> None:
    """Log periodic recursive discovery progress."""
    if processed != 1 and processed % 10 != 0:
        return

    elapsed = max(time.time() - context.started, 1)
    context.hooks.log(
        f"       PROGRESS processed={processed}/{context.limits.max_pages} "
        f"queued={len(context.queue)} discovered={len(context.discovered)} "
        f"blocked={len(context.blocked)} depth={depth} "
        f"speed={processed / elapsed:.2f}/s"
    )
    context.hooks.log(f"       current={current_url}")


def _mark_processed(
    context: RecursiveBFSContext,
    *,
    current_url: str,
    links: list[str],
) -> None:
    """Persist that a queued URL was processed and links were extracted."""
    context.hooks.update_seen(
        context.connection,
        seed_key=context.seed_key,
        url=current_url,
        status="processed",
        reason=f"links_extracted:{len(links)}",
    )


async def _process_current_url(
    context: RecursiveBFSContext,
    *,
    current_url: str,
    depth: int,
) -> None:
    """Fetch one queued URL, extract links, and enqueue child candidates."""
    html = await context.hooks.fetch_text(context.session, current_url)

    if not html:
        _mark_fetch_empty(context, current_url)
        return

    language_result = allow_english_html(html)
    if not language_result.allowed:
        context.hooks.update_seen(
            context.connection,
            seed_key=context.seed_key,
            url=current_url,
            status="non_english_html",
            reason=language_result.reason,
        )
        _add_blocked(context, current_url, language_result.reason)
        return

    links = context.hooks.extract_real_urls_from_html(html, current_url)
    _mark_processed(context, current_url=current_url, links=links)

    for link in links:
        _enqueue(
            context,
            link,
            depth=depth + 1,
            discovered_from=current_url,
            reason="html_recursive_link",
        )


async def _walk_link_graph(context: RecursiveBFSContext) -> int:
    """Walk the queued URL graph until the queue or page budget is exhausted."""
    context.hooks.log("  [4/6] walking real link graph recursively")
    processed = 0

    while context.queue and processed < context.limits.max_pages:
        current_url, depth, _parent_url = context.queue.pop(0)

        if depth > context.limits.max_default_depth:
            _mark_depth_limited(context, current_url)
            continue

        processed += 1
        _log_progress(
            context,
            processed=processed,
            current_url=current_url,
            depth=depth,
        )
        await _process_current_url(context, current_url=current_url, depth=depth)

    return processed


def _build_context(
    *,
    session: Any,
    base_url: str,
    hooks: RecursiveBFSHooks,
    limits: RecursiveBFSLimits,
) -> RecursiveBFSContext:
    """Create the mutable runtime context for recursive discovery."""
    seed_key = hooks.discovery_db_key(base_url)
    return RecursiveBFSContext(
        session=session,
        base_url=base_url,
        hooks=hooks,
        limits=limits,
        seed_key=seed_key,
        connection=hooks.open_discovery_db(),
        started=time.time(),
        queue=[],
        discovered=[],
        blocked=[],
    )


# pylint: disable=too-many-arguments,too-many-locals
async def run_recursive_bfs_discovery(
    *,
    session: Any,
    base_url: str,
    limit: int,
    discovery_result_type: type,
    normalize_url: Callable[..., str | None],
    final_txt_candidate: Callable[[str, str], tuple[str | None, str | None]],
    sitemap_candidates: Callable[..., Awaitable[list[str]]],
    certificate_transparency_subdomain_candidates: Callable[..., Awaitable[list[str]]],
    fetch_text: Callable[..., Awaitable[str | None]],
    extract_real_urls_from_html: Callable[[str, str], list[str]],
    discovery_db_key: Callable[[str], str],
    open_discovery_db: Callable[[], DiscoveryDatabase],
    mark_seen: Callable[..., bool],
    update_seen: Callable[..., None],
    log: Callable[[str], None],
    max_default_pages: int,
    max_accepted_multiplier: int,
    max_default_depth: int,
) -> RecursiveBFSResult:
    """Run recursive BFS discovery while preserving the legacy callback API."""
    hooks = RecursiveBFSHooks(
        discovery_result_type=discovery_result_type,
        normalize_url=normalize_url,
        final_txt_candidate=final_txt_candidate,
        sitemap_candidates=sitemap_candidates,
        certificate_transparency_subdomain_candidates=(
            certificate_transparency_subdomain_candidates
        ),
        fetch_text=fetch_text,
        extract_real_urls_from_html=extract_real_urls_from_html,
        discovery_db_key=discovery_db_key,
        open_discovery_db=open_discovery_db,
        mark_seen=mark_seen,
        update_seen=update_seen,
        log=log,
    )
    limits = RecursiveBFSLimits(
        limit=limit,
        max_default_pages=max_default_pages,
        max_accepted_multiplier=max_accepted_multiplier,
        max_default_depth=max_default_depth,
    )
    context = _build_context(
        session=session,
        base_url=base_url,
        hooks=hooks,
        limits=limits,
    )

    try:
        _enqueue(context, base_url, depth=0, discovered_from=None, reason="seed")
        log("  [1/6] recursive BFS seed prepared")
        log(f"       seed={base_url}")

        await _enqueue_sitemap_candidates(context)
        await _enqueue_ct_candidates(context)
        processed = await _walk_link_graph(context)

        log(
            f"       BFS finished processed={processed} "
            f"discovered={len(context.discovered)} blocked={len(context.blocked)}"
        )
    finally:
        context.connection.close()

    return RecursiveBFSResult(
        discovered=list(dict.fromkeys(context.discovered)),
        blocked=context.blocked,
    )
