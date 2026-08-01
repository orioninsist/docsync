"""Safe sitemap discovery for documentation crawls."""

from __future__ import annotations

import asyncio
import gzip
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit
from urllib.request import Request

from defusedxml import ElementTree as ET

from docsync.url_security import (
    is_safe_in_scope_url,
    normalize_url,
    secure_urlopen,
    validated_http_url,
)

SITEMAP_MAX_FILES = 50
SITEMAP_MAX_URLS = 10_000
SITEMAP_FETCH_TIMEOUT_SECONDS = 20
SITEMAP_MAX_PAYLOAD_BYTES = 20 * 1024 * 1024
SITEMAP_USER_AGENT = "docsync/0.1 (+safe documentation crawler)"


@dataclass(slots=True)
class SitemapDiscoveryResult:
    """Bounded sitemap-discovery outcome."""

    urls: list[str] = field(default_factory=list)
    sitemap_files_checked: int = 0
    sitemap_files_found: int = 0
    errors: list[str] = field(default_factory=list)


def decode_sitemap_payload(payload: bytes, url: str) -> str:
    """Decode plain or gzip-compressed sitemap content."""

    validated_url = validated_http_url(url)

    if validated_url.lower().endswith(".gz") or payload[:2] == b"\x1f\x8b":
        payload = gzip.decompress(payload)

    return payload.decode("utf-8", errors="replace")


def extract_robots_sitemaps(
    robots_text: str,
    base_url: str,
) -> list[str]:
    """Extract unique Sitemap directives from robots.txt."""

    validated_base = validated_http_url(base_url)
    results: list[str] = []

    for line in robots_text.splitlines():
        clean_line = line.split("#", 1)[0].strip()

        if not clean_line:
            continue

        key, separator, value = clean_line.partition(":")

        if not separator or key.strip().lower() != "sitemap":
            continue

        sitemap_url = value.strip()

        if not sitemap_url:
            continue

        absolute = normalize_url(urljoin(validated_base, sitemap_url))

        if absolute not in results:
            results.append(absolute)

    return results


def fetch_text_url(
    url: str,
    timeout_seconds: int,
) -> tuple[str, str]:
    """Fetch bounded text content with redirect validation."""

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero")

    validated_url = validated_http_url(url)

    request = Request(
        validated_url,
        headers={
            "User-Agent": SITEMAP_USER_AGENT,
            "Accept": (
                "application/xml,text/xml,text/plain,"
                "application/gzip,application/x-gzip;q=0.9,"
                "*/*;q=0.1"
            ),
        },
        method="GET",
    )

    with secure_urlopen(
        request,
        timeout=timeout_seconds,
    ) as response:
        final_url = normalize_url(response.geturl())
        payload = response.read(SITEMAP_MAX_PAYLOAD_BYTES + 1)

    if len(payload) > SITEMAP_MAX_PAYLOAD_BYTES:
        raise ValueError("Response exceeded the 20 MiB sitemap safety limit.")

    return (
        final_url,
        decode_sitemap_payload(payload, final_url),
    )


def sitemap_candidate_urls(start_url: str) -> list[str]:
    """Return conventional root sitemap locations."""

    validated_start = validated_http_url(start_url)
    parsed = urlsplit(validated_start)

    root_url = f"{parsed.scheme}://{parsed.netloc}/"

    return [
        normalize_url(urljoin(root_url, "sitemap.xml")),
        normalize_url(urljoin(root_url, "sitemap_index.xml")),
        normalize_url(urljoin(root_url, "sitemap.xml.gz")),
    ]


def sitemap_xml_locations(
    xml_text: str,
) -> tuple[str, list[str]]:
    """Parse sitemap-index or URL-set locations safely."""

    root = ET.fromstring(xml_text)
    root_name = root.tag.rsplit("}", 1)[-1].lower()

    locations: list[str] = []

    for element in root.iter():
        element_name = element.tag.rsplit("}", 1)[-1].lower()

        if element_name != "loc":
            continue

        if element.text and element.text.strip():
            locations.append(element.text.strip())

    if root_name == "sitemapindex":
        return "index", locations

    if root_name == "urlset":
        return "urlset", locations

    raise ValueError(f"Unsupported sitemap root element: {root_name}")


