"""Redirect target extraction and final-root probing for discovery."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlparse

import aiohttp

from crawler.discovery_score import promote_discovery_root
from crawler.discovery_url_rules import normalize_candidate_url

_REDIRECT_TARGET_PARAMS = frozenset(
    {
        "url",
        "u",
        "uri",
        "target",
        "redirect",
        "redirect_url",
        "redirect_uri",
        "return",
        "return_to",
        "return_url",
        "next",
        "next_url",
        "continue",
        "continue_url",
        "dest",
        "destination",
        "to",
    }
)


def redirect_param_targets(raw_url: str) -> list[str]:
    """Extract normalized URLs from recognized redirect query parameters."""

    parsed = urlparse(raw_url)
    targets = {
        normalized
        for key, value in parse_qsl(parsed.query, keep_blank_values=False)
        if key.lower() in _REDIRECT_TARGET_PARAMS
        if (normalized := normalize_candidate_url(value))
    }

    return sorted(targets)


async def probe_final_working_root(
    session: aiohttp.ClientSession,
    *,
    seed_url: str,
    raw_url: str,
) -> str | None:
    """Return the promoted root of a reachable URL."""

    normalized = normalize_candidate_url(raw_url)

    try:
        async with session.get(
            normalized,
            allow_redirects=True,
        ) as response:
            if response.status >= 400:
                return None

            final_url = str(response.url)
    except Exception:
        return None

    return promote_discovery_root(seed_url, final_url)


async def probe_redirect_final_roots(
    session: aiohttp.ClientSession,
    *,
    seed_url: str,
    raw_urls: list[str],
) -> list[str]:
    """Probe redirect candidates and return unique reachable roots."""

    roots: set[str] = set()

    for raw_url in raw_urls:
        candidate_urls = redirect_param_targets(raw_url) or [raw_url]

        for candidate_url in candidate_urls:
            root = await probe_final_working_root(
                session,
                seed_url=seed_url,
                raw_url=candidate_url,
            )

            if root is not None:
                roots.add(root)

    return sorted(roots)


__all__ = [
    "probe_final_working_root",
    "probe_redirect_final_roots",
    "redirect_param_targets",
]
