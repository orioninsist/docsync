"""HTML extraction, scoring, and queue-item processing for discovery."""

from __future__ import annotations

from urllib.parse import urlparse

import aiohttp

from crawler.discovery_fetch import fetch_text
from crawler.discovery_links import (
    extract_real_urls_from_html as extract_html_urls,
)
from crawler.discovery_runtime import (
    DiscoveryRunState,
    log,
    strict_normalize_discovery_url,
)
from crawler.discovery_types import (
    DiscoveryQueueItem,
    DiscoveryScore,
)
from crawler.discovery_url_rules import normalize_candidate_url

DISCOVERY_MAX_DEFAULT_DEPTH = 3
DISCOVERY_MAX_LINKS_PER_PAGE = 250

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


def host_without_www(url: str) -> str:
    """Return a normalized hostname without the leading www label."""

    hostname = (urlparse(url).hostname or "").lower()

    if hostname.startswith("www."):
        return hostname[4:]

    return hostname


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

        state.record_page_quality(
            links,
            scorer=score_real_discovered_url,
        )

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
            f"url={item.url} "
            f"detail={exc}"
        )
        return True