def discover_sitemap_urls_sync(
    *,
    start_url: str,
    timeout_seconds: int,
    max_urls: int,
) -> SitemapDiscoveryResult:
    """Discover bounded in-scope URLs from robots and sitemaps."""

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero")

    if max_urls <= 0:
        raise ValueError("max_urls must be greater than zero")

    normalized_start = normalize_url(start_url)
    parsed_start = urlsplit(normalized_start)
    root_url = f"{parsed_start.scheme}://{parsed_start.netloc}/"
    robots_url = normalize_url(urljoin(root_url, "robots.txt"))

    sitemap_queue: list[str] = []
    queued_sitemaps: set[str] = set()
    visited_sitemaps: set[str] = set()
    discovered_urls: list[str] = []
    discovered_url_set: set[str] = set()
    errors: list[str] = []
    sitemap_files_found = 0

    bounded_timeout = min(
        timeout_seconds,
        SITEMAP_FETCH_TIMEOUT_SECONDS,
    )
    bounded_url_limit = min(
        max_urls,
        SITEMAP_MAX_URLS,
    )

    try:
        _, robots_text = fetch_text_url(
            robots_url,
            bounded_timeout,
        )

        for sitemap_url in extract_robots_sitemaps(
            robots_text,
            root_url,
        ):
            if sitemap_url in queued_sitemaps:
                continue

            queued_sitemaps.add(sitemap_url)
            sitemap_queue.append(sitemap_url)
    except Exception as error:
        errors.append(f"{robots_url}: {type(error).__name__}: {error}")

    for candidate in sitemap_candidate_urls(normalized_start):
        if candidate in queued_sitemaps:
            continue

        queued_sitemaps.add(candidate)
        sitemap_queue.append(candidate)

    while sitemap_queue and len(visited_sitemaps) < SITEMAP_MAX_FILES:
        sitemap_url = sitemap_queue.pop(0)

        if sitemap_url in visited_sitemaps:
            continue

        visited_sitemaps.add(sitemap_url)

        try:
            final_url, xml_text = fetch_text_url(
                sitemap_url,
                bounded_timeout,
            )
            sitemap_type, locations = sitemap_xml_locations(xml_text)
            sitemap_files_found += 1
        except Exception as error:
            errors.append(f"{sitemap_url}: {type(error).__name__}: {error}")
            continue

        if sitemap_type == "index":
            for location in locations:
                child_sitemap = normalize_url(urljoin(final_url, location))

                child_parts = urlsplit(child_sitemap)

                if (child_parts.hostname or "").lower() != (
                    parsed_start.hostname or ""
                ).lower():
                    continue

                if child_sitemap in queued_sitemaps:
                    continue

                if len(queued_sitemaps) >= SITEMAP_MAX_FILES:
                    break

                queued_sitemaps.add(child_sitemap)
                sitemap_queue.append(child_sitemap)

            continue

        for location in locations:
            page_url = normalize_url(urljoin(final_url, location))

            if not is_safe_in_scope_url(
                page_url,
                start_url=normalized_start,
            ):
                continue

            if page_url in discovered_url_set:
                continue

            discovered_url_set.add(page_url)
            discovered_urls.append(page_url)

            if len(discovered_urls) >= bounded_url_limit:
                break

        if len(discovered_urls) >= bounded_url_limit:
            break

    return SitemapDiscoveryResult(
        urls=discovered_urls,
        sitemap_files_checked=len(visited_sitemaps),
        sitemap_files_found=sitemap_files_found,
        errors=errors,
    )


async def discover_sitemap_urls(
    *,
    start_url: str,
    timeout_seconds: int,
    max_urls: int,
) -> SitemapDiscoveryResult:
    """Run blocking sitemap discovery in a worker thread."""

    return await asyncio.to_thread(
        discover_sitemap_urls_sync,
        start_url=start_url,
        timeout_seconds=timeout_seconds,
        max_urls=max_urls,
    )
