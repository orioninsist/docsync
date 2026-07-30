"""Network and external-provider boundaries for recursive discovery."""

from __future__ import annotations

import aiohttp
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from crawler.discovery_runtime import DiscoveryRunState, log
from crawler.discovery_url_rules import html_needs_playwright

DISCOVERY_REQUEST_TIMEOUT_SECONDS = 20
DISCOVERY_PLAYWRIGHT_TIMEOUT_MS = 30_000
DISCOVERY_PLAYWRIGHT_WAIT_MS = 1_500
HTTP_ERROR_STATUS = 400
PROTECTED_STATUS_CODES = frozenset({401, 403, 407, 429, 451})

DISCOVERY_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)

DISCOVERY_REQUEST_HEADERS = {
    "User-Agent": DISCOVERY_BROWSER_USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}


async def fetch_text(
    session: aiohttp.ClientSession,
    url: str,
) -> str | None:
    """Fetch textual content and render blocked or JavaScript pages."""

    timeout = aiohttp.ClientTimeout(
        total=DISCOVERY_REQUEST_TIMEOUT_SECONDS,
        connect=10,
        sock_connect=10,
        sock_read=DISCOVERY_REQUEST_TIMEOUT_SECONDS,
    )

    try:
        async with session.get(
            url,
            headers=DISCOVERY_REQUEST_HEADERS,
            allow_redirects=True,
            timeout=timeout,
        ) as response:
            if response.status in PROTECTED_STATUS_CODES:
                log(
                    "       FETCH PROTECTED "
                    + f"status={response.status} url={url} "
                    + "fallback=playwright"
                )
                return await _fetch_rendered_text(url)

            if response.status >= HTTP_ERROR_STATUS:
                log(f"       FETCH SKIP status={response.status} url={url}")
                return None

            html = await response.text()
    except TimeoutError:
        log(
            f"       FETCH TIMEOUT after={DISCOVERY_REQUEST_TIMEOUT_SECONDS}s url={url}"
        )
        return await _fetch_rendered_text(url)
    except aiohttp.ClientError as exc:
        log(
            "       FETCH ERROR "
            + f"type={type(exc).__name__} url={url} detail={exc} "
            + "fallback=playwright"
        )
        return await _fetch_rendered_text(url)
    except (OSError, UnicodeError) as exc:
        log(f"       FETCH ERROR type={type(exc).__name__} url={url} detail={exc}")
        return None

    if not html_needs_playwright(html):
        return html

    rendered_html = await _fetch_rendered_text(url)

    if rendered_html is None:
        return html

    return rendered_html


async def _fetch_rendered_text(url: str) -> str | None:
    """Render one protected or JavaScript-dependent discovery page."""

    log(f"       FETCH RENDER START url={url}")

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)

            try:
                context = await browser.new_context(
                    user_agent=DISCOVERY_BROWSER_USER_AGENT,
                    locale="en-US",
                    java_script_enabled=True,
                    ignore_https_errors=True,
                    extra_http_headers={
                        "Accept-Language": "en-US,en;q=0.9",
                        "Cache-Control": "no-cache",
                        "Pragma": "no-cache",
                    },
                )

                try:
                    page = await context.new_page()
                    response = await page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=DISCOVERY_PLAYWRIGHT_TIMEOUT_MS,
                    )

                    if response is not None and response.status >= HTTP_ERROR_STATUS:
                        log(
                            "       FETCH RENDER SKIP "
                            + f"status={response.status} url={url}"
                        )
                        return None

                    await page.wait_for_timeout(DISCOVERY_PLAYWRIGHT_WAIT_MS)
                    await page.mouse.wheel(0, 1600)
                    await page.wait_for_timeout(500)

                    html = await page.content()
                    log(f"       FETCH RENDER SUCCESS url={page.url}")
                    return html
                finally:
                    await context.close()
            finally:
                await browser.close()
    except PlaywrightTimeoutError:
        log(
            "       FETCH RENDER TIMEOUT "
            + f"after={DISCOVERY_PLAYWRIGHT_TIMEOUT_MS}ms url={url}"
        )
        return None
    except PlaywrightError as exc:
        log(
            "       FETCH RENDER ERROR "
            + f"type={type(exc).__name__} url={url} detail={exc}"
        )
        return None
    except OSError as exc:
        log(
            "       FETCH RENDER ERROR "
            + f"type={type(exc).__name__} url={url} detail={exc}"
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
