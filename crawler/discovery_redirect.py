"""
Discovery redirect module.

Single job:
- Redirect/query target probing.
"""

from __future__ import annotations

import aiohttp

from crawler.discovery import (
    _probe_final_working_root,
    _probe_redirect_final_roots,
    _redirect_param_targets,
)


def redirect_param_targets(raw_url: str) -> list[str]:
    """Extract redirect target URLs from known query parameters."""
    return _redirect_param_targets(raw_url)


async def probe_final_working_root(
    session: aiohttp.ClientSession,
    *,
    seed_url: str,
    raw_url: str,
) -> str | None:
    """Probe a URL and return its final working root when allowed."""
    return await _probe_final_working_root(
        session,
        seed_url=seed_url,
        raw_url=raw_url,
    )


async def probe_redirect_final_roots(
    session: aiohttp.ClientSession,
    *,
    seed_url: str,
    raw_urls: list[str],
) -> list[str]:
    """Probe redirect candidates and return final working roots."""
    return await _probe_redirect_final_roots(
        session,
        seed_url=seed_url,
        raw_urls=raw_urls,
    )
