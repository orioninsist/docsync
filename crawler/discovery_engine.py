"""Recursive discovery engine for building crawler queue candidates."""

from __future__ import annotations

import aiohttp

from crawler.discovery_fetch import (
    certificate_transparency_candidates,
    robots_sitemaps,
    sitemap_candidates,
)
from crawler.discovery_parts.state import open_discovery_db
from crawler.discovery_paths import normalized_host
from crawler.discovery_processing import process_queue_item
from crawler.discovery_result import DiscoveryResult
from crawler.discovery_runtime import DiscoveryRunState, log

DISCOVERY_MAX_ACCEPTED_MULTIPLIER = 10
DISCOVERY_MAX_DEFAULT_PAGES = 30
DISCOVERY_MAX_NO_NEW_GOOD = 40
DISCOVERY_MIN_GOOD_SCORE = 2
DISCOVERY_QUALITY_EXTRA_SCAN_PAGES = 80
DISCOVERY_SCOPE_WIDENING_CONFIRMATIONS = 2


def host_without_www(url: str) -> str:
    """Return a normalized host without a leading www label."""

    return normalized_host(url)


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

    log(f"       external candidates={len(candidates)} " + "scope_evidence=disabled")


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

    log(f"       CT candidates={len(ct_candidates)} " + "scope_evidence=disabled")


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
            _ = state.mark_status(
                item.url,
                "unexpected_error",
                type(exc).__name__,
            )
            log(
                "       UNEXPECTED PROCESS ERROR "
                + f"type={type(exc).__name__} "
                + f"url={item.url}"
            )
            should_continue = True

        if not should_continue:
            break


def finish_discovery(
    state: DiscoveryRunState,
) -> tuple[list[str], list[DiscoveryResult]]:
    """Return fetched discovery URLs and blocked results."""

    successful_urls = list(dict.fromkeys(state.discovered))

    log(
        f"       BFS finished processed={state.processed} "
        + f"verified={len(successful_urls)} "
        + f"blocked={len(state.blocked_results)} "
        + f"scope={state.learned_path_prefix or '<unlearned>'}"
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
