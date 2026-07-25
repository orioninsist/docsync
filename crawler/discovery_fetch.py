"""Network and external-provider boundaries for recursive discovery."""

from __future__ import annotations

import aiohttp

from crawler.discovery_runtime import DiscoveryRunState, log

DISCOVERY_REQUEST_TIMEOUT_SECONDS = 20
HTTP_ERROR_STATUS = 400


async def fetch_text(
    session: aiohttp.ClientSession,
    url: str,
) -> str | None:
    """Fetch textual content without leaking network failures."""

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
                log(f"       FETCH SKIP status={response.status} url={url}")
                return None

            return await response.text()
    except TimeoutError:
        log(
            f"       FETCH TIMEOUT after={DISCOVERY_REQUEST_TIMEOUT_SECONDS}s url={url}"
        )
        return None
    except aiohttp.ClientError as exc:
        log(f"       FETCH ERROR type={type(exc).__name__} url={url} detail={exc}")
        return None
    except (OSError, UnicodeError) as exc:
        log(f"       FETCH ERROR type={type(exc).__name__} url={url} detail={exc}")
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


async def certificate_transparency_candidates(
    session: aiohttp.ClientSession,
    state: DiscoveryRunState,
) -> list[str]:
    """Return CT candidates without terminating discovery on failure."""

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
            "       CT SKIP "
            + f"type={type(exc).__name__} "
            + f"seed={state.base_url} "
            + f"detail={exc}"
        )
        return []
